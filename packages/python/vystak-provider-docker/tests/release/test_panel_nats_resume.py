"""Panel x NATS -- detached, resumable streaming (integration tier).

Deploys the panel channel on the NATS transport, starts a turn, and drops
the POST connection immediately. The failure or success of the underlying
LLM call is irrelevant to what this test proves: the turn outcome flows
through JetStream to the panel's **detached** persister, which writes the
assistant row (when there is output) and always clears `active_turn_id`
with no browser attached. Then the resume endpoint must report 204 (turn
over). This proves the decoupling that HTTP streaming cannot provide: the
turn outcome lands regardless of the requester.

Deliberately diverges from the D-series smoke cells (and from this repo's
own `test_D4_docker_default_chat_stream.py`, cited as the reference idiom)
in three ways forced by the current CLI/schema behaviour, verified by hand
before this file was written:

1. The agent config is authored as `vystak.py` (module-level `Agent` /
   `Channel` objects), not `vystak.yaml`. A YAML `channels: [...]` block's
   `agents:` field only gets its string references resolved for
   type in ("slack", "chat", "discord") -- see
   `vystak.schema.multi_loader._resolve_channel_agent_refs`. Panel isn't in
   that tuple, so a YAML panel channel's `agents:` list of agent names
   would fail Agent validation (or silently resolve to no routes). The
   `.py` DSL passes real `Agent` objects directly, sidestepping the gap.
2. Every agent needs an explicit `framework=` -- confirmed empirically
   that `Agent.framework` is a required field with no default (since
   commit 244e9e6, "Agent.framework is now required; drop default").
   The existing D1-D8 release cells never added it, so those cells
   currently fail at `vystak plan` with a pydantic "framework: Field
   required" error -- a pre-existing, unrelated breakage (this suite
   isn't part of `just ci-live`; see repo CLAUDE.md "Release tests
   never run in GitHub Actions"). Out of scope to fix here.
3. `vystak apply` now hard-requires `_vystak/manifest.json` in the
   project dir (`_validate_template_for_apply`, added the same day as
   #2) -- i.e. the project must be scaffolded via `vystak init` first.
   The D1-D8 `project` fixture usage predates this and never scaffolds,
   so those cells also fail here independent of #2. This test calls
   `vystak init` itself before writing its own `vystak.py` over the
   scaffolded placeholder.

One more non-obvious wrinkle: channel secrets (unlike agent secrets) are
delivered from `os.environ` at apply time, not from the project's `.env`
file -- see `vystak_provider_docker.nodes.channel`'s default (no-vault)
path. `PANEL_SERVICE_TOKEN` must be set via `monkeypatch.setenv`, not by
writing it into `.env`.
"""

from __future__ import annotations

import time

import httpx
import pytest

from .conftest import assert_apply_ok, assert_destroy_ok, docker_exec, docker_running, run

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]

PANEL_PORT = 18111
SERVICE_TOKEN = "test-panel-token"
ADMIN = "admin@example.test"

# `.py` DSL config: a single agent + the panel channel routed to it, both on
# a docker platform whose transport is NATS/JetStream. Agent objects are
# passed directly into `agents=[paneled]` -- no string-ref resolution
# needed (see module docstring point 1).
PANEL_NATS_PY = f"""\
import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="panel-nats-test",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True),
    ),
)

sonnet = ast.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

paneled = ast.Agent(
    name="paneled",
    framework="langchain-python",
    default_model=sonnet,
    platform=platform,
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
    agents=[paneled],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
"""


def _panel(path: str) -> str:
    return f"http://localhost:{PANEL_PORT}{path}"


def _headers(user: str = ADMIN) -> dict:
    return {"Authorization": f"Bearer {SERVICE_TOKEN}", "X-Panel-User": user}


@pytest.fixture
def panel_clean():
    """Remove stale panel state before this test runs.

    The panel's sqlite DB lives on `vystak-panel-state`, a volume that
    (like the vault/postgres/workspace volumes this suite already guards
    against) persists across `vystak destroy` by design -- and the
    channel container name (`vystak-channel-panel`) isn't namespaced per
    project. Without this, a prior run's admin user survives and this
    run's `/api/setup` 409s against a stranger, or a stale container
    blocks the fresh one from binding the port. Mirrors `vault_clean`'s
    pattern for the same class of problem.
    """
    run(["docker", "rm", "-f", "vystak-channel-panel"], check=False)
    run(["docker", "volume", "rm", "vystak-panel-state"], check=False)
    yield


