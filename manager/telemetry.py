"""Demo-side event ingestion. Customer identity is supplied by the demo authentication store."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from manager.api import same_origin


class Interaction(BaseModel):
    id: UUID
    name: Literal["page_view", "click", "change"]
    session_id: str = Field(default="", max_length=128)
    path: str = Field(max_length=250, pattern=r"^/[^?#]*$")
    target: str = Field(default="", max_length=160)
    label: str = Field(default="", max_length=160)
    value: str | None = Field(default=None, max_length=160)


class InteractionBatch(BaseModel):
    events: list[Interaction] = Field(min_length=1, max_length=30)


def create_telemetry_router(auth, activity):
    router = APIRouter()

    @router.post("/api/telemetry/events", status_code=202)
    async def collect(payload: InteractionBatch, request: Request):
        same_origin(request)
        user = await run_in_threadpool(auth.current_user, session=request.cookies.get("pm_session"))
        if not user:
            raise HTTPException(401, "需要演示用户登录。")
        for event in payload.events:
            # The browser supplies UI hints only, never identities, risk outcomes or server timestamps.
            await run_in_threadpool(activity.append, user["id"], kind="interaction", name=event.name,
                                    event_id=f"ui_{user['id']}_{event.id}", session_id=event.session_id, path=event.path,
                                    properties={"target": event.target, "label": event.label, "value": event.value, "source": "browser"})
        return {"accepted": len(payload.events)}

    return router
