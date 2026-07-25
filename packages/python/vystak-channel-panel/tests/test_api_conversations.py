"""Conversations + message history."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _ready(api):
    await api.post(
        "/api/setup",
        json={"email": "o@example.com", "name": "O", "image": ""},
        headers=as_user("o@example.com"),
    )
    boot = await api.get("/api/bootstrap", headers=as_user("o@example.com"))
    return "o@example.com", boot.json()["default_project_id"]


async def test_create_requires_known_agent(api):
    owner, pid = await _ready(api)
    bad = await api.post(
        f"/api/projects/{pid}/conversations",
        json={"agent_name": "ghost-agent"},
        headers=as_user(owner),
    )
    assert bad.status_code == 422


async def test_create_list_rename_delete(api):
    owner, pid = await _ready(api)
    created = await api.post(
        f"/api/projects/{pid}/conversations",
        json={"agent_name": "weather-agent"},
        headers=as_user(owner),
    )
    assert created.status_code == 200
    cid = created.json()["conversation"]["id"]

    listed = await api.get(
        f"/api/projects/{pid}/conversations", headers=as_user(owner)
    )
    assert [c["id"] for c in listed.json()["conversations"]] == [cid]

    renamed = await api.patch(
        f"/api/conversations/{cid}", json={"title": "Weather chat"},
        headers=as_user(owner),
    )
    assert renamed.json()["conversation"]["title"] == "Weather chat"

    assert (
        await api.delete(f"/api/conversations/{cid}", headers=as_user(owner))
    ).status_code == 204
    listed = await api.get(
        f"/api/projects/{pid}/conversations", headers=as_user(owner)
    )
    assert listed.json()["conversations"] == []


async def test_messages_history_visibility(api):
    owner, pid = await _ready(api)
    await api.post(
        "/api/users", json={"email": "s@example.com"}, headers=as_user(owner)
    )
    cid = (
        await api.post(
            f"/api/projects/{pid}/conversations",
            json={"agent_name": "weather-agent"},
            headers=as_user(owner),
        )
    ).json()["conversation"]["id"]

    # stranger (not in project) cannot read
    deny = await api.get(
        f"/api/conversations/{cid}/messages", headers=as_user("s@example.com")
    )
    assert deny.status_code == 403

    ok = await api.get(
        f"/api/conversations/{cid}/messages", headers=as_user(owner)
    )
    assert ok.status_code == 200
    assert ok.json()["messages"] == []


async def test_unknown_conversation_404(api):
    owner, _ = await _ready(api)
    resp = await api.get(
        "/api/conversations/nope/messages", headers=as_user(owner)
    )
    assert resp.status_code == 404
    # Pins the 404 to require_conversation_access's own check, not FastAPI's
    # default "route not found" 404 (which a missing route would also satisfy).
    assert resp.json()["detail"] == "unknown conversation"


async def test_rename_concurrently_deleted_conversation_404(api, panel_rt):
    owner, pid = await _ready(api)
    cid = (
        await api.post(
            f"/api/projects/{pid}/conversations",
            json={"agent_name": "weather-agent"},
            headers=as_user(owner),
        )
    ).json()["conversation"]["id"]

    # Simulate the row vanishing between require_conversation_access's check
    # and the update itself (e.g. a concurrent DELETE): update_conversation
    # returns None, as it does for a row that no longer exists.
    async def vanished(conversation_id, *, title=None, last_response_id=None):
        return None

    panel_rt.panel_store.update_conversation = vanished

    resp = await api.patch(
        f"/api/conversations/{cid}", json={"title": "New title"},
        headers=as_user(owner),
    )
    assert resp.status_code == 404
    # Same detail string as require_conversation_access's 404, so the two
    # cases are indistinguishable to a client.
    assert resp.json()["detail"] == "unknown conversation"
