from dataclasses import dataclass
from collections.abc import AsyncIterator
from time import perf_counter

from backend.llm_client import LlmClient
from backend.rag import build_rag_context, retrieve_context
from backend.schemas import AgentTraceItem, ChatRequest, RagTraceItem, ScenarioPayload
from backend.scenarios import resolve_scenario
from backend.session_store import SessionStore


MAX_HISTORY_CHARS = 12000


@dataclass
class AgentRunResult:
    scenario: ScenarioPayload
    assistant_message: str
    raw_output: str
    rag_trace: list[RagTraceItem]
    agent_trace: list[AgentTraceItem]


@dataclass
class AgentRunPrepared:
    scenario: ScenarioPayload
    messages: list[dict[str, str]]
    rag_trace: list[RagTraceItem]
    agent_trace: list[AgentTraceItem]
    session_history: list[dict[str, str]]


class AgentLoop:
    def __init__(self, llm_client: LlmClient, session_store: SessionStore) -> None:
        self.llm_client = llm_client
        self.session_store = session_store

    async def run(self, request: ChatRequest) -> AgentRunResult:
        prepared = self._prepare_run(request)

        started = perf_counter()
        raw_output = await self.llm_client.chat(prepared.messages, request.model_params)
        prepared.agent_trace.append(trace_item("LLM Generate", started, "OpenAI Compatible /chat/completions", "模型原始输出已返回"))

        self._commit_result(prepared.session_history, request.message, raw_output)
        prepared.agent_trace.append(AgentTraceItem(name="Result Commit", status="success", input="用户消息与助手回复", output="已写入会话", duration=0))

        return AgentRunResult(
            scenario=prepared.scenario,
            assistant_message=raw_output,
            raw_output=raw_output,
            rag_trace=prepared.rag_trace,
            agent_trace=prepared.agent_trace,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[tuple[str, str | AgentRunResult]]:
        prepared = self._prepare_run(request)

        chunks: list[str] = []
        started = perf_counter()
        async for delta in self.llm_client.stream_chat(prepared.messages, request.model_params):
            chunks.append(delta)
            yield "delta", delta

        raw_output = "".join(chunks)
        prepared.agent_trace.append(trace_item("LLM Generate", started, "OpenAI Compatible /chat/completions", "模型流式输出已返回"))
        self._commit_result(prepared.session_history, request.message, raw_output)
        prepared.agent_trace.append(AgentTraceItem(name="Result Commit", status="success", input="用户消息与助手回复", output="已写入会话", duration=0))

        yield "final", AgentRunResult(
            scenario=prepared.scenario,
            assistant_message=raw_output,
            raw_output=raw_output,
            rag_trace=prepared.rag_trace,
            agent_trace=prepared.agent_trace,
        )

    def _prepare_run(self, request: ChatRequest) -> AgentRunPrepared:
        trace: list[AgentTraceItem] = []
        scenario = resolve_scenario(request.scenario_id, request.scenario)

        started = perf_counter()
        session = self.session_store.get_or_create(request.session_id, scenario.id)
        trace.append(trace_item("Session Load", started, request.session_id, f"{scenario.name} / history={len(session.history)}"))

        started = perf_counter()
        if should_use_rag(scenario):
            rag_trace = retrieve_context(scenario, request.message)
            trace.append(trace_item("RAG Retrieve", started, scenario.target, f"{len(rag_trace)} 个片段召回"))
        else:
            rag_trace = []
            trace.append(AgentTraceItem(name="RAG Retrieve", status="skipped", input=scenario.target, output="当前场景不使用 RAG", duration=0))

        started = perf_counter()
        messages = self._build_messages(scenario.system_prompt, session.history, request.message, rag_trace)
        trace.append(trace_item("Context Build", started, "System Prompt + History + RAG", f"{len(messages)} 条消息"))

        return AgentRunPrepared(
            scenario=scenario,
            messages=messages,
            rag_trace=rag_trace,
            agent_trace=trace,
            session_history=session.history,
        )

    def _commit_result(self, history: list[dict[str, str]], user_message: str, raw_output: str) -> None:
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": raw_output})
        history[:] = trim_history_by_budget(history, max_chars=MAX_HISTORY_CHARS * 2)

    def _build_messages(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
        rag_trace: list[RagTraceItem],
    ) -> list[dict[str, str]]:
        rag_context = build_rag_context(rag_trace)
        system_content = system_prompt
        if rag_context:
            system_content = f"{system_prompt}\n\n{rag_context}"

        return [
            {"role": "system", "content": system_content},
            *trim_history_by_budget(history),
            {"role": "user", "content": user_message},
        ]


def trace_item(name: str, started: float, input_text: str, output_text: str) -> AgentTraceItem:
    return AgentTraceItem(
        name=name,
        status="success",
        input=input_text,
        output=output_text,
        duration=round((perf_counter() - started) * 1000),
    )


def should_use_rag(scenario: ScenarioPayload) -> bool:
    return "rag" in scenario.target.lower()


def trim_history_by_budget(history: list[dict[str, str]], max_chars: int = MAX_HISTORY_CHARS) -> list[dict[str, str]]:
    selected_pairs: list[list[dict[str, str]]] = []
    used_chars = 0
    index = len(history)

    while index > 0:
        if index >= 2 and history[index - 2].get("role") == "user" and history[index - 1].get("role") == "assistant":
            chunk = history[index - 2 : index]
            index -= 2
        else:
            chunk = [history[index - 1]]
            index -= 1

        chunk_cost = sum(len(message.get("content", "")) for message in chunk)
        if selected_pairs and used_chars + chunk_cost > max_chars:
            break
        selected_pairs.append(chunk)
        used_chars += chunk_cost

    result: list[dict[str, str]] = []
    for chunk in reversed(selected_pairs):
        result.extend(chunk)
    return result
