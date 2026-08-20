"""Human-in-the-loop tool approvals — release cells for Task 13.

Three cells, all against `examples/docker-approvals`'s shape (one agent
with a `Skill.needs_approval`-gated tool, plus the `panel` channel over the
NATS transport):

1. `test_live_approval_approve_runs_gated_tool_once` (`release_live_chat`):
   real LLM, approve path. Sends "the web service is broken - check status
   and restart it", waits for the turn to park, asserts the persisted
   `approval-requested` part, POSTs an approve decision, and asserts the
   turn concludes with exactly one side-effect log line.
2. `test_live_approval_deny_skips_gated_tool` (`release_live_chat`): same
   deploy shape, deny path — zero side-effect lines, turn still concludes
   normally (not failed), final assistant row exists.
3. `test_slack_approvals_deploy_smoke` (`release_slack`): deploy-only smoke
   with a slack channel + the same gated tool. Slack's Approve/Deny Block
   Kit buttons require a live workspace click; that part isn't mechanically
   assertable here and is left as the manual walkthrough already documented
   in `examples/docker-approvals/README.md` ("Walkthrough: Slack
   (optional)").

Both live cells copy `test_durable_turns.py`'s post-fd8d01a live-model
pattern verbatim: `ANTHROPIC_API_KEY` alone is not enough against a
MiniMax-style Anthropic-compatible endpoint — the model's `parameters`
dict must also carry `anthropic_api_url`, and the secret must reach the
container's env too (an agent that only gets the key sends it to
`api.anthropic.com` and 401s against a MiniMax key).

Why the park assertion is strict (parked *before* any side-effect log line
exists), not just "eventually parked": this cell caught a real regression
live during Task 13 development that a looser "eventually parked" check
would have missed entirely -- see
`vystak-template-langchain-python/_vystak/runtime/approvals.py`'s
`_dispatch_name` docstring for the bug (gated `tools/*.py` functions,
loaded as bare callables with no `.name`, never matched the approval map,
so the gate silently no-opped and `restart_service` ran unparked). Fixed
in the same commit that added this file. NOTE, corrected from an earlier
draft of this docstring: the installed PyPI `vystak` in the deployed image
(0.2.0 as of this writing) already carries the `needs_approval` field, so
`load_approval_map`'s typed path resolves it directly -- the raw-
`agent.json` fallback this cell was originally thought to be exercising
is NOT what caught the regression above; the gate never even reached
`load_approval_map`'s output before failing to wrap the tool. The
fallback still exists for whenever the installed `vystak` genuinely
predates the field, but this cell verified empirically that it isn't
currently in play. Verified the assertion actually discriminates: reverted
`_dispatch_name` locally, reinstalled the CLI's bundled template snapshot,
and confirmed `test_live_approval_approve_runs_gated_tool_once` fails
(never parks, 90s timeout) against the broken build before restoring the
fix.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

from .conftest import assert_apply_ok, assert_destroy_ok, docker_running, run

PANEL_PORT = 18150
SERVICE_TOKEN = "approvals-test-panel-token"  # noqa: S105 — test fixture token, not a secret
ADMIN = "admin@example.test"
AGENT_CONTAINER = "vystak-approvals-agent"
SIDE_EFFECT_LOG = "/data/restart_invocations.log"

_SENTINEL_MARKERS = ("sentinel", "your-", "<your", "fake", "test-")


def _looks_real(value: str | None) -> bool:
    if not value:
        return False
    low = value.lower()
    return not any(m in low for m in _SENTINEL_MARKERS)


def _panel(path: str) -> str:
    return f"http://localhost:{PANEL_PORT}{path}"


def _headers(user: str = ADMIN) -> dict:
    return {"Authorization": f"Bearer {SERVICE_TOKEN}", "X-Panel-User": user}


# Shared `vystak.py` DSL shape: one agent (`approvals-agent`) with a single
# gated tool, plus the `panel` channel, both on a docker platform whose
# transport is NATS. Mirrors `examples/docker-approvals/vystak.py`, but
# `restart_service` is swapped for a variant that records a side-effect
# log line per real execution (see `_RESTART_SERVICE_LIVE` below) so the
# approve/deny cells have something mechanical to count.
def _live_vystak_py() -> str:
    return f"""\
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="approvals-live",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True),
    ),
)

