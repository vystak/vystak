"""Admin set-password and service-auth verify endpoints."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _setup_admin(api, email="admin@example.com"):
    await api.post(
        "/api/setup",
        json={"email": email, "name": "A", "image": ""},
        headers=as_user(email),
    )
    return email


async def _create_member(api, admin, email="member@example.com"):
    resp = await api.post(
        "/api/users",
        json={"email": email, "role": "member"},
        headers=as_user(admin),
    )
    return resp.json()["user"]


async def test_admin_sets_password_then_verify_ok(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)

    put_resp = await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "testpass-m-123"},
        headers=as_user(admin),
    )
    assert put_resp.status_code == 204

    verify_resp = await api.post(
        "/api/auth/verify",
        json={"email": member["email"], "password": "testpass-m-123"},
    )
    body = verify_resp.json()
    assert verify_resp.status_code == 200
    assert body["ok"] is True
    assert body["user"]["email"] == member["email"]
    assert "password_hash" not in body["user"]


async def test_member_cannot_set_password(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)

    listed = await api.get("/api/users", headers=as_user(admin))
    admin_id = next(
        u["id"] for u in listed.json()["users"] if u["email"] == admin
    )
    resp = await api.put(
        f"/api/users/{admin_id}/password",
        json={"password": "testpass-x-123"},
        headers=as_user(member["email"]),
    )
    assert resp.status_code == 403


async def test_short_password_rejected(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)

    resp = await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "short"},
        headers=as_user(admin),
    )
    assert resp.status_code == 422


async def test_set_password_unknown_user_404(api):
    admin = await _setup_admin(api)

    resp = await api.put(
        "/api/users/nope/password",
        json={"password": "testpass-x-123"},
        headers=as_user(admin),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown user"


async def test_verify_failure_modes_identical_shape(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)
    await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "testpass-m-123"},
        headers=as_user(admin),
    )

    wrong = await api.post(
        "/api/auth/verify",
        json={"email": member["email"], "password": "wrongpass-000"},
    )
    ghost = await api.post(
        "/api/auth/verify",
        json={"email": "ghost@example.com", "password": "wrongpass-000"},
    )
    assert wrong.status_code == ghost.status_code == 200
    assert wrong.json() == ghost.json() == {"ok": False, "user": None}


async def test_verify_requires_service_token(panel_rt):
    import httpx
    from vystak_channel_panel.app import build_app

    transport = httpx.ASGITransport(app=build_app(panel_rt))
    async with httpx.AsyncClient(transport=transport, base_url="http://panel") as bare:
        resp = await bare.post(
            "/api/auth/verify", json={"email": "a@b.c", "password": "x"}
        )
    assert resp.status_code == 401


async def test_list_users_includes_has_password(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)
    await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "testpass-m-123"},
        headers=as_user(admin),
    )

    resp = await api.get("/api/users", headers=as_user(admin))
    users = {u["email"]: u for u in resp.json()["users"]}
    assert users[member["email"]]["has_password"] is True
    assert users[admin]["has_password"] is False


async def test_nul_password_rejected_on_set(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)

    resp = await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "bad\x00pass-123"},
        headers=as_user(admin),
    )
    assert resp.status_code == 422


async def test_too_long_password_rejected_on_set(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)

    resp = await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "a" * 73},
        headers=as_user(admin),
    )
    assert resp.status_code == 422


async def test_nul_password_on_verify_returns_ok_false_not_500(api):
    admin = await _setup_admin(api)
    member = await _create_member(api, admin)
    await api.put(
        f"/api/users/{member['id']}/password",
        json={"password": "testpass-m-123"},
        headers=as_user(admin),
    )

    resp = await api.post(
        "/api/auth/verify",
        json={"email": member["email"], "password": "bad\x00pass"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "user": None}
