from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.config import Settings
from backend.customer_agent_config import CustomerAgentRuntimeConfig
from backend.customer_agent_rag import tokenize_for_bm25
from backend.customer_agent_catalog import (
    SCENARIO,
    build_knowledge_tool_result,
    lookup_order,
    public_asset_descriptors,
    public_knowledge_sources,
)
from backend.customer_agent_schemas import (
    AttackId,
    CustomerAgentBootstrapResponse,
    CustomerAgentCompareRequest,
    CustomerAgentCompareResponse,
    CustomerAgentDefenseEffect,
    CustomerAgentDefenseSignal,
    CustomerAgentHealthResponse,
    CustomerAgentProfileResponse,
    CustomerAgentRagTraceItem,
    CustomerAgentRunRequest,
    CustomerAgentRunResponse,
    CustomerAgentStageTraceItem,
    CustomerAgentToolTraceItem,
    DefenseId,
)
from backend.customer_agent_security import (
    build_attack_assessment,
    build_reasoning_report,
    evaluate_asset_exposures,
    mark_rag_demo_exposure,
    with_delivery_status,
)
from backend.llm_client import LlmClient
from backend.schemas import ModelParams
from backend.session_store import ChatSession, SessionStore
from backend.watchers.activation_probe import ActivationProbeGuard
from backend.watchers.llama_prompt_guard import (
    LlamaPromptGuardAssessment,
    LlamaPromptGuardClient,
)
from backend.watchers.netease_yidun import (
    SUGGESTION_TEXT,
    NeteaseYidunAssessment,
    NeteaseYidunClient,
)
from backend.watchers.qwen_guard import Qwen3GuardClient, QwenGuardAssessment
from backend.watchers.safegauge.client import SafeGaugeAssessment, SafeGaugeGuard


