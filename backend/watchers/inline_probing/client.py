from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

import httpx

from backend.config import Settings


INLINE_PROBING_REQUEST_SCHEMA = "inline_probing.request.v1"
INLINE_PROBING_RESULT_SCHEMA = "inline_probing.result.v1"
INLINE_PROBING_RESPONSE_FIELD = "inline_probing"


@dataclass(frozen=True)
class InlineProbingAssessment:
    score: float | None
    logit: float | None
    threshold: float
    checkpoint_id: str | None
    layer: int | None
    effective_position: int | None
    protocol: str
    raw_output: str
    latency_ms: int
    error: str | None = None

    @property
    def risky(self) -> bool | None:
        if self.score is None:
            return None
        return self.score >= self.threshold

    @property
    def blocked(self) -> bool:
        return self.risky is True

    @property
    def label(self) -> str | None:
        if self.risky is None:
            return None
        return "risk" if self.risky else "safe"


class InlineProbingGuard:
    """ProspectMonitor wrapper for patched-vLLM runtime inline probing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.inline_probing_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def moderate_messages(
        self,
        messages: list[dict[str, Any]],
        threshold: float | None = None,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> InlineProbingAssessment:
        started = perf_counter()
        resolved_threshold = (
            self.settings.inline_probing_threshold
            if threshold is None
            else float(threshold)
        )
        try:
            if not self.settings.inline_probing_expected_checkpoint_id.strip():
                raise RuntimeError("INLINE_PROBING_EXPECTED_CHECKPOINT_ID is required")
            result = await self._probe(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                model=model,
                base_url=base_url,
            )
            return InlineProbingAssessment(
                score=float(result["score"]),
                logit=float(result["logit"]),
                threshold=resolved_threshold,
                checkpoint_id=str(result.get("checkpoint_id") or ""),
                layer=_optional_int(result.get("layer")),
                effective_position=_optional_int(result.get("effective_position")),
                protocol=str(result["_protocol"]),
                raw_output=json.dumps(result, ensure_ascii=False, sort_keys=True),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as error:
            return InlineProbingAssessment(
                score=None,
                logit=None,
                threshold=resolved_threshold,
                checkpoint_id=None,
                layer=None,
                effective_position=None,
                protocol=self.settings.inline_probing_protocol,
                raw_output="",
                latency_ms=round((perf_counter() - started) * 1000),
                error=str(error),
            )

    async def _probe(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        protocol = self.settings.inline_probing_protocol.strip().lower()
        if protocol != "inline_probing":
            raise ValueError("INLINE_PROBING_PROTOCOL must be inline_probing")
        return await self._probe_once(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            base_url=base_url,
        )

    async def _probe_once(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.settings.vllm_model,
            "messages": messages,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 1,
            "stream": False,
            "n": 1,
            "best_of": 1,
            "return_token_ids": True,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        payload["inline_probing_request"] = build_inline_probing_request(
            payload,
            expected_checkpoint_id=self.settings.inline_probing_expected_checkpoint_id,
            timeout_seconds=self.settings.inline_probing_timeout_seconds,
            probe_id=getattr(self.settings, "inline_probing_probe_id", "") or None,
        )
        response = await self._client.post(
            f"{(base_url or self.settings.vllm_base_url).rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.vllm_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return parse_inline_probing_response(
            data,
            expected_checkpoint_id=self.settings.inline_probing_expected_checkpoint_id,
            expected_probe_id=(
                getattr(self.settings, "inline_probing_probe_id", "") or None
            ),
        )

    async def get_model_info(self) -> dict[str, Any]:
        return {
            "base_url": self.settings.vllm_base_url,
            "model": self.settings.vllm_model,
            "protocol": self.settings.inline_probing_protocol,
            "task": self.settings.inline_probing_task,
            "threshold": self.settings.inline_probing_threshold,
            "expected_checkpoint_id": self.settings.inline_probing_expected_checkpoint_id,
            "probe_id": getattr(self.settings, "inline_probing_probe_id", ""),
        }


def input_attempt_fingerprint(chat: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {
            key: chat[key]
            for key in (
                "model",
                "messages",
                "prompt",
                "tools",
                "tool_choice",
                "temperature",
                "top_p",
                "max_tokens",
                "max_completion_tokens",
                "prompt_logprobs",
                "return_token_ids",
                "add_special_tokens",
                "cache_salt",
            )
            if key in chat
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_inline_probing_request(
    chat: Mapping[str, Any],
    *,
    expected_checkpoint_id: str,
    timeout_seconds: float,
    target_token_index: int | None = None,
    probe_id: str | None = None,
) -> dict[str, Any]:
    if not expected_checkpoint_id.strip():
        raise RuntimeError("INLINE_PROBING_EXPECTED_CHECKPOINT_ID is required")
    if target_token_index is not None and (
        isinstance(target_token_index, bool)
        or not isinstance(target_token_index, int)
        or target_token_index < 0
    ):
        raise ValueError("target_token_index must be a non-negative integer")
    if probe_id is not None and not probe_id.strip():
        raise ValueError("probe_id must be non-empty")
    return {
        "schema": INLINE_PROBING_REQUEST_SCHEMA,
        "required": True,
        "logical_request_id": f"perspective-watch/inline_probing/{uuid.uuid4()}",
        "attempt_id": str(uuid.uuid4()),
        "expected_checkpoint_id": expected_checkpoint_id,
        "input_attempt_fingerprint": input_attempt_fingerprint(chat),
        "deadline_ms": max(1, int(timeout_seconds * 1000)),
        "target_token_index": target_token_index,
        "probe_id": probe_id,
    }


def parse_inline_probing_response(
    response: Mapping[str, Any],
    *,
    expected_checkpoint_id: str,
    expected_probe_id: str | None = None,
) -> dict[str, Any]:
    probe = response.get(INLINE_PROBING_RESPONSE_FIELD)
    if not isinstance(probe, Mapping):
        raise RuntimeError("vLLM response did not include inline_probing")
    result = dict(probe)
    if result.get("schema") != INLINE_PROBING_RESULT_SCHEMA:
        raise RuntimeError("inline probing result has unsupported schema")
    if result.get("status") != "ok":
        raise RuntimeError(f"inline probing result status is {result.get('status') or 'missing'}")
    if result.get("checkpoint_id") != expected_checkpoint_id:
        raise RuntimeError("inline probing result checkpoint mismatch")
    if expected_probe_id is not None and result.get("probe_id") != expected_probe_id:
        raise RuntimeError("inline probing result probe mismatch")
    _validate_probe_result(result)
    result["_protocol"] = "inline_probing"
    return result


def assessment_from_probe_result(
    result: Mapping[str, Any],
    *,
    threshold: float,
    latency_ms: int,
) -> InlineProbingAssessment:
    return InlineProbingAssessment(
        score=float(result["score"]),
        logit=float(result["logit"]),
        threshold=float(threshold),
        checkpoint_id=str(result.get("checkpoint_id") or ""),
        layer=_optional_int(result.get("layer")),
        effective_position=_optional_int(result.get("effective_position")),
        protocol=str(result.get("_protocol") or "inline_probing"),
        raw_output=json.dumps(dict(result), ensure_ascii=False, sort_keys=True),
        latency_ms=latency_ms,
    )


def _validate_probe_result(result: Mapping[str, Any]) -> None:
    score = result.get("score")
    logit = result.get("logit")
    if (
        not isinstance(score, (int, float))
        or isinstance(score, bool)
        or not math.isfinite(float(score))
        or not 0.0 <= float(score) <= 1.0
        or not isinstance(logit, (int, float))
        or isinstance(logit, bool)
        or not math.isfinite(float(logit))
    ):
        raise RuntimeError("inline probing result has invalid score/logit")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
