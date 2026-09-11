"""Client for 方寸跃迁安全护栏 remote input safety assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from backend.config import Settings


SAFE_RISK_LEVELS = {"no_risk", "low_risk", "safe", "pass", "allow"}
RISKY_RISK_LEVELS = {
    "medium_risk",
    "high_risk",
    "critical_risk",
    "risk",
    "unsafe",
    "block",
    "blocked",
}
BLOCK_ACTIONS = {"reject", "block", "blocked", "deny"}
RISK_ACTIONS = BLOCK_ACTIONS | {"replace", "review", "warn"}


@dataclass(frozen=True)
class FangcunGuardAssessment:
    overall_risk_level: str | None
    suggest_action: str | None
    suggest_answer: str | None
    categories: list[str]
    raw_output: str
    latency_ms: int
    error: str | None = None

    @property
    def risky(self) -> bool | None:
        level = _normalise(self.overall_risk_level)
        action = _normalise(self.suggest_action)
        if level in RISKY_RISK_LEVELS or action in RISK_ACTIONS:
            return True
        if level in SAFE_RISK_LEVELS or action in {"pass", "allow", "approved"}:
            return False
        return None

    @property
    def blocked(self) -> bool:
        return _normalise(self.suggest_action) in BLOCK_ACTIONS


class FangcunGuardClient:
    """Async client for Fangcun Guard's hook API.

    The hook API is separate from the older ``/v1/guardrails`` endpoint. It
    accepts a conversation for input scanning and a plain string for output
    scanning, and returns a top-level ``action`` plus ``detection_result``.
    Errors are converted to an assessment with ``error`` set so callers can
    implement the documented fail-open policy without exposing the API key.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.fangcun_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate_prompt(self, prompt: str) -> FangcunGuardAssessment:
        """Backward-compatible alias used by the input guard pipeline."""

        return await self.scan_input([{"role": "user", "content": prompt}])

    async def scan_input(
        self,
        messages: list[dict[str, str]],
    ) -> FangcunGuardAssessment:
        """Scan user/context messages before invoking the business model."""

        return await self._scan(
            "/v1/hook/scan-input",
            {"messages": messages, "stream": False},
        )

    async def scan_output(self, content: str) -> FangcunGuardAssessment:
        """Scan generated model output before delivering it to the user."""

        return await self._scan(
            "/v1/hook/scan-output",
            {"content": content, "stream": False},
        )

    async def _scan(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> FangcunGuardAssessment:
        started = perf_counter()
        if not self.settings.fangcun_api_key.strip():
            return self._error_assessment("未配置 FANGCUN_API_KEY", started)
        try:
            response = await self._client.post(
                self._endpoint(path),
                headers={
                    "Authorization": f"Bearer {self.settings.fangcun_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("方寸跃迁安全护栏返回格式不是 JSON 对象")
        except httpx.HTTPStatusError as error:
            # Preserve the provider's short error body (for example, an
            # application/key mismatch) in the inspector while keeping the
            # fail-open behavior of the caller.
            detail = error.response.text.strip()
            suffix = f": {detail[:500]}" if detail else ""
            return self._error_assessment(
                f"方寸 Hook HTTP {error.response.status_code}{suffix}",
                started,
            )
        except Exception as error:
            return self._error_assessment(str(error), started)

        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        detection = (
            body.get("detection_result")
            if isinstance(body.get("detection_result"), dict)
            else {}
        )
        overall = _first_string(
            body.get("overall_risk_level"),
            detection.get("overall_risk_level"),
            result.get("overall_risk_level"),
        )
        # Hook responses use ``action`` (allow/block); the legacy endpoint
        # used ``suggest_action``. Normalize both into one assessment field.
        action = _first_string(
            body.get("action"),
            body.get("suggest_action"),
            detection.get("action"),
            result.get("suggest_action"),
        )
        answer = _first_string(body.get("suggest_answer"), result.get("suggest_answer"))
        categories = _extract_categories(detection, result)
        return FangcunGuardAssessment(
            overall_risk_level=overall,
            suggest_action=action,
            suggest_answer=answer,
            categories=categories,
            raw_output=json.dumps(body, ensure_ascii=False),
            latency_ms=round((perf_counter() - started) * 1000),
        )

    def _endpoint(self, path: str) -> str:
        """Build a hook URL from either a host or a legacy ``.../v1`` base."""

        base = self.settings.fangcun_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return f"{base}{path}"

    @staticmethod
    def _error_assessment(error: str, started: float) -> FangcunGuardAssessment:
        return FangcunGuardAssessment(
            overall_risk_level=None,
            suggest_action=None,
            suggest_answer=None,
            categories=[],
            raw_output="",
            latency_ms=round((perf_counter() - started) * 1000),
            error=error,
        )


def _normalise(value: str | None) -> str:
    return value.strip().lower().replace("-", "_") if isinstance(value, str) else ""


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_categories(*sections: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    for result in sections:
        for section in result.values():
            if not isinstance(section, dict):
                continue
            values = section.get("categories")
            if not isinstance(values, list):
                continue
            categories.extend(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )
    return list(dict.fromkeys(categories))
