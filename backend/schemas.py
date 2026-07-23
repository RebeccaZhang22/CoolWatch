from typing import Literal
from pydantic import BaseModel, Field


class ModelParams(BaseModel):
    model: str = "Qwen3.5-27B"
    temperature: float = 0.2
    top_p: float = 0.8
    max_tokens: int = 2048


class OutputGuardConfig(BaseModel):
    exact_match_threshold: int = Field(default=80, ge=0, le=100)
    rouge_l_threshold: int = Field(default=80, ge=0, le=100)


class SafeGaugeConfig(BaseModel):
    threshold: float | None = Field(default=None, ge=0, le=1)


class ScenarioDocument(BaseModel):
    title: str
    type: str
    sensitive: bool = False
    content: str | None = None


class ScenarioPayload(BaseModel):
    id: str = "support"
    name: str = "企业客服助手"
    target: str = "系统提示词"
    system_prompt: str = Field(default="", alias="systemPrompt")
    documents: list[ScenarioDocument] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class ChatRequest(BaseModel):
    session_id: str
    message: str
    is_attack: bool = False
    attack_type: str | None = None
    selected_guards: list[str] = Field(default_factory=lambda: ["baseline"])
    model_params: ModelParams = Field(default_factory=ModelParams)
    output_guard: OutputGuardConfig = Field(default_factory=OutputGuardConfig)
    safegauge: SafeGaugeConfig = Field(default_factory=SafeGaugeConfig)
    scenario_id: str | None = None
    scenario: ScenarioPayload | None = None


class LeakageMetrics(BaseModel):
    exact_match: int
    coverage: int
    rouge_l: int = 0


class GuardResult(BaseModel):
    guard_id: str
    guard_name: str
    status: str
    blocked: bool
    latency_ms: int
    output: str
    raw_output: str
    leakage: LeakageMetrics
    query_risk: bool | None = None
    matched_labels: list[str] = Field(default_factory=list)
    connected: bool = True
    note: str = ""
    safety_label: str | None = None
    task: str | None = None
    probability: float | None = None
    threshold: float | None = None
    raw_guard_output: str = ""


class MatchedSpan(BaseModel):
    source: str
    text: str
    severity: Literal["low", "medium", "high", "critical"] = "high"


class RagTraceItem(BaseModel):
    id: str
    title: str
    type: str
    sensitive: bool
    score: float
    snippet: str


class AgentTraceItem(BaseModel):
    name: str
    status: Literal["success", "skipped", "error"]
    input: str
    output: str
    duration: int
    error: str | None = None


class ChatResponse(BaseModel):
    active_guard: str
    assistant_message: str
    guard_results: dict[str, GuardResult]
    leakage_summary: str
    output_blocked: bool = False
    output_guard: OutputGuardConfig = Field(default_factory=OutputGuardConfig)
    matched_spans: list[MatchedSpan]
    rag_trace: list[RagTraceItem]
    agent_trace: list[AgentTraceItem]


class SessionCreateRequest(BaseModel):
    scenario_id: str = "support"
    selected_guards: list[str] = Field(default_factory=lambda: ["baseline"])
    model_params: ModelParams = Field(default_factory=ModelParams)


class SessionCreateResponse(BaseModel):
    session_id: str


class HealthResponse(BaseModel):
    status: str
    vllm_base_url: str
    vllm_model: str
    vllm_reachable: bool
    models: list[str] = Field(default_factory=list)
    error: str | None = None
