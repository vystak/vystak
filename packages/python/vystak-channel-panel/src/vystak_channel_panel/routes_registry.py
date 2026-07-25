"""Mounts resource routers onto the panel app. Extended by later tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


def mount_routes(app: FastAPI, rt: PanelChannelRuntime, current_user, admin_user) -> None:
    # Tasks 8-11 add users/projects/conversations/messages routes here.
    return None
