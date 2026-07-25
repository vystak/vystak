"""Mounts resource routers onto the panel app. Extended by later tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


def mount_routes(app: FastAPI, rt: PanelChannelRuntime, current_user, admin_user) -> None:
    from vystak_channel_panel.routes_conversations import build_conversations_router
    from vystak_channel_panel.routes_projects import build_projects_router
    from vystak_channel_panel.routes_users import build_users_router

    app.include_router(build_users_router(rt, admin_user))
    app.include_router(build_projects_router(rt, current_user))
    app.include_router(build_conversations_router(rt, current_user))
