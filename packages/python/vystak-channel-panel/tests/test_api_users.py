"""Admin user management."""

import asyncio


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


async def test_concurrent_duplicate_add_conflict(api, panel_rt, monkeypatch):
    admin = await _setup_admin(api)
    await api.post(
        "/api/users", json={"email": "race@example.com"}, headers=as_user(admin)
    )

    # Simulate the pre-check losing the race: it reports no existing user,
    # so the conflict must be caught from create_user's IntegrityError.
    # Only the lookup for the invited email is faked — the admin's own
    # auth lookup (current_user dependency) must resolve normally.
    original_get_user_by_email = panel_rt.panel_store.get_user_by_email
    calls = {"n": 0}

    async def flaky_get_user_by_email(email):
        if email == "race@example.com":
            calls["n"] += 1
            if calls["n"] == 1:
                return None
        return await original_get_user_by_email(email)

    monkeypatch.setattr(
        panel_rt.panel_store, "get_user_by_email", flaky_get_user_by_email
    )

    dup = await api.post(
        "/api/users", json={"email": "race@example.com"}, headers=as_user(admin)
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


async def test_sole_admin_cannot_self_demote(api):
    admin = await _setup_admin(api)
    listed = await api.get("/api/users", headers=as_user(admin))
    admin_id = listed.json()["users"][0]["id"]

    resp = await api.patch(
        f"/api/users/{admin_id}", json={"role": "member"}, headers=as_user(admin)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "cannot remove the last administrator"

    listed = await api.get("/api/users", headers=as_user(admin))
    admins = [
        u for u in listed.json()["users"]
        if u["role"] == "admin" and u["status"] == "active"
    ]
    assert len(admins) == 1
    assert admins[0]["id"] == admin_id


async def test_sole_admin_cannot_self_deactivate(api):
    admin = await _setup_admin(api)
    listed = await api.get("/api/users", headers=as_user(admin))
    admin_id = listed.json()["users"][0]["id"]

    resp = await api.patch(
        f"/api/users/{admin_id}",
        json={"status": "deactivated"},
        headers=as_user(admin),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "cannot remove the last administrator"

    listed = await api.get("/api/users", headers=as_user(admin))
    admins = [
        u for u in listed.json()["users"]
        if u["role"] == "admin" and u["status"] == "active"
    ]
    assert len(admins) == 1
    assert admins[0]["id"] == admin_id


async def test_demotion_allowed_with_second_admin(api):
    admin = await _setup_admin(api)
    listed = await api.get("/api/users", headers=as_user(admin))
    admin_id = listed.json()["users"][0]["id"]

    created = await api.post(
        "/api/users",
        json={"email": "second-admin@example.com", "role": "admin"},
        headers=as_user(admin),
    )
    assert created.status_code == 200

    resp = await api.patch(
        f"/api/users/{admin_id}", json={"role": "member"}, headers=as_user(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "member"

    listed = await api.get("/api/users", headers=as_user("second-admin@example.com"))
    admins = [
        u for u in listed.json()["users"]
        if u["role"] == "admin" and u["status"] == "active"
    ]
    assert len(admins) == 1
    assert admins[0]["email"] == "second-admin@example.com"


async def test_concurrent_demotion_of_two_admins_leaves_one(api, panel_rt):
    admin = await _setup_admin(api)
    listed = await api.get("/api/users", headers=as_user(admin))
    admin1_id = listed.json()["users"][0]["id"]

    created = await api.post(
        "/api/users",
        json={"email": "second-admin@example.com", "role": "admin"},
        headers=as_user(admin),
    )
    admin2_id = created.json()["user"]["id"]

    results = await asyncio.gather(
        api.patch(
            f"/api/users/{admin1_id}",
            json={"role": "member"},
            headers=as_user(admin),
        ),
        api.patch(
            f"/api/users/{admin2_id}",
            json={"role": "member"},
            headers=as_user("second-admin@example.com"),
        ),
    )
    assert {r.status_code for r in results} == {200, 409}

    # Query the store directly — whichever admin lost the race may have
    # been demoted, so an HTTP call authenticated as them would 403.
    all_users = await panel_rt.panel_store.list_users()
    active_admins = [
        u for u in all_users if u.role == "admin" and u.status == "active"
    ]
    assert len(active_admins) >= 1
