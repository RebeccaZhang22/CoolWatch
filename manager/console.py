"""Mount management APIs and assets into either the standalone server or demo host."""
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from manager.api import create_manager_router
from manager.auth import COOKIE
from manager.config import MANAGER_ROOT


def install_console(app, users, managers, activity, usage):
    app.include_router(create_manager_router(users, managers, activity))

    @app.middleware("http")
    async def manager_access(request: Request, call_next):
        path = request.url.path
        if path == "/admin.html":
            return RedirectResponse("/manager/", status_code=303)
        if path in {"/manager", "/manager/", "/manager/index.html"} and not managers.current(request.cookies.get(COOKIE)):
            response = RedirectResponse("/manager/login.html", status_code=303)
        else:
            response = await call_next(request)
        if path.startswith(("/manager", "/api/manager", "/api/admin")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    def require_manager(request):
        if not managers.current(request.cookies.get(COOKIE)):
            raise HTTPException(401, "请登录独立管理者账号。")

    @app.get("/api/admin/users", include_in_schema=False)
    def legacy_users(request: Request, page: int = 1, page_size: int = 20):
        require_manager(request)
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(400, "分页参数无效。")
        result = users.list_users(page=page, page_size=page_size)
        counts = usage.counts_by_account()
        for user in result["users"]:
            user["api_calls"] = counts.get(user["id"], 0)
        return result

    @app.get("/api/admin/usage", include_in_schema=False)
    def legacy_usage(request: Request, page: int = 1, page_size: int = 20):
        require_manager(request)
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(400, "分页参数无效。")
        result = usage.page_all(page=page, page_size=page_size)
        accounts = users.users_by_id()
        for event in result["events"]:
            user = accounts.get(event.get("account_id"), {})
            event["account_email"] = event.get("account_email") or user.get("email") or "未知账户"
        return result

    # Only public frontend assets are served. The sibling data directory is never mounted.
    app.mount("/manager", StaticFiles(directory=MANAGER_ROOT / "frontend", html=True), name="manager")