CUSTOMER_AGENT_ID = SCENARIO.id
DEFENSE_ORDER: tuple[DefenseId, ...] = SCENARIO.defense_pipeline
DEFENSE_STAGE = {
    "activation_probe": "input",
    "safegauge": "input",
    "qwen_guard": "input",
    "llama_prompt_guard": "input",
    "netease_yidun": "input",
}
MAX_CUSTOMER_HISTORY_CHARS = 8000
MAX_AGENT_MODEL_TURNS = 4
MAX_TOOL_CALLS_PER_TURN = 4
DELIVERY_CHUNK_SIZE = 6
DELIVERY_CHUNK_DELAY_SECONDS = 0.018
RUNTIME_PROBE_DEFENSES = frozenset(
    {"activation_probe", "safegauge"}
)
EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class CustomerServiceAgent:
    """The sandboxed customer-service Agent behind the single-Agent console."""

    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: LlmClient,
        shadow_llm_client: LlmClient | None = None,
        session_store: SessionStore,
        activation_probe_guard: ActivationProbeGuard,
        safegauge_guard: SafeGaugeGuard,
        qwen_guard_client: Qwen3GuardClient,
        llama_prompt_guard_client: LlamaPromptGuardClient,
        netease_yidun_client: NeteaseYidunClient,
        runtime_config: CustomerAgentRuntimeConfig | None = None,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        # A separate client is deliberately optional for backwards-compatible
        # unit tests and local integrations. Production app wiring supplies it
        # to expose shadow-model health and keep the two-model boundary. Actual
        # hidden-state/logprob prefill requests are issued by the probe guards.
        self.shadow_llm_client = shadow_llm_client
        self._dual_model_enabled = (
            shadow_llm_client is not None and shadow_llm_client is not llm_client
        )
        self.session_store = session_store
        self.activation_probe_guard = activation_probe_guard
        self.safegauge_guard = safegauge_guard
        self.qwen_guard_client = qwen_guard_client
        self.llama_prompt_guard_client = llama_prompt_guard_client
        self.netease_yidun_client = netease_yidun_client
        self.runtime_config = runtime_config or CustomerAgentRuntimeConfig()

    def bootstrap(self) -> CustomerAgentBootstrapResponse:
        scenario, _ = self.runtime_config.snapshot()
        return CustomerAgentBootstrapResponse(
            profile=self.profile(),
            conversation_starters=[
                starter.model_copy(deep=True)
                for starter in scenario.conversation_starters
            ],
        )

    def profile(self) -> CustomerAgentProfileResponse:
        scenario, _ = self.runtime_config.snapshot()
        return CustomerAgentProfileResponse(
            id=scenario.id,
            name=scenario.name,
            description=scenario.description,
            model=self.settings.customer_agent_model or scenario.default_model,
            reasoning_enabled=True,
            capabilities=list(scenario.capabilities),
            tools=[str(tool["function"]["name"]) for tool in scenario.tools],
            knowledge_sources=public_knowledge_sources(scenario),
            protected_assets=public_asset_descriptors(scenario),
            # The profile is the scenario catalog. Runtime availability is
            # reported separately by health(). This keeps the console stable
            # when a plain vLLM temporarily disables probe-backed methods.
            defense_pipeline=list(scenario.defense_pipeline),
        )

    async def health(self) -> CustomerAgentHealthResponse:
        base_url = self.settings.customer_agent_business_base_url
        shadow_base_url = self.settings.customer_agent_shadow_base_url
        shadow_available: bool | None = None
        shadow_error: str | None = None
        try:
            models = await self.llm_client.list_models(base_url=base_url)
            available = self.settings.customer_agent_model in models
            if self._dual_model_enabled:
                try:
                    shadow_models = await self.shadow_llm_client.list_models(base_url=shadow_base_url)
                    shadow_available = self.settings.customer_agent_shadow_model in shadow_models
                    if not shadow_available:
                        shadow_error = f"模型列表中没有 {self.settings.customer_agent_shadow_model}"
                except Exception as error:
                    shadow_available = False
                    shadow_error = str(error)
            return CustomerAgentHealthResponse(
                status="ready" if available else "degraded",
                base_url=base_url,
                model=self.settings.customer_agent_model,
                model_available=available,
                defense_methods=list(self._enabled_defenses()),
                shadow_base_url=shadow_base_url if self._dual_model_enabled else None,
                shadow_model=self.settings.customer_agent_shadow_model if self._dual_model_enabled else None,
                shadow_available=shadow_available,
                shadow_error=shadow_error,
                error=None if available else f"模型列表中没有 {self.settings.customer_agent_model}",
            )
        except Exception as error:
            return CustomerAgentHealthResponse(
                status="degraded",
                base_url=base_url,
                model=self.settings.customer_agent_model,
                model_available=False,
                defense_methods=list(self._enabled_defenses()),
                shadow_base_url=shadow_base_url if self._dual_model_enabled else None,
                shadow_model=self.settings.customer_agent_shadow_model if self._dual_model_enabled else None,
                shadow_available=False if self._dual_model_enabled else None,
                shadow_error=shadow_error,
                error=str(error),
            )

    def reset_session(self, session_id: str) -> int:
        self.session_store.reset(session_id)
        return self.runtime_config.clear_uploaded_rag_documents()

    async def run(
        self,
        request: CustomerAgentRunRequest,
        *,
        event_sink: EventSink | None = None,
    ) -> CustomerAgentRunResponse:
        scenario, retriever = self.runtime_config.snapshot()
        attack = _scenario_attack(scenario, request.attack_id) if request.attack_id else None
        user_message = request.message or (attack.prompt if attack else "")
        enabled_defenses = set(self._enabled_defenses())
        requested_defenses = [
            defense_id
            for defense_id in request.defenses
            if defense_id in enabled_defenses
        ]
        selected = (
            set(requested_defenses)
            if request.defense_mode == "defended"
            else set()
        )
        model_params = self._business_model_params(request.model_params)
        base_url = self._base_url(model_params)
        guard_model_params = (
            self._shadow_model_params(request.model_params)
            if self._dual_model_enabled
            else model_params
        )
        guard_base_url = (
            self._shadow_base_url()
            if self._dual_model_enabled
            else base_url
        )
        stage_trace: list[CustomerAgentStageTraceItem] = []

        started = perf_counter()
        session = self._session(request.session_id, scenario.id)
        stage_trace.append(
            _stage(
                "session",
                "success",
                started,
                f"会话已加载，历史消息 {len(session.history)} 条",
            )
        )
        await _emit_event(
            event_sink,
            phase="session",
            message="会话已就绪",
            detail=f"已载入 {len(session.history)} 条历史消息",
        )

        guard_started = perf_counter()
        await _emit_event(
            event_sink,
            phase="input_guard",
            message="正在检查用户消息",
            detail="输入侧防护并行运行",
        )
        signals = await self._run_input_guards(
            user_message=user_message,
            selected=selected,
            model_params=guard_model_params,
            base_url=guard_base_url,
            safegauge_threshold=request.safegauge_threshold,
            probe_threshold=request.probe_threshold,
            system_prompt=scenario.system_prompt,
        )
        input_risk_detected = any(signal.status == "risk" for signal in signals)
        # Input detectors run as an observation sidecar. A risk finding is
        # recorded for the inspector, but the original query always continues
        # into the business Agent loop.
        input_guard_failed = any(signal.status == "error" for signal in signals)
        input_guards_enabled = bool(selected)
        completed_signals = _complete_signals(signals, requested_defenses)
        stage_trace.append(
            _stage(
                "input_guard",
                (
                    "error"
                    if input_guard_failed
                    else "success" if input_guards_enabled else "skipped"
                ),
                guard_started,
                (
                    "部分输入检测异常，详情见防护信号"
                    if input_guard_failed
                    else "输入检测命中风险，已标记并继续业务生成"
                    if input_risk_detected
                    else "输入检测完成"
                    if input_guards_enabled
                    else "观察模式未执行输入防护"
                ),
            )
        )
        attempted = request.attack_id is not None
        if input_guards_enabled:
            await _emit_event(
                event_sink,
                phase="input_guard",
                message=(
                    "部分检测器运行异常"
                    if input_guard_failed
                    else "检测到风险"
                    if input_risk_detected
                    else "输入安全检测已完成"
                ),
                detail=(
                    "检测结果已更新，业务模型将继续生成响应"
                    if input_guard_failed
                    else "风险信号仅用于审计，业务模型将继续生成响应"
                    if input_risk_detected
                    else "所有已启用方法均已返回结果"
                ),
                status=(
                    "error"
                    if input_guard_failed
                    else "risk"
                    if input_risk_detected
                    else "success"
                ),
                defense_signals=completed_signals,
            )

        (
            raw_output,
            private_reasoning,
            rag_trace,
            tool_trace,
            usage,
        ) = await self._run_model_tool_loop(
            session=session,
            user_message=user_message,
            base_url=base_url,
            model_params=model_params,
            request=request,
            stage_trace=stage_trace,
            event_sink=event_sink,
            scenario=scenario,
            retriever=retriever,
        )

        raw_exposures = evaluate_asset_exposures(
            raw_output,
            private_assets=scenario.private_assets,
        )
        raw_exposures = mark_rag_demo_exposure(
            raw_output,
            raw_exposures,
            rag_trace,
            attack_id=request.attack_id,
        )
        output_blocked = False
        assistant_message = raw_output
        blocked_stage = None
        exposures = with_delivery_status(raw_exposures, delivered=not output_blocked)
        reasoning = build_reasoning_report(
            private_reasoning,
            raw_output,
            requested=True,
            delivered=not output_blocked,
        )

        context_risk = any(
            item.included and "prompt_injection" in item.risk_flags
            for item in rag_trace
        )
        attempted = attempted or context_risk or any(
            signal.status == "risk" for signal in signals
        )

        attack_assessment = build_attack_assessment(
            request.attack_id,
            exposures,
            reasoning,
            assistant_message,
            attempted=attempted,
            blocked_stage=blocked_stage,
            scenario=scenario,
        )
        verdict = _verdict(attack_assessment.success, attempted, output_blocked)

        commit_started = perf_counter()
        self._commit(session, user_message, assistant_message)
        stage_trace.append(_stage("commit", "success", commit_started, "仅保存客户端可见消息"))
        await _emit_event(
            event_sink,
            phase="commit",
            message="本轮对话已完成",
            detail="会话历史只保存用户可见内容",
        )

        return CustomerAgentRunResponse(
            run_id=f"run-{uuid4().hex[:12]}",
            session_id=session.session_id,
            defense_mode=request.defense_mode,
            model=model_params.model,
            reasoning=reasoning,
            assistant_message=assistant_message,
            output_blocked=output_blocked,
            verdict=verdict,
            attack=attack_assessment,
            defense_signals=completed_signals,
            asset_exposures=exposures,
            rag_trace=rag_trace,
            tool_trace=tool_trace,
            stage_trace=stage_trace,
            usage=usage,
        )

    async def stream_events(
        self,
        request: CustomerAgentRunRequest,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def event_sink(payload: dict[str, Any]) -> None:
            await queue.put(("status", payload))

        async def execute() -> None:
            ok = False
            try:
                response = await self.run(request, event_sink=event_sink)
                # Input guards have completed before generation starts, so the
                # selected Agent answer can be streamed without a generation
                # side detector delaying delivery.
                for content in _delivery_chunks(response.assistant_message):
                    await queue.put(("delta", {"content": content}))
                    await asyncio.sleep(DELIVERY_CHUNK_DELAY_SECONDS)
                await queue.put(("final", response.model_dump(mode="json")))
                ok = True
            except Exception as error:
                await queue.put(("error", {"message": str(error)}))
            finally:
                await queue.put(("done", {"ok": ok}))

        task = asyncio.create_task(execute())
        try:
            while True:
                event, payload = await queue.get()
                yield event, payload
                if event == "done":
                    break
        finally:
            await task

    async def compare(
        self,
        request: CustomerAgentCompareRequest,
    ) -> CustomerAgentCompareResponse:
        scenario, _ = self.runtime_config.snapshot()
        attack = _scenario_attack(scenario, request.attack_id) if request.attack_id else None
        input_message = request.message or (attack.prompt if attack else "")
        common = {
            "attack_id": request.attack_id,
            "message": input_message,
            "defenses": request.defenses,
            "model_params": request.model_params,
            "safegauge_threshold": request.safegauge_threshold,
            "probe_threshold": request.probe_threshold,
        }
        baseline = await self.run(
            CustomerAgentRunRequest(defense_mode="baseline", **common)
        )
        defended = await self.run(
            CustomerAgentRunRequest(defense_mode="defended", **common)
        )
        baseline_leaks = sum(
            exposure.exposed_to_client for exposure in baseline.asset_exposures
        )
        defended_leaks = sum(
            exposure.exposed_to_client for exposure in defended.asset_exposures
        )
        prevented = baseline.attack.success and not defended.attack.success
        if prevented:
            summary = "同一条消息在无防护基线中造成风险，在防护链路中未造成风险。"
        elif baseline.attack.success and defended.attack.success:
            summary = "防护开启后仍观察到风险，需要调整阈值、策略或探针。"
        elif defended.output_blocked:
            summary = "基线未观察到成功泄漏，但防护链路识别风险并阻断了交付。"
        else:
            summary = "本次基线与防护运行均未观察到风险结果，结果按真实模型输出记录。"
        effect = CustomerAgentDefenseEffect(
            baseline_success=baseline.attack.success,
            defended_success=defended.attack.success,
            prevented=prevented,
            baseline_leaked_assets=baseline_leaks,
            defended_leaked_assets=defended_leaks,
            leakage_reduction=max(0, baseline_leaks - defended_leaks),
            blocked_stage=defended.attack.blocked_stage,
            summary=summary,
        )
        return CustomerAgentCompareResponse(
            input_message=input_message,
            attack=attack,
            baseline=baseline,
            defended=defended,
            effect=effect,
        )

    async def _run_input_guards(
        self,
        *,
        user_message: str,
        selected: set[DefenseId],
        model_params: ModelParams,
        base_url: str,
        safegauge_threshold: float | None,
        probe_threshold: float | None,
        system_prompt: str,
    ) -> list[CustomerAgentDefenseSignal]:
        signals: list[CustomerAgentDefenseSignal] = []
        tasks: list[tuple[DefenseId, Any]] = []
        if "activation_probe" in selected:
            tasks.append(
                (
                    "activation_probe",
                    self.activation_probe_guard.moderate_messages(
                        system_prompt=system_prompt,
                        user_message=user_message,
                        scenario_category="prompt",
                        model=model_params.model,
                        threshold=probe_threshold,
                        base_url=base_url,
                    ),
                )
            )
        if "safegauge" in selected:
            tasks.append(
                (
                    "safegauge",
                    self.safegauge_guard.moderate_messages(
                        [{"role": "user", "content": user_message}],
                        threshold=safegauge_threshold,
                        task="system_prompt_leakage_intent",
                        model=model_params.model,
                        base_url=base_url,
                    ),
                )
            )
        if "qwen_guard" in selected:
            tasks.append(
                (
                    "qwen_guard",
                    self.qwen_guard_client.moderate_prompt(user_message),
                )
            )
        if "llama_prompt_guard" in selected:
            tasks.append(
                (
                    "llama_prompt_guard",
                    self.llama_prompt_guard_client.moderate_prompt(user_message),
                )
            )
        if "netease_yidun" in selected:
            tasks.append(
                (
                    "netease_yidun",
                    self.netease_yidun_client.moderate_prompt(user_message),
                )
            )
        if tasks:
            results = await asyncio.gather(*(task for _, task in tasks))
            for (defense_id, _), assessment in zip(tasks, results, strict=True):
                if defense_id == "activation_probe":
                    signals.append(_activation_signal(assessment))
                elif defense_id == "safegauge":
                    signals.append(_safegauge_signal(assessment))
                elif defense_id == "qwen_guard":
                    signals.append(_qwen_guard_signal(assessment))
                elif defense_id == "llama_prompt_guard":
                    signals.append(_llama_prompt_guard_signal(assessment))
                else:
                    signals.append(_netease_yidun_signal(assessment))
        return signals

    def _session(self, session_id: str | None, agent_id: str) -> ChatSession:
        if session_id:
            return self.session_store.get_or_create(session_id, agent_id)
        return self.session_store.create(agent_id)

    def _enabled_defenses(self) -> tuple[DefenseId, ...]:
        scenario, _ = self.runtime_config.snapshot()
        probes_enabled = bool(
            getattr(self.settings, "customer_agent_enable_runtime_probes", True)
        )
        if probes_enabled:
            return scenario.defense_pipeline
        return tuple(
            defense_id
            for defense_id in scenario.defense_pipeline
            if defense_id not in RUNTIME_PROBE_DEFENSES
        )

    def _base_url(self, model_params: ModelParams) -> str:
        # Never trust a client-supplied port: public requests are pinned to
        # the ordinary business vLLM endpoint.
        return self.settings.customer_agent_business_base_url

    def _shadow_base_url(self) -> str:
        return self.settings.customer_agent_shadow_base_url

    def _business_model_params(self, model_params: ModelParams) -> ModelParams:
        updates = {
            "model": self.settings.customer_agent_model or SCENARIO.default_model,
            "vllm_port": None,
        }
        if self._dual_model_enabled:
            # The user-facing model emits only its final answer. The shadow
            # model is used only by the pre-generation hidden-state/logprob
            # probes; it never generates a second answer or reasoning trace.
            updates["enable_reasoning"] = False
        else:
            # Preserve the original single-endpoint behavior for integrations
            # that construct the Agent directly.
            updates["enable_reasoning"] = True
        return model_params.model_copy(update=updates)

    def _shadow_model_params(self, model_params: ModelParams) -> ModelParams:
        return model_params.model_copy(
            update={
                "model": self.settings.customer_agent_shadow_model or SCENARIO.default_model,
                "vllm_port": None,
                "enable_reasoning": True,
            }
        )

    def _reasoning_model_params(self, model_params: ModelParams) -> ModelParams:
        return self._business_model_params(model_params)

    async def _run_model_tool_loop(
        self,
        *,
        session: ChatSession,
        user_message: str,
        base_url: str,
        model_params: ModelParams,
        request: CustomerAgentRunRequest,
        stage_trace: list[CustomerAgentStageTraceItem],
        event_sink: EventSink | None,
        scenario,
        retriever,
    ) -> tuple[
        str,
        str,
        list[CustomerAgentRagTraceItem],
        list[CustomerAgentToolTraceItem],
        dict[str, Any],
    ]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": scenario.system_prompt},
            *_trim_history(session.history),
            {"role": "user", "content": user_message},
        ]
        tool_trace: list[CustomerAgentToolTraceItem] = []
        retrieved_items: list[Any] = []
        reasoning_parts: list[str] = []
        usage: dict[str, Any] = {}
        raw_output = ""
        follows_tool_result = False
        required_tool_names = _required_tool_names(
            user_message,
            scenario.tool_requirements,
        )
        completed_tool_names: set[str] = set()

        for turn_index in range(MAX_AGENT_MODEL_TURNS):
            final_turn = turn_index == MAX_AGENT_MODEL_TURNS - 1
            generation_started = perf_counter()
            await _emit_event(
                event_sink,
                phase="generation",
                message=(
                    "正在分析工具结果"
                    if follows_tool_result
                    else f"{scenario.name} 正在处理消息"
                ),
                detail=f"Agent loop 第 {turn_index + 1} 轮",
            )
            generation = await self.llm_client.generate(
                messages,
                model_params,
                base_url=base_url,
                tools=list(scenario.tools),
                tool_choice="none" if final_turn else "auto",
            )
            follows_tool_result = False
            _merge_usage(usage, generation.usage)
            reasoning_content = (
                generation.reasoning_content if model_params.enable_reasoning else ""
            )
            if reasoning_content:
                reasoning_parts.append(reasoning_content)
            stage_trace.append(
                _stage(
                    "reasoning",
                    "success" if reasoning_content else "skipped",
                    generation_started,
                    (
                        f"第 {turn_index + 1} 轮 reasoning 已在服务端生成"
                        if reasoning_content
                        else f"第 {turn_index + 1} 轮未返回独立 reasoning"
                    ),
                )
            )

            tool_calls = _extract_tool_calls(generation.message)[
                :MAX_TOOL_CALLS_PER_TURN
            ]
            missing_required_tools = required_tool_names - completed_tool_names
            stage_trace.append(
                _stage(
                    "generation",
                    "success",
                    generation_started,
                    (
                        f"模型选择调用 {len(tool_calls)} 个业务工具"
                        if tool_calls
                        else (
                            "模型答复尚缺必要业务查询，Agent loop 将继续"
                            if missing_required_tools and not final_turn
                            else "模型生成最终答复"
                        )
                    ),
                )
            )

            if tool_calls and not final_turn:
                messages.append(_assistant_tool_call_message(generation.message, tool_calls))
                tool_started = perf_counter()
                turn_retrieved: list[Any] = []
                for tool_call in tool_calls:
                    tool_message, trace, retrieved = self._execute_tool_call(
                        tool_call,
                        fallback_query=user_message,
                        attack_id=request.attack_id,
                        defended=request.defense_mode == "defended",
                        retriever=retriever,
                        scenario=scenario,
                    )
                    messages.append(tool_message)
                    tool_trace.append(trace)
                    if trace.status == "success":
                        completed_tool_names.add(trace.name)
                    turn_retrieved.extend(retrieved)
                if turn_retrieved:
                    retrieved_items = _merge_retrieved_documents(
                        retrieved_items,
                        turn_retrieved,
                    )
                    included_count = sum(item.included for item in turn_retrieved)
                    stage_trace.append(
                        _stage(
                            "retrieval",
                            "success",
                            tool_started,
                            f"本轮召回 {included_count} 个知识片段",
                        )
                    )
                    await _emit_event(
                        event_sink,
                        phase="retrieval",
                        message="知识库检索完成",
                        detail=f"召回 {included_count} 个知识片段",
                        status="success",
                    )
                failed_tools = sum(
                    trace.status != "success"
                    for trace in tool_trace[-len(tool_calls) :]
                )
                stage_trace.append(
                    _stage(
                        "tool",
                        "error" if failed_tools else "success",
                        tool_started,
                        (
                            f"模型自主调用 {len(tool_calls)} 个沙盒工具"
                            if not failed_tools
                            else f"模型调用 {len(tool_calls)} 个沙盒工具，其中 {failed_tools} 个未成功"
                        ),
                    )
                )
                await _emit_event(
                    event_sink,
                    phase="tool",
                    message="业务工具调用完成",
                    detail=" · ".join(trace.name for trace in tool_trace[-len(tool_calls) :]),
                )
                follows_tool_result = True
                continue

            missing_required_tools = required_tool_names - completed_tool_names
            if missing_required_tools:
                if not final_turn:
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "完成当前请求前仍需调用这些已授权业务工具："
                                f"{', '.join(sorted(missing_required_tools))}。"
                                "请先调用工具，并以真实返回结果为准。"
                            ),
                        }
                    )
                    await _emit_event(
                        event_sink,
                        phase="tool",
                        message="正在补全必要业务查询",
                        detail=" · ".join(sorted(missing_required_tools)),
                    )
                    continue
                raw_output = (
                    "抱歉，当前未能完成必要的业务查询，因此不能可靠回答。"
                    "请稍后重试或查阅对应的权威来源。"
                )
                break

            raw_output = generation.content.strip()
            break

        if not raw_output:
            raw_output = "抱歉，本轮没有生成可交付答复，请稍后重试。"

        return (
            raw_output,
            "\n\n".join(reasoning_parts),
            [_public_rag_trace(item) for item in retrieved_items],
            tool_trace,
            usage,
        )

    def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        fallback_query: str,
        attack_id: AttackId | None,
        defended: bool,
        retriever,
        scenario,
    ) -> tuple[dict[str, Any], CustomerAgentToolTraceItem, list[Any]]:
        started = perf_counter()
        call_id = str(tool_call.get("id") or f"tool-{uuid4().hex[:8]}")
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "unknown_tool")
        arguments, parse_error = _parse_tool_arguments(function.get("arguments"))
        retrieved: list[Any] = []
        status = "success"
        metadata: dict[str, Any] = {}

        if parse_error:
            status = "error"
            result = {"ok": False, "error": parse_error}
            summary = "工具参数不是有效 JSON"
        elif name == "search_knowledge_base":
            query = str(arguments.get("query") or fallback_query).strip()
            retrieval_query = (
                query
                if query.lower() == fallback_query.lower()
                else f"{query}\n{fallback_query}"
            )
            # attack_id never influences retrieval; every path uses this turn's
            # immutable BM25 snapshot.
            _ = attack_id
            retrieved = retriever.search(retrieval_query)
            result = build_knowledge_tool_result(retrieved, defended=defended)
            included = sum(item.included for item in retrieved)
            summary = f"返回 {included} 个知识片段"
            metadata = {
                "replay_schema": "bm25.retrieval.v1",
                "retriever": retriever.config.algorithm,
                "tokenizer": retriever.config.tokenizer,
                "retrieval_query": retrieval_query,
                "query_tokens": tokenize_for_bm25(retrieval_query),
                "corpus_chunks": len(retriever.chunks),
                "top_k": retriever.config.top_k,
                "min_score": retriever.config.min_score,
                "k1": retriever.config.k1,
                "b": retriever.config.b,
                "returned_chunk_ids": [item.chunk_id for item in retrieved],
            }
        elif name == "search_legal_corpus":
            query = str(arguments.get("query") or fallback_query).strip()
            as_of_date = _resolve_legal_as_of_date(fallback_query)
            retrieval_query = (
                query
                if query.lower() == fallback_query.lower()
                else f"{query}\n{fallback_query}"
            )
            retrieved = retriever.search(retrieval_query)
            result = build_knowledge_tool_result(retrieved, defended=defended)
            result = (
                f"本次适用日期 as_of_date={as_of_date}。"
                "检索结果是候选资料，必须根据 status、effective_from 和 "
                f"effective_to 继续校验。\n{result}"
            )
            included = sum(item.included for item in retrieved)
            summary = f"返回 {included} 个法规候选片段"
            metadata = {
                "replay_schema": "bm25.retrieval.v1",
                "retriever": retriever.config.algorithm,
                "tokenizer": retriever.config.tokenizer,
                "retrieval_query": retrieval_query,
                "query_tokens": tokenize_for_bm25(retrieval_query),
                "as_of_date": as_of_date,
                "jurisdiction": arguments.get("jurisdiction"),
                "corpus_chunks": len(retriever.chunks),
                "top_k": retriever.config.top_k,
                "min_score": retriever.config.min_score,
                "k1": retriever.config.k1,
                "b": retriever.config.b,
                "returned_chunk_ids": [item.chunk_id for item in retrieved],
            }
        elif name == "get_legal_document":
            document_id = str(arguments.get("document_id") or "").strip()
            document = next(
                (item for item in scenario.knowledge_documents if item.id == document_id),
                None,
            )
            if document is None:
                status = "error"
                result = {"ok": False, "error": "document_id not found"}
                summary = "未找到法规文档"
            else:
                result = {
                    "ok": True,
                    "id": document.id,
                    "title": document.title,
                    "visibility": document.visibility,
                    "metadata": document.metadata or {},
                    "content": document.content,
                }
                summary = f"读取法规文档：{document.title}"
        elif name == "compare_legal_versions":
            older_id = str(arguments.get("older_document_id") or "").strip()
            newer_id = str(arguments.get("newer_document_id") or "").strip()
            documents = {item.id: item for item in scenario.knowledge_documents}
            older = documents.get(older_id)
            newer = documents.get(newer_id)
            if older is None or newer is None:
                status = "error"
                result = {"ok": False, "error": "one or both document ids not found"}
                summary = "法规版本参数不完整"
            else:
                result = {
                    "ok": True,
                    "article": arguments.get("article"),
                    "older": {
                        "id": older.id,
                        "title": older.title,
                        "metadata": older.metadata or {},
                        "content": older.content,
                    },
                    "newer": {
                        "id": newer.id,
                        "title": newer.title,
                        "metadata": newer.metadata or {},
                        "content": newer.content,
                    },
                }
                summary = f"比较 {older.title} 与 {newer.title}"
        elif name == "lookup_order":
            order_id = str(arguments.get("order_id") or "").strip()
            if not order_id:
                status = "error"
                result = {"ok": False, "error": "order_id is required"}
                summary = "缺少订单号"
            else:
                order = lookup_order(order_id)
                result = json.dumps(order, ensure_ascii=False)
                summary = "找到演示订单" if order["found"] else "未找到订单"
        else:
            status = "denied"
            result = {"ok": False, "error": f"unsupported tool: {name}"}
            summary = "工具不在当前 Agent 白名单中"

        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        trace = CustomerAgentToolTraceItem(
            call_id=call_id,
            name=name,
            status=status,  # type: ignore[arg-type]
            arguments=arguments,
            result_summary=summary,
            duration_ms=round((perf_counter() - started) * 1000),
            metadata=metadata,
        )
        return (
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": content,
            },
            trace,
            retrieved,
        )

    @staticmethod
    def _commit(session: ChatSession, user_message: str, assistant_message: str) -> None:
        session.history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )
        session.history[:] = _trim_history(
            session.history,
            max_chars=MAX_CUSTOMER_HISTORY_CHARS * 2,
        )


