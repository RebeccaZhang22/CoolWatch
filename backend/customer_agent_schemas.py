from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.schemas import ModelParams


AttackId = Literal[
    "cot_extraction",
    "skill_extraction",
    "system_prompt_extraction",
    "rag_extraction",
    "prompt_injection",
]
DefenseMode = Literal["baseline", "defended"]
DefenseId = Literal[
    "activation_probe",
    "safegauge",
    "qwen_guard",
    "llama_prompt_guard",
    "netease_yidun",
]
DEFAULT_CUSTOMER_SAFEGAUGE_THRESHOLD = 0.65


def default_customer_model_params() -> ModelParams:
    return ModelParams(
        model="qwen3-8b",
        temperature=0.0,
        top_p=0.8,
        max_tokens=2048,
        enable_reasoning=True,
    )


def default_customer_defenses() -> list[DefenseId]:
    return [
        "activation_probe",
        "safegauge",
    ]


class CustomerAgentAttackCard(BaseModel):
    id: AttackId
    title: str
    target: str
    delivery: Literal["direct", "retrieval"]
    description: str
    prompt: str
    success_condition: str


class CustomerAgentConversationStarter(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=12000)
    attack_id: AttackId | None = None


class CustomerAgentAssetDescriptor(BaseModel):
    id: str
    kind: Literal["reasoning", "skill", "system_prompt", "rag"]
    label: str
    confidentiality: Literal["private", "restricted"]
    protected_by: list[DefenseId]


class CustomerAgentKnowledgeSource(BaseModel):
    id: str
    title: str
    visibility: Literal["public", "private", "untrusted"]
    content_exposed: bool = False


class CustomerAgentProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    model: str
    reasoning_enabled: bool
    capabilities: list[str]
    tools: list[str]
    knowledge_sources: list[CustomerAgentKnowledgeSource]
    protected_assets: list[CustomerAgentAssetDescriptor]
    defense_pipeline: list[DefenseId]


class CustomerAgentBootstrapResponse(BaseModel):
    profile: CustomerAgentProfileResponse
    conversation_starters: list[CustomerAgentConversationStarter]


class CustomerAgentSystemPromptResponse(BaseModel):
    content: str
    source: Literal["default", "custom"]
    updated: bool = False


class CustomerAgentSystemPromptUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100000)

    @model_validator(mode="after")
    def normalize_content(self) -> "CustomerAgentSystemPromptUpdateRequest":
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("system prompt must not be blank")
        return self


class CustomerAgentRagDocumentResponse(BaseModel):
    id: str
    title: str
    visibility: Literal["public", "private"]
    origin: Literal["builtin", "upload"]
    filename: str | None = None
    character_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    deletable: bool


class CustomerAgentRagDocumentContentResponse(BaseModel):
    id: str
    title: str
    visibility: Literal["public", "private"]
    origin: Literal["builtin", "upload"]
    filename: str | None = None
    content: str


class CustomerAgentRagConfigResponse(BaseModel):
    retriever: Literal["bm25_okapi"]
    tokenizer: Literal["jieba_search"]
    top_k: int = Field(ge=1)
    chunk_count: int = Field(ge=0)
    documents: list[CustomerAgentRagDocumentResponse]


class CustomerAgentRagMutationResponse(BaseModel):
    ok: bool = True
    document: CustomerAgentRagDocumentResponse | None = None
    rag: CustomerAgentRagConfigResponse


class CustomerAgentHealthResponse(BaseModel):
    status: Literal["ready", "degraded"]
    base_url: str
    model: str
    model_available: bool
    reasoning_enabled: bool = True
    safegauge_threshold: float = Field(
        default=DEFAULT_CUSTOMER_SAFEGAUGE_THRESHOLD,
        ge=0,
        le=1,
    )
    defense_methods: list[DefenseId]
    # Shadow model status is metadata only; no shadow generation content is
    # ever included in a run response.
    shadow_base_url: str | None = None
    shadow_model: str | None = None
    shadow_available: bool | None = None
    shadow_error: str | None = None
    error: str | None = None


class CustomerAgentRunRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128)
    attack_id: AttackId | None = None
    message: str | None = Field(default=None, min_length=1, max_length=12000)
    defense_mode: DefenseMode = "defended"
    defenses: list[DefenseId] = Field(default_factory=default_customer_defenses)
    model_params: ModelParams = Field(default_factory=default_customer_model_params)
    safegauge_threshold: float | None = Field(
        default=DEFAULT_CUSTOMER_SAFEGAUGE_THRESHOLD,
        ge=0,
        le=1,
    )
    probe_threshold: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_prompt_source(self) -> "CustomerAgentRunRequest":
        if self.attack_id is None and self.message is None:
            raise ValueError("one of 'attack_id' or 'message' is required")
        if self.message is not None and not self.message.strip():
            raise ValueError("message must not be blank")
        if len(set(self.defenses)) != len(self.defenses):
            raise ValueError("defenses must not contain duplicates")
        return self


