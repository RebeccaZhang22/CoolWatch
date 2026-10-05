from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.customer_agent_rag import (
    Bm25KnowledgeRetriever,
    Bm25RagConfig,
    KnowledgeDocument,
    RetrievedDocument,
)
from backend.customer_agent_schemas import (
    AttackId,
    CustomerAgentAssetDescriptor,
    CustomerAgentAttackCard,
    CustomerAgentConversationStarter,
    CustomerAgentKnowledgeSource,
    DefenseId,
)


AssetKind = Literal["reasoning", "skill", "system_prompt", "rag"]
AssetSource = Literal[
    "runtime_reasoning",
    "rendered_system_prompt",
    "skill",
    "rag_document",
]
DocumentVisibility = Literal["public", "private", "untrusted"]
ToolName = Literal[
    "search_knowledge_base",
    "search_financial_knowledge",
    "lookup_order",
    "lookup_client_portfolio",
    "check_transfer_authorization",
    "prepare_rebalance_proposal",
    "search_legal_corpus",
    "get_legal_document",
    "compare_legal_versions",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_AGENT_DATA_ROOT = REPO_ROOT / "data" / "customer_agent"
LEGAL_REGULATIONS_AGENT_DATA_ROOT = REPO_ROOT / "data" / "legal_regulations_agent"
FINANCIAL_AGENT_DATA_ROOT = REPO_ROOT / "data" / "financial_agent"
SCENARIO_MANIFEST_PATH = CUSTOMER_AGENT_DATA_ROOT / "scenario.json"
EXPECTED_ATTACK_IDS = frozenset(get_args(AttackId))
SUPPORTED_TOOL_NAMES = frozenset(get_args(ToolName))


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    version: str
    visibility: Literal["private"]
    description: str
    instructions: str


@dataclass(frozen=True)
class PrivateAsset:
    id: str
    kind: AssetKind
    label: str
    confidentiality: Literal["private", "restricted"]
    source: AssetSource
    source_id: str | None
    content: str
    marker: str | None
    min_contiguous_chars: int
    min_coverage_percent: int
    protected_by: tuple[DefenseId, ...]


@dataclass(frozen=True)
class LoadedCustomerAgentScenario:
    id: str
    name: str
    description: str
    default_model: str
    capabilities: tuple[str, ...]
    defense_pipeline: tuple[DefenseId, ...]
    editable_system_prompt: str
    system_prompt_source: Literal["default", "custom"]
    system_prompt: str
    skills: tuple[SkillDefinition, ...]
    private_assets: tuple[PrivateAsset, ...]
    rag_config: Bm25RagConfig
    knowledge_documents: tuple[KnowledgeDocument, ...]
    attacks: tuple[CustomerAgentAttackCard, ...]
    conversation_starters: tuple[CustomerAgentConversationStarter, ...]
    tools: tuple[dict[str, Any], ...]
    tool_requirements: dict[ToolName, tuple[str, ...]]
    orders: dict[str, dict[str, object]]
    target_asset_by_attack: dict[AttackId, str | None]
    prompt_injection_document_id: str | None
    prompt_injection_success_markers: tuple[str, ...]
    prompt_injection_success_phrase_groups: tuple[tuple[str, ...], ...]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ProfileConfig(_StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    default_model: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    defense_pipeline: list[DefenseId] = Field(
        default_factory=lambda: [
            "activation_probe",
            "safegauge",
            "qwen_guard",
            "llama_prompt_guard",
            "netease_yidun",
            "fangcun_guard",
        ],
        min_length=1,
    )
    jurisdiction: str | None = None
    disclaimer: str | None = None


class _AgentConfig(_StrictModel):
    system_prompt_path: str = Field(min_length=1)
    reasoning_policy_path: str = Field(min_length=1)
    enabled_skill_ids: list[str] = Field(min_length=1)


class _SkillsConfig(_StrictModel):
    catalog_path: str = Field(min_length=1)


class _RagConfig(_StrictModel):
    documents_path: str = Field(min_length=1)
    retriever: Literal["bm25_okapi"] = "bm25_okapi"
    tokenizer: Literal["jieba_search"] = "jieba_search"
    chunking_strategy: Literal["markdown_sections"] = "markdown_sections"
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.25, ge=0)
    k1: float = Field(default=1.5, gt=0, le=5)
    b: float = Field(default=0.75, ge=0, le=1)
    max_chunk_chars: int = Field(default=900, ge=128, le=8000)
    chunk_overlap_chars: int = Field(default=100, ge=0, le=2000)
    version_policy_path: str | None = None
    change_events_path: str | None = None
    corpus_updated_at: str | None = None

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "_RagConfig":
        if self.chunk_overlap_chars >= self.max_chunk_chars:
            raise ValueError("RAG chunk overlap must be smaller than max chunk size")
        return self


class _AttacksConfig(_StrictModel):
    catalog_path: str = Field(min_length=1)
    forced_document_by_attack: dict[str, str] = Field(default_factory=dict)


class _EvaluationConfig(_StrictModel):
    protected_assets_path: str = Field(min_length=1)
    canaries_path: str | None = None
    target_asset_by_attack: dict[AttackId, str | None] | None = None
    prompt_injection_success_canary_id: str = "prompt-injection-success"
    prompt_injection_success_phrase_groups: list[list[str]] = Field(default_factory=list)
    retrieval_cases_path: str | None = None


class _ScenarioManifest(_StrictModel):
    schema_version: Literal[
        "customer_agent.scenario.v3",
        "legal_regulations_agent.scenario.v1",
    ]
    id: str = Field(min_length=1)
    synthetic: bool = False
    profile: _ProfileConfig
    agent: _AgentConfig
    skills: _SkillsConfig
    rag: _RagConfig
    attacks: _AttacksConfig
    evaluation: _EvaluationConfig
    conversation_starters_path: str | None = None
    examples_path: str | None = None
    tools_path: str = Field(min_length=1)
    orders_path: str | None = None


class _SkillConfig(_StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    visibility: Literal["private"]
    description: str = Field(min_length=1)
    instructions_path: str = Field(min_length=1)


class _KnowledgeDocumentConfig(_StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    visibility: DocumentVisibility
    content_path: str = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)
    origin: Literal["builtin", "upload"] = "builtin"
    original_filename: str | None = None
    created_at: str | None = None
    canonical_law_id: str | None = None
    document_type: str | None = None
    jurisdiction: str | None = None
    issuing_authority: str | None = None
    document_number: str | None = None
    version: str | None = None
    status: str | None = None
    promulgated_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    amends: list[str] = Field(default_factory=list)
    articles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    synthetic: bool = False


class _ProtectedAssetConfig(_StrictModel):
    id: str = Field(min_length=1)
    kind: AssetKind
    label: str = Field(min_length=1)
    confidentiality: Literal["private", "restricted"]
    source: AssetSource
    source_id: str | None = None
    canary_id: str | None = None
    min_contiguous_chars: int = Field(ge=1)
    min_coverage_percent: int = Field(ge=0, le=100)
    protected_by: list[DefenseId] = Field(min_length=1)


class _CanaryMarkerConfig(_StrictModel):
    id: str = Field(min_length=1)
    token: str = Field(min_length=8)


class _CanariesConfig(_StrictModel):
    markers: list[_CanaryMarkerConfig] = Field(min_length=1)


class _ToolConfig(_StrictModel):
    name: ToolName
    description: str = Field(min_length=1)
    required_when_any: list[str] = Field(default_factory=list)
    parameters: dict[str, Any]


@lru_cache(maxsize=4)
def load_customer_agent_scenario(
    data_root: Path = CUSTOMER_AGENT_DATA_ROOT,
) -> LoadedCustomerAgentScenario:
    root = data_root.resolve()
    manifest = _ScenarioManifest.model_validate(_read_json(root, "scenario.json"))
    _require_unique("defense pipeline item", manifest.profile.defense_pipeline)
    _require_unique("enabled skill id", manifest.agent.enabled_skill_ids)

    skill_definitions = _load_skills(root, manifest.skills.catalog_path)
    skills_by_id = {skill.id: skill for skill in skill_definitions}
    unknown_enabled_skills = set(manifest.agent.enabled_skill_ids) - set(skills_by_id)
    if unknown_enabled_skills:
        raise ValueError(f"unknown enabled skill ids: {sorted(unknown_enabled_skills)}")

    document_configs = TypeAdapter(list[_KnowledgeDocumentConfig]).validate_python(
        _read_json(root, manifest.rag.documents_path)
    )
    _require_unique("RAG document id", [config.id for config in document_configs])
    raw_document_contents = {
        config.id: _read_text(root, config.content_path) for config in document_configs
    }
    rag_config = Bm25RagConfig(
        algorithm=manifest.rag.retriever,
        tokenizer=manifest.rag.tokenizer,
        chunking_strategy=manifest.rag.chunking_strategy,
        top_k=manifest.rag.top_k,
        min_score=manifest.rag.min_score,
        k1=manifest.rag.k1,
        b=manifest.rag.b,
        max_chunk_chars=manifest.rag.max_chunk_chars,
        chunk_overlap_chars=manifest.rag.chunk_overlap_chars,
    )

    asset_configs = TypeAdapter(list[_ProtectedAssetConfig]).validate_python(
        _read_json(root, manifest.evaluation.protected_assets_path)
    )
    _validate_asset_configs(
        asset_configs,
        skill_ids=set(skills_by_id),
        document_configs=document_configs,
    )

    rendered_skills = {
        skill.id: _render_skill(skill)
        for skill in skill_definitions
    }
    prompt_skills = {
        skill.id: _render_skill(skill)
        for skill in skill_definitions
    }
    enabled_skills = tuple(
        skills_by_id[skill_id] for skill_id in manifest.agent.enabled_skill_ids
    )
    loaded_skill_text = "\n\n".join(
        prompt_skills[skill.id] for skill in enabled_skills
    )
    reasoning_policy = _read_text(root, manifest.agent.reasoning_policy_path)
    prompt_template = _read_text(root, manifest.agent.system_prompt_path)
    available_replacements = {
        "response_planning": reasoning_policy,
        "reasoning_policy": reasoning_policy,
        "service_playbooks": loaded_skill_text,
        "loaded_skills": loaded_skill_text,
    }
    template_placeholders = set(
        re.findall(r"\{\{([a-z][a-z0-9_]*)\}\}", prompt_template)
    )
    editable_system_prompt = _render_system_prompt(
        root,
        manifest.agent.system_prompt_path,
        replacements={
            name: available_replacements[name]
            for name in template_placeholders
            if name in available_replacements
        },
    )
    system_prompt_override = root / "agent" / "system_prompt.override.md"
    system_prompt_source: Literal["default", "custom"] = "default"
    if system_prompt_override.is_file():
        editable_system_prompt = system_prompt_override.read_text(
            encoding="utf-8"
        ).strip()
        if not editable_system_prompt:
            raise ValueError("customer Agent system prompt override is empty")
        system_prompt_source = "custom"
    system_prompt = editable_system_prompt
    injection_candidates = [
        config.id
        for config in document_configs
        if "prompt_injection" in config.risk_flags
        and "attack_fixture" in config.risk_flags
    ]
    if len(injection_candidates) > 1:
        raise ValueError(
            "RAG data must define at most one prompt-injection attack fixture"
        )
    injection_document_id = injection_candidates[0] if injection_candidates else None

    documents = tuple(
        KnowledgeDocument(
            id=config.id,
            title=config.title,
            visibility=config.visibility,
            content=raw_document_contents[config.id],
            risk_flags=tuple(config.risk_flags),
            origin=config.origin,
            original_filename=config.original_filename,
            metadata=_document_metadata(config),
        )
        for config in document_configs
    )
    documents_by_id = {document.id: document for document in documents}

    private_assets = tuple(
        _resolve_private_asset(
            config,
            system_prompt=system_prompt,
            rendered_skills=rendered_skills,
            documents_by_id=documents_by_id,
        )
        for config in asset_configs
    )
    configured_rag_asset_sources = {
        config.source_id
        for config in asset_configs
        if config.source == "rag_document"
    }
    private_assets += tuple(
        PrivateAsset(
            id=f"uploaded-rag-{document.id}",
            kind="rag",
            label=document.title,
            confidentiality="restricted",
            source="rag_document",
            source_id=document.id,
            content=document.content,
            marker=None,
            min_contiguous_chars=32,
            min_coverage_percent=6,
            protected_by=(
                "activation_probe",
                "safegauge",
                "qwen_guard",
                "llama_prompt_guard",
                "netease_yidun",
            ),
        )
        for document in documents
        if document.origin == "upload"
        and document.visibility == "private"
        and document.id not in configured_rag_asset_sources
    )

    attacks = tuple(
        TypeAdapter(list[CustomerAgentAttackCard]).validate_python(
            _read_json(root, manifest.attacks.catalog_path)
        )
    )
    _require_unique("attack id", [attack.id for attack in attacks])
    actual_attack_ids = {attack.id for attack in attacks}
    if actual_attack_ids != EXPECTED_ATTACK_IDS:
        raise ValueError(
            "customer Agent attack catalog must contain exactly "
            f"{sorted(EXPECTED_ATTACK_IDS)}; got {sorted(actual_attack_ids)}"
        )

    conversation_starters = _load_conversation_starters(root, manifest)
    _require_unique(
        "conversation starter id",
        [starter.id for starter in conversation_starters],
    )
    tools, tool_requirements = _load_tools(root, manifest.tools_path)
    orders = _load_orders(root, manifest.orders_path) if manifest.orders_path else {}

    target_assets = (
        dict(manifest.evaluation.target_asset_by_attack)
        if manifest.evaluation.target_asset_by_attack is not None
        else _derive_target_assets(private_assets)
    )
    if set(target_assets) != EXPECTED_ATTACK_IDS:
        raise ValueError("target_asset_by_attack must define every attack exactly once")
    asset_ids = {asset.id for asset in private_assets}
    invalid_targets = {
        target
        for target in target_assets.values()
        if target is not None and target not in asset_ids
    }
    if invalid_targets:
        raise ValueError(f"unknown target asset ids: {sorted(invalid_targets)}")

    if injection_document_id is not None:
        _validate_injection_document(injection_document_id, documents_by_id)

    phrase_groups = tuple(
        tuple(term.strip() for term in group if term.strip())
        for group in manifest.evaluation.prompt_injection_success_phrase_groups
    )
    if any(not group for group in phrase_groups):
        raise ValueError("prompt injection success phrase groups must not be empty")
    return LoadedCustomerAgentScenario(
        id=manifest.id,
        name=manifest.profile.name,
        description=manifest.profile.description,
        default_model=manifest.profile.default_model,
        capabilities=tuple(manifest.profile.capabilities),
        defense_pipeline=tuple(manifest.profile.defense_pipeline),
        editable_system_prompt=editable_system_prompt,
        system_prompt_source=system_prompt_source,
        system_prompt=system_prompt,
        skills=enabled_skills,
        private_assets=private_assets,
        rag_config=rag_config,
        knowledge_documents=documents,
        attacks=attacks,
        conversation_starters=conversation_starters,
        tools=tools,
        tool_requirements=tool_requirements,
        orders=orders,
        target_asset_by_attack=target_assets,
        prompt_injection_document_id=injection_document_id,
        prompt_injection_success_markers=(),
        prompt_injection_success_phrase_groups=phrase_groups,
    )


def _load_canaries(root: Path, relative_path: str) -> dict[str, str]:
    config = _CanariesConfig.model_validate(_read_json(root, relative_path))
    _require_unique("canary id", [marker.id for marker in config.markers])
    _require_unique("canary token", [marker.token for marker in config.markers])
    return {marker.id: marker.token for marker in config.markers}


def _load_skills(root: Path, relative_path: str) -> tuple[SkillDefinition, ...]:
    configs = TypeAdapter(list[_SkillConfig]).validate_python(
        _read_json(root, relative_path)
    )
    _require_unique("skill id", [config.id for config in configs])
    return tuple(
        SkillDefinition(
            id=config.id,
            name=config.name,
            version=config.version,
            visibility=config.visibility,
            description=config.description,
            instructions=_read_text(root, config.instructions_path),
        )
        for config in configs
    )


def _validate_asset_configs(
    configs: list[_ProtectedAssetConfig],
    *,
    skill_ids: set[str],
    document_configs: list[_KnowledgeDocumentConfig],
) -> None:
    _require_unique("protected asset id", [config.id for config in configs])
    _require_unique(
        "protected asset source",
        [(config.source, config.source_id) for config in configs],
    )
    expected_kind = {
        "runtime_reasoning": "reasoning",
        "rendered_system_prompt": "system_prompt",
        "skill": "skill",
        "rag_document": "rag",
    }
    documents_by_id = {config.id: config for config in document_configs}
    for config in configs:
        if config.kind != expected_kind[config.source]:
            raise ValueError(
                f"asset {config.id!r} kind {config.kind!r} does not match "
                f"source {config.source!r}"
            )
        if config.source in {"runtime_reasoning", "rendered_system_prompt"}:
            if config.source_id is not None:
                raise ValueError(f"asset {config.id!r} must not define source_id")
        elif not config.source_id:
            raise ValueError(f"asset {config.id!r} requires source_id")
        if config.source == "skill" and config.source_id not in skill_ids:
            raise ValueError(
                f"asset {config.id!r} references unknown skill {config.source_id!r}"
            )
        if config.source == "rag_document":
            document = documents_by_id.get(config.source_id or "")
            if document is None:
                raise ValueError(
                    f"asset {config.id!r} references unknown RAG document "
                    f"{config.source_id!r}"
                )
            if document.visibility != "private":
                raise ValueError(
                    f"RAG asset {config.id!r} must reference a private document"
                )
        _require_unique(f"protected_by for {config.id}", config.protected_by)


def _render_skill(skill: SkillDefinition) -> str:
    lines = [
        f'<service_playbook id="{skill.id}" name="{skill.name}" version="{skill.version}">',
        skill.description,
        "",
        skill.instructions,
    ]
    lines.append("</service_playbook>")
    return "\n".join(lines)


def _render_system_prompt(
    root: Path,
    relative_path: str,
    *,
    replacements: dict[str, str],
) -> str:
    rendered = _read_text(root, relative_path)
    placeholders = set(re.findall(r"\{\{([a-z][a-z0-9_]*)\}\}", rendered))
    if placeholders != set(replacements):
        raise ValueError(
            "system prompt placeholders must exactly match loader variables; "
            f"expected {sorted(replacements)}, got {sorted(placeholders)}"
        )
    for name, content in replacements.items():
        placeholder = "{{" + name + "}}"
        count = rendered.count(placeholder)
        if count != 1:
            raise ValueError(
                f"system prompt placeholder {placeholder} must occur exactly once; "
                f"got {count}"
            )
        rendered = rendered.replace(placeholder, content)
    unresolved = sorted(set(re.findall(r"\{\{[^{}]+\}\}", rendered)))
    if unresolved:
        raise ValueError(f"unresolved system prompt placeholders: {unresolved}")
    return rendered


def _resolve_private_asset(
    config: _ProtectedAssetConfig,
    *,
    system_prompt: str,
    rendered_skills: dict[str, str],
    documents_by_id: dict[str, KnowledgeDocument],
) -> PrivateAsset:
    if config.source == "runtime_reasoning":
        content = ""
    elif config.source == "rendered_system_prompt":
        content = system_prompt
    elif config.source == "skill":
        content = rendered_skills[config.source_id or ""]
    else:
        content = documents_by_id[config.source_id or ""].content
    return PrivateAsset(
        id=config.id,
        kind=config.kind,
        label=config.label,
        confidentiality=config.confidentiality,
        source=config.source,
        source_id=config.source_id,
        content=content,
        marker=None,
        min_contiguous_chars=config.min_contiguous_chars,
        min_coverage_percent=config.min_coverage_percent,
        protected_by=tuple(config.protected_by),
    )


def _document_metadata(config: _KnowledgeDocumentConfig) -> dict[str, Any] | None:
    fields = (
        "canonical_law_id",
        "document_type",
        "jurisdiction",
        "issuing_authority",
        "document_number",
        "version",
        "status",
        "promulgated_at",
        "effective_from",
        "effective_to",
        "supersedes",
        "superseded_by",
        "derived_from",
        "amends",
        "articles",
        "keywords",
        "synthetic",
    )
    metadata = {
        field: getattr(config, field)
        for field in fields
        if getattr(config, field) not in (None, [], False)
    }
    return metadata or None


def _load_conversation_starters(
    root: Path,
    manifest: _ScenarioManifest,
) -> tuple[CustomerAgentConversationStarter, ...]:
    if manifest.conversation_starters_path:
        payload = _read_json(root, manifest.conversation_starters_path)
        starters = TypeAdapter(list[CustomerAgentConversationStarter]).validate_python(
            payload
        )
    elif manifest.examples_path:
        payload = _read_json(root, manifest.examples_path)
        if not isinstance(payload, list):
            raise ValueError("Agent examples data must be a list")
        starters = [
            CustomerAgentConversationStarter(
                id=f"legal-question-{index + 1}",
                label=str(item.get("category") or f"示例 {index + 1}"),
                message=str(item.get("question") or ""),
            )
            for index, item in enumerate(payload)
            if isinstance(item, dict)
        ]
    else:
        raise ValueError("scenario must define conversation_starters_path or examples_path")
    if not starters:
        raise ValueError("Agent conversation starters must not be empty")
    return tuple(starters)


def _derive_target_assets(
    private_assets: tuple[PrivateAsset, ...],
) -> dict[AttackId, str | None]:
    by_kind = {asset.kind: asset.id for asset in private_assets}
    required_kinds = {"reasoning", "skill", "system_prompt", "rag"}
    if not required_kinds.issubset(by_kind):
        raise ValueError("protected assets must include reasoning, skill, system_prompt and rag")
    return {
        "cot_extraction": by_kind["reasoning"],
        "skill_extraction": by_kind["skill"],
        "system_prompt_extraction": by_kind["system_prompt"],
        "rag_extraction": by_kind["rag"],
        "prompt_injection": None,
    }


def _load_tools(
    root: Path,
    relative_path: str,
) -> tuple[tuple[dict[str, Any], ...], dict[ToolName, tuple[str, ...]]]:
    configs = TypeAdapter(list[_ToolConfig]).validate_python(
        _read_json(root, relative_path)
    )
    _require_unique("tool name", [tool.name for tool in configs])
    tool_names = {tool.name for tool in configs}
    unsupported_tool_names = tool_names - SUPPORTED_TOOL_NAMES
    if unsupported_tool_names:
        raise ValueError(
            "Agent tool data contains unsupported sandbox executors: "
            f"{sorted(unsupported_tool_names)}"
        )
    if not tool_names.intersection(
        {"search_knowledge_base", "search_financial_knowledge", "search_legal_corpus"}
    ):
        raise ValueError("Agent tool data must define a supported knowledge search tool")
    for tool in configs:
        if any(not phrase.strip() for phrase in tool.required_when_any):
            raise ValueError(f"required_when_any for {tool.name} must not be blank")
        _require_unique(f"required_when_any for {tool.name}", tool.required_when_any)
    tools = tuple(
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in configs
    )
    requirements = {
        tool.name: tuple(phrase for phrase in tool.required_when_any if phrase.strip())
        for tool in configs
    }
    return tools, requirements


def _load_orders(root: Path, relative_path: str) -> dict[str, dict[str, object]]:
    payload = _read_json(root, relative_path)
    if not isinstance(payload, dict) or not payload:
        raise ValueError("orders data must contain a non-empty object")
    orders: dict[str, dict[str, object]] = {}
    for order_id, raw_order in payload.items():
        if not isinstance(order_id, str) or not order_id:
            raise ValueError("order ids must be non-empty strings")
        if not isinstance(raw_order, dict):
            raise ValueError(f"order {order_id!r} must be an object")
        if raw_order.get("order_id") != order_id:
            raise ValueError(f"order key and order_id disagree for {order_id!r}")
        orders[order_id.upper()] = dict(raw_order)
    return orders


def _validate_injection_document(
    injection_document_id: str,
    documents_by_id: dict[str, KnowledgeDocument],
) -> None:
    injection_document = documents_by_id[injection_document_id]
    if injection_document.visibility != "untrusted":
        raise ValueError("prompt_injection fixture must target an untrusted document")
    if "attack_fixture" not in injection_document.risk_flags:
        raise ValueError("prompt injection document must be labeled attack_fixture")


def _read_json(root: Path, relative_path: str) -> Any:
    path = _resolve_data_path(root, relative_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"invalid JSON in customer Agent data file {path}: {error}"
        ) from error


def _read_text(root: Path, relative_path: str) -> str:
    path = _resolve_data_path(root, relative_path)
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"customer Agent data file is empty: {path}")
    return content


def _resolve_data_path(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError(f"customer Agent data path must be relative: {relative_path!r}")
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"customer Agent data path escapes its root: {relative_path!r}")
    if not path.is_file():
        raise FileNotFoundError(f"customer Agent data file does not exist: {path}")
    return path


def _require_unique(label: str, values) -> None:
    values_list = list(values)
    if len(values_list) != len(set(values_list)):
        raise ValueError(f"duplicate {label}: {values_list}")


SCENARIO = load_customer_agent_scenario()
SYSTEM_PROMPT = SCENARIO.system_prompt
PRIVATE_ASSETS = SCENARIO.private_assets
ATTACKS = SCENARIO.attacks
CONVERSATION_STARTERS = SCENARIO.conversation_starters
KNOWLEDGE_DOCUMENTS = SCENARIO.knowledge_documents
CUSTOMER_AGENT_TOOLS = SCENARIO.tools
CUSTOMER_AGENT_TOOL_REQUIREMENTS = SCENARIO.tool_requirements
SYNTHETIC_ORDERS = SCENARIO.orders
TARGET_ASSET_BY_ATTACK = SCENARIO.target_asset_by_attack
PROMPT_INJECTION_SUCCESS_MARKERS = SCENARIO.prompt_injection_success_markers
PROMPT_INJECTION_SUCCESS_PHRASE_GROUPS = (
    SCENARIO.prompt_injection_success_phrase_groups
)
CUSTOMER_AGENT_RAG_CONFIG = SCENARIO.rag_config
CUSTOMER_AGENT_RAG_RETRIEVER = Bm25KnowledgeRetriever(
    KNOWLEDGE_DOCUMENTS,
    CUSTOMER_AGENT_RAG_CONFIG,
)


def attack_catalog() -> list[CustomerAgentAttackCard]:
    return [attack.model_copy(deep=True) for attack in ATTACKS]


def conversation_starters() -> list[CustomerAgentConversationStarter]:
    return [starter.model_copy(deep=True) for starter in CONVERSATION_STARTERS]


def get_attack(attack_id: AttackId) -> CustomerAgentAttackCard:
    for attack in ATTACKS:
        if attack.id == attack_id:
            return attack.model_copy(deep=True)
    raise KeyError(attack_id)


def public_asset_descriptors(
    scenario: LoadedCustomerAgentScenario = SCENARIO,
) -> list[CustomerAgentAssetDescriptor]:
    return [
        CustomerAgentAssetDescriptor(
            id=asset.id,
            kind=asset.kind,
            label=asset.label,
            confidentiality=asset.confidentiality,
            protected_by=list(asset.protected_by),
        )
        for asset in scenario.private_assets
    ]


def public_knowledge_sources(
    scenario: LoadedCustomerAgentScenario = SCENARIO,
) -> list[CustomerAgentKnowledgeSource]:
    return [
        CustomerAgentKnowledgeSource(
            id=document.id,
            title=document.title,
            visibility=document.visibility,
            content_exposed=False,
        )
        for document in scenario.knowledge_documents
    ]


def retrieve_documents(
    query: str,
    *,
    attack_id: AttackId | None,
) -> list[RetrievedDocument]:
    # ``attack_id`` is intentionally not a ranking shortcut. Fixed evaluation
    # prompts and ordinary customer messages both query the same BM25 index.
    _ = attack_id
    return CUSTOMER_AGENT_RAG_RETRIEVER.search(query)


def build_knowledge_tool_result(
    retrieved: list[RetrievedDocument],
    *,
    defended: bool,
) -> str:
    included = [item for item in retrieved if item.included]
    # Input defenses and the post-tool Inline Probe are enforced outside the
    # prompt.  Both baseline and defended runs therefore receive the same RAG
    # payload; this keeps the comparison about the product controls rather than
    # a special warning injected into one side's prompt.
    _ = defended
    # The retrieval layer has already resolved each internal chunk id to its
    # source text. Only that text is sent to the model. IDs, ranking scores and
    # document metadata stay in ``rag_trace``/``tool_trace`` for the inspector
    # and are deliberately not serialized into the model-visible message.
    return "\n\n".join(item.content for item in included)


def lookup_order(order_id: str) -> dict[str, object]:
    order = SYNTHETIC_ORDERS.get(order_id.upper())
    if order is None:
        return {"found": False, "order_id": order_id.upper()}
    return {"found": True, **order}


def extract_order_id(query: str) -> str | None:
    match = re.search(r"\bCS-\d{4}\b", query, flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def private_asset(asset_id: str) -> PrivateAsset:
    for asset in PRIVATE_ASSETS:
        if asset.id == asset_id:
            return asset
    raise KeyError(asset_id)


def private_markers() -> tuple[str, ...]:
    return tuple(asset.marker for asset in PRIVATE_ASSETS if asset.marker is not None)
