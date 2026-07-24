# packages/python/vystak-provider-docker/tests/release/test_workspace_tools_v11.py
"""V11 + seed-folder cell — Docker default path, no LLM.

Proves the full agent→workspace SSH-RPC path (keys, known_hosts,
subsystem, jail) by running the shipped WorkspaceRpcClient INSIDE the
agent container, plus seed-folder copy-if-absent semantics across
re-applies. Sentinel API keys throughout.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_apply_ok,
    assert_destroy_ok,
    docker_exec,
    docker_running,
    run,
    vystak,
)

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]


WS_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: wstools
    framework: langchain-python
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    workspace:
      name: dev
      image: python:3.12-slim
"""

V11_SNIPPET = """\
import asyncio, os, sys
sys.path.insert(0, "/app")
from _vystak.runtime.workspace import _make_client

async def main():
    c = _make_client(os.environ["VYSTAK_WORKSPACE_HOST"])
    entries = await c.invoke("fs.listDir", path=".")
    print(sorted(e["name"] for e in entries))
    await c.close()

asyncio.run(main())
"""

TOOLS_SNIPPET = """\
import asyncio, sys, types
sys.path.insert(0, "/app")
from _vystak.runtime.workspace import build_workspace_tools

agent = types.SimpleNamespace(name="wstools", workspace=types.SimpleNamespace(name="dev"))

async def main():
    tools = {t.name: t for t in build_workspace_tools(agent)}
    out = await tools["run"].ainvoke({"cmd": "cat hello.txt"})
    print(out)

asyncio.run(main())
"""


def test_workspace_tools_v11_and_seed(workspace_clean, project):
    # `vystak apply` requires a scaffolded `_vystak/` tree (the no-codegen
    # pivot's apply-time validation, added after D1 was written — D1's
    # bare-yaml-then-apply pattern is stale against current main). Init
    # first, matching the real user workflow documented in CLAUDE.md, then
    # overwrite the template's default vystak.yaml with our own. --force
    # is required because the `project` fixture pre-creates `.env` +
    # `tools/`, making the target dir non-empty.
    vystak(["init", "--framework", "langchain-python", "--force", "."], cwd=project)
    (project / "vystak.yaml").write_text(WS_YAML)
    seed = project / "workspaces" / "dev"
    seed.mkdir(parents=True)
    (seed / "hello.txt").write_text("seeded-v1\n")

    assert_apply_ok(project)
    assert docker_running("vystak-wstools")
    assert docker_running("vystak-wstools-workspace")

    # Seed landed in /workspace
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/hello.txt"
    ).strip() == "seeded-v1"

    # V11 — shipped client, inside the agent container, over real SSH.
    result = run(
        ["docker", "exec", "-i", "vystak-wstools", "python3", "-"],
        input=V11_SNIPPET,
    )
    assert "hello.txt" in result.stdout, (
        f"V11 fs.listDir failed:\n{result.stdout}\n{result.stderr}"
    )

    # Tools layer — build_workspace_tools + the `run` tool end-to-end,
    # inside the agent container. This is the layer where the shlex-split
    # fix (client sends unstructured "cmd string" vs. the RPC server's
    # argv=[cmd] no-shell exec) actually hid; V11 above only exercises
    # _make_client + fs.listDir directly and would not have caught it.
    result = run(
        ["docker", "exec", "-i", "vystak-wstools", "python3", "-"],
        input=TOOLS_SNIPPET,
    )
    assert "seeded-v1" in result.stdout, (
        f"tools-layer run() failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "exit_code=0" in result.stdout, (
        f"tools-layer run() missing exit_code:\n{result.stdout}\n{result.stderr}"
    )

    # Copy-if-absent across re-apply: mutate the seeded file in the
    # workspace, re-apply (rebuilds + restarts the workspace container),
    # assert the mutation survived and a NEW seed file arrived.
    docker_exec(
        "vystak-wstools-workspace",
        "sh -c 'echo mutated > /workspace/hello.txt'",
    )
    (seed / "extra.txt").write_text("new-file\n")
    assert_apply_ok(project)
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/hello.txt"
    ).strip() == "mutated"
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/extra.txt"
    ).strip() == "new-file"

    assert_destroy_ok(project)
