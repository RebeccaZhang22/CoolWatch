import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agent_loop import AgentLoop
from backend.attack_library import load_attack_examples
from backend.chat_orchestrator import ChatOrchestrator
from backend.config import get_settings
from backend.case_studies import case_study_pdf, list_case_studies, load_case_study
from backend.experiment_audit import (
    list_audit_risks,
    load_audit_catalog,
    load_case_detail,
    load_experiment_overview,
    load_finvault_case_page,
    load_finvault_case_detail,
    load_finvault_overview,
    load_prompt_extraction_case_detail,
    load_prompt_extraction_overview,
)
from backend.finvault_replay import FinVaultReplayService, replay_catalog, replay_metadata
from backend.llm_client import LlmClient
from backend.moderation import ModerationService, SUPPORTED_GUARDS
from backend.scenarios import default_scenario_catalog
from backend.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    FinVaultReplayRequest,
    ModerationRequest,
    ModerationResponse,
    SessionCreateRequest,
    SessionCreateResponse,
)
from backend.session_store import SessionStore
from backend.watchers import (
    ActivationProbeGuard,
    InlineProbingGuard,
    LlamaPromptGuardClient,
    NeteaseYidunClient,
    Qwen3GuardClient,
    SafeGaugeGuard,
)

logger = logging.getLogger(__name__)

