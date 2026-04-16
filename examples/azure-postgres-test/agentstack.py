"""Azure Postgres test — agent with session persistence on managed Flexible Server."""

import agentstack as ast

azure = ast.Provider(name="azure", type="azure", config={
    "subscription_id": "YOUR_SUBSCRIPTION_ID",
    "resource_group": "agentstack-pg-test-rg",
    "location": "eastus2",
})
anthropic = ast.Provider(name="anthropic", type="anthropic")
model = ast.Model(
    name="minimax", provider=anthropic, model_name="MiniMax-M2.7",
    parameters={"temperature": 0.7, "anthropic_api_url": "https://api.minimax.io/anthropic"},
)
platform = ast.Platform(name="aca", type="container-apps", provider=azure)
db = ast.Postgres(name="test-db", provider=azure)

agent = ast.Agent(
    name="pg-test-agent",
    instructions="You are a helpful assistant. Remember what the user tells you across messages.",
    model=model,
    platform=platform,
    sessions=db,
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
