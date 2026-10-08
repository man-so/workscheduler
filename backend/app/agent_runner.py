from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AGENT_NAMES = {"codex": "codex", "claude": "claude"}


@dataclass
class AgentResult:
    payload: dict[str, Any]
    stdout: str
    stderr: str
    command: list[str]


class AgentRunError(RuntimeError):
    pass


def _parse_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AgentRunError("agent returned invalid JSON") from exc
    if isinstance(parsed, dict) and isinstance(parsed.get("result"), str):
        try:
            nested = json.loads(parsed["result"])
            if isinstance(nested, dict):
                return nested
        except json.JSONDecodeError:
            pass
    if not isinstance(parsed, dict):
        raise AgentRunError("agent response must be a JSON object")
    return parsed


def _run(command: list[str], prompt: str, cwd: Path, timeout_seconds: int, cancel_event: Any = None) -> tuple[str, str]:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=dict(os.environ),
        )
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()
        started = time.monotonic()
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                stdout, stderr = process.communicate()
                raise AgentRunError("agent canceled by user")
            if time.monotonic() - started >= timeout_seconds:
                process.kill()
                stdout, stderr = process.communicate()
                raise AgentRunError(f"agent timed out after {timeout_seconds} seconds")
            time.sleep(0.1)
        stdout, stderr = process.communicate()
    except OSError as exc:
        raise AgentRunError(f"failed to start agent: {exc}") from exc
    if process.returncode != 0:
        raise AgentRunError(f"agent exited with code {process.returncode}: {stderr[-1000:]}")
    return stdout, stderr


def run_agent(agent_id: str, constraint_input: dict[str, Any], timeout_seconds: int, cancel_event: Any = None) -> AgentResult:
    if agent_id not in AGENT_NAMES:
        raise AgentRunError("unsupported agent")
    executable = shutil.which(AGENT_NAMES[agent_id])
    if not executable:
        raise AgentRunError(f"{agent_id} CLI is not installed")
    with tempfile.TemporaryDirectory(prefix="workscheduler-agent-") as temp_dir:
        work_dir = Path(temp_dir)
        prompt = json.dumps({"approved_settings": constraint_input}, ensure_ascii=False)
        instruction = (
            "Read the approved_settings JSON below. Do not edit files, run shell commands, or infer missing business rules. "
            "Return only a JSON object with schema_version, team_id, year, month, hard, soft, unsupported. "
            "Preserve all supported hard constraints exactly; put any unsupported rule description in unsupported.\n"
            + prompt
        )
        if agent_id == "codex":
            schema_path = work_dir / "constraint.schema.json"
            output_path = work_dir / "constraint.json"
            schema_path.write_text(json.dumps({
                "type": "object",
                "required": ["schema_version", "team_id", "year", "month", "hard", "soft", "unsupported"],
                "properties": {"schema_version": {"type": "string"}, "team_id": {"type": "integer"}, "year": {"type": "integer"}, "month": {"type": "integer"}, "hard": {"type": "object"}, "soft": {"type": "object"}, "unsupported": {"type": "array", "items": {"type": "string"}}},
            }), encoding="utf-8")
            command = [executable, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--output-schema", str(schema_path), "--output-last-message", str(output_path), "-"]
            stdout, stderr = _run(command, instruction, work_dir, timeout_seconds, cancel_event)
            if output_path.exists():
                stdout = output_path.read_text(encoding="utf-8")
        else:
            command = [executable, "-p", "--output-format", "json", "--permission-mode", "plan", "--max-turns", "3"]
            stdout, stderr = _run(command, instruction, work_dir, timeout_seconds, cancel_event)
        return AgentResult(payload=_parse_json(stdout), stdout=stdout[-10000:], stderr=stderr[-10000:], command=command)
