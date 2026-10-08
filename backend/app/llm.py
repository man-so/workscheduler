from __future__ import annotations

import json
import os
from typing import Any, Protocol


class LlmProviderAdapter(Protocol):
    def interpret_setup(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        ...

    def interpret_schedule_edit(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        ...


class OfflineLlmProvider:
    """Fallback provider used when no API key is configured."""

    def interpret_setup(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "intent": "offline_fallback",
            "proposedPatch": {},
            "missingFields": context.get("missingFields", []),
            "clarificationQuestion": "폼 또는 규칙 기반 챗봇 입력으로 설정을 계속 진행해 주세요.",
            "confidence": 0.0,
            "warnings": ["LLM API key is not configured."],
        }

    def interpret_schedule_edit(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "intent": "offline_fallback",
            "proposedPatch": {},
            "missingFields": [],
            "clarificationQuestion": "Phase 3 이후 배정 수정 해석에서 사용할 예정입니다.",
            "confidence": 0.0,
            "warnings": ["LLM API key is not configured."],
        }


class JsonOnlyLlmProvider:
    """Minimal adapter shell for future LLM providers that must return JSON."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def interpret_setup(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("External LLM calls are intentionally not wired in Phase 2.")

    def interpret_schedule_edit(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Schedule edit interpretation belongs to a later phase.")


def validate_llm_json(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    required = {"intent", "proposedPatch", "missingFields", "clarificationQuestion", "confidence", "warnings"}
    missing = required.difference(parsed)
    if missing:
        raise ValueError(f"LLM response is missing fields: {sorted(missing)}")
    if not isinstance(parsed["proposedPatch"], dict):
        raise ValueError("LLM proposedPatch must be an object")
    return parsed


def get_llm_provider() -> LlmProviderAdapter:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return OfflineLlmProvider()
    return JsonOnlyLlmProvider(api_key)