sonnet = ast.Model(
    name="llm",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
    parameters={{"temperature": 0.3}},
)

ops = ast.Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    needs_approval=["restart_service"],
)

approvals_agent = ast.Agent(
    name="approvals-agent",
    framework="langchain-python",
    instructions=(
        "When asked to fix the service, first call read_status, then call "
        "restart_service for the failing service, then summarize."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ops],
    # ANTHROPIC_API_URL must reach the container too: the live fixture
    # supports Anthropic-compatible endpoints (e.g. MiniMax), and without
    # the URL the agent sends that key to api.anthropic.com and 401s.
    secrets=[
        ast.Secret(name="ANTHROPIC_API_KEY"),
        ast.Secret(name="ANTHROPIC_API_URL"),
    ],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={{"port": {PANEL_PORT}}},
    agents=[approvals_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
"""


_READ_STATUS = """\
async def read_status(service: str) -> str:
    \"\"\"Read the current health status of a named service.\"\"\"
    return f"service {service} is DOWN (health check failing since 09:14 UTC)"
"""

# Records one line per *actual* execution -- only reached if the approval
# gate lets the call through. The park assertion below reads this file
# BEFORE approving, so a broken gate (tool runs unparked) shows up as a
# nonempty log at a point the test expects it empty.
_RESTART_SERVICE_LIVE = """\
from pathlib import Path

LOG_PATH = Path("/data/restart_invocations.log")


async def restart_service(name: str) -> str:
    \"\"\"Restart the named service. Destructive: requires approval.\"\"\"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(name + "\\n")
    return f"service {name} restarted"
"""


@pytest.fixture
def panel_approvals_clean():
    """Remove stale panel state before this test runs.

    Mirrors `test_durable_turns.py`'s `panel_durable_clean`: the panel's
    sqlite DB volume and the (unnamespaced) channel container name both
    survive `vystak destroy`, so a prior run's admin user / bound port
    would otherwise leak into this one.
    """
    run(["docker", "rm", "-f", "vystak-channel-panel"], check=False)
    run(["docker", "volume", "rm", "vystak-panel-state"], check=False)
    yield


def _journal_rows(container: str) -> list[list] | None:
    """Read every row of `/data/turns.db`'s `detached_turns` table inside
    `container` via `docker exec ... python -c ...`. Returns `None` if the
    container can't be reached rather than raising, so callers can poll."""
    script = (
        "import sqlite3, json\n"
        "conn = sqlite3.connect('/data/turns.db')\n"
        "cur = conn.execute(\n"
        "    'SELECT turn_id, status, attempts, thread_id, last_seq '\n"
        "    'FROM detached_turns'\n"
        ")\n"
        "print(json.dumps(cur.fetchall()))\n"
    )
    result = run(["docker", "exec", container, "python", "-c", script], check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _journal_row_for(container: str, turn_id: str) -> dict | None:
    rows = _journal_rows(container)
    if rows is None:
        return None
    for tid, status, attempts, thread_id, last_seq in rows:
        if tid == turn_id:
            return {
                "turn_id": tid,
                "status": status,
                "attempts": attempts,
                "thread_id": thread_id,
                "last_seq": last_seq,
            }
    return None


def _wait_until(predicate, timeout: float, interval: float = 1.0):
    """Poll `predicate()` until it returns a truthy value or `timeout`
    elapses. Returns the last (possibly falsy) result."""
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return result


def _bootstrap_panel_conversation(client: httpx.Client, agent_name: str) -> tuple[str, str]:
    """Wait for panel readiness, bootstrap the admin user + a project,
    and create a conversation against `agent_name`. Returns
    (project_id, conversation_id)."""
    for _ in range(30):
        try:
            if client.get(_panel("/health")).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        pytest.fail("panel API never became healthy")

    setup_resp = client.post(
        _panel("/api/setup"),
        json={"email": ADMIN, "name": "Admin", "image": ""},
        headers=_headers(),
    )
    assert setup_resp.status_code in (200, 409), setup_resp.text

    boot = client.get(_panel("/api/bootstrap"), headers=_headers()).json()
    assert boot["user"] is not None, f"admin not recognized after setup: {boot}"
    project_id = boot["default_project_id"]
    conv = client.post(
        _panel(f"/api/projects/{project_id}/conversations"),
        json={"agent_name": agent_name},
        headers=_headers(),
    ).json()["conversation"]
    return project_id, conv["id"]


def _dispatch_turn_and_get_id(client: httpx.Client, conv_id: str, project_id: str) -> str:
    """POST a message and drop the connection once headers land: the panel
    writes `active_turn_id` and acks the agent *before* streaming the SSE
    body, so this doesn't need to wait for any turn output. Returns the
    turn_id once it's visible on the conversation."""
    try:
        with client.stream(
            "POST",
            _panel(f"/api/conversations/{conv_id}/messages"),
            json={"text": "the web service is broken - check status and restart it"},
            headers=_headers(),
        ) as resp:
            assert resp.status_code == 200
    except httpx.HTTPError:
        pass  # dropping mid-stream can surface as a transport error

    def _find_turn_id():
        convs = client.get(
            _panel(f"/api/projects/{project_id}/conversations"), headers=_headers()
        ).json()["conversations"]
        match = next((c for c in convs if c["id"] == conv_id), None)
        return match["active_turn_id"] if match and match.get("active_turn_id") else None

    turn_id = _wait_until(_find_turn_id, timeout=10, interval=0.2)
    assert turn_id, "turn never got an active_turn_id on the conversation"
    return turn_id


def _parked_row(container: str, turn_id: str) -> dict | None:
    """Journal row for `turn_id` if (and only if) it has reached `parked`,
    else `None`. Deliberately NOT `dict-or-False` -- an earlier version of
    this helper used `row and row["status"] == "parked" and row`, which
    evaluates to `False` (not `None`) while still running, and
    `_wait_until` returns its last result verbatim on timeout. `assert
    result is not None` against that `False` silently passes, so a turn
    that never parks would falsely read as parked. Verified live: this
    exact bug let a real gate regression (see approvals.py's
    `_dispatch_name` fix) through a first pass of this cell."""
    row = _journal_row_for(container, turn_id)
    if row is not None and row["status"] == "parked":
        return row
    return None


def _restart_invocations(container: str) -> list[str]:
    result = run(
        ["docker", "exec", container, "cat", SIDE_EFFECT_LOG],
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _deploy_live_approvals(project, monkeypatch, key: str, url: str):
    (project / ".env").write_text(f"ANTHROPIC_API_KEY={key}\nANTHROPIC_API_URL={url}\n")

    run(
        ["uv", "run", "vystak", "init", "--framework", "langchain-python", "--force", "."],
        cwd=project,
    )
    (project / "vystak.yaml").unlink(missing_ok=True)
    (project / "vystak.py").write_text(_live_vystak_py())
    (project / "tools" / "__init__.py").write_text("")
    (project / "tools" / "read_status.py").write_text(_READ_STATUS)
    (project / "tools" / "restart_service.py").write_text(_RESTART_SERVICE_LIVE)

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-nats")
    assert docker_running("vystak-channel-panel")
    assert docker_running(AGENT_CONTAINER)


@pytest.fixture
def live_credentials():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not _looks_real(key):
        pytest.skip(
            "ANTHROPIC_API_KEY not set or looks like a sentinel -- live "
            "approval test requires real credentials"
        )
    return key, os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com")


@pytest.mark.release_live_chat
@pytest.mark.docker
def test_live_approval_approve_runs_gated_tool_once(
    project, docker_required, durable_volume_clean, panel_approvals_clean,
    monkeypatch, live_credentials,
):
    """release_live_chat: real LLM, approve path.

    Strict ordering: the turn must reach `parked` in the journal, and the
    persisted conversation must carry the `approval-requested` part,
    BEFORE any line lands in the side-effect log -- proof the gate ran
    before the tool, not after (see module docstring: this exact assertion
    caught a real "gate never fires" regression during development, and
    was verified to fail correctly against the broken build). After
    approving: exactly one side-effect line, `active_turn_id` clears, the
    journal reaches `done`, and a final assistant row exists.
    """
    key, url = live_credentials
    _deploy_live_approvals(project, monkeypatch, key, url)

    with httpx.Client(timeout=30.0) as client:
        project_id, conv_id = _bootstrap_panel_conversation(client, "approvals-agent")
        turn_id = _dispatch_turn_and_get_id(client, conv_id, project_id)

        parked_row = _wait_until(
            lambda: _parked_row(AGENT_CONTAINER, turn_id),
            timeout=90,
            interval=1.0,
        )
        assert parked_row is not None, "turn never parked on the gated tool"

        # Strict: no side effect yet. A broken gate would have let
        # restart_service run before (or instead of) parking.
        assert _restart_invocations(AGENT_CONTAINER) == [], (
            "restart_service ran before the approval gate parked the turn"
        )

        messages = client.get(
            _panel(f"/api/conversations/{conv_id}/messages"), headers=_headers()
        ).json()["messages"]
        pending = next(
            (
                m
                for m in messages
                if any(
                    p.get("type") == "tool"
                    and p.get("state") == "approval-requested"
                    and p.get("tool_name") == "restart_service"
                    for p in (m.get("parts") or [])
                )
            ),
            None,
        )
        assert pending is not None, (
            f"no persisted approval-requested part for restart_service: {messages}"
        )

        approve_resp = client.post(
            _panel(f"/api/conversations/{conv_id}/approval"),
            json={"turn_id": turn_id, "approved": True, "note": None},
            headers=_headers(),
        )
        assert approve_resp.status_code == 200, approve_resp.text

        def _turn_over():
            convs = client.get(
                _panel(f"/api/projects/{project_id}/conversations"), headers=_headers()
            ).json()["conversations"]
            match = next(c for c in convs if c["id"] == conv_id)
            return match if match["active_turn_id"] is None else None

        final_conv = _wait_until(_turn_over, timeout=120, interval=2.0)
        assert final_conv is not None, "turn never concluded after approval"

        final_row = _journal_row_for(AGENT_CONTAINER, turn_id)
        assert final_row is not None and final_row["status"] == "done", (
            f"journal row didn't reach done: {final_row}"
        )

        invocations = _restart_invocations(AGENT_CONTAINER)
        assert len(invocations) == 1, f"expected exactly one restart, got {invocations}"

        messages = client.get(
            _panel(f"/api/conversations/{conv_id}/messages"), headers=_headers()
        ).json()["messages"]
        assistant_rows = [m for m in messages if m["role"] == "assistant"]
        assert assistant_rows, "no final assistant row after approval"

    assert_destroy_ok(cwd=project)


@pytest.mark.release_live_chat
@pytest.mark.docker
def test_live_approval_deny_skips_gated_tool(
    project, docker_required, durable_volume_clean, panel_approvals_clean,
    monkeypatch, live_credentials,
):
    """release_live_chat: real LLM, deny path.

    Same deploy + park mechanics as the approve cell (fresh conversation).
    On deny: zero side-effect log lines ever, the turn still concludes
    normally (journal `done`, not `failed` -- the model adapts and
    replies), and a final assistant row exists.
    """
    key, url = live_credentials
    _deploy_live_approvals(project, monkeypatch, key, url)

    with httpx.Client(timeout=30.0) as client:
        project_id, conv_id = _bootstrap_panel_conversation(client, "approvals-agent")
        turn_id = _dispatch_turn_and_get_id(client, conv_id, project_id)

        parked_row = _wait_until(
            lambda: _parked_row(AGENT_CONTAINER, turn_id),
            timeout=90,
            interval=1.0,
        )
        assert parked_row is not None, "turn never parked on the gated tool"
        assert _restart_invocations(AGENT_CONTAINER) == [], (
            "restart_service ran before any decision was made"
        )

        deny_resp = client.post(
            _panel(f"/api/conversations/{conv_id}/approval"),
            json={"turn_id": turn_id, "approved": False, "note": "not now"},
            headers=_headers(),
        )
        assert deny_resp.status_code == 200, deny_resp.text

        def _turn_over():
            convs = client.get(
                _panel(f"/api/projects/{project_id}/conversations"), headers=_headers()
            ).json()["conversations"]
            match = next(c for c in convs if c["id"] == conv_id)
            return match if match["active_turn_id"] is None else None

        final_conv = _wait_until(_turn_over, timeout=120, interval=2.0)
        assert final_conv is not None, "turn never concluded after denial"

        final_row = _journal_row_for(AGENT_CONTAINER, turn_id)
        assert final_row is not None and final_row["status"] == "done", (
            f"journal row didn't reach done (denial should not fail the turn): {final_row}"
        )

        assert _restart_invocations(AGENT_CONTAINER) == [], (
            f"restart_service ran despite denial: {_restart_invocations(AGENT_CONTAINER)}"
        )

        messages = client.get(
            _panel(f"/api/conversations/{conv_id}/messages"), headers=_headers()
        ).json()["messages"]
        assistant_rows = [m for m in messages if m["role"] == "assistant"]
        assert assistant_rows, "no final assistant row after denial"

    assert_destroy_ok(cwd=project)


# ----- Slack cell ---------------------------------------------------------

_SLACK_VYSTAK_PY = """\
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(name="local", type="docker", provider=docker, namespace="approvals-slack")

sonnet = ast.Model(
    name="llm",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
)

ops = ast.Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    needs_approval=["restart_service"],
)

approvals_agent = ast.Agent(
    name="approvals-agent",
    framework="langchain-python",
    instructions=(
        "When asked to fix the service, first call read_status, then call "
        "restart_service for the failing service, then summarize."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ops],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY"), ast.Secret(name="ANTHROPIC_API_URL")],
)

slack = ast.Channel(
    name="slack-main",
    type=ast.ChannelType.SLACK,
    platform=platform,
    secrets=[ast.Secret(name="SLACK_BOT_TOKEN"), ast.Secret(name="SLACK_APP_TOKEN")],
    agents=[approvals_agent],
)
"""


@pytest.fixture
def slack_env(project):
    bot = os.environ.get("SLACK_BOT_TOKEN")
    app = os.environ.get("SLACK_APP_TOKEN")
    if not bot or not app:
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set -- skipping slack approvals cell")
    env_path = project / ".env"
    with env_path.open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project


@pytest.mark.release_slack
@pytest.mark.docker
def test_slack_approvals_deploy_smoke(slack_env, docker_required, durable_volume_clean):
    """release_slack: deploy-only smoke for a gated tool behind Slack.

    Slack's Block Kit Approve/Deny buttons require a real workspace click
    to drive end to end -- there is no mechanical proxy for "a human
    pressed the button" available to this cell (slack-bolt registers its
    `app.action(...)` handlers at import time, not observably in
    `docker logs`, so asserting "handlers registered" would just be
    re-testing that the container imported without raising, which the
    health check below already covers more directly). This cell verifies
    only the deploy-side mechanics: the agent and slack channel containers
    come up healthy with the gated skill, and cross-principal secret
    isolation holds. The full human click-through is documented in
    `examples/docker-approvals/README.md`, "Walkthrough: Slack (optional)".
    """
    project = slack_env
    run(
        ["uv", "run", "vystak", "init", "--framework", "langchain-python", "--force", "."],
        cwd=project,
    )
    (project / "vystak.yaml").unlink(missing_ok=True)
    (project / "vystak.py").write_text(_SLACK_VYSTAK_PY)
    (project / "tools" / "__init__.py").write_text("")
    (project / "tools" / "read_status.py").write_text(_READ_STATUS)
    (project / "tools" / "restart_service.py").write_text(_RESTART_SERVICE_LIVE)

    assert_apply_ok(cwd=project)
    assert docker_running(AGENT_CONTAINER)
    assert docker_running("vystak-channel-slack")

    from .conftest import assert_isolation

    assert_isolation(
        containers_to_secrets={
            AGENT_CONTAINER: {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
            "vystak-channel-slack": {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
        },
        forbidden_per_container={
            AGENT_CONTAINER: {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
            "vystak-channel-slack": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
        },
    )

    assert_destroy_ok(cwd=project)
    assert not docker_running(AGENT_CONTAINER)
    assert not docker_running("vystak-channel-slack")
