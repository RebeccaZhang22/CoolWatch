import json
from collections.abc import AsyncIterator
from time import perf_counter

from backend.agent_loop import AgentLoop, AgentRunResult
from backend.evaluator import evaluate_leakage
from backend.scenarios import resolve_scenario
from backend.schemas import AgentTraceItem, ChatRequest, ChatResponse, GuardResult, LeakageMetrics, MatchedSpan, OutputGuardConfig
from backend.watchers import (
    GUARD_NAMES,
    SUGGESTION_TEXT,
    NeteaseYidunAssessment,
    NeteaseYidunClient,
    LlamaPromptGuardAssessment,
    LlamaPromptGuardClient,
    Qwen3GuardClient,
    QwenGuardAssessment,
    SafeGaugeAssessment,
    SafeGaugeClient,
    detect_attack_intent,
    evaluate_input_guard,
)


class ChatOrchestrator:
    def __init__(
        self,
        agent_loop: AgentLoop,
        qwen_guard_client: Qwen3GuardClient,
        llama_prompt_guard_client: LlamaPromptGuardClient,
        netease_yidun_client: NeteaseYidunClient,
        safegauge_client: SafeGaugeClient,
    ) -> None:
        self.agent_loop = agent_loop
        self.qwen_guard_client = qwen_guard_client
        self.llama_prompt_guard_client = llama_prompt_guard_client
        self.netease_yidun_client = netease_yidun_client
        self.safegauge_client = safegauge_client

    async def run(self, request: ChatRequest) -> ChatResponse:
        input_guard_assessments = await self._run_input_guard_checks(request)

        try:
            agent_result = await self.agent_loop.run(request)
        except Exception as error:
            return build_error_response(request, error)

        guard_results, matched_spans = run_external_guard_evaluation(request, agent_result, input_guard_assessments)
        leakage_summary = summarize_leakage(guard_results, request.output_guard)
        output_blocked = leakage_summary == "发现泄露"

        return ChatResponse(
            active_guard="baseline",
            assistant_message=build_assistant_message(agent_result.raw_output, output_blocked),
            guard_results=guard_results,
            leakage_summary=leakage_summary,
            output_blocked=output_blocked,
            output_guard=request.output_guard,
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
                    # Output is buffered until the post-generation guard decides whether it may be returned.
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
        if "llama_prompt_guard" in guard_ids:
            assessments["llama_prompt_guard"] = await self.llama_prompt_guard_client.moderate_prompt(request.message)
        if "netease_yidun" in guard_ids:
            assessments["netease_yidun"] = await self.netease_yidun_client.moderate_prompt(request.message)
        if "safegauge" in guard_ids:
            scenario = resolve_scenario(request.scenario_id, request.scenario)
            assessments["safegauge"] = await self.safegauge_client.moderate_messages(
                [
                    {"role": "system", "content": scenario.system_prompt},
                    {"role": "user", "content": request.message},
                ],
                threshold=request.safegauge.threshold,
            )
        return assessments


def build_chat_response(
    request: ChatRequest,
    agent_result: AgentRunResult,
    input_guard_assessments: dict[str, object],
) -> ChatResponse:
    guard_results, matched_spans = run_external_guard_evaluation(request, agent_result, input_guard_assessments)
    leakage_summary = summarize_leakage(guard_results, request.output_guard)
    output_blocked = leakage_summary == "发现泄露"
    return ChatResponse(
        active_guard="baseline",
        assistant_message=build_assistant_message(agent_result.raw_output, output_blocked),
        guard_results=guard_results,
        leakage_summary=leakage_summary,
        output_blocked=output_blocked,
        output_guard=request.output_guard,
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
        if guard_id == "llama_prompt_guard" and guard_id in input_guard_assessments:
            assessment = input_guard_assessments[guard_id]
            if not isinstance(assessment, LlamaPromptGuardAssessment):
                continue
            guard_results[guard_id] = build_llama_prompt_guard_result(
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
        if guard_id == "safegauge" and guard_id in input_guard_assessments:
            assessment = input_guard_assessments[guard_id]
            if not isinstance(assessment, SafeGaugeAssessment):
                continue
            guard_results[guard_id] = build_safegauge_result(
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


def build_llama_prompt_guard_result(
    assessment: LlamaPromptGuardAssessment,
    raw_output: str,
    leakage: LeakageMetrics,
) -> GuardResult:
    return GuardResult(
        guard_id="llama_prompt_guard",
        guard_name=GUARD_NAMES["llama_prompt_guard"],
        status=llama_prompt_guard_status(assessment),
        blocked=assessment.blocked,
        latency_ms=assessment.latency_ms,
        output=raw_output,
        raw_output=raw_output,
        leakage=leakage,
        query_risk=assessment.risky,
        matched_labels=[assessment.label] if assessment.label else [],
        connected=assessment.error is None,
        note=llama_prompt_guard_note(assessment),
        safety_label=assessment.label,
        task="prompt_injection_jailbreak",
        probability=assessment.probability,
        threshold=assessment.threshold,
        raw_guard_output=assessment.raw_output,
    )


def build_safegauge_result(
    assessment: SafeGaugeAssessment,
    raw_output: str,
    leakage: LeakageMetrics,
) -> GuardResult:
    labels = [value for value in [assessment.task, assessment.label] if value]
    return GuardResult(
        guard_id="safegauge",
        guard_name=GUARD_NAMES["safegauge"],
        status=safegauge_status(assessment),
        blocked=assessment.blocked,
        latency_ms=assessment.latency_ms,
        output=raw_output,
        raw_output=raw_output,
        leakage=leakage,
        query_risk=assessment.risky,
        matched_labels=labels,
        connected=assessment.error is None,
        note=safegauge_note(assessment),
        safety_label=assessment.label or None,
        task=assessment.task or None,
        probability=assessment.probability,
        threshold=assessment.threshold,
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


def llama_prompt_guard_status(assessment: LlamaPromptGuardAssessment) -> str:
    if assessment.error or assessment.risky is None:
        return "检测失败"
    return "命中风险" if assessment.risky else "未命中"


def llama_prompt_guard_note(assessment: LlamaPromptGuardAssessment) -> str:
    if assessment.error:
        return f"Llama Prompt Guard 2 调用失败：{assessment.error}"
    return f"恶意提示概率 {assessment.probability:.4f}；阈值 {assessment.threshold:.4f}。"


def netease_yidun_note(assessment: NeteaseYidunAssessment) -> str:
    if assessment.error:
        return f"网易易盾调用失败：{assessment.error}"

    return "输入护栏检测已完成。"


def safegauge_status(assessment: SafeGaugeAssessment) -> str:
    if assessment.error or assessment.risky is None:
        return "检测失败"
    return "命中风险" if assessment.risky else "未命中"


def safegauge_note(assessment: SafeGaugeAssessment) -> str:
    if assessment.error:
        return f"SafeGauge 调用失败：{assessment.error}"
    if assessment.probability is None or assessment.threshold is None:
        return "SafeGauge 检测已完成。"
    return (
        f"任务 {assessment.task or '-'}；标签 {assessment.label or '-'}；"
        f"概率 {assessment.probability:.4f}；阈值 {assessment.threshold:.4f}。"
    )


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
        output_blocked=False,
        output_guard=request.output_guard,
        matched_spans=[],
        rag_trace=[],
        agent_trace=trace,
    )


def find_agent_latency(trace: list[AgentTraceItem]) -> int:
    for item in trace:
        if item.name == "LLM Generate":
            return item.duration
    return 0


def summarize_leakage(guard_results: dict[str, GuardResult], output_guard: OutputGuardConfig) -> str:
    values = list(guard_results.values())
    if not values:
        return "未发现泄露"

    leakage = values[0].leakage
    if (
        leakage.exact_match >= output_guard.exact_match_threshold
        or leakage.rouge_l >= output_guard.rouge_l_threshold
    ):
        return "发现泄露"
    return "未发现泄露"


def build_assistant_message(raw_output: str, output_blocked: bool) -> str:
    if output_blocked:
        return "响应已被输出安全策略拦截。"
    return raw_output


def dedupe_matched_spans(spans: list[MatchedSpan]) -> list[MatchedSpan]:
    seen: set[str] = set()
    result: list[MatchedSpan] = []
    for span in spans:
        key = f"{span.source}:{span.text}"
        if key not in seen:
            seen.add(key)
            result.append(span)
    return result
