from types import SimpleNamespace

import pytest

from backend.agent_loop import AgentLoop
from backend.agent_loop import AgentRunResult
from backend.chat_orchestrator import run_external_guard_evaluation
from backend.llm_client import LlmClient, LlmGeneration
from backend.schemas import AgentTraceItem, ChatRequest, ModelParams
from backend.scenarios import DEFAULT_SCENARIOS
from backend.session_store import SessionStore
from backend.watchers.inline_probing import InlineProbingAssessment


CHECKPOINT_ID = "sha256:" + "b" * 64


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"role": "assistant", "content": "final answer"}}],
            "inline_probing": {
                "schema": "inline_probing.result.v1",
                "status": "ok",
                "score": 0.8,
                "logit": 1.4,
                "checkpoint_id": CHECKPOINT_ID,
                "layer": 4,
                "effective_position": -1,
            },
        }


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        llm_timeout_seconds=30.0,
        vllm_base_url="http://127.0.0.1:8013/v1",
        vllm_api_key="EMPTY",
        vllm_model="qwen3-8b",
        inline_probing_threshold=0.5,
        inline_probing_expected_checkpoint_id=CHECKPOINT_ID,
        inline_probing_timeout_seconds=10.0,
    )


@pytest.mark.asyncio
async def test_real_generation_request_carries_probe_and_returns_both_outputs() -> None:
    client = LlmClient(settings())
    fake = FakeHttpClient()
    await client._client.aclose()
    client._client = fake
    messages = [
        {"role": "user", "content": "question"},
        {"role": "tool", "tool_call_id": "call-1", "content": "full tool result"},
    ]

    result = await client.generate(
        messages,
        ModelParams(model="qwen3-8b", max_tokens=128),
        enable_inline_probing=True,
        inline_probing_threshold=0.5,
    )

    assert len(fake.calls) == 1
    payload = fake.calls[0]["json"]
    assert payload["messages"] == messages
    assert payload["max_tokens"] == 128
    assert payload["inline_probing_request"]["expected_checkpoint_id"] == CHECKPOINT_ID
    assert result.content == "final answer"
    assert result.inline_probing is not None
    assert result.inline_probing.risky is True


class RecordingLlmClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, messages, model_params, **kwargs) -> LlmGeneration:
        self.calls.append({"messages": messages, **kwargs})
        assessment = None
        if kwargs["enable_inline_probing"]:
            assessment = InlineProbingAssessment(
                score=0.8,
                logit=1.4,
                threshold=0.5,
                checkpoint_id=CHECKPOINT_ID,
                layer=4,
                effective_position=-1,
                protocol="inline_probing",
                raw_output="{}",
                latency_ms=12,
            )
        return LlmGeneration(
            content="agent decision",
            message={"role": "assistant", "content": "agent decision"},
            inline_probing=assessment,
        )


@pytest.mark.asyncio
async def test_agent_loop_probes_first_real_decision_after_full_rag_tool_result() -> None:
    llm = RecordingLlmClient()
    loop = AgentLoop(llm, SessionStore(), None)
    request = ChatRequest(
        session_id="rag-session",
        message="请回答问题",
        scenario_id="knowledge",
        selected_guards=["inline_probing"],
        model_params=ModelParams(model="qwen3-8b"),
        inline_probing={"threshold": 0.5},
    )

    result = await loop.run(request)

    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["enable_inline_probing"] is True
    assert call["messages"][-1]["role"] == "tool"
    assert "以下是本轮 RAG 检索到的上下文片段" in call["messages"][-1]["content"]
    assert call["tools"][0]["function"]["name"] == "retrieve_context"
    assert call["tool_choice"] == "none"
    assert result.inline_probing_assessment is not None


@pytest.mark.asyncio
async def test_agent_loop_does_not_probe_when_no_tool_result_exists() -> None:
    llm = RecordingLlmClient()
    loop = AgentLoop(llm, SessionStore(), None)
    request = ChatRequest(
        session_id="plain-session",
        message="hello",
        scenario_id="support",
        selected_guards=["inline_probing"],
    )

    result = await loop.run(request)

    assert llm.calls[0]["enable_inline_probing"] is False
    assert result.inline_probing_assessment is None


def test_orchestrator_reports_selected_probe_as_not_triggered_without_tool_result() -> None:
    request = ChatRequest(
        session_id="plain-session",
        message="hello",
        selected_guards=["inline_probing"],
        inline_probing={"threshold": 0.5},
    )
    agent_result = AgentRunResult(
        scenario=DEFAULT_SCENARIOS["support"],
        assistant_message="answer",
        raw_output="answer",
        rag_trace=[],
        agent_trace=[
            AgentTraceItem(
                name="LLM Generate",
                status="success",
                input="request",
                output="response",
                duration=10,
            )
        ],
    )

    guard_results, _ = run_external_guard_evaluation(request, agent_result)

    assert guard_results["inline_probing"].status == "未触发"
    assert guard_results["inline_probing"].query_risk is None
    assert guard_results["inline_probing"].blocked is False