settings = get_settings()
session_store = SessionStore()
llm_client = LlmClient(settings)
qwen_guard_client = Qwen3GuardClient(settings)
llama_prompt_guard_client = LlamaPromptGuardClient(settings)
netease_yidun_client = NeteaseYidunClient(settings)
safegauge_guard = SafeGaugeGuard(settings)
inline_probing_guard = InlineProbingGuard(settings)
activation_probe_guard = ActivationProbeGuard(settings)
agent_loop = AgentLoop(
    llm_client=llm_client,
    session_store=session_store,
)
chat_orchestrator = ChatOrchestrator(
    agent_loop=agent_loop,
    qwen_guard_client=qwen_guard_client,
    llama_prompt_guard_client=llama_prompt_guard_client,
    netease_yidun_client=netease_yidun_client,
    safegauge_guard=safegauge_guard,
    inline_probing_guard=inline_probing_guard,
    activation_probe_guard=activation_probe_guard,
)
moderation_service = ModerationService(
    qwen_guard_client=qwen_guard_client,
    llama_prompt_guard_client=llama_prompt_guard_client,
    netease_yidun_client=netease_yidun_client,
    safegauge_guard=safegauge_guard,
)
finvault_replay_service = FinVaultReplayService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Building the FinVault audit index is CPU- and I/O-heavy on its first use.
    # Warm it before the app reports itself ready so the audit page does not pay
    # that cost on its first request. Audit data is optional, so a missing or
    # incomplete local result set must not prevent the rest of the app starting.
    try:
        await asyncio.to_thread(load_finvault_overview, "qwen3-32b")
    except Exception:
        logger.warning("Unable to warm the FinVault audit cache", exc_info=True)
    yield
    await llm_client.close()
    await qwen_guard_client.close()
    await llama_prompt_guard_client.close()
    await netease_yidun_client.close()
    await safegauge_guard.close()
    await inline_probing_guard.close()
    await activation_probe_guard.close()
    await finvault_replay_service.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_frontend_asset_cache(request: Request, call_next):
    """Prevent an old HTML shell from loading against a newer frontend bundle."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        models = await llm_client.list_models()
        return HealthResponse(
            status="ok",
            vllm_base_url=settings.vllm_base_url,
            vllm_model=settings.vllm_model,
            vllm_reachable=True,
            models=models,
        )
    except Exception as error:
        return HealthResponse(
            status="degraded",
            vllm_base_url=settings.vllm_base_url,
            vllm_model=settings.vllm_model,
            vllm_reachable=False,
            error=str(error),
        )


@app.get("/api/scenarios")
async def list_scenarios():
    scenarios = default_scenario_catalog()
    return {"scenarios": [scenario.model_dump(by_alias=True) for scenario in scenarios]}


@app.get("/api/attacks")
async def list_attacks(language: str = "cn"):
    return {"attacks": load_attack_examples(language=language)}


@app.get("/api/guards/safegauge/info")
async def safegauge_info(task: str | None = None, model: str | None = None, port: int | None = None):
    if port is not None and not 1 <= port <= 65535:
        raise HTTPException(status_code=422, detail="vLLM port must be between 1 and 65535")
    return await safegauge_guard.get_model_info(
        task=task,
        model=model,
        base_url=f"http://127.0.0.1:{port}/v1" if port is not None else None,
    )


@app.get("/api/moderation/guards")
async def moderation_guards():
    return {"guards": list(SUPPORTED_GUARDS)}


@app.post("/v1/moderations", response_model=ModerationResponse)
@app.post("/api/moderate", response_model=ModerationResponse, include_in_schema=False)
async def moderate(request: ModerationRequest) -> ModerationResponse:
    try:
        return await moderation_service.moderate(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/guards/inline_probing/info")
async def inline_probing_info():
    return await inline_probing_guard.get_model_info()


@app.get("/api/guards/activation_probe/info")
async def activation_probe_info():
    return await activation_probe_guard.get_model_info()


@app.get("/api/audit/experiment")
async def experiment_audit_overview():
    return load_experiment_overview()


@app.get("/api/audit/risks")
async def audit_risks():
    return list_audit_risks()


@app.get("/api/audit/catalog")
async def audit_catalog():
    return load_audit_catalog()


def _prefers_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@app.get("/api/audit/experiment/cases/{sample_index}")
async def experiment_audit_case(sample_index: int, request: Request):
    if _prefers_html(request):
        return RedirectResponse(url=f"/cases.html?case={sample_index}", status_code=303)
    try:
        return load_case_detail(sample_index)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/audit/prompt-extraction")
async def prompt_extraction_audit_overview(model: str = "qwen3-32b"):
    return load_prompt_extraction_overview(model)


@app.get("/api/audit/prompt-extraction/cases/{sample_index}")
async def prompt_extraction_audit_case(sample_index: int, model: str = "qwen3-32b"):
    try:
        return load_prompt_extraction_case_detail(sample_index, model)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/audit/finvault")
async def finvault_audit_overview(include_cases: bool = True, model: str = "qwen3-8b"):
    overview = load_finvault_overview(model)
    if include_cases:
        return overview
    return {**overview, "cases": [], "case_count": len(overview["cases"])}


@app.get("/api/audit/finvault/cases")
async def finvault_audit_cases(
    model: str = "qwen3-8b",
    risk_type: str = "all",
    domain: str = "all",
    dataset_type: str = "all",
    evaluation_status: str = "all",
    search: str = "",
    offset: int = 0,
    limit: int = 50,
):
    return load_finvault_case_page(
        agent_model=model,
        risk_type=risk_type,
        domain=domain,
        dataset_type=dataset_type,
        evaluation_status=evaluation_status,
        search=search,
        offset=offset,
        limit=limit,
    )


@app.get("/api/audit/finvault/cases/{sample_index}")
async def finvault_audit_case(sample_index: int, model: str = "qwen3-8b"):
    try:
        return load_finvault_case_detail(sample_index, model)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/case-studies")
async def case_studies():
    return list_case_studies()


@app.get("/api/case-studies/{case_study_id}")
async def case_study(case_study_id: str, request: Request):
    if _prefers_html(request):
        return RedirectResponse(url=f"/cases.html?case=study%3A{case_study_id}", status_code=303)
    try:
        return load_case_study(case_study_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/case-studies/{case_study_id}/pdf")
async def case_study_document(case_study_id: str):
    try:
        path = case_study_pdf(case_study_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    session = session_store.create(request.scenario_id)
    return SessionCreateResponse(session_id=session.session_id)


@app.post("/api/sessions/{session_id}/reset")
async def reset_session(session_id: str):
    session_store.reset(session_id)
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await chat_orchestrator.run(request)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        chat_orchestrator.stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/replay/finvault/default")
async def finvault_replay_default():
    return replay_metadata()


@app.get("/api/replay/finvault/cases")
async def finvault_replay_cases(limit: int = 18):
    return replay_catalog(limit=limit)


@app.post("/api/replay/finvault/stream")
async def finvault_replay_stream(request: FinVaultReplayRequest) -> StreamingResponse:
    return StreamingResponse(
        finvault_replay_service.stream(request.sample_index, request.selected_guards),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
