"""Manager-only APIs and the authenticated, user-attributed browser event collector."""
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from manager.auth import COOKIE


class ManagerCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LeadLabel(BaseModel):
    status: Literal["unreviewed", "follow_up", "not_interested"]
    note: str = Field(default="", max_length=2000)


def same_origin(request):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.url.netloc):
        raise HTTPException(403, "请从当前站点提交请求。")


def date_filters(since: str = "", until: str = ""):
    values = []
    for value in (since, until):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
            values.append(date.replace(tzinfo=date.tzinfo or UTC).astimezone(UTC).isoformat() if date else "")
        except ValueError as error:
            raise HTTPException(422, "时间格式无效。") from error
    if all(values) and values[0] > values[1]:
        raise HTTPException(422, "开始时间不能晚于结束时间。")
    return dict(zip(("since", "until"), values))


def create_manager_router(auth, managers, activity):
    router = APIRouter()

    def require_manager(request: Request):
        manager = managers.current(request.cookies.get(COOKIE))
        if not manager:
            raise HTTPException(401, "请登录独立管理者账号。")
        if request.method not in {"GET", "HEAD"}:
            same_origin(request)
        return manager

    @router.post("/api/manager/login")
    def login(payload: ManagerCredentials, request: Request, response: Response):
        same_origin(request)
        try:
            manager, session = managers.login(payload.email, payload.password, request.client.host if request.client else "unknown")
        except PermissionError as error:
            raise HTTPException(429, str(error), headers={"Retry-After": "900"}) from error
        except ValueError as error:
            raise HTTPException(401, str(error)) from error
        response.set_cookie(COOKIE, session, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=8 * 3600, path="/")
        response.headers["Cache-Control"] = "no-store"
        return {"manager": manager}

    @router.get("/api/manager/me")
    def me(manager=Depends(require_manager)):
        return {"manager": manager}

    @router.post("/api/manager/logout")
    def logout(request: Request, response: Response, manager=Depends(require_manager)):
        managers.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/api/manager/overview")
    def overview(user_id: str = "", dates=Depends(date_filters), manager=Depends(require_manager)):
        return {"registered_users": len(auth.users_by_id()), **activity.metrics(user_id=user_id, **dates)}

    @router.get("/api/manager/users")
    def users(q: str = Query("", max_length=254), engagement: str = "", lead_status: str = "",
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              dates=Depends(date_filters), manager=Depends(require_manager)):
        return activity.users(auth.users_by_id(), q=q, engagement=engagement, lead_status=lead_status,
                              page=page, page_size=page_size, **dates)

    @router.patch("/api/manager/users/{user_id}/lead")
    def lead(user_id: str, payload: LeadLabel, manager=Depends(require_manager)):
        if user_id not in auth.users_by_id():
            raise HTTPException(404, "用户不存在。")
        activity.label(user_id, payload.status, payload.note, manager["email"])
        return {"ok": True}

    @router.get("/api/manager/events")
    def events(user_id: str = "", session_id: str = "", kind: str = "", risk_only: bool = False,
               q: str = Query("", max_length=250), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               dates=Depends(date_filters), manager=Depends(require_manager)):
        result = activity.events(user_id=user_id, session_id=session_id, kind=kind, risk_only=risk_only, q=q,
                                 page=page, page_size=page_size, **dates)
        accounts = auth.users_by_id()
        for event in result["events"]:
            event["email"] = accounts.get(event["user_id"], {}).get("email", event["user_id"])
        return result

    @router.get("/api/manager/events/{event_id}")
    def detail(event_id: str, manager=Depends(require_manager)):
        event = activity.detail(event_id)
        if not event:
            raise HTTPException(404, "记录不存在。")
        event["email"] = auth.users_by_id().get(event["user_id"], {}).get("email", event["user_id"])
        return event


    return router
