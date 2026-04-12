#!/usr/bin/env python3
"""Preview the generated code without deploying.

Run: uv run python examples/hello-agent/preview.py
"""

from pathlib import Path

from agentstack.schema.loader import load_agent
from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter


def main():
    agent_path = Path(__file__).parent / "agentstack.yaml"
    agent = load_agent(agent_path)

    print(f"Agent: {agent.name}")
    print(f"Model: {agent.model.provider.type} / {agent.model.model_name}")
    print(f"Skills: {[s.name for s in agent.skills]}")
    print(f"Channels: {[c.name for c in agent.channels]}")
    print()

    # Validate
    adapter = LangChainAdapter()
    errors = adapter.validate(agent)
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  {err.field}: {err.message}")
        return

    # Hash
    tree = hash_agent(agent)
    print(f"Hash: {tree.root[:16]}...")
    print(f"  brain:       {tree.brain[:16]}...")
    print(f"  skills:      {tree.skills[:16]}...")
    print(f"  channels:    {tree.channels[:16]}...")
    print()

    # Generate
    code = adapter.generate(agent)
    print(f"Generated {len(code.files)} files (entrypoint: {code.entrypoint})")
    print()

    for filename, content in code.files.items():
        print(f"{'=' * 60}")
        print(f"  {filename}")
        print(f"{'=' * 60}")
        print(content)
        print()


if __name__ == "__main__":
    main()
