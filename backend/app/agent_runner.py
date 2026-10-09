from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
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
    def __init__(self, message: str, log_text: str | None = None) -> None:
        super().__init__(message)
        self.log_text = log_text


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


def _run(command: list[str], prompt: str, cwd: Path, timeout_seconds: int, cancel_event: Any = None) -> tuple[str, str, str]:
    events: list[str] = [
        f"started_at={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"cwd={cwd}",
        f"timeout_seconds={timeout_seconds}",
        f"command={command}",
    ]
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def capture(stream: Any, target: list[str], label: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                target.append(line)
                events.append(f"{time.monotonic() - started:.2f}s {label}: {line.rstrip()}")
        finally:
            stream.close()

    started = time.monotonic()
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
        events.append(f"{time.monotonic() - started:.2f}s spawned pid={process.pid}")
        stdout_thread = threading.Thread(target=capture, args=(process.stdout, stdout_parts, "stdout"), daemon=True) if process.stdout else None
        stderr_thread = threading.Thread(target=capture, args=(process.stderr, stderr_parts, "stderr"), daemon=True) if process.stderr else None
        if stdout_thread:
            stdout_thread.start()
        if stderr_thread:
            stderr_thread.start()
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()
            events.append(f"{time.monotonic() - started:.2f}s prompt_written chars={len(prompt)}")
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait(timeout=5)
                events.append(f"{time.monotonic() - started:.2f}s canceled_by_user")
                raise AgentRunError("agent canceled by user", "\n".join(events))
            if time.monotonic() - started >= timeout_seconds:
                process.kill()
                process.wait(timeout=5)
                elapsed = time.monotonic() - started
                events.append(f"{elapsed:.2f}s timeout")
                events.append(f"stdout_tail={''.join(stdout_parts)[-2000:]}")
                events.append(f"stderr_tail={''.join(stderr_parts)[-2000:]}")
                raise AgentRunError(f"agent timed out after {timeout_seconds} seconds", "\n".join(events))
            time.sleep(0.1)
    except OSError as exc:
        events.append(f"{time.monotonic() - started:.2f}s start_failed={exc}")
        raise AgentRunError(f"failed to start agent: {exc}", "\n".join(events)) from exc
    if stdout_thread:
        stdout_thread.join(timeout=2)
    if stderr_thread:
        stderr_thread.join(timeout=2)
    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
    elapsed = time.monotonic() - started
    events.append(f"{elapsed:.2f}s exited returncode={process.returncode}")
    if process.returncode != 0:
        events.append(f"stdout_tail={stdout[-2000:]}")
        events.append(f"stderr_tail={stderr[-2000:]}")
        raise AgentRunError(f"agent exited with code {process.returncode}: {stderr[-1000:]}", "\n".join(events))
    return stdout, stderr, "\n".join(events)


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
            output_path = work_dir / "constraint.json"
            command = [
                executable,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--json",
                "--color",
                "never",
                "--output-last-message",
                str(output_path),
                "-",
            ]
            stdout, stderr, log_text = _run(command, instruction, work_dir, timeout_seconds, cancel_event)
            if output_path.exists():
                stdout = output_path.read_text(encoding="utf-8")
                log_text += f"\noutput_file={output_path}\noutput_file_bytes={len(stdout.encode('utf-8'))}"
            else:
                log_text += f"\noutput_file_missing={output_path}"
        else:
            command = [executable, "-p", "--output-format", "json", "--permission-mode", "plan", "--max-turns", "3"]
            stdout, stderr, log_text = _run(command, instruction, work_dir, timeout_seconds, cancel_event)
        return AgentResult(payload=_parse_json(stdout), stdout=(log_text + "\n" + stdout)[-10000:], stderr=stderr[-10000:], command=command)
