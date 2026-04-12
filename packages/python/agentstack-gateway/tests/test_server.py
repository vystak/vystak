import pytest
from fastapi.testclient import TestClient

from agentstack_gateway.server import app, router, providers


@pytest.fixture(autouse=True)
def reset_state():
    router._routes.clear()
    providers.clear()
    yield
    router._routes.clear()
    providers.clear()


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
