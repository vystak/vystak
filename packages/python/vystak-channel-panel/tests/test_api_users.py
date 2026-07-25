"""Admin user management."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _setup_admin(api, email="admin@example.com"):
    await api.post(
        "/api/setup",
        json={"email": email, "name": "A", "image": ""},
        headers=as_user(email),
    )
    return email


async def test_member_cannot_manage_users(api):
    admin = await _setup_admin(api)
    await api.post(
        "/api/users", json={"email": "m@example.com"}, headers=as_user(admin)
    )
    resp = await api.get("/api/users", headers=as_user("m@example.com"))
    assert resp.status_code == 403


async def test_admin_add_list_update(api):
    admin = await _setup_admin(api)
    created = await api.post(
        "/api/users",
        json={"email": "New@Example.com", "role": "member"},
        headers=as_user(admin),
    )
    assert created.status_code == 200
    uid = created.json()["user"]["id"]
    assert created.json()["user"]["email"] == "new@example.com"

    listed = await api.get("/api/users", headers=as_user(admin))
    assert {u["email"] for u in listed.json()["users"]} == {
        "admin@example.com", "new@example.com",
    }

    updated = await api.patch(
        f"/api/users/{uid}", json={"status": "deactivated"}, headers=as_user(admin)
    )
    assert updated.json()["user"]["status"] == "deactivated"

    # deactivated user is locked out
    resp = await api.get("/api/bootstrap", headers=as_user("new@example.com"))
    assert resp.json()["user"] is None


async def test_duplicate_add_conflict(api):
    admin = await _setup_admin(api)
    await api.post(
        "/api/users", json={"email": "x@example.com"}, headers=as_user(admin)
    )
    dup = await api.post(
        "/api/users", json={"email": "x@example.com"}, headers=as_user(admin)
    )
    assert dup.status_code == 409


async def test_patch_unknown_user_404(api):
    admin = await _setup_admin(api)
    resp = await api.patch(
        "/api/users/nope", json={"role": "admin"}, headers=as_user(admin)
    )
    assert resp.status_code == 404


async def test_uninvited_user_rejected(api):
    await _setup_admin(api)
    resp = await api.get("/api/users", headers=as_user("stranger@example.com"))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "not invited"
