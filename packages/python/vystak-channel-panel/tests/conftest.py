"""Shared fixtures for panel channel API tests."""

import httpx
import pytest
from vystak_channel_panel.responses_client import ResponsesClient
from vystak_channel_panel.store import SqlitePanelStore

SERVICE_TOKEN = "test-service-token"

ROUTES = {
    "weather-agent": {
        "canonical": "weather-agent.agents.default",
        "address": "http://vystak-weather-agent:8000/a2a",
    },
    "time-agent": {
        "canonical": "time-agent.agents.default",
        "address": "http://vystak-time-agent:8000/a2a",
    },
}


@pytest.fixture
async def panel_rt(tmp_path, monkeypatch):
    from vystak_channel_panel.runtime import PanelChannelRuntime
    from vystak_channel_runtime.store import MemoryChannelStore

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)
    panel_store = SqlitePanelStore(tmp_path / "panel.db")
    await panel_store.connect()
    rt = PanelChannelRuntime(
        config={"channel_type": "panel", "port": 8080},
        routes=ROUTES,
        store=MemoryChannelStore(),
        panel_store=panel_store,
        responses_client=ResponsesClient(),
    )
    yield rt
    await panel_store.close()


@pytest.fixture
async def api(panel_rt):
    from vystak_channel_panel.app import build_app

    app = build_app(panel_rt)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://panel",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    ) as client:
        yield client
