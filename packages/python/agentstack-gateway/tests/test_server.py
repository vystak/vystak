import pytest
from fastapi.testclient import TestClient

from agentstack_gateway.server import app, router, providers, thread_store


@pytest.fixture(autouse=True)
def reset_state():
    router._routes.clear()
    providers.clear()
    thread_store._threads.clear()
    yield
    router._routes.clear()
    providers.clear()
    thread_store._threads.clear()


client = TestClient(app)


class TestHealth:
    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestRegisterRoute:
    def test_register(self):
        response = client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
            "listen": "mentions",
            "threads": True,
            "dm": True,
        })
        assert response.status_code == 200

    def test_list_after_register(self):
        client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
        })
        response = client.get("/routes")
        assert response.status_code == 200
        routes = response.json()
        assert len(routes) == 1
        assert routes[0]["agent_name"] == "support-bot"


class TestRemoveRoutes:
    def test_remove(self):
        client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
        })
        response = client.delete("/routes/support-bot")
        assert response.status_code == 200
        routes = client.get("/routes").json()
        assert len(routes) == 0


class TestRegisterProvider:
    def test_register(self):
        response = client.post("/register-provider", json={
            "name": "internal-slack",
            "type": "slack",
            "config": {"bot_token": "xoxb-test", "app_token": "xapp-test"},
        })
        assert response.status_code == 200
        assert response.json()["status"] == "registered"


import json


class TestLoadRoutesFile:
    def test_loads_routes(self, tmp_path):
        from agentstack_gateway.server import load_routes_file, router
        router._routes.clear()

        routes_file = tmp_path / "routes.json"
        routes_file.write_text(json.dumps({
            "providers": [],
            "routes": [
                {
                    "provider_name": "test-slack",
                    "agent_name": "support-bot",
                    "agent_url": "http://agent:8000",
                    "channels": ["#support"],
                    "listen": "mentions",
                    "threads": True,
                    "dm": True,
                }
            ],
        }))

        load_routes_file(str(routes_file))
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "support-bot"
        router._routes.clear()

    def test_missing_file_no_error(self):
        from agentstack_gateway.server import load_routes_file
        load_routes_file("/nonexistent/routes.json")


class TestV1Models:
    def test_empty_models(self):
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert data["data"] == []

    def test_models_after_registration(self):
        client.post("/register", json={
            "name": "test-bot",
            "url": "http://test-bot:8000",
        })
        response = client.get("/v1/models")
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "agentstack/test-bot"
        assert data["data"][0]["object"] == "model"
        assert data["data"][0]["owned_by"] == "agentstack"


class TestV1ChatCompletions:
    def test_unknown_model_returns_404(self):
        response = client.post("/v1/chat/completions", json={
            "model": "agentstack/nonexistent",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "model_not_found"


class TestV1Threads:
    def test_create_thread(self):
        response = client.post("/v1/threads", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "thread"
        assert "id" in data

    def test_create_thread_with_model(self):
        client.post("/register", json={
            "name": "test-bot",
            "url": "http://test-bot:8000",
        })
        response = client.post("/v1/threads", json={"model": "agentstack/test-bot"})
        assert response.status_code == 200

    def test_thread_not_found(self):
        response = client.get("/v1/threads/nonexistent/messages")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "thread_not_found"


class TestOldEndpointsRemoved:
    def test_invoke_gone(self):
        response = client.post("/invoke/test-bot", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_stream_gone(self):
        response = client.post("/stream/test-bot", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_proxy_invoke_gone(self):
        response = client.post("/proxy/test-bot/invoke", json={"message": "hi"})
        assert response.status_code in (404, 405)

    def test_proxy_stream_gone(self):
        response = client.post("/proxy/test-bot/stream", json={"message": "hi"})
        assert response.status_code in (404, 405)