def test_panel_nats_detached_persistence(project, panel_clean, monkeypatch):
    # Scaffold the project (required by `_validate_template_for_apply`
    # since the no-codegen pivot), then replace the placeholder
    # `vystak.yaml` it drops with our own `vystak.py` -- `find_agent_file`
    # prefers vystak.yaml over vystak.py, so the placeholder must go.
    run(
        ["uv", "run", "vystak", "init", "--framework", "langchain-python", "--force", "."],
        cwd=project,
    )
    (project / "vystak.yaml").unlink(missing_ok=True)
    (project / "vystak.py").write_text(PANEL_NATS_PY)

    # Channel secrets are read from the apply process's own environment,
    # not from the project .env file (see module docstring).
    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-nats")
    assert docker_running("vystak-channel-panel")
    assert docker_running("vystak-paneled")

    # Confirm the NATS branch is actually wired before trusting a 204 --
    # `resume_stream` also returns 204 when `rt.nats_client is None`, so
    # this check is what keeps the final assertion from passing vacuously.
    panel_env = docker_exec("vystak-channel-panel", "env")
    assert "VYSTAK_TRANSPORT_TYPE=nats" in panel_env, (
        f"panel channel not wired for NATS:\n{panel_env}"
    )

    with httpx.Client(timeout=30.0) as client:
        # panel readiness
        for _ in range(30):
            try:
                if client.get(_panel("/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("panel API never became healthy")

        # bootstrap admin + conversation. Setup may 409 if `panel_clean`
        # missed a volume from a differently-named prior deployment --
        # tolerate it and proceed as the existing admin.
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
            json={"agent_name": "paneled"}, headers=_headers(),
        ).json()["conversation"]

        # Start a turn and DROP the connection immediately: read at most
        # one SSE line, then close. The detached persister must finish
        # the job regardless.
        try:
            with client.stream(
                "POST", _panel(f"/api/conversations/{conv['id']}/messages"),
                json={"text": "ping"}, headers=_headers(),
            ) as resp:
                assert resp.status_code == 200
        except httpx.HTTPError:
            pass  # dropping mid-stream can surface as a transport error

        # Poll for the detached outcome: either the assistant row lands
        # (turn produced output) or the active turn clears with no row
        # (an errored empty turn -- e.g. the sentinel key failing fast --
        # writes no row per Task 7 semantics, matching HTTP behaviour).
        # Exit as soon as either is observed instead of always burning
        # the full deadline.
        deadline = time.time() + 90
        assistant_rows: list[dict] = []
        resume = None
        while time.time() < deadline:
            msgs = client.get(
                _panel(f"/api/conversations/{conv['id']}/messages"),
                headers=_headers(),
            ).json()["messages"]
            assistant_rows = [m for m in msgs if m["role"] == "assistant"]
            resume = client.get(
                _panel(f"/api/conversations/{conv['id']}/stream"), headers=_headers()
            )
            if assistant_rows or resume.status_code == 204:
                break
            time.sleep(2)

        assert resume is not None and resume.status_code == 204, (
            f"expected turn to be over (204), got "
            f"{resume.status_code if resume else 'no response'}"
        )
        if assistant_rows:
            assert assistant_rows[0].get("turn_id"), "assistant row missing turn_id"

        # The 204 above is only proof of the detached persister at work if
        # the turn actually started on the agent side. With sentinel
        # credentials, `assistant_rows` is typically empty (the LLM call
        # fails fast, an errored empty turn writes no row) -- so the 204 +
        # empty-row combination alone would also be true if `createDetached`
        # never reached the agent at all. Require positive proof the
        # detached dispatch happened (`tx responses/createDetached ...` is
        # logged unconditionally, success or failure) and rule out the
        # specific short-circuit where it failed outright.
        logs = run(
            ["docker", "logs", "--tail", "200", "vystak-channel-panel"], check=False,
        )
        combined_log = logs.stdout + logs.stderr
        assert "tx responses/createDetached" in combined_log, (
            f"createDetached was never dispatched to the agent:\n{combined_log}"
        )
        assert "createDetached failed" not in combined_log, (
            f"createDetached failed outright rather than running the turn:\n{combined_log}"
        )

    assert_destroy_ok(cwd=project)