def _extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tool_calls = message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return []
    return [tool_call for tool_call in raw_tool_calls if isinstance(tool_call, dict)]


def _required_tool_names(
    user_message: str,
    requirements: dict[str, tuple[str, ...]],
) -> set[str]:
    lowered = user_message.lower()
    return {
        tool_name
        for tool_name, phrases in requirements.items()
        if any(phrase.lower() in lowered for phrase in phrases)
    }


def _scenario_attack(scenario, attack_id: AttackId):
    for attack in scenario.attacks:
        if attack.id == attack_id:
            return attack.model_copy(deep=True)
    raise KeyError(attack_id)


def _resolve_legal_as_of_date(user_message: str) -> str:
    iso_match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", user_message)
    if iso_match:
        year, month, day = (int(value) for value in iso_match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    chinese_match = re.search(
        r"\b(20\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?",
        user_message,
    )
    if chinese_match:
        year = int(chinese_match.group(1))
        month = int(chinese_match.group(2))
        day = int(chinese_match.group(3) or 1)
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


def _assistant_tool_call_message(
    message: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": tool_calls,
    }


def _parse_tool_arguments(value: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(value, dict):
        return dict(value), None
    if not isinstance(value, str) or not value.strip():
        return {}, None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        return {}, str(error)
    if not isinstance(parsed, dict):
        return {}, "tool arguments must decode to an object"
    return parsed, None


def _merge_retrieved_documents(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged = {item.chunk_id: item for item in existing}
    for item in incoming:
        current = merged.get(item.chunk_id)
        if current is None or item.score > current.score:
            merged[item.chunk_id] = item
    return sorted(
        merged.values(),
        key=lambda item: (-item.score, item.chunk_id),
    )


def _merge_usage(total: dict[str, Any], current: dict[str, Any] | None) -> None:
    for key, value in (current or {}).items():
        if isinstance(value, int) and isinstance(total.get(key, 0), int):
            total[key] = int(total.get(key, 0)) + value
        else:
            total[key] = value


def _delivery_chunks(text: str) -> list[str]:
    """Split a guard-approved answer into small, readable SSE deltas."""
    chunks: list[str] = []
    current = ""
    boundaries = frozenset("，。！？；：,.!?;:\n")
    for character in text:
        current += character
        if len(current) >= DELIVERY_CHUNK_SIZE or character in boundaries:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


async def _emit_event(
    event_sink: EventSink | None,
    *,
    phase: str,
    message: str,
    detail: str,
    status: str = "running",
    defense_signals: list[CustomerAgentDefenseSignal] | None = None,
) -> None:
    if event_sink is None:
        return
    payload: dict[str, Any] = {
        "phase": phase,
        "status": status,
        "message": message,
        "detail": detail,
    }
    if defense_signals is not None:
        payload["defense_signals"] = [
            signal.model_dump(mode="json") for signal in defense_signals
        ]
    await event_sink(payload)


def _public_rag_trace(item) -> CustomerAgentRagTraceItem:
    document = item.document
    if document.visibility == "public":
        preview = item.content[:120]
    elif document.visibility == "private":
        preview = "[内部文档内容已隐藏]"
    else:
        preview = "[模拟恶意指令内容已隐藏]"
    return CustomerAgentRagTraceItem(
        id=item.chunk_id,
        document_id=document.id,
        chunk_id=item.chunk_id,
        chunk_index=item.chunk_index,
        heading=item.heading,
        title=document.title,
        visibility=document.visibility,
        included=item.included,
        score=round(item.score, 6),
        rank=item.rank,
        retriever=item.retriever,
        preview=preview,
        matched_terms=list(item.matched_terms),
        token_count=item.token_count,
        content_chars=len(item.content),
        risk_flags=list(document.risk_flags),
        decision=item.decision,
    )


def _activation_signal(assessment: Any) -> CustomerAgentDefenseSignal:
    if assessment.error:
        return CustomerAgentDefenseSignal(
            defense_id="activation_probe",
            stage="input",
            status="error",
            connected=False,
            latency_ms=assessment.latency_ms,
            detail=assessment.error,
            raw_output=assessment.raw_output,
        )
    risky = assessment.risky is True
    runtime = {}
    if assessment.raw_output:
        try:
            runtime = json.loads(assessment.raw_output)
        except json.JSONDecodeError:
            runtime = {}
    return CustomerAgentDefenseSignal(
        defense_id="activation_probe",
        stage="input",
        status="risk" if risky else "safe",
        connected=True,
        blocked=False,
        score=assessment.score,
        threshold=assessment.threshold,
        latency_ms=assessment.latency_ms,
        detail="隐藏层激活探针命中窃密意图，风险已记录。" if risky else "隐藏层激活探针未命中。",
        raw_output=assessment.raw_output,
        metadata={
            "protocol": assessment.protocol,
            "layer": assessment.layer,
            "layers": runtime.get("layers", [assessment.layer]),
            "classifier_type": runtime.get("classifier_type", "linear"),
            "checkpoint_id": assessment.checkpoint_id,
            "enforcement": "observe_only",
        },
    )


def _safegauge_signal(assessment: SafeGaugeAssessment) -> CustomerAgentDefenseSignal:
    if assessment.error:
        return CustomerAgentDefenseSignal(
            defense_id="safegauge",
            stage="input",
            status="error",
            connected=False,
            latency_ms=assessment.latency_ms,
            detail=assessment.error,
            raw_output=assessment.raw_output,
        )
    risky = assessment.risky is True
    return CustomerAgentDefenseSignal(
        defense_id="safegauge",
        stage="input",
        status="risk" if risky else "safe",
        connected=True,
        blocked=False,
        score=assessment.probability,
        threshold=assessment.threshold,
        latency_ms=assessment.latency_ms,
        detail="后缀概率探针命中窃密意图，风险已记录。" if risky else "后缀概率探针未命中。",
        raw_output=assessment.raw_output,
        metadata={"task": assessment.task, "label": assessment.label, "enforcement": "observe_only"},
    )


def _qwen_guard_signal(
    assessment: QwenGuardAssessment,
) -> CustomerAgentDefenseSignal:
    if assessment.error or assessment.risky is None:
        return CustomerAgentDefenseSignal(
            defense_id="qwen_guard",
            stage="input",
            status="error",
            connected=False,
            latency_ms=assessment.latency_ms,
            detail=assessment.error or "Qwen3 安全护栏未返回可解析的安全标签。",
            raw_output=assessment.raw_output,
        )
    risky = assessment.risky is True
    return CustomerAgentDefenseSignal(
        defense_id="qwen_guard",
        stage="input",
        status="risk" if risky else "safe",
        connected=True,
        blocked=False,
        latency_ms=assessment.latency_ms,
        detail=(
            f"Qwen3 安全护栏判定为 {assessment.safety_label}，风险已记录。"
            if risky
            else "Qwen3 安全护栏未命中。"
        ),
        raw_output=assessment.raw_output,
        metadata={
            "safety_label": assessment.safety_label,
            "categories": assessment.categories,
            "backend": assessment.backend,
            "enforcement": "observe_only",
        },
    )


def _llama_prompt_guard_signal(
    assessment: LlamaPromptGuardAssessment,
) -> CustomerAgentDefenseSignal:
    if assessment.error:
        return CustomerAgentDefenseSignal(
            defense_id="llama_prompt_guard",
            stage="input",
            status="error",
            connected=False,
            latency_ms=assessment.latency_ms,
            detail=assessment.error,
            raw_output=assessment.raw_output,
        )
    risky = assessment.risky is True
    return CustomerAgentDefenseSignal(
        defense_id="llama_prompt_guard",
        stage="input",
        status="risk" if risky else "safe",
        connected=True,
        blocked=False,
        score=assessment.probability,
        threshold=assessment.threshold,
        latency_ms=assessment.latency_ms,
        detail=(
            "Llama 安全护栏命中风险输入，风险已记录。"
            if risky
            else "Llama 安全护栏未命中。"
        ),
        raw_output=assessment.raw_output,
        metadata={"label": assessment.label, "enforcement": "observe_only"},
    )


def _netease_yidun_signal(
    assessment: NeteaseYidunAssessment,
) -> CustomerAgentDefenseSignal:
    if assessment.error or assessment.risky is None:
        return CustomerAgentDefenseSignal(
            defense_id="netease_yidun",
            stage="input",
            status="error",
            connected=False,
            latency_ms=assessment.latency_ms,
            detail=assessment.error or "网易易盾未返回可用判定。",
            raw_output=assessment.raw_output,
        )
    risky = assessment.risky is True
    suggestion = SUGGESTION_TEXT.get(assessment.suggestion, "未知")
    return CustomerAgentDefenseSignal(
        defense_id="netease_yidun",
        stage="input",
        status="risk" if risky else "safe",
        connected=True,
        blocked=False,
        latency_ms=assessment.latency_ms,
        detail=(
            f"网易易盾判定为“{suggestion}”，风险已记录。"
            if risky
            else "网易易盾判定为“通过”。"
        ),
        raw_output=assessment.raw_output,
        metadata={
            "suggestion": assessment.suggestion,
            "suggestion_level": assessment.suggestion_level,
            "labels": assessment.labels,
            "task_id": assessment.task_id,
            "chunk_count": assessment.chunk_count,
            "enforcement": "observe_only",
        },
    )


def _not_run_signal(defense_id: DefenseId, detail: str) -> CustomerAgentDefenseSignal:
    return CustomerAgentDefenseSignal(
        defense_id=defense_id,
        stage=DEFENSE_STAGE[defense_id],  # type: ignore[arg-type]
        status="not_run",
        connected=True,
        detail=detail,
    )


def _complete_signals(
    signals: list[CustomerAgentDefenseSignal],
    requested: list[DefenseId],
) -> list[CustomerAgentDefenseSignal]:
    by_id = {signal.defense_id: signal for signal in signals}
    for defense_id in requested:
        if defense_id not in by_id:
            by_id[defense_id] = _not_run_signal(
                defense_id,
                "本轮在该方法执行前已经结束，或当前模式未启用防护。",
            )
    return [by_id[defense_id] for defense_id in DEFENSE_ORDER if defense_id in by_id]


def _verdict(success: bool, attempted: bool, blocked: bool) -> str:
    if success:
        return "compromised"
    if blocked:
        return "blocked"
    if attempted:
        return "resisted"
    return "normal"


def _stage(stage: str, status: str, started: float, detail: str) -> CustomerAgentStageTraceItem:
    return CustomerAgentStageTraceItem(
        stage=stage,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        duration_ms=round((perf_counter() - started) * 1000),
        detail=detail,
    )


def _trim_history(
    history: list[dict[str, str]],
    *,
    max_chars: int = MAX_CUSTOMER_HISTORY_CHARS,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(history):
        cost = len(message.get("content", ""))
        if selected and used + cost > max_chars:
            break
        selected.append(message)
        used += cost
    return list(reversed(selected))
