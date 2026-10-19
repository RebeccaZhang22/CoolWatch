"""Small demo-host integration; all management implementation stays in manager/."""
import logging

from manager.activity_middleware import ActivityMiddleware
from manager.activity_store import ActivityStore
from manager.auth import ManagerAuthStore
from manager.config import get_config
from manager.console import install_console
from manager.telemetry import create_telemetry_router


def install_demo_tracking(app, auth_store, usage_store):
    config = get_config()
    activity = ActivityStore(config.data_dir / "activity.db")
    managers = ManagerAuthStore(config.data_dir / "manager.db")
    if config.email and config.password:
        managers.provision(config.email, config.password)
    app.add_middleware(ActivityMiddleware, auth_store=auth_store, activity_store=activity)
    app.include_router(create_telemetry_router(auth_store, activity))
    install_console(app, auth_store, managers, activity, usage_store)
    return activity


def record_account_event(activity, user_id, name):
    try:
        activity.append(user_id, kind="account", name=name)
    except Exception:
        logging.getLogger(__name__).exception("Cannot record account activity: %s", name)
