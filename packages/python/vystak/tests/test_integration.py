"""Integration test: define an agent using the top-level API, hash it, serialize it."""

import vystak as ast


def test_namespace_api():
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(name="bot", model=model)
    assert agent.name == "bot"


def test_direct_import_api():
    from vystak import Agent, Model, Provider

    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = Agent(name="bot", model=model)
    assert agent.name == "bot"


def test_full_agent_definition():
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    docker = ast.Provider(name="docker", type="docker")
    aws = ast.Provider(name="aws", type="aws")

    sonnet = ast.Model(
        name="sonnet",
        provider=anthropic,
        model_name="claude-sonnet-4-20250514",
        parameters={"temperature": 0.7},
    )

    agent = ast.Agent(
        name="support-bot",
        model=sonnet,
        skills=[
            ast.Skill(
                name="refund-handling",
                tools=["lookup_order", "process_refund"],
                prompt="Always verify the order before processing a refund.",
                guardrails={"max_amount": 500},
            ),
        ],
        channels=[
            ast.Channel(name="api", type=ast.ChannelType.API),
            ast.Channel(name="slack", type=ast.ChannelType.SLACK, config={"channel": "#support"}),
        ],
        mcp_servers=[
            ast.McpServer(name="github", transport=ast.McpTransport.STDIO, command="github-mcp"),
        ],
        workspace=ast.Workspace(
            name="sandbox",
            type=ast.WorkspaceType.SANDBOX,
            filesystem=True,
            terminal=True,
            timeout="30m",
        ),
        resources=[ast.SessionStore(name="sessions", provider=aws, engine="redis")],
        secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
        platform=ast.Platform(name="local", type="docker", provider=docker),
    )

    assert agent.name == "support-bot"
    assert len(agent.skills) == 1
    assert len(agent.channels) == 2
    assert len(agent.mcp_servers) == 1
    assert agent.workspace.filesystem is True
    assert len(agent.resources) == 1
    assert len(agent.secrets) == 1
    assert agent.platform.type == "docker"


def test_hash_agent():
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(
        name="bot", model=model, skills=[ast.Skill(name="greeting", tools=["say_hello"])]
    )
    tree = ast.hash_agent(agent)
    assert tree.root
    assert tree.brain
    assert len(tree.root) == 64


def test_yaml_roundtrip(tmp_path):
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(
        name="bot",
        model=model,
        skills=[ast.Skill(name="greeting", tools=["say_hello"])],
        channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    )
    path = tmp_path / "agent.yaml"
    ast.dump_agent(agent, path)
    restored = ast.load_agent(path)
    assert restored == agent


def test_hash_change_detection():
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent1 = ast.Agent(name="bot", model=model, skills=[ast.Skill(name="a")])
    agent2 = ast.Agent(name="bot", model=model, skills=[ast.Skill(name="b")])
    tree1 = ast.hash_agent(agent1)
    tree2 = ast.hash_agent(agent2)
    assert tree1.skills != tree2.skills
    assert tree1.brain == tree2.brain
    assert tree1.root != tree2.root
