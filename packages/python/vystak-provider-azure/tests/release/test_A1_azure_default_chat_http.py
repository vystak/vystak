"""Cell A1 — azure × default × chat × http.

Smoke tier. Azure Container Apps with no Vault, chat channel, HTTP
transport. Each principal deploys as a separate ACA app; secrets are
inlined into each app's `configuration.secrets[]` and wired into env
via `secretRef`. No UAMI, no lifecycle:None — since no Vault is declared.

**Wall time expectation:** 3–5 minutes for first apply (RG + Log
Analytics + ACR + ACA env + image build + push + two app creates).
~30s for destroy (--no-wait). Tests use generous timeouts.

**Known limitation** — test_plan.md § "Known gaps": this cell today
still deploys **single-container apps per principal**; the
`build_revision_default_path` multi-container helper exists but is not
yet wired into `ContainerAppNode.provision`. Per-principal isolation
still holds because each principal gets its own ACA app with its own
env.
"""

from __future__ import annotations

import pytest

from .conftest import (
    app_exists,
    assert_agent_card_azure,
    assert_apply_ok,
    assert_env_contains,
    assert_health_azure,
    assert_plan_ok,
    vystak,
)

pytestmark = [pytest.mark.release_smoke_azure]


A1_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
  anthropic: {{type: anthropic}}
platforms:
  aca: {{type: container-apps, provider: azure}}
models:
  sonnet: {{provider: anthropic, model_name: claude-sonnet-4-20250514}}
channels:
  - name: chat
    type: chat
    platform: aca
agents:
  - name: smokeagentazure
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
"""


def test_A1_full_cycle(azure_project):
    project, rg_name = azure_project
    (project / "vystak.yaml").write_text(A1_YAML_TEMPLATE.format(rg_name=rg_name))

    # V1 — plan: EnvFiles section (default path), no Vault sections
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "smokeagentazure-agent"],
        absent_sections=["Vault:", "Identities:", "Grants:"],
    )

    # V2 — apply. Expect 3–5 min wall time.
    assert_apply_ok(cwd=project, timeout=900)
    assert app_exists("smokeagentazure", rg_name), "agent ACA app missing"
    # NOTE: chat channel on Azure is currently deployed as its own ACA
    # app; name pattern is `<channel-name>` per the provider. Verify
    # whichever name your provider emits here — this is a known area
    # of provider wiring that may evolve.

    # V3 — agent env contains its declared secrets
    assert_env_contains("smokeagentazure", rg_name, "ANTHROPIC_API_KEY")
    assert_env_contains("smokeagentazure", rg_name, "ANTHROPIC_API_URL")

    # V4 — health via HTTPS FQDN (ingress propagation can take 1–3 min
    # after app creation; conftest waits up to 180s by default)
    assert_health_azure("smokeagentazure", rg_name)

    # V5 — agent card
    card = assert_agent_card_azure("smokeagentazure", rg_name)
    assert card["name"] == "smokeagentazure"

    # V9 — destroy. --include-resources tears down RG + all Azure state.
    # The azure_project fixture also nukes the RG with `az group delete`
    # on teardown as belt-and-braces; destroy here just exercises the
    # CLI path.
    vystak(["destroy", "--include-resources", "--no-wait"], cwd=project, check=False)
