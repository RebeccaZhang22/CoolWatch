from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.watchers.inline_probing.client import InlineProbingGuard


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    async def post(self, url: str, *, headers: dict, json: dict):
        self.calls.append((url, headers, json))
        return FakeResponse(self.response)

    async def aclose(self) -> None:
        return None


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        inline_probing_timeout_seconds=10.0,
        inline_probing_threshold=0.76,
        inline_probing_expected_checkpoint_id="sha256:" + "a" * 64,
        inline_probing_protocol="inline_probing",
        vllm_model="gpt-oss-20b",
        vllm_base_url="http://127.0.0.1:8012/v1",
        vllm_api_key="EMPTY",
    )


@pytest.mark.asyncio
async def test_inline_probing_guard_sends_only_inline_probing_request() -> None:
    guard = InlineProbingGuard(settings())
    fake = FakeClient(
        {
            "inline_probing": {
                "schema": "inline_probing.result.v1",
                "status": "ok",
                "score": 0.9,
                "logit": 2.0,
                "checkpoint_id": "sha256:" + "a" * 64,
                "layer": 4,
                "effective_position": -1,
            }
        }
    )
    guard._client = fake

    assessment = await guard.moderate_messages(
        [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]
    )

    assert assessment.error is None
    assert assessment.score == 0.9
    assert assessment.risky is True
    payload = fake.calls[0][2]
    assert "inline_probing_request" in payload
    assert "fyh_probe_request" not in payload
    assert payload["inline_probing_request"]["schema"] == "inline_probing.request.v1"


@pytest.mark.asyncio
async def test_inline_probing_guard_preserves_tools_and_model_chat_template() -> None:
    guard = InlineProbingGuard(settings())
    guard._client = FakeClient(
        {
            "inline_probing": {
                "schema": "inline_probing.result.v1",
                "status": "ok",
                "score": 0.1,
                "logit": -2.0,
                "checkpoint_id": "sha256:" + "a" * 64,
            }
        }
    )
    tools = [{"type": "function", "function": {"name": "lookup"}}]

    assessment = await guard.moderate_messages(
        [{"role": "user", "content": "Look this up"}],
        tools=tools,
        tool_choice="auto",
    )

    assert assessment.error is None
    payload = guard._client.calls[0][2]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert "chat_template_kwargs" not in payload


@pytest.mark.asyncio
async def test_inline_probing_guard_fails_if_server_omits_inline_probing() -> None:
    guard = InlineProbingGuard(settings())
    guard._client = FakeClient({"choices": []})

    assessment = await guard.moderate_messages(
        [{"role": "user", "content": "Hello"}]
    )

    assert assessment.error is not None
    assert "inline_probing" in assessment.error
    assert assessment.risky is None
