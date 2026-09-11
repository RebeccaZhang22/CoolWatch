"""Unified input-classification service for all ProspectMonitor guards."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from backend.schemas import ModerationGuardResult, ModerationRequest, ModerationResponse
from backend.watchers import (
    GUARD_NAMES,
    SUGGESTION_TEXT,
    FangcunGuardClient,
    LlamaPromptGuardClient,
    NeteaseYidunClient,
    Qwen3GuardClient,
    SafeGaugeAssessment,
    SafeGaugeGuard,
    InlineProbingAssessment,
    InlineProbingGuard,
    detect_attack_intent,
)


SUPPORTED_GUARDS = (
    "safegauge",
    "inline_probing",
    "qwen_guard",
    "llama_prompt_guard",
    "netease_yidun",
    "fangcun_guard",
    "rule_guard",
)


class ModerationService:
    def __init__(
        self,
        qwen_guard_client: Qwen3GuardClient,
        llama_prompt_guard_client: LlamaPromptGuardClient,
        netease_yidun_client: NeteaseYidunClient,
        fangcun_guard_client: FangcunGuardClient,
        safegauge_guard: SafeGaugeGuard,
        inline_probing_guard: InlineProbingGuard,
    ) -> None:
        self.qwen_guard_client = qwen_guard_client
        self.llama_prompt_guard_client = llama_prompt_guard_client
        self.netease_yidun_client = netease_yidun_client
        self.fangcun_guard_client = fangcun_guard_client
        self.safegauge_guard = safegauge_guard
        self.inline_probing_guard = inline_probing_guard

    async def moderate(self, request: ModerationRequest) -> ModerationResponse:
        guard_ids = list(dict.fromkeys(request.guards))
        unknown = [guard_id for guard_id in guard_ids if guard_id not in SUPPORTED_GUARDS]
        if unknown:
            raise ValueError(f"unsupported guards: {', '.join(unknown)}")

        results: dict[str, ModerationGuardResult] = {}
        remaining = list(guard_ids)
        if (
            "safegauge" in guard_ids
            and "inline_probing" in guard_ids
            and self.safegauge_guard.can_fuse_inline(request.task)
        ):
            fused = await self.safegauge_guard.moderate_messages_with_inline(
                request.to_messages(),
                threshold=request.threshold,
                inline_threshold=request.threshold,
                task=request.task,
                model=request.model,
                base_url=self._request_base_url(request),
            )
            results["safegauge"] = self._safegauge_result(fused.safegauge)
            results["inline_probing"] = self._inline_probing_result(
                fused.inline_probing
            )
            remaining = [
                guard_id
                for guard_id in remaining
                if guard_id not in {"safegauge", "inline_probing"}
            ]

        values = await asyncio.gather(
            *(self._moderate_guard(guard_id, request) for guard_id in remaining)
        )
        results.update(dict(zip(remaining, values, strict=True)))
        results = {guard_id: results[guard_id] for guard_id in guard_ids}
        values = list(results.values())
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
                base_url=self._request_base_url(request),
            )
            return self._safegauge_result(value)
        if guard_id == "inline_probing":
            value = await self.inline_probing_guard.moderate_messages(
                request.to_messages(),
                threshold=request.threshold,
                model=request.model,
                base_url=self._request_base_url(request),
            )
            return self._inline_probing_result(value)
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
        if guard_id == "fangcun_guard":
            value = await self.fangcun_guard_client.moderate_prompt(prompt)
            labels = [item for item in ([value.overall_risk_level, value.suggest_action] + value.categories) if item]
            return ModerationGuardResult(
                guard_id=guard_id,
                guard_name=GUARD_NAMES[guard_id],
                label=value.overall_risk_level,
                risky=value.risky,
                blocked=value.blocked,
                connected=value.error is None,
                labels=labels,
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

    @staticmethod
    def _request_base_url(request: ModerationRequest) -> str | None:
        if request.vllm_port is None:
            return None
        return f"http://127.0.0.1:{request.vllm_port}/v1"

    @staticmethod
    def _safegauge_result(value: SafeGaugeAssessment) -> ModerationGuardResult:
        labels = [item for item in (value.task, value.label) if item]
        return ModerationGuardResult(
            guard_id="safegauge",
            guard_name=GUARD_NAMES["safegauge"],
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

    @staticmethod
    def _inline_probing_result(
        value: InlineProbingAssessment,
    ) -> ModerationGuardResult:
        return ModerationGuardResult(
            guard_id="inline_probing",
            guard_name=GUARD_NAMES["inline_probing"],
            label=value.label,
            risky=value.risky,
            blocked=value.blocked,
            connected=value.error is None,
            labels=[value.label] if value.label else [],
            probability=value.score,
            threshold=value.threshold,
            latency_ms=value.latency_ms,
            error=value.error,
        )


def dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
