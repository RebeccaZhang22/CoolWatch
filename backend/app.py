import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.auth_store import AuthStore
from manager.integration import install_demo_tracking, record_account_event
from backend.config import get_settings
from backend.customer_agent import CustomerServiceAgent
from backend.customer_agent_config import CustomerAgentRuntimeConfig
from backend.customer_agent_catalog import HANGLV_AGENT_DATA_ROOT
from backend.customer_agent_schemas import (
    CustomerAgentAttackCard,
    CustomerAgentBootstrapResponse,
    CustomerAgentCompareRequest,
    CustomerAgentCompareResponse,
    CustomerAgentHealthResponse,
    CustomerAgentProfileResponse,
    CustomerAgentRunRequest,
    CustomerAgentRunResponse,
    CustomerAgentRagConfigResponse,
    CustomerAgentRagDocumentContentResponse,
    CustomerAgentRagMutationResponse,
    CustomerAgentSystemPromptResponse,
    CustomerAgentSystemPromptUpdateRequest,
)
from backend.case_studies import case_study_pdf, list_case_studies, load_case_study
from backend.experiment_audit import (
    list_audit_risks,
    load_audit_catalog,
    load_case_detail,
    load_experiment_overview,
    load_prompt_extraction_case_detail,
    load_prompt_extraction_overview,
)
from backend.llm_client import LlmClient
from backend.moderation import ModerationService, SUPPORTED_GUARDS
from backend.schemas import (
    HealthResponse,
    ModerationRequest,
    ModerationResponse,
    SessionCreateRequest,
    SessionCreateResponse,
)
from pydantic import BaseModel, Field
from backend.session_store import SessionStore
from backend.usage_store import UsageStore
from backend.watchers.probe_bank import ProbeBankGuard
from backend.watchers import (
    ActivationProbeGuard,
    InlineProbingGuard,
    LlamaPromptGuardClient,
    NeteaseYidunClient,
    FangcunGuardClient,
    Qwen3GuardClient,
    SafeGaugeGuard,
)
from backend.financial_tool_mock import FinancialToolMocker

logger = logging.getLogger(__name__)


class GuardrailsApiRequest(BaseModel):
    input: str = Field(min_length=1, max_length=12000)
    session_id: str | None = Field(default=None, max_length=128)


class CustomerAgentTranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30000)


class CustomerAgentTranslationResponse(BaseModel):
    content: str


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)

