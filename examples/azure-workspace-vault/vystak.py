"""Azure + workspace sidecar — demonstrates LLM ↔ tool-secret isolation.

The agent container holds ANTHROPIC_API_KEY (needed to call the model) but
can NOT read STRIPE_API_KEY. STRIPE_API_KEY lives only inside the workspace
sidecar container, reachable by the tool process (``charge_card``) via
``vystak.secrets.get("STRIPE_API_KEY")``. Each container has a separate
User-Assigned Managed Identity with ``lifecycle: None``.

Run:
    cp .env.example .env       # then fill in both keys
    vystak apply
    vystak secrets list
    vystak destroy
"""

import vystak as ast

azure = ast.Provider(
    name="azure",
    type="azure",
    config={
        "location": "eastus2",
        "resource_group": "vystak-ws-example-rg",
    },
)
anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault",
    provider=azure,
    mode=ast.VaultMode.DEPLOY,
    config={"vault_name": "vystak-ws-example-vault"},
)

platform = ast.Platform(name="aca", type="container-apps", provider=azure)
model = ast.Model(
    name="sonnet",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
)

workspace = ast.Workspace(
    name="tools",
    type=ast.WorkspaceType.PERSISTENT,
    secrets=[ast.Secret(name="STRIPE_API_KEY")],
    filesystem=True,
)

agent = ast.Agent(
    name="assistant",
    instructions="Use the charge_card tool to collect Stripe payments.",
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    workspace=workspace,
    skills=[ast.Skill(name="payments", tools=["charge_card"])],
    platform=platform,
)
