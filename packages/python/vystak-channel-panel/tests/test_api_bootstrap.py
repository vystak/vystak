"""Bootstrap + first-run setup + service auth."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def test_health_no_auth(api):
    resp = await api.get("/health")
    assert resp.status_code == 200


async def test_missing_service_token_rejected(panel_rt):
    import httpx
    from vystak_channel_panel.app import build_app

    transport = httpx.ASGITransport(app=build_app(panel_rt))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://panel"
    ) as bare:
        resp = await bare.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert resp.status_code == 401


async def test_wrong_service_token_rejected(panel_rt):
    import httpx
    from vystak_channel_panel.app import build_app

    transport = httpx.ASGITransport(app=build_app(panel_rt))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://panel",
        headers={"Authorization": "Bearer wrong"},
    ) as bad:
        resp = await bad.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert resp.status_code == 401


async def test_bootstrap_setup_required_when_no_users(api):
    resp = await api.get("/api/bootstrap", headers=as_user("first@example.com"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["setup_required"] is True
    assert body["user"] is None
    assert body["agents"] == ["weather-agent", "time-agent"]
    assert body["default_project_id"] is None


async def test_setup_creates_admin_and_closes(api):
    resp = await api.post(
        "/api/setup",
        json={"email": "First@Example.com", "name": "First", "image": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert resp.json()["user"]["email"] == "first@example.com"

    # second setup attempt is rejected
    again = await api.post(
        "/api/setup", json={"email": "second@example.com", "name": "", "image": ""}
    )
    assert again.status_code == 409


async def test_bootstrap_known_user_gets_default_project(api):
    await api.post(
        "/api/setup", json={"email": "a@example.com", "name": "A", "image": ""}
    )
    resp = await api.get("/api/bootstrap", headers=as_user("a@example.com"))
    body = resp.json()
    assert body["setup_required"] is False
    assert body["user"]["email"] == "a@example.com"
    assert body["default_project_id"] is not None
    # idempotent
    again = await api.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert again.json()["default_project_id"] == body["default_project_id"]


async def test_bootstrap_unknown_user_after_setup(api):
    await api.post(
        "/api/setup", json={"email": "a@example.com", "name": "A", "image": ""}
    )
    resp = await api.get("/api/bootstrap", headers=as_user("stranger@example.com"))
    body = resp.json()
    assert body["setup_required"] is False
    assert body["user"] is None
