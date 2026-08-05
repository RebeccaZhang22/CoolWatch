"""Unified input-classification service for all Perspective Watch guards."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from backend.schemas import ModerationGuardResult, ModerationRequest, ModerationResponse
from backend.watchers import (
    GUARD_NAMES,
    SUGGESTION_TEXT,
    LlamaPromptGuardClient,
    NeteaseYidunClient,
    Qwen3GuardClient,
    SafeGaugeGuard,
    detect_attack_intent,
)


SUPPORTED_GUARDS = (
    "safegauge",
    "qwen_guard",
    "llama_prompt_guard",
    "netease_yidun",
    "rule_guard",
)


class ModerationService:
    def __init__(
        self,
        qwen_guard_client: Qwen3GuardClient,
        llama_prompt_guard_client: LlamaPromptGuardClient,
        netease_yidun_client: NeteaseYidunClient,
        safegauge_guard: SafeGaugeGuard,
    ) -> None:
        self.qwen_guard_client = qwen_guard_client
        self.llama_prompt_guard_client = llama_prompt_guard_client
        self.netease_yidun_client = netease_yidun_client
        self.safegauge_guard = safegauge_guard

    async def moderate(self, request: ModerationRequest) -> ModerationResponse:
        guard_ids = list(dict.fromkeys(request.guards))
        unknown = [guard_id for guard_id in guard_ids if guard_id not in SUPPORTED_GUARDS]
        if unknown:
            raise ValueError(f"unsupported guards: {', '.join(unknown)}")

        tasks = [self._moderate_guard(guard_id, request) for guard_id in guard_ids]
        values = await asyncio.gather(*tasks)
        results = dict(zip(guard_ids, values, strict=True))
        successful = [result for result in values if result.connected and result.risky is not None]
        risky = True if any(result.risky is True for result in successful) else (False if successful else None)
        labels = dedupe(label for result in values for label in result.labels)
        return ModerationResponse(
            label="risk" if risky is True else ("safe" if risky is False else "unknown"),
            risky=risky,
            blocked=any(result.blocked for result in values),
            labels=labels,
            results=results,
        )

    async def _moderate_guard(
        self,
        guard_id: str,
        request: ModerationRequest,
    ) -> ModerationGuardResult:
        prompt = request.prompt_text()
        if guard_id == "safegauge":
            value = await self.safegauge_guard.moderate_messages(
                request.to_messages(),
                threshold=request.threshold,
                task=request.task,
                model=request.model,
                base_url=(
                    f"http://127.0.0.1:{request.vllm_port}/v1"
                    if request.vllm_port is not None
                    else None
                ),
            )
            labels = [item for item in (value.task, value.label) if item]
            return ModerationGuardResult(
                guard_id=guard_id,
                guard_name=GUARD_NAMES[guard_id],
                label=value.label or None,
                risky=value.risky,
                blocked=value.blocked,
                connected=value.error is None,
                labels=labels,
                probability=value.probability,
                threshold=value.threshold,
                latency_ms=value.latency_ms,
                error=value.error,
            )
        if guard_id == "qwen_guard":
            value = await self.qwen_guard_client.moderate_prompt(prompt)
            labels = [item for item in ([value.safety_label] + value.categories) if item]
            return ModerationGuardResult(
                guard_id=guard_id,
                guard_name=GUARD_NAMES[guard_id],
                label=value.safety_label,
                risky=value.risky,
                blocked=value.blocked,
                connected=value.error is None,
                labels=labels,
                latency_ms=value.latency_ms,
                error=value.error,
            )
        if guard_id == "llama_prompt_guard":
            value = await self.llama_prompt_guard_client.moderate_prompt(prompt)
            return ModerationGuardResult(
                guard_id=guard_id,
                guard_name=GUARD_NAMES[guard_id],
                label=value.label,
                risky=value.risky,
                blocked=value.blocked,
                connected=value.error is None,
                labels=[value.label] if value.label else [],
                probability=value.probability,
                threshold=value.threshold,
                latency_ms=value.latency_ms,
                error=value.error,
            )
        if guard_id == "netease_yidun":
            value = await self.netease_yidun_client.moderate_prompt(prompt)
            label = SUGGESTION_TEXT.get(value.suggestion) if value.suggestion is not None else None
            return ModerationGuardResult(
                guard_id=guard_id,
                guard_name=GUARD_NAMES[guard_id],
                label=label,
                risky=value.risky,
                blocked=value.blocked,
                connected=value.error is None,
                labels=value.labels,
                latency_ms=value.latency_ms,
                error=value.error,
            )

        matched = detect_attack_intent(prompt, is_attack=False)
        risky = bool(matched)
        return ModerationGuardResult(
            guard_id=guard_id,
            guard_name=GUARD_NAMES[guard_id],
            label="attack" if risky else "benign",
            risky=risky,
            blocked=risky,
            connected=True,
            labels=matched,
            latency_ms=0,
        )


def dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
