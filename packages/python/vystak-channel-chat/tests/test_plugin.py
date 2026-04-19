"""Tests for the ChatChannelPlugin — unit-level, no Docker required."""

import json

from vystak.schema.channel import Channel, RouteRule
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_channel_chat import ChatChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "chat",
        "type": ChannelType.CHAT,
        "platform": _platform(),
        "routes": [
            RouteRule(match={}, agent="weather-agent"),
            RouteRule(match={}, agent="time-agent"),
        ],
    }
    base.update(overrides)
    return Channel(**base)


class TestChatChannelPlugin:
    def test_plugin_metadata(self):
        plugin = ChatChannelPlugin()
        assert plugin.type == ChannelType.CHAT
        assert plugin.default_runtime_mode == RuntimeMode.SHARED
        assert plugin.agent_protocol == AgentProtocol.A2A_TURN

    def test_generate_code_emits_expected_files(self):
        plugin = ChatChannelPlugin()
        resolved = {
            "weather-agent": "http://vystak-weather-agent:8000",
            "time-agent": "http://vystak-time-agent:8000",
        }
        code = plugin.generate_code(_channel(), resolved)

        assert code.entrypoint == "server.py"
        assert set(code.files.keys()) == {
            "server.py",
            "Dockerfile",
            "requirements.txt",
            "routes.json",
        }

    def test_routes_baked_into_routes_json(self):
        plugin = ChatChannelPlugin()
        resolved = {
            "weather-agent": "http://vystak-weather-agent:8000",
        }
        code = plugin.generate_code(_channel(), resolved)
        routes = json.loads(code.files["routes.json"])
        assert routes == resolved

    def test_server_template_is_self_contained(self):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        server = code.files["server.py"]
        # Must not import from vystak — the container has no vystak dependency.
        assert "from vystak" not in server
        assert "import vystak" not in server

    def test_empty_routes_still_valid(self):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(routes=[]), {})
        assert json.loads(code.files["routes.json"]) == {}

    def test_dockerfile_uses_python_311(self):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), {})
        assert "FROM python:3.11-slim" in code.files["Dockerfile"]

    def test_thread_name_format(self):
        plugin = ChatChannelPlugin()
        name = plugin.thread_name({"channel": "web", "session_id": "abc123"})
        assert name == "thread:chat:web:abc123"

    def test_thread_name_default_channel(self):
        plugin = ChatChannelPlugin()
        name = plugin.thread_name({"id": "xyz"})
        assert name == "thread:chat:default:xyz"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.CHAT)
        assert isinstance(plugin, ChatChannelPlugin)


class TestGeneratedServer:
    """Execute the generated server's logic via fastapi.testclient."""

    def _boot_generated_app(self, tmp_path, routes):
        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), routes)
        for name, content in code.files.items():
            (tmp_path / name).write_text(content)
        import os
        import runpy
        import sys

        os.environ["ROUTES_PATH"] = str(tmp_path / "routes.json")
        sys.path.insert(0, str(tmp_path))
        try:
            module_globals = runpy.run_path(
                str(tmp_path / "server.py"),
                run_name="__channel_chat_test__",
            )
        finally:
            sys.path.remove(str(tmp_path))
        return module_globals["app"]

    def test_health_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(tmp_path, {"weather-agent": "http://example.test"})
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["agents"] == ["weather-agent"]

    def test_models_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(
            tmp_path,
            {"a": "http://a.test", "b": "http://b.test"},
        )
        client = TestClient(app)
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.json()["data"]}
        assert ids == {"vystak/a", "vystak/b"}

    def test_chat_completion_unknown_model_returns_404(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(tmp_path, {"known-agent": "http://known.test"})
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "vystak/unknown-agent",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_not_found"

    def test_chat_completion_unknown_model_with_stream_returns_404(self, tmp_path):
        """Streaming shouldn't bypass the unknown-model guard."""
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(tmp_path, {"known-agent": "http://known.test"})
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "vystak/unknown-agent",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_not_found"


class TestServerTemplateStreaming:
    """String-level checks that the generated server contains streaming logic."""

    def test_template_mentions_send_subscribe(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "tasks/sendSubscribe" in SERVER_PY

    def test_template_emits_done_sentinel(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "[DONE]" in SERVER_PY

    def test_template_uses_streaming_response(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "StreamingResponse" in SERVER_PY
        assert "text/event-stream" in SERVER_PY

    def test_template_branches_on_stream_flag(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "if request.stream:" in SERVER_PY


class TestServerTemplateResponsesApi:
    """The chat channel should also expose OpenAI Responses API routes."""

    def test_template_has_v1_responses_post(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert '@app.post("/v1/responses")' in SERVER_PY
        assert "async def create_response(" in SERVER_PY

    def test_template_has_v1_responses_get(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert '@app.get("/v1/responses/{response_id}")' in SERVER_PY
        assert "async def get_response(" in SERVER_PY

    def test_template_tracks_response_owners(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "_RESPONSE_OWNERS" in SERVER_PY

    def test_template_guards_cross_agent_chaining(self):
        from vystak_channel_chat.server_template import SERVER_PY

        # previous_response_id must belong to the same agent
        assert "previous_response_id" in SERVER_PY
        assert "invalid_previous_response" in SERVER_PY

    def test_template_proxies_responses_stream(self):
        from vystak_channel_chat.server_template import SERVER_PY

        assert "_proxy_responses_stream" in SERVER_PY


class TestGeneratedResponsesApi:
    """Execute the generated server's Responses API via TestClient."""

    def _boot_generated_app(self, tmp_path, routes):
        import runpy
        import sys

        plugin = ChatChannelPlugin()
        code = plugin.generate_code(_channel(), routes)
        for name, content in code.files.items():
            (tmp_path / name).write_text(content)
        import os

        os.environ["ROUTES_PATH"] = str(tmp_path / "routes.json")
        sys.path.insert(0, str(tmp_path))
        try:
            module_globals = runpy.run_path(
                str(tmp_path / "server.py"),
                run_name="__channel_chat_test__",
            )
        finally:
            sys.path.remove(str(tmp_path))
        return module_globals["app"]

    def test_responses_unknown_model_returns_404(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(tmp_path, {"known-agent": "http://known.test"})
        client = TestClient(app)
        resp = client.post(
            "/v1/responses",
            json={"model": "vystak/unknown-agent", "input": "hi"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_not_found"

    def test_responses_get_unknown_id_returns_404(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._boot_generated_app(tmp_path, {"known-agent": "http://known.test"})
        client = TestClient(app)
        resp = client.get("/v1/responses/resp-never-created")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "response_not_found"
