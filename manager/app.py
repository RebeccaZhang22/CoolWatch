"""Standalone manager web server: no models or demo backend are loaded."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from manager.activity_store import ActivityStore
from manager.auth import ManagerAuthStore
from manager.config import ManagerConfig, get_config
from manager.console import install_console
from manager.user_directory import LegacyUsage, UserDirectory


def create_app(config: ManagerConfig | None = None):
    config = config or get_config()
    users = UserDirectory(config.user_db)
    managers = ManagerAuthStore(config.data_dir / "manager.db")
    activity = ActivityStore(config.data_dir / "activity.db")
    if config.email and config.password:
        managers.provision(config.email, config.password)
    app = FastAPI(title="CoolWatch Manager", docs_url=None, redoc_url=None, openapi_url=None)
    install_console(app, users, managers, activity, LegacyUsage(config.usage_log))

    @app.get("/")
    def index():
        return RedirectResponse("/manager/", status_code=303)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "coolwatch-manager"}

    return app