settings = get_settings()
auth_store = AuthStore()
usage_store = UsageStore()
session_store = SessionStore()
business_llm_client = LlmClient(
    settings,
    base_url=settings.customer_agent_business_base_url,
    default_model=settings.customer_agent_model,
)
shadow_llm_client = LlmClient(
    settings,
    base_url=settings.customer_agent_shadow_base_url,
    default_model=settings.customer_agent_shadow_model,
)
# Legacy routes continue to use the public business endpoint.
llm_client = business_llm_client
qwen_guard_client = Qwen3GuardClient(settings)
llama_prompt_guard_client = LlamaPromptGuardClient(settings)
netease_yidun_client = NeteaseYidunClient(settings)
fangcun_guard_client = FangcunGuardClient(settings)
safegauge_guard = SafeGaugeGuard(settings)
inline_probing_guard = InlineProbingGuard(settings)
activation_probe_guard = ActivationProbeGuard(settings)
probe_bank_guard = ProbeBankGuard(settings)
financial_tool_mocker = FinancialToolMocker(settings)
moderation_service = ModerationService(
    qwen_guard_client=qwen_guard_client,
    llama_prompt_guard_client=llama_prompt_guard_client,
    netease_yidun_client=netease_yidun_client,
    fangcun_guard_client=fangcun_guard_client,
    safegauge_guard=safegauge_guard,
    inline_probing_guard=inline_probing_guard,
)
customer_data_root = (
    Path(settings.customer_agent_data_root).expanduser().resolve()
    if settings.customer_agent_data_root.strip()
    else HANGLV_AGENT_DATA_ROOT
)
customer_agent_runtime_config = CustomerAgentRuntimeConfig(customer_data_root)
customer_agent_service = CustomerServiceAgent(
    settings=settings,
    llm_client=llm_client,
    shadow_llm_client=shadow_llm_client,
    session_store=session_store,
    activation_probe_guard=activation_probe_guard,
    safegauge_guard=safegauge_guard,
    qwen_guard_client=qwen_guard_client,
    llama_prompt_guard_client=llama_prompt_guard_client,
    netease_yidun_client=netease_yidun_client,
    fangcun_guard_client=fangcun_guard_client,
    financial_tool_mocker=financial_tool_mocker,
    runtime_config=customer_agent_runtime_config,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await llm_client.close()
    await shadow_llm_client.close()
    await qwen_guard_client.close()
    await llama_prompt_guard_client.close()
    await netease_yidun_client.close()
    await fangcun_guard_client.close()
    await safegauge_guard.close()
    await inline_probing_guard.close()
    await activation_probe_guard.close()
    await probe_bank_guard.close()
    await financial_tool_mocker.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
activity_store = install_demo_tracking(app, auth_store, usage_store)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROTECTED_FRONTEND_PATHS = {
    "/hr.html",
    "/",
    "/index.html",
    "/audit.html",
    "/cases.html",
    "/competitors.html",
    "/account.html",
    "/developer-docs.html",
    "/developer-examples.html",
}


@app.middleware("http")
async def require_frontend_session(request: Request, call_next):
    """Redirect protected HTML before it can render for a signed-out browser."""
    if request.url.path not in PROTECTED_FRONTEND_PATHS:
        return await call_next(request)
    if request.query_params.get("demo") == "1":
        return await call_next(request)
    user = auth_store.current_user(session=request.cookies.get("pm_session"))
    if not user:
        return RedirectResponse(url="/login.html", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def disable_frontend_asset_cache(request: Request, call_next):
    """Prevent an old HTML shell from loading against a newer frontend bundle."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _as_millis(value: float | int | None) -> float:
    """Normalise a detector-side duration to milliseconds as a plain number."""
    return round(float(value), 1) if isinstance(value, (int, float)) else 0.0


@app.middleware("http")
async def require_customer_agent_api_key(request: Request, call_next):
    """Keep the customer product behind a browser session or CLI token."""
    path = request.url.path
    if not path.startswith("/api/customer-agent") and path != "/v1/guardrails":
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    user = auth_store.current_user(
        session=request.cookies.get("pm_session"),
        token=value.strip() if scheme.lower() == "bearer" else None,
    )
    if not user:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "需要登录的 ProspectMonitor 账号，或携带 CLI Token。",
                "code": "unauthorized",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


@app.post("/api/auth/register")
async def auth_register(payload: AuthCredentials, response: Response) -> dict:
    try:
        result = auth_store.register(payload.email, payload.password)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response.set_cookie("pm_session", result["session"], httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    record_account_event(activity_store, result["user"]["id"], "register")
    return {"user": result["user"], "token": result["token"]}


@app.post("/api/auth/login")
async def auth_login(payload: AuthCredentials, response: Response) -> dict:
    try:
        result = auth_store.login(payload.email, payload.password)
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    response.set_cookie("pm_session", result["session"], httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    record_account_event(activity_store, result["user"]["id"], "login")
    return {"user": result["user"], "token": result["token"]}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    user = auth_store.current_user(
        session=request.cookies.get("pm_session"),
        token=value.strip() if scheme.lower() == "bearer" else None,
    )
    if not user:
        raise HTTPException(status_code=401, detail="尚未登录。")
    return {"user": user}


@app.post("/api/auth/token/rotate")
async def auth_token_rotate(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    try:
        result = auth_store.rotate_token(
            session=request.cookies.get("pm_session"),
            token=value.strip() if scheme.lower() == "bearer" else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return result


@app.post("/api/auth/logout")
async def auth_logout(response: Response) -> dict:
    response.delete_cookie("pm_session")
    return {"ok": True}


@app.get("/api/usage")
async def usage_events(request: Request, limit: int = 100, page: int | None = None, page_size: int = 10) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, value = authorization.partition(" ")
    user = auth_store.current_user(
        session=request.cookies.get("pm_session"),
        token=value.strip() if scheme.lower() == "bearer" else None,
    )
    if not user:
        raise HTTPException(status_code=401, detail="尚未登录。")
    if page is not None:
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(status_code=400, detail="分页参数无效。")
        return usage_store.page_for_user(user["id"], page=page, page_size=page_size)
    return {"events": usage_store.list_for_user(user["id"], limit=limit)}


@app.post("/v1/guardrails")
async def guardrails_api(payload: GuardrailsApiRequest) -> dict:
    """Minimal product API: one key, one input, one protected answer.

    A refused run (detection unavailable, no usable method) is a service-state
    problem, not a caller mistake, so it maps to 503 rather than an unhandled 500.
    """
    try:
        result = await customer_agent_service.run(
            CustomerAgentRunRequest(
                message=payload.input,
                session_id=payload.session_id,
                defense_mode="defended",
            )
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "id": result.run_id,
        "object": "guardrails.result",
        "output": result.assistant_message,
        "blocked": result.output_blocked,
        "verdict": result.verdict,
        "model": result.model,
    }


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # The demo console needs to know whether detection is usable, not only
    # whether the business model answers. A probe outage is an unavailable
    # verdict for defended runs, so it belongs in the health payload.
    #
    # `/info` still answers when only *some* instances are down - that is a
    # diagnostic, not a success signal. Detection is fail-closed per enabled
    # risk, so one dead instance means every defended run will be refused; read
    # the per-risk `unavailable` list instead of treating any reply as healthy.
    probe_reachable: bool | None = None
    probe_error: str | None = None
    enabled_risks: list[str] = []
    if settings.activation_probe_backend == "probe_bank":
        enabled_risks = list(probe_bank_guard.enabled_risks)
        try:
            info = await probe_bank_guard.get_model_info()
            unavailable = list(info.get("unavailable") or [])
            if unavailable:
                probe_reachable = False
                probe_error = "; ".join(
                    f"{item.get('risk', '?')}@{item.get('base_url', '?')}: {item.get('error', 'unavailable')}"
                    for item in unavailable
                )
            else:
                probe_reachable = True
            enabled_risks = list(info.get("enabled_risks", enabled_risks))
        except Exception as error:
            probe_reachable = False
            probe_error = str(error)
    try:
        models = await llm_client.list_models()
        return HealthResponse(
            status="ok" if probe_reachable is not False else "degraded",
            vllm_base_url=settings.vllm_base_url,
            vllm_model=settings.vllm_model,
            vllm_reachable=True,
            models=models,
            error=None if probe_reachable is not False else probe_error,
            activation_probe_backend=settings.activation_probe_backend,
            probe_bank_reachable=probe_reachable,
            probe_bank_error=probe_error,
            probe_bank_enabled_risks=enabled_risks,
        )
    except Exception as error:
        return HealthResponse(
            status="degraded",
            vllm_base_url=settings.vllm_base_url,
            vllm_model=settings.vllm_model,
            vllm_reachable=False,
            error=str(error),
            activation_probe_backend=settings.activation_probe_backend,
            probe_bank_reachable=probe_reachable,
            probe_bank_error=probe_error,
            probe_bank_enabled_risks=enabled_risks,
        )


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


@app.post("/api/moderate", response_model=ModerationResponse, include_in_schema=False)
async def moderate(request: Request) -> Response:
    try:
        payload = await request.json()
        result = await moderation_service.moderate(ModerationRequest.model_validate(payload))
        return JSONResponse(result.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/v1/moderations")
async def standardized_moderate(request: Request) -> JSONResponse:
    """Run every trained risk probe on the same complete conversation."""
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "invalid_json", "message": "Request body must be valid JSON."}})
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "invalid_request", "message": "Request body must be a JSON object."}})
    api_key = request.headers.get("authorization", "")
    token = api_key.removeprefix("Bearer ").strip() if api_key.startswith("Bearer ") else ""
    user = auth_store.current_user(token=token)
    if not user:
        return JSONResponse(status_code=401, content={"error": {"type": "invalid_request_error", "code": "invalid_api_key", "message": "A Bearer API key is required."}})
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "invalid_messages", "message": "messages must be a non-empty array."}})
    normalized_messages: list[dict] = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in {"developer", "system", "user", "assistant", "tool"}:
            return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "invalid_messages", "message": "messages contain an invalid role."}})
        content = item.get("content") or ""
        if not isinstance(content, str):
            return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "unsupported_content_type", "message": "v1 currently supports text content only."}})
        reasoning = item.get("reasoning_content") or ""
        if not isinstance(reasoning, str):
            return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "code": "unsupported_content_type", "message": "reasoning_content must be text."}})
        normalized_messages.append({**item, "content": content})
    tools = payload.get("tools")
    if tools is not None and (not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools)):
        return JSONResponse(status_code=400, content={"error": {"code": "invalid_tools", "message": "tools must be an array of objects."}})
    started = time.perf_counter()
    assessment = await probe_bank_guard.moderate(normalized_messages, tools=payload.get("tools"))
    if assessment.error:
        request_id = f"req_{uuid4().hex}"
        error_code = {400: "invalid_messages", 413: "input_too_large",
                      429: "detector_overloaded", 504: "detector_timeout"}.get(assessment.status_code, "detector_unavailable")
        return JSONResponse(
            status_code=assessment.status_code,
            content={"error": {"type": "server_error" if assessment.status_code >= 500 else "rate_limit_error" if assessment.status_code == 429 else "invalid_request_error", "code": error_code, "message": assessment.error, "request_id": request_id}},
            headers={"X-Request-Id": request_id, "Retry-After": "5"},
        )
    bank_result = assessment.payload
    flagged = assessment.risky
    request_id = f"req_{uuid4().hex}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    input_tokens = bank_result["input_tokens"]
    response = {
        "id": f"mod_{uuid4().hex}",
        "request_id": request_id,
        "created": int(time.time()),
        "detector_model": bank_result["detector_model"],
        "bank_version": bank_result["bank_version"],
        "action": "block" if flagged else "pass",
        "per_risk": bank_result["per_risk"],
        "per_risk_detail": bank_result["per_risk_detail"],
        "enabled_risks": bank_result["enabled_risks"],
        "disabled_risks": bank_result["disabled_risks"],
        "overall": bank_result["overall"],
        "probes": {risk: {"checkpoint_sha256": detail.get("checkpoint_sha256"),
                           "probe": detail.get("composer_profile")}
                   for risk, detail in bank_result["per_risk_detail"].items()},
        "per_entry": bank_result["per_entry"],
        "triggered_entries": bank_result["triggered_entries"],
        "usage": {"input_tokens": input_tokens, "billable_tokens": input_tokens, "billable_units": round(input_tokens / 1000, 6), "unit": "1k_input_tokens"},
        # One documented shape for every success path: numbers, with the
        # detector share and the full request time side by side.
        "latency_ms": {
            "detector": _as_millis(bank_result.get("latency_ms")),
            "total": elapsed_ms,
        },
    }
    usage_store.append(user=user, request_id=request_id, messages=normalized_messages, tools=tools, result=response)
    return JSONResponse(response, headers={"X-Request-Id": request_id})


@app.get("/api/guards/inline_probing/info")
async def inline_probing_info():
    return await inline_probing_guard.get_model_info()


@app.get("/api/guards/activation_probe/info")
async def activation_probe_info():
    if settings.activation_probe_backend == "probe_bank":
        try:
            return await probe_bank_guard.get_model_info()
        except Exception as error:
            # Info is diagnostics only; never let it take the page down.
            return JSONResponse(status_code=503,
                                content={"error": "probe_bank_unavailable", "message": str(error)})
    # The legacy recipe backends were removed; report their absence explicitly
    # instead of asking a guard that can only fail.
    return JSONResponse(
        status_code=503,
        content={
            "error": "unsupported_backend",
            "message": (
                f"ACTIVATION_PROBE_BACKEND={settings.activation_probe_backend} 已不再支持，"
                "请使用 probe_bank 或 standalone"
            ),
        },
    )


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


def _customer_agent_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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


@app.get("/api/customer-agent", response_model=CustomerAgentBootstrapResponse)
async def customer_agent_bootstrap() -> CustomerAgentBootstrapResponse:
    return customer_agent_service.bootstrap()


@app.get("/api/customer-agent/scenarios")
async def customer_agent_scenarios():
    from backend.hr_demo import HrRuntimeConfig
    current, _ = customer_agent_runtime_config.snapshot()
    hr, _ = HrRuntimeConfig().snapshot()
    return {"scenarios": [
        {"id": "default", "name": current.name, "description": current.description},
        {"id": "hr", "name": hr.name, "description": hr.description},
    ]}


@app.get(
    "/api/customer-agent/profile",
    response_model=CustomerAgentProfileResponse,
)
async def customer_agent_profile() -> CustomerAgentProfileResponse:
    return customer_agent_service.profile()


@app.get(
    "/api/customer-agent/health",
    response_model=CustomerAgentHealthResponse,
)
async def customer_agent_health() -> CustomerAgentHealthResponse:
    return await customer_agent_service.health()


@app.get("/api/customer-agent/replay-cases/{case_id}")
async def customer_agent_replay_case(case_id: str):
    from backend.customer_agent_replay import replay_preview
    try:
        scenario, _ = customer_agent_runtime_config.snapshot()
        return replay_preview(case_id, scenario.system_prompt)
    except KeyError:
        raise HTTPException(status_code=404, detail="回放案例不存在")


@app.get(
    "/api/customer-agent/config/system-prompt",
    response_model=CustomerAgentSystemPromptResponse,
)
async def customer_agent_system_prompt() -> CustomerAgentSystemPromptResponse:
    return customer_agent_runtime_config.system_prompt()


@app.put(
    "/api/customer-agent/config/system-prompt",
    response_model=CustomerAgentSystemPromptResponse,
)
async def update_customer_agent_system_prompt(
    request: CustomerAgentSystemPromptUpdateRequest,
) -> CustomerAgentSystemPromptResponse:
    try:
        return customer_agent_runtime_config.update_system_prompt(request.content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get(
    "/api/customer-agent/config/rag",
    response_model=CustomerAgentRagConfigResponse,
)
async def customer_agent_rag_config() -> CustomerAgentRagConfigResponse:
    return customer_agent_runtime_config.rag_config()


@app.get(
    "/api/customer-agent/config/rag/documents/{document_id}",
    response_model=CustomerAgentRagDocumentContentResponse,
)
async def customer_agent_rag_document_content(
    document_id: str,
) -> CustomerAgentRagDocumentContentResponse:
    try:
        return customer_agent_runtime_config.rag_document_content(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="RAG 文档不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/customer-agent/config/rag/documents",
    response_model=CustomerAgentRagMutationResponse,
)
async def upload_customer_agent_rag_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    visibility: str = Form(default="public"),
) -> CustomerAgentRagMutationResponse:
    try:
        return await customer_agent_runtime_config.upload_rag_document(
            file,
            title=title,
            visibility=visibility,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()


@app.delete(
    "/api/customer-agent/config/rag/documents/{document_id}",
    response_model=CustomerAgentRagMutationResponse,
)
async def delete_customer_agent_rag_document(
    document_id: str,
) -> CustomerAgentRagMutationResponse:
    try:
        return customer_agent_runtime_config.delete_rag_document(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="RAG 文档不存在") from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/customer-agent/sessions/{session_id}/reset")
async def reset_customer_agent_session(session_id: str):
    cleared_documents = customer_agent_service.reset_session(session_id)
    return {
        "ok": True,
        "cleared_rag_documents": cleared_documents,
        "rag": customer_agent_runtime_config.rag_config().model_dump(mode="json"),
    }


@app.get(
    "/api/customer-agent/attacks",
    response_model=list[CustomerAgentAttackCard],
    include_in_schema=False,
)
async def customer_agent_attacks() -> list[CustomerAgentAttackCard]:
    """Legacy evaluation catalog; the single-Agent console does not use it."""
    scenario, _ = customer_agent_runtime_config.snapshot()
    return [attack.model_copy(deep=True) for attack in scenario.attacks]


@app.post(
    "/api/customer-agent/run",
    response_model=CustomerAgentRunResponse,
)
async def run_customer_agent(
    request: CustomerAgentRunRequest,
) -> CustomerAgentRunResponse:
    try:
        return await customer_agent_service.run(request)
    except Exception as error:
        logger.exception("Customer Agent run failed")
        raise HTTPException(
            status_code=502,
            detail=f"客服 Agent 模型服务调用失败：{error}",
        ) from error


@app.post(
    "/api/customer-agent/compare",
    response_model=CustomerAgentCompareResponse,
)
async def compare_customer_agent(
    request: CustomerAgentCompareRequest,
) -> CustomerAgentCompareResponse:
    try:
        return await customer_agent_service.compare(request)
    except Exception as error:
        logger.exception("Customer Agent comparison failed")
        raise HTTPException(
            status_code=502,
            detail=f"客服 Agent 攻防对比失败：{error}",
        ) from error


@app.post(
    "/api/customer-agent/translate",
    response_model=CustomerAgentTranslationResponse,
)
async def translate_customer_agent_output(
    request: CustomerAgentTranslationRequest,
) -> CustomerAgentTranslationResponse:
    try:
        content = await financial_tool_mocker.translate_to_chinese(request.text)
        return CustomerAgentTranslationResponse(content=content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Customer Agent output translation failed")
        raise HTTPException(status_code=502, detail=f"输出翻译失败：{error}") from error


@app.post("/api/customer-agent/run/stream")
async def stream_customer_agent(request: CustomerAgentRunRequest) -> StreamingResponse:
    async def events():
        async for event, payload in customer_agent_service.stream_events(request):
            yield _customer_agent_sse(event, payload)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


from backend.hr_demo import create_hr_router

app.include_router(create_hr_router(customer_agent_service))

app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
