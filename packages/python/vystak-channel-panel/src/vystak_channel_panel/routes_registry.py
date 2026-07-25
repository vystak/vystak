"""Mounts resource routers onto the panel app. Extended by later tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


def mount_routes(app: FastAPI, rt: PanelChannelRuntime, current_user, admin_user) -> None:
    from vystak_channel_panel.routes_users import build_users_router

    app.include_router(build_users_router(rt, admin_user))
