"""Durable/checkpointed execution — release cells for Task 15.

Two cells, both against `docker-panel-durable`'s shape (one agent + the
`panel` channel over the NATS transport; see `examples/docker-panel-durable`):

1. `test_durable_turn_restart_resumes_without_concluding` (`release_integration`):
   deterministic, sentinel credentials, no live LLM. Dispatches a turn,
   `docker restart`s the agent mid-flight, and asserts the mechanical facts
   that hold regardless of LLM behavior.
2. `test_durable_turn_live_resume_not_rerun` (`release_live_chat`): real
   `ANTHROPIC_API_KEY`, restarts mid-tool-call, and proves resume-from-
   checkpoint (four completed steps, not five) rather than a re-run.

Deviations from the brief, forced by behaviour verified by hand against a
live deploy before this file was written (mirrors `test_panel_nats_resume`'s
module-docstring convention for documenting exactly this kind of gap):

1. **A sentinel key against the real `api.anthropic.com` fails in well
   under a second** (measured: <350ms from dispatch to the journal row
   reading `status="failed"`). A `docker restart` — CLI dispatch, dockerd
   stop/start round trip — cannot reliably beat that; racing it made the
   cell flaky by design. The deterministic cell instead points
   `anthropic_api_url` at `192.0.2.1` (RFC 5737 TEST-NET-1, guaranteed
   non-routable) with a generous client `timeout`. Verified empirically:
   the connect attempt hangs (no fast ICMP reject observed in this
   network path) rather than failing, so `response.created` fires (see
   point 2), the journal row sits `running` indefinitely, and there is no
   race at all — the restart has minutes of margin, not milliseconds.

2. **The turn journal row exists before any restart is needed at all.**
   `openai/responses.py`'s `_stream_iterator` yields the `response.created`
   SSE event (which `nats_bridge` uses to capture `thread_id` into the
   journal) *before* calling the LangGraph model at all — so the journal
   row and its `thread_id` land within tens of milliseconds of dispatch,
   independent of whether the LLM call ever succeeds.

3. **`nats_bridge`'s own "sweep" log line never reaches `docker logs`.**
   The brief points at `nats_bridge.redrove_unfinished count=%d` (an
   `INFO`-level `logger.info` call) as the redrive signal. The runtime
   never calls `logging.basicConfig` (or any other handler setup) for the
   `vystak.runtime.nats_bridge` logger, so every `INFO` record from that
   logger is silently dropped by Python's `logging.lastResort` handler,
   which only surfaces `WARNING`+ records. Verified empirically: a
   redrive that completed normally (rewind published, resume streamed,
   200 OK) left zero `nats_bridge.*` lines in `docker logs`, at any level
   below `WARNING`. The reliable observable proxy is the *uvicorn access
   log* line for `POST /v1/_vystak/resume` — an endpoint the runtime only
   ever calls from the redrive path — combined with the journal's own
   `attempts` counter (bumped synchronously, before the slow LLM call,
   so it's independent of the logging gap and of the blackhole hang).

4. **Restart mid-`slow_step` yields five invocations, four completions**
   (README's own wording: the interrupted step "gets re-driven from the
   beginning of that step, not resumed mid-sleep"). Counting raw
   `slow_step` invocations after a restart would see 5, not 4, and
   misread that as evidence of a re-run rather than a resume. The live
   cell's `slow_step` instead appends its label to a `/data` side-effect
   file *after* `asyncio.sleep` returns (i.e., only on a step that ran to
   completion), and the assertion is the exact ordered list
   `["one", "two", "three", "four"]` — the interrupted call's line was
   never written, so a naive "5 invocations" bug would still show 4 here.

5. Same three CLI/schema requirements `test_panel_nats_resume` documents
   (`vystak.py` DSL not YAML — panel isn't in the YAML `agents:`
   string-ref resolution tuple; `framework=` is required with no default;
   `vystak apply` requires `vystak init` scaffolding first) apply here
   too; not re-derived, see that file's docstring for why.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

from .conftest import assert_apply_ok, assert_destroy_ok, docker_running, run

PANEL_PORT = 18140
SERVICE_TOKEN = "durable-test-panel-token"  # noqa: S105 — test fixture token, not a secret
ADMIN = "admin@example.test"
AGENT_CONTAINER = "vystak-durable-agent"
AGENT_VOLUME = "vystak-agent-durable-agent-data"

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


# `vystak.py` DSL config shared shape: one agent (`durable-agent`) + the
# `panel` channel, both on a docker platform whose transport is NATS. See
# module docstring point 5 for why this can't be a YAML `vystak.yaml`.
def _det_vystak_py() -> str:
    return f"""\
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="durable-turns-det",
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
    parameters={{
        "temperature": 0.3,
        # RFC 5737 TEST-NET-1 -- guaranteed non-routable. The connect
        # attempt hangs rather than failing fast (see module docstring
        # point 1), which is exactly what this cell needs: no live LLM,
        # no restart-race, and the journal row stays `running` well past
        # the 120s checkpoint below.
        "anthropic_api_url": "http://192.0.2.1",
        "timeout": 180.0,
    }},
)

