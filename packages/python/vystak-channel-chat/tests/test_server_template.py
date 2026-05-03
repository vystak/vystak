"""Tests for the /v1/sessions/* proxy routes emitted in SERVER_PY."""

from vystak_channel_chat.server_template import SERVER_PY


def test_sessions_proxy_emitted():
    assert '@app.post("/v1/sessions/{thread_id}/compact")' in SERVER_PY
    assert '@app.get("/v1/sessions/{thread_id}/compactions")' in SERVER_PY
    assert '@app.get("/v1/sessions/{thread_id}/compactions/{generation}")' in SERVER_PY


def test_resolve_agent_for_thread_helper_present():
    assert "_resolve_agent_for_thread" in SERVER_PY


def test_sessions_routes_return_404_when_not_routed():
    assert "thread_not_found" in SERVER_PY


def test_sessions_routes_use_httpx():
    assert "httpx.AsyncClient" in SERVER_PY
