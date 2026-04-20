"""Minimal Azure Key Vault example — one agent, model API key via vault.

Run:
    cp .env.example .env    # then fill in ANTHROPIC_API_KEY
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
        "resource_group": "vystak-vault-example-rg",
    },
)

anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault",
    provider=azure,
    mode=ast.VaultMode.DEPLOY,
    config={"vault_name": "vystak-vault-example"},
)

platform = ast.Platform(name="aca", type="container-apps", provider=azure)

model = ast.Model(
    name="sonnet",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
)

agent = ast.Agent(
    name="assistant",
    instructions="You are a helpful assistant.",
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    platform=platform,
)
