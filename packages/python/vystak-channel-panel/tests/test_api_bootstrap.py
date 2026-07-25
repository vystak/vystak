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
        headers=as_user("First@Example.com"),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert resp.json()["user"]["email"] == "first@example.com"

    # second setup attempt is rejected
    again = await api.post(
        "/api/setup",
        json={"email": "second@example.com", "name": "", "image": ""},
        headers=as_user("second@example.com"),
    )
    assert again.status_code == 409


async def test_bootstrap_known_user_gets_default_project(api):
    await api.post(
        "/api/setup",
        json={"email": "a@example.com", "name": "A", "image": ""},
        headers=as_user("a@example.com"),
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
        "/api/setup",
        json={"email": "a@example.com", "name": "A", "image": ""},
        headers=as_user("a@example.com"),
    )
    resp = await api.get("/api/bootstrap", headers=as_user("stranger@example.com"))
    body = resp.json()
    assert body["setup_required"] is False
    assert body["user"] is None


async def test_setup_concurrent_different_emails_only_one_admin(api, panel_rt):
    import asyncio

    results = await asyncio.gather(
        api.post(
            "/api/setup",
            json={"email": "alice@example.com", "name": "Alice", "image": ""},
            headers=as_user("alice@example.com"),
        ),
        api.post(
            "/api/setup",
            json={"email": "bob@example.com", "name": "Bob", "image": ""},
            headers=as_user("bob@example.com"),
        ),
        return_exceptions=True,
    )
    statuses = sorted(
        r.status_code for r in results if not isinstance(r, BaseException)
    )
    assert statuses == [200, 409]

    users = await panel_rt.panel_store.list_users()
    admins = [u for u in users if u.role == "admin"]
    assert len(users) == 1
    assert len(admins) == 1


async def test_setup_header_body_mismatch_rejected(api, panel_rt):
    resp = await api.post(
        "/api/setup",
        json={"email": "b@example.com", "name": "", "image": ""},
        headers=as_user("a@example.com"),
    )
    assert resp.status_code == 400
    assert await panel_rt.panel_store.count_users() == 0


async def test_setup_missing_header_rejected(api, panel_rt):
    resp = await api.post(
        "/api/setup", json={"email": "a@example.com", "name": "", "image": ""}
    )
    assert resp.status_code == 400
    assert await panel_rt.panel_store.count_users() == 0


async def test_non_ascii_service_token_returns_401_not_500(panel_rt):
    from vystak_channel_panel.app import build_app

    app = build_app(panel_rt)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/bootstrap",
        "raw_path": b"/api/bootstrap",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", "Bearer caf\xe9".encode("latin-1")),
            (b"x-panel-user", b"a@example.com"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("panel", 80),
    }

    status_holder = {}
    body_chunks = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status_holder["status"] = message["status"]
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    assert status_holder["status"] == 401
