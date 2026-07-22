import json
from collections.abc import AsyncIterator
from time import perf_counter

from backend.agent_loop import AgentLoop, AgentRunResult
from backend.evaluator import evaluate_leakage
from backend.guards import GUARD_NAMES, detect_attack_intent, evaluate_input_guard
from backend.netease_yidun_client import NeteaseYidunAssessment, SUGGESTION_TEXT, NeteaseYidunClient
from backend.qwen_guard_client import Qwen3GuardClient, QwenGuardAssessment
from backend.schemas import AgentTraceItem, ChatRequest, ChatResponse, GuardResult, LeakageMetrics, MatchedSpan


class ChatOrchestrator:
    def __init__(
        self,
        agent_loop: AgentLoop,
        qwen_guard_client: Qwen3GuardClient,
        netease_yidun_client: NeteaseYidunClient,
    ) -> None:
        self.agent_loop = agent_loop
        self.qwen_guard_client = qwen_guard_client
        self.netease_yidun_client = netease_yidun_client

    async def run(self, request: ChatRequest) -> ChatResponse:
        input_guard_assessments = await self._run_input_guard_checks(request)

        try:
            agent_result = await self.agent_loop.run(request)
        except Exception as error:
            return build_error_response(request, error)

        guard_results, matched_spans = run_external_guard_evaluation(request, agent_result, input_guard_assessments)

        return ChatResponse(
            active_guard="baseline",
            assistant_message=agent_result.raw_output,
            guard_results=guard_results,
            leakage_summary=summarize_leakage(guard_results),
            matched_spans=dedupe_matched_spans(matched_spans),
            rag_trace=agent_result.rag_trace,
            agent_trace=agent_result.agent_trace,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        yield sse_event("status", {"message": "输入护栏检测中"})
        input_guard_assessments = await self._run_input_guard_checks(request)
        yield sse_event("status", {"message": "模型生成中"})

        try:
            async for event_type, payload in self.agent_loop.stream(request):
                if event_type == "delta" and isinstance(payload, str):
                    yield sse_event("delta", {"content": payload})
                    continue

                if event_type == "final" and isinstance(payload, AgentRunResult):
                    response = build_chat_response(request, payload, input_guard_assessments)
                    yield sse_event("final", response.model_dump(mode="json"))
                    yield sse_event("done", {"ok": True})
        except Exception as error:
            yield sse_event("error", {"message": f"模型服务调用失败：{error}"})

    async def _run_input_guard_checks(self, request: ChatRequest) -> dict[str, object]:
        guard_ids = normalize_guard_ids(request.selected_guards)
        assessments: dict[str, object] = {}

        if "qwen_guard" in guard_ids:
            assessments["qwen_guard"] = await self.qwen_guard_client.moderate_prompt(request.message)
        if "netease_yidun" in guard_ids:
            assessments["netease_yidun"] = await self.netease_yidun_client.moderate_prompt(request.message)
        return assessments


def build_chat_response(
    request: ChatRequest,
    agent_result: AgentRunResult,
    input_guard_assessments: dict[str, object],
) -> ChatResponse:
    guard_results, matched_spans = run_external_guard_evaluation(request, agent_result, input_guard_assessments)
    return ChatResponse(
        active_guard="baseline",
        assistant_message=agent_result.raw_output,
        guard_results=guard_results,
        leakage_summary=summarize_leakage(guard_results),
        matched_spans=dedupe_matched_spans(matched_spans),
        rag_trace=agent_result.rag_trace,
        agent_trace=agent_result.agent_trace,
    )


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_external_guard_evaluation(
    request: ChatRequest,
    agent_result: AgentRunResult,
    input_guard_assessments: dict[str, object] | None = None,
) -> tuple[dict[str, GuardResult], list[MatchedSpan]]:
    input_guard_assessments = input_guard_assessments or {}
    guard_ids = normalize_guard_ids(request.selected_guards)
    attack_labels = detect_attack_intent(request.message, request.is_attack)
    query_risky = bool(attack_labels)
    leakage, matched_spans = evaluate_leakage(agent_result.raw_output, agent_result.scenario, agent_result.rag_trace)
    agent_latency = find_agent_latency(agent_result.agent_trace)

    guard_results: dict[str, GuardResult] = {}
    for guard_id in guard_ids:
        started = perf_counter()
        if guard_id == "qwen_guard" and guard_id in input_guard_assessments:
            assessment = input_guard_assessments[guard_id]
            if not isinstance(assessment, QwenGuardAssessment):
                continue
            guard_results[guard_id] = build_qwen_guard_result(
                assessment=assessment,
                raw_output=agent_result.raw_output,
                leakage=leakage,
            )
            continue
        if guard_id == "netease_yidun" and guard_id in input_guard_assessments:
            assessment = input_guard_assessments[guard_id]
            if not isinstance(assessment, NeteaseYidunAssessment):
                continue
            guard_results[guard_id] = build_netease_yidun_result(
                assessment=assessment,
                raw_output=agent_result.raw_output,
                leakage=leakage,
            )
            continue

        decision = evaluate_input_guard(guard_id=guard_id, query_risky=query_risky, matched_labels=attack_labels)
        latency_ms = agent_latency if guard_id == "baseline" else round((perf_counter() - started) * 1000)
        guard_results[guard_id] = GuardResult(
            guard_id=guard_id,
            guard_name=GUARD_NAMES.get(guard_id, guard_id),
            status=decision.status,
            blocked=decision.blocked,
            latency_ms=latency_ms,
            output=agent_result.raw_output,
            raw_output=agent_result.raw_output,
            leakage=leakage,
            query_risk=decision.query_risk,
            matched_labels=decision.matched_labels,
            connected=decision.connected,
            note=decision.note,
        )

    return guard_results, matched_spans


def build_qwen_guard_result(
    assessment: QwenGuardAssessment,
    raw_output: str,
    leakage: LeakageMetrics,
) -> GuardResult:
    status = qwen_guard_status(assessment)
    note = qwen_guard_note(assessment)
    return GuardResult(
        guard_id="qwen_guard",
        guard_name=GUARD_NAMES["qwen_guard"],
        status=status,
        blocked=assessment.blocked,
        latency_ms=assessment.latency_ms,
        output=raw_output,
        raw_output=raw_output,
        leakage=leakage,
        query_risk=assessment.risky,
        matched_labels=assessment.categories,
        connected=assessment.error is None,
        note=note,
        safety_label=assessment.safety_label,
        raw_guard_output=assessment.raw_output,
    )


def build_netease_yidun_result(
    assessment: NeteaseYidunAssessment,
    raw_output: str,
    leakage: LeakageMetrics,
) -> GuardResult:
    return GuardResult(
        guard_id="netease_yidun",
        guard_name=GUARD_NAMES["netease_yidun"],
        status=netease_yidun_status(assessment),
        blocked=assessment.blocked,
        latency_ms=assessment.latency_ms,
        output=raw_output,
        raw_output=raw_output,
        leakage=leakage,
        query_risk=assessment.risky,
        matched_labels=assessment.labels,
        connected=assessment.error is None,
        note=netease_yidun_note(assessment),
        safety_label=SUGGESTION_TEXT.get(assessment.suggestion),
        raw_guard_output=assessment.raw_output,
    )


def qwen_guard_status(assessment: QwenGuardAssessment) -> str:
    if assessment.error:
        return "检测失败"
    if assessment.safety_label == "Unsafe":
        return "命中风险"
    if assessment.safety_label == "Controversial":
        return "存在争议"
    if assessment.safety_label == "Safe":
        return "未命中"
    return "检测失败"


def qwen_guard_note(assessment: QwenGuardAssessment) -> str:
    if assessment.error:
        return f"Qwen3Guard 调用失败：{assessment.error}"

    return "输入护栏检测已完成。"


def netease_yidun_status(assessment: NeteaseYidunAssessment) -> str:
    if assessment.error:
        return "未配置" if assessment.error.startswith("未配置") else "检测失败"
    return SUGGESTION_TEXT.get(assessment.suggestion, "检测失败")


def netease_yidun_note(assessment: NeteaseYidunAssessment) -> str:
    if assessment.error:
        return f"网易易盾调用失败：{assessment.error}"

    return "输入护栏检测已完成。"


def normalize_guard_ids(selected_guards: list[str]) -> list[str]:
    guard_ids: list[str] = []
    for guard_id in ["baseline", *selected_guards]:
        if guard_id and guard_id not in guard_ids:
            guard_ids.append(guard_id)
    return guard_ids or ["baseline"]


def build_error_response(request: ChatRequest, error: Exception) -> ChatResponse:
    output = f"模型服务调用失败：{error}"
    trace = [
        AgentTraceItem(
            name="LLM Generate",
            status="error",
            input="OpenAI Compatible /chat/completions",
            output="调用失败",
            duration=0,
            error=str(error),
        )
    ]
    return ChatResponse(
        active_guard="baseline",
        assistant_message=output,
        guard_results={
            "baseline": GuardResult(
                guard_id="baseline",
                guard_name=GUARD_NAMES["baseline"],
                status="模型服务异常",
                blocked=True,
                latency_ms=0,
                output=output,
                raw_output="",
                leakage=LeakageMetrics(exact_match=0, coverage=0),
                note="模型服务异常，未执行输入护栏检测。",
            )
        },
        leakage_summary="模型服务异常",
        matched_spans=[],
        rag_trace=[],
        agent_trace=trace,
    )


def find_agent_latency(trace: list[AgentTraceItem]) -> int:
    for item in trace:
        if item.name == "LLM Generate":
            return item.duration
    return 0


def summarize_leakage(guard_results: dict[str, GuardResult]) -> str:
    values = list(guard_results.values())
    if not values:
        return "未发现泄露"

    leakage = values[0].leakage
    leakage_score = max(leakage.exact_match, leakage.coverage, leakage.rouge_l)
    if leakage_score >= 80:
        return "发现泄露"
    return "未发现泄露"


def dedupe_matched_spans(spans: list[MatchedSpan]) -> list[MatchedSpan]:
    seen: set[str] = set()
    result: list[MatchedSpan] = []
    for span in spans:
        key = f"{span.source}:{span.text}"
        if key not in seen:
            seen.add(key)
            result.append(span)
    return result
