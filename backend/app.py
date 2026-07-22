from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agent_loop import AgentLoop
from backend.attack_library import load_attack_examples
from backend.chat_orchestrator import ChatOrchestrator
from backend.config import get_settings
from backend.llm_client import LlmClient
from backend.netease_yidun_client import NeteaseYidunClient
from backend.qwen_guard_client import Qwen3GuardClient
from backend.scenarios import DEFAULT_SCENARIOS
from backend.schemas import ChatRequest, ChatResponse, HealthResponse, SessionCreateRequest, SessionCreateResponse
from backend.session_store import SessionStore

settings = get_settings()
session_store = SessionStore()
llm_client = LlmClient(settings)
qwen_guard_client = Qwen3GuardClient(settings)
netease_yidun_client = NeteaseYidunClient(settings)
agent_loop = AgentLoop(llm_client=llm_client, session_store=session_store)
chat_orchestrator = ChatOrchestrator(
    agent_loop=agent_loop,
    qwen_guard_client=qwen_guard_client,
    netease_yidun_client=netease_yidun_client,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await llm_client.close()
    await qwen_guard_client.close()
    await netease_yidun_client.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return {"scenarios": [scenario.model_dump(by_alias=True) for scenario in DEFAULT_SCENARIOS.values()]}


@app.get("/api/attacks")
async def list_attacks(language: str = "cn"):
    return {"attacks": load_attack_examples(language=language)}


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


app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
