"""Docker workspace compute — coding assistant with fs/exec/git built-ins + custom tool."""

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
    name="dev",
    image="python:3.12-slim",
    provision=[
        "apt-get update && apt-get install -y git ripgrep",
        "pip install ruff pytest",
    ],
    persistence="volume",
)

agent = ast.Agent(
    name="coder",
    instructions=(
        "You are a coding assistant. Use fs.readFile to read, fs.edit to change, "
        "exec.run to test, git.status / git.diff to review changes."
    ),
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    workspace=workspace,
    skills=[
        ast.Skill(name="editing", tools=["fs.readFile", "fs.writeFile", "fs.listDir", "fs.edit"]),
        ast.Skill(name="shell", tools=["exec.run", "exec.shell"]),
        ast.Skill(name="vcs", tools=["git.status", "git.diff", "git.commit"]),
        ast.Skill(name="search", tools=["search_project"]),
    ],
    platform=platform,
)