class CustomerAgentCompareRequest(BaseModel):
    attack_id: AttackId | None = None
    message: str | None = Field(default=None, min_length=1, max_length=12000)
    defenses: list[DefenseId] = Field(default_factory=default_customer_defenses)
    model_params: ModelParams = Field(default_factory=default_customer_model_params)
    safegauge_threshold: float | None = Field(
        default=DEFAULT_CUSTOMER_SAFEGAUGE_THRESHOLD,
        ge=0,
        le=1,
    )
    probe_threshold: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_defenses(self) -> "CustomerAgentCompareRequest":
        if self.attack_id is None and self.message is None:
            raise ValueError("one of 'attack_id' or 'message' is required")
        if self.message is not None and not self.message.strip():
            raise ValueError("message must not be blank")
        if len(set(self.defenses)) != len(self.defenses):
            raise ValueError("defenses must not contain duplicates")
        return self


class CustomerAgentDefenseSignal(BaseModel):
    defense_id: DefenseId
    stage: Literal["input", "context", "generation", "output"]
    status: Literal["safe", "risk", "error", "not_run"]
    connected: bool
    blocked: bool = False
    score: float | None = None
    threshold: float | None = None
    latency_ms: int = 0
    detail: str = ""
    raw_output: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerAgentRagTraceItem(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    chunk_index: int = Field(ge=0)
    heading: str | None = None
    title: str
    visibility: Literal["public", "private", "untrusted"]
    included: bool
    score: float = Field(ge=0)
    rank: int = Field(ge=1)
    retriever: Literal["bm25_okapi"] = "bm25_okapi"
    preview: str
    matched_terms: list[str] = Field(default_factory=list)
    token_count: int = Field(default=0, ge=0)
    content_chars: int = Field(default=0, ge=0)
    risk_flags: list[str] = Field(default_factory=list)
    decision: str


class CustomerAgentToolTraceItem(BaseModel):
    call_id: str
    name: str
    status: Literal["success", "denied", "error"]
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerAgentStageTraceItem(BaseModel):
    stage: Literal[
        "session",
        "input_guard",
        "retrieval",
        "tool",
        "reasoning",
        "generation",
        "commit",
    ]
    status: Literal["success", "blocked", "skipped", "error"]
    duration_ms: int
    detail: str


class CustomerAgentAssetExposure(BaseModel):
    asset_id: str
    kind: Literal["reasoning", "skill", "system_prompt", "rag"]
    label: str
    exposed_in_output: bool
    exposed_to_client: bool
    exact_marker_match: bool
    coverage: int = Field(ge=0, le=100)
    max_contiguous_chars: int = Field(ge=0)


class CustomerAgentReasoningReport(BaseModel):
    requested: bool
    generated: bool
    character_count: int = Field(ge=0)
    exposed_to_client: bool = False
    visible_overlap: int = Field(ge=0, le=100)
    leak_detected: bool
    leak_delivered: bool
    policy: str = "server_side_only"


class CustomerAgentAttackAssessment(BaseModel):
    attack_id: AttackId | None
    target: str | None
    attempted: bool
    success: bool
    blocked_stage: Literal["input", "context", "generation", "output"] | None = None
    leaked_asset_ids: list[str] = Field(default_factory=list)
    summary: str


class CustomerAgentRunResponse(BaseModel):
    schema_version: Literal["customer_agent.run.v1"] = "customer_agent.run.v1"
    run_id: str
    session_id: str
    defense_mode: DefenseMode
    model: str
    reasoning: CustomerAgentReasoningReport
    assistant_message: str
    output_blocked: bool
    verdict: Literal["normal", "resisted", "blocked", "compromised"]
    attack: CustomerAgentAttackAssessment
    defense_signals: list[CustomerAgentDefenseSignal]
    asset_exposures: list[CustomerAgentAssetExposure]
    rag_trace: list[CustomerAgentRagTraceItem]
    tool_trace: list[CustomerAgentToolTraceItem]
    stage_trace: list[CustomerAgentStageTraceItem]
    usage: dict[str, Any] = Field(default_factory=dict)


class CustomerAgentDefenseEffect(BaseModel):
    baseline_success: bool
    defended_success: bool
    prevented: bool
    baseline_leaked_assets: int
    defended_leaked_assets: int
    leakage_reduction: int
    blocked_stage: str | None = None
    summary: str


class CustomerAgentCompareResponse(BaseModel):
    schema_version: Literal["customer_agent.compare.v1"] = "customer_agent.compare.v1"
    input_message: str
    attack: CustomerAgentAttackCard | None = None
    baseline: CustomerAgentRunResponse
    defended: CustomerAgentRunResponse
    effect: CustomerAgentDefenseEffect
