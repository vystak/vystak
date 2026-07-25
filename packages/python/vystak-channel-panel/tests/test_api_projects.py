"""Projects + sharing."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _two_users(api):
    await api.post(
        "/api/setup",
        json={"email": "owner@example.com", "name": "O", "image": ""},
        headers=as_user("owner@example.com"),
    )
    await api.post(
        "/api/users", json={"email": "guest@example.com"},
        headers=as_user("owner@example.com"),
    )
    return "owner@example.com", "guest@example.com"


async def test_create_and_list_visible_only(api):
    owner, guest = await _two_users(api)
    created = await api.post(
        "/api/projects", json={"name": "Research"}, headers=as_user(owner)
    )
    assert created.status_code == 200

    owner_list = await api.get("/api/projects", headers=as_user(owner))
    names = {p["name"] for p in owner_list.json()["projects"]}
    assert names == {"Personal", "Research"}  # default project + created

    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert {p["name"] for p in guest_list.json()["projects"]} == set()

    # bootstrap creates guest's default project lazily
    await api.get("/api/bootstrap", headers=as_user(guest))
    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert {p["name"] for p in guest_list.json()["projects"]} == {"Personal"}


async def test_sharing_flow(api):
    owner, guest = await _two_users(api)
    pid = (
        await api.post(
            "/api/projects", json={"name": "Shared"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]

    add = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": guest},
        headers=as_user(owner),
    )
    assert add.status_code == 204

    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert "Shared" in {p["name"] for p in guest_list.json()["projects"]}

    members = await api.get(
        f"/api/projects/{pid}/members", headers=as_user(guest)
    )
    assert {m["email"] for m in members.json()["members"]} == {guest}

    # only owner can manage members
    deny = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": owner},
        headers=as_user(guest),
    )
    assert deny.status_code == 403

    uid = members.json()["members"][0]["id"]
    rm = await api.delete(
        f"/api/projects/{pid}/members/{uid}", headers=as_user(owner)
    )
    assert rm.status_code == 204
    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert "Shared" not in {p["name"] for p in guest_list.json()["projects"]}


async def test_add_unknown_member_404(api):
    owner, _ = await _two_users(api)
    pid = (
        await api.post(
            "/api/projects", json={"name": "P"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]
    resp = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": "nobody@example.com"},
        headers=as_user(owner),
    )
    assert resp.status_code == 404


async def test_delete_project_rules(api):
    owner, guest = await _two_users(api)
    boot = await api.get("/api/bootstrap", headers=as_user(owner))
    default_pid = boot.json()["default_project_id"]

    pid = (
        await api.post(
            "/api/projects", json={"name": "Doomed"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]

    assert (
        await api.delete(f"/api/projects/{default_pid}", headers=as_user(owner))
    ).status_code == 400
    assert (
        await api.delete(f"/api/projects/{pid}", headers=as_user(guest))
    ).status_code in (403, 404)
    assert (
        await api.delete(f"/api/projects/{pid}", headers=as_user(owner))
    ).status_code == 204
