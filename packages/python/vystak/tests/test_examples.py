"""Smoke tests: every published example under `examples/<name>/vystak.yaml`
loads cleanly through the multi-loader.

These are cheap, offline sanity checks — they do not deploy anything. They
exist because it is easy for a drift in the schema to silently break one
example while the rest of the test suite stays green. Running these in CI
catches the breakage at the source.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from vystak.schema.multi_loader import load_multi_yaml


def _examples_dir() -> Path:
    # packages/python/vystak/tests/test_examples.py → repo root
    return Path(__file__).resolve().parent.parent.parent.parent.parent / "examples"


def test_azure_vault_example_loads():
    """`examples/azure-vault/vystak.yaml` — the minimal one-agent vault example.

    Validates:
    - YAML parses via ``load_multi_yaml``.
    - Top-level ``vault:`` is materialized into a ``Vault`` model (not None).
    - The single declared agent has ``ANTHROPIC_API_KEY`` as a model-side secret.
    """
    path = _examples_dir() / "azure-vault" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, vault = load_multi_yaml(data)

    assert vault is not None, "Expected a top-level vault: block to materialize"
    assert len(agents) == 1
    assert agents[0].name == "assistant"
    assert agents[0].secrets[0].name == "ANTHROPIC_API_KEY"


def test_azure_workspace_vault_example_loads():
    """`examples/azure-workspace-vault/vystak.yaml` — agent + workspace sidecar.

    Validates:
    - Top-level vault materializes.
    - The agent declares ``ANTHROPIC_API_KEY`` as its own secret.
    - The agent has a workspace whose secrets include ``STRIPE_API_KEY`` —
      tools inside the workspace sidecar read this via ``vystak.secrets.get``
      while the LLM-facing agent container cannot reach it.
    """
    path = _examples_dir() / "azure-workspace-vault" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, vault = load_multi_yaml(data)

    assert vault is not None
    assert len(agents) == 1
    agent = agents[0]
    assert agent.secrets[0].name == "ANTHROPIC_API_KEY"
    assert agent.workspace is not None
    assert agent.workspace.secrets[0].name == "STRIPE_API_KEY"


def test_docker_workspace_vault_example_loads():
    path = _examples_dir() / "docker-workspace-vault" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert vault.type.value == "vault"
    assert vault.provider.type == "docker"
    assert agents[0].workspace is not None
    assert agents[0].workspace.secrets[0].name == "STRIPE_API_KEY"


def test_docker_workspace_compute_example_loads():
    """`examples/docker-workspace-compute/vystak.yaml` — coding assistant with
    fs/exec/git built-in services, custom search tool, and Vault-backed SSH.

    Validates:
    - Vault materializes (required for workspace).
    - Workspace declares ``image`` + multi-step ``provision``.
    - ``persistence: volume`` round-trips cleanly.
    """
    path = _examples_dir() / "docker-workspace-compute" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace is not None
    assert agents[0].workspace.image == "python:3.12-slim"
    assert "pip install ruff pytest" in agents[0].workspace.provision[1]


def test_docker_workspace_nodejs_example_loads():
    """`examples/docker-workspace-nodejs/vystak.yaml` — workspace on the
    default (no-Vault) delivery path.

    Validates:
    - No top-level ``vault:`` block → loader returns ``vault=None``.
    - The agent declares ``ANTHROPIC_API_KEY`` + ``ANTHROPIC_API_URL`` as
      model-side secrets (delivered via per-container ``--env-file``).
    - The workspace declares a node:20-slim image with multi-step
      provisioning AND its own ``STRIPE_API_KEY`` secret — the example
      demonstrates the per-container isolation invariant without Vault.
    """
    path = _examples_dir() / "docker-workspace-nodejs" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is None, (
        "docker-workspace-nodejs demonstrates the default (no-Vault) path"
    )
    assert len(agents) == 1
    assert agents[0].name == "node-coder"
    agent_secret_names = {s.name for s in agents[0].secrets}
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"} <= agent_secret_names
    assert agents[0].workspace is not None
    assert agents[0].workspace.image == "node:20-slim"
    assert any("typescript" in step for step in agents[0].workspace.provision)
    # Workspace-scoped secret demonstrates per-container isolation.
    workspace_secret_names = {s.name for s in agents[0].workspace.secrets}
    assert "STRIPE_API_KEY" in workspace_secret_names
    # Cross-scoping invariant: workspace secrets must not appear on the agent
    # and vice versa.
    assert "STRIPE_API_KEY" not in agent_secret_names
    assert "ANTHROPIC_API_KEY" not in workspace_secret_names


def test_docker_slack_example_loads():
    """`examples/docker-slack/vystak.yaml` — Slack channel with self-serve routing."""
    path = _examples_dir() / "docker-slack" / "vystak.yaml"
    assert path.exists(), f"Example file missing: {path}"

    data = yaml.safe_load(path.read_text())
    agents, channels, _vault = load_multi_yaml(data)

    assert len(agents) == 1
    assert agents[0].name == "weather-agent"
    assert len(channels) == 1
    ch = channels[0]
    assert ch.type.value == "slack"
    # Single routable agent — channel will auto-bind on invite.
    assert [a.name for a in ch.agents] == ["weather-agent"]
    # state defaults applied at load time
    assert ch.state is not None
    assert ch.state.type == "sqlite"
    assert ch.state.path == "/data/channel-state.db"
