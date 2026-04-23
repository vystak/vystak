"""Docker + HashiCorp Vault — agent + workspace sidecar with real secret isolation."""

import vystak as ast


docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault",
    provider=docker,
    type="vault",
    mode="deploy",
    config={},
)

platform = ast.Platform(name="local", type="docker", provider=docker)

model = ast.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

workspace = ast.Workspace(
    name="tools",
    type="persistent",
    secrets=[ast.Secret(name="STRIPE_API_KEY")],
    filesystem=True,
)

agent = ast.Agent(
    name="assistant",
    instructions="Use charge_card for Stripe charges.",
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    workspace=workspace,
    skills=[ast.Skill(name="payments", tools=["charge_card"])],
    platform=platform,
)
