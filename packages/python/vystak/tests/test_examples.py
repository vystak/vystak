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
