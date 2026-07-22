import json
from collections.abc import AsyncIterator

import httpx
from backend.config import Settings
from backend.schemas import ModelParams


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

    async def chat(self, messages: list[dict[str, str]], model_params: ModelParams) -> str:
        model = model_params.model or self.settings.vllm_model

        payload = {
            "model": model,
            "messages": messages,
            "temperature": model_params.temperature,
            "top_p": model_params.top_p,
            "max_tokens": model_params.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = await self._client.post(
            f"{self.settings.vllm_base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        return message.get("content") or message.get("reasoning") or ""

    async def stream_chat(self, messages: list[dict[str, str]], model_params: ModelParams) -> AsyncIterator[str]:
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
