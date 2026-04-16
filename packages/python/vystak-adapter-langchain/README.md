# vystak-adapter-langchain

Framework adapter that generates LangChain / LangGraph agent code from a Vystak `Agent` definition.

Vystak targets frameworks — it doesn't abstract them. This adapter emits **idiomatic LangGraph react-agent code** plus a FastAPI harness and A2A protocol endpoints, written as plain Python source files you can read, debug, and extend.

## Install

```bash
pip install vystak-adapter-langchain
```

Usually you don't install this directly — [`vystak-cli`](https://pypi.org/project/vystak-cli/) depends on it and invokes it automatically.

## What it generates

For each `vystak apply`, the adapter writes:

- **`agent.py`** — LangGraph `create_react_agent` setup bound to the configured model and tools
- **`server.py`** — FastAPI server exposing `/invoke`, `/stream`, `/health`, `/.well-known/agent.json`, `/a2a`
- **`requirements.txt`** — pinned runtime deps (`langgraph`, `langchain-anthropic`, `fastapi`, etc.)
- **Session/memory stores** — wired up automatically when `sessions` or `memory` are declared on the agent
- **Tool stubs** — scaffolded from `tools/` directory of Python files

## A2A protocol

Generated servers implement Google's [Agent-to-Agent](https://github.com/google/A2A) JSON-RPC 2.0 protocol — agents discover each other via `/.well-known/agent.json` and communicate via `/a2a` with `tasks/send`, `tasks/sendSubscribe`, `tasks/get`, `tasks/cancel`.

## License

Apache-2.0
