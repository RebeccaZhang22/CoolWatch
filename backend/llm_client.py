import json
from dataclasses import dataclass
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

import httpx
from backend.config import Settings
from backend.schemas import ModelParams
from backend.watchers.inline_probing.client import (
    InlineProbingAssessment,
    assessment_from_probe_result,
    build_inline_probing_request,
    parse_inline_probing_response,
)


@dataclass(frozen=True)
class LlmGeneration:
    content: str
    message: dict[str, Any]
    inline_probing: InlineProbingAssessment | None = None


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        response = await self._client.get(f"{self.settings.vllm_base_url}/models", headers=self._headers())
        response.raise_for_status()
        payload = response.json()
        return [item["id"] for item in payload.get("data", []) if item.get("id")]

    async def chat(self, messages: list[dict[str, Any]], model_params: ModelParams) -> str:
        generation = await self.generate(messages, model_params)
        return generation.content

    async def generate(
        self,
        messages: list[dict[str, Any]],
        model_params: ModelParams,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        enable_inline_probing: bool = False,
        inline_probing_threshold: float | None = None,
    ) -> LlmGeneration:
        model = model_params.model or self.settings.vllm_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": model_params.temperature,
            "top_p": model_params.top_p,
            "max_tokens": model_params.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        threshold = (
            self.settings.inline_probing_threshold
            if inline_probing_threshold is None
            else float(inline_probing_threshold)
        )
        if enable_inline_probing:
            payload["inline_probing_request"] = build_inline_probing_request(
                payload,
                expected_checkpoint_id=self.settings.inline_probing_expected_checkpoint_id,
                timeout_seconds=self.settings.inline_probing_timeout_seconds,
            )
        started = perf_counter()
        response = await self._client.post(
            f"{self.settings.vllm_base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        assessment = None
        if enable_inline_probing:
            result = parse_inline_probing_response(
                data,
                expected_checkpoint_id=self.settings.inline_probing_expected_checkpoint_id,
            )
            assessment = assessment_from_probe_result(
                result,
                threshold=threshold,
                latency_ms=round((perf_counter() - started) * 1000),
            )
        return LlmGeneration(
            content=message.get("content") or message.get("reasoning") or "",
            message=message,
            inline_probing=assessment,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model_params: ModelParams,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> AsyncIterator[str]:
        model = model_params.model or self.settings.vllm_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": model_params.temperature,
            "top_p": model_params.top_p,
            "max_tokens": model_params.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        async with self._client.stream(
            "POST",
            f"{self.settings.vllm_base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                chunk = parse_openai_stream_line(line)
                if chunk is None:
                    continue
                if chunk == "[DONE]":
                    break
                if chunk:
                    yield chunk

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.vllm_api_key}"}


def parse_openai_stream_line(line: str) -> str | None:
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None

    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return "[DONE]"

    payload = json.loads(data)
    choice = payload.get("choices", [{}])[0]
    delta = choice.get("delta") or {}
    return delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning") or ""