durable_agent = ast.Agent(
    name="durable-agent",
    framework="langchain-python",
    instructions=(
        "You run a four-step job. When asked to run the job, call the "
        "slow_step tool exactly four times, in order, with label='one', "
        "then label='two', then label='three', then label='four'."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="steps", tools=["slow_step"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={{"port": {PANEL_PORT}}},
    agents=[durable_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
"""


def _live_vystak_py() -> str:
    return f"""\
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="durable-turns-live",
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

durable_agent = ast.Agent(
    name="durable-agent",
    framework="langchain-python",
    instructions=(
        "You run a four-step job. When asked to run the job, call the "
        "slow_step tool exactly four times, in order, with label='one', "
        "then label='two', then label='three', then label='four'. Wait "
        "for each call to complete before making the next one. After all "
        "four steps finish, reply with a short summary confirming all "
        "four steps completed."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="steps", tools=["slow_step"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={{"port": {PANEL_PORT}}},
    agents=[durable_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
"""


_SLOW_STEP_DET = """\
import asyncio


async def slow_step(label: str) -> str:
    \"\"\"Take a slow step in a multi-step job. Call once per step, in order.\"\"\"
    await asyncio.sleep(20)
    return f"step {label} complete"
"""

# The live cell's `slow_step` records a completion line to a `/data`
# side-effect file *after* the sleep returns -- see module docstring
# point 4 for why this (not a raw invocation count) is the "four, not
# five" proof.
_SLOW_STEP_LIVE = """\
import asyncio
from pathlib import Path

LOG_PATH = Path("/data/slow_step_completions.log")


async def slow_step(label: str) -> str:
    \"\"\"Take a slow step in a multi-step job. Call once per step, in order.\"\"\"
    await asyncio.sleep(20)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(label + "\\n")
    return f"step {label} complete"
"""


@pytest.fixture
def panel_durable_clean():
    """Remove stale panel state before this test runs.

    Mirrors `test_panel_nats_resume.py`'s `panel_clean`: the panel's
    sqlite DB volume and the (unnamespaced) channel container name both
    survive `vystak destroy`, so a prior run's admin user / bound port
    would otherwise leak into this one.
    """
    run(["docker", "rm", "-f", "vystak-channel-panel"], check=False)
    run(["docker", "volume", "rm", "vystak-panel-state"], check=False)
    yield


def _journal_rows(container: str) -> list[list] | None:
    """Read every row of `/data/turns.db`'s `detached_turns` table inside
    `container` via `docker exec ... python -c ...` (the agent image is a
    plain `python:3.12-slim` app -- no `sqlite3` CLI, but the stdlib
    module is always present). Returns `None` if the container can't be
    reached (e.g. mid-restart) rather than raising, so callers can poll.
    """
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
    """POST a message and drop the connection once headers land (mirrors
    `test_panel_nats_resume`'s pattern): the panel writes
    `active_turn_id` and acks the agent *before* streaming the SSE body,
    so this doesn't need to wait for any turn output. Returns the turn_id
    once it's visible on the conversation."""
    try:
        with client.stream(
            "POST",
            _panel(f"/api/conversations/{conv_id}/messages"),
            json={"text": "run the four-step job"},
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


@pytest.mark.release_integration
@pytest.mark.docker
def test_durable_turn_restart_resumes_without_concluding(
    project, docker_required, durable_volume_clean, panel_durable_clean, monkeypatch
):
    """release_integration: deterministic restart-mid-turn cell.

    No live LLM (see module docstring point 1 for why a sentinel key
    against the real API doesn't work here). Asserts only mechanical
    facts that hold regardless of what the LLM would have said:
    - the journal row exists and is `running` before any restart;
    - after `docker restart`, the sweep bumps `attempts` and publishes a
      rewind (advancing `last_seq`) -- proof a redrive was dispatched;
    - `/v1/_vystak/resume` was actually called (the observable proxy for
      the redrive path -- see module docstring point 3);
    - the panel still has `active_turn_id` set at the 120s mark from
      dispatch -- the turn has not concluded.
    """
    run(
        ["uv", "run", "vystak", "init", "--framework", "langchain-python", "--force", "."],
        cwd=project,
    )
    (project / "vystak.yaml").unlink(missing_ok=True)
    (project / "vystak.py").write_text(_det_vystak_py())
    (project / "tools" / "__init__.py").write_text("")
    (project / "tools" / "slow_step.py").write_text(_SLOW_STEP_DET)

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-nats")
    assert docker_running("vystak-channel-panel")
    assert docker_running(AGENT_CONTAINER)

    with httpx.Client(timeout=30.0) as client:
        project_id, conv_id = _bootstrap_panel_conversation(client, "durable-agent")

        t_dispatch = time.monotonic()
        turn_id = _dispatch_turn_and_get_id(client, conv_id, project_id)

        # Journal row exists, thread_id captured, still running -- proof
        # `response.created` fired before any restart (module docstring
        # point 2). `attempts` is still 0: no redrive has happened yet.
        row = _journal_row_for(AGENT_CONTAINER, turn_id)
        assert row is not None, f"journal row missing for turn {turn_id} before restart"
        assert row["status"] == "running", f"unexpected pre-restart status: {row}"
        assert row["attempts"] == 0, f"attempts already nonzero before any restart: {row}"
        assert row["thread_id"], f"thread_id not captured before restart: {row}"
        pre_restart_last_seq = row["last_seq"]

        # Restart -- the blackhole model URL (module docstring point 1)
        # gives this comfortable margin; it isn't a tight race.
        run(["docker", "restart", AGENT_CONTAINER], check=True)

        # The sweep bumps `attempts` synchronously (before the slow
        # resume call) and the rewind marker publish advances `last_seq`
        # -- both observable independent of whether the redrive's own
        # (blackholed) LLM call has resolved.
        def _redriven():
            r = _journal_row_for(AGENT_CONTAINER, turn_id)
            if r and r["attempts"] >= 1 and r["last_seq"] > pre_restart_last_seq:
                return r
            return None

        redriven_row = _wait_until(_redriven, timeout=90, interval=1.0)
        assert redriven_row is not None, (
            "redrive sweep never bumped attempts/last_seq after restart "
            f"(pre-restart: {row})"
        )
        assert redriven_row["status"] in ("running", "parked"), (
            f"turn already concluded shortly after restart: {redriven_row}"
        )

        logs = run(["docker", "logs", "--tail", "500", AGENT_CONTAINER], check=False)
        combined_log = logs.stdout + logs.stderr
        assert "/v1/_vystak/resume" in combined_log, (
            f"no resume call observed on the agent after restart:\n{combined_log}"
        )

        # At the 120s mark from dispatch, the panel must not have
        # concluded the turn.
        remaining = 120 - (time.monotonic() - t_dispatch)
        if remaining > 0:
            time.sleep(remaining)

        convs = client.get(
            _panel(f"/api/projects/{project_id}/conversations"), headers=_headers()
        ).json()["conversations"]
        match = next(c for c in convs if c["id"] == conv_id)
        assert match["active_turn_id"] == turn_id, (
            f"panel concluded the turn before the 120s mark: {match}"
        )

        final_row = _journal_row_for(AGENT_CONTAINER, turn_id)
        assert final_row is not None and final_row["status"] in ("running", "parked"), (
            f"journal row concluded before the 120s mark: {final_row}"
        )

    assert_destroy_ok(cwd=project)


@pytest.fixture
def live_credentials():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not _looks_real(key):
        pytest.skip(
            "ANTHROPIC_API_KEY not set or looks like a sentinel -- live "
            "durable-turn resume test requires real credentials"
        )
    return key, os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com")


@pytest.mark.release_live_chat
@pytest.mark.docker
def test_durable_turn_live_resume_not_rerun(
    project,
    docker_required,
    durable_volume_clean,
    panel_durable_clean,
    monkeypatch,
    live_credentials,
):
    """release_live_chat: real LLM, restart mid-tool-call.

    Proves resume-from-checkpoint rather than re-run: exactly one
    assistant row lands (carrying the turn's `turn_id`), `active_turn_id`
    clears, and the completion-log side effect (module docstring point 4)
    shows exactly `["one", "two", "three", "four"]` -- not five entries,
    and not "three" landing twice.
    """
    key, url = live_credentials
    (project / ".env").write_text(f"ANTHROPIC_API_KEY={key}\nANTHROPIC_API_URL={url}\n")

    run(
        ["uv", "run", "vystak", "init", "--framework", "langchain-python", "--force", "."],
        cwd=project,
    )
    (project / "vystak.yaml").unlink(missing_ok=True)
    (project / "vystak.py").write_text(_live_vystak_py())
    (project / "tools" / "__init__.py").write_text("")
    (project / "tools" / "slow_step.py").write_text(_SLOW_STEP_LIVE)

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-nats")
    assert docker_running("vystak-channel-panel")
    assert docker_running(AGENT_CONTAINER)

    with httpx.Client(timeout=30.0) as client:
        project_id, conv_id = _bootstrap_panel_conversation(client, "durable-agent")
        turn_id = _dispatch_turn_and_get_id(client, conv_id, project_id)

        def _completions():
            result = run(
                ["docker", "exec", AGENT_CONTAINER, "cat", "/data/slow_step_completions.log"],
                check=False,
            )
            if result.returncode != 0:
                return []
            return [line for line in result.stdout.splitlines() if line]

        # Wait for steps "one" and "two" to land, then restart partway
        # into step "three" -- a hard kill mid-`slow_step`, matching the
        # example README's manual walkthrough.
        _wait_until(lambda: len(_completions()) >= 2, timeout=60, interval=1.0)
        assert _completions()[:2] == ["one", "two"], _completions()
        time.sleep(10)  # ~10s into step "three"'s 20s sleep

        run(["docker", "restart", AGENT_CONTAINER], check=True)

        # Budget: step "three" re-driven from scratch (20s) + step
        # "four" (20s) + restart/redrive overhead.
        def _turn_over():
            convs = client.get(
                _panel(f"/api/projects/{project_id}/conversations"), headers=_headers()
            ).json()["conversations"]
            match = next(c for c in convs if c["id"] == conv_id)
            return match if match["active_turn_id"] is None else None

        final_conv = _wait_until(_turn_over, timeout=180, interval=3.0)
        assert final_conv is not None, "turn never concluded (active_turn_id still set)"

        messages = client.get(
            _panel(f"/api/conversations/{conv_id}/messages"), headers=_headers()
        ).json()["messages"]
        assistant_rows = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_rows) == 1, (
            f"expected exactly one assistant row, got {len(assistant_rows)}: {assistant_rows}"
        )
        assert assistant_rows[0].get("turn_id") == turn_id, (
            f"assistant row's turn_id doesn't match the dispatched turn: {assistant_rows[0]}"
        )

        # The resume-not-rerun proof: exactly these four labels, in
        # order, each exactly once. A re-run (rather than a resume) would
        # show "three" duplicated or five total entries.
        assert _completions() == ["one", "two", "three", "four"], _completions()

    assert_destroy_ok(cwd=project)
