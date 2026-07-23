# mcp-files — MCP tools from a stdio server

An agent that reads files through the Model Context Protocol: the official
`@modelcontextprotocol/server-filesystem` server runs as a local stdio
process inside the agent container (spawned via `npx`), and its tools are
attached to the LangGraph agent at startup.

What it demonstrates:

- **Claude-style MCP config** — `command` is the bare executable, arguments
  in `args`; no `transport` needed (inferred: `command` → stdio, `url` →
  streamable HTTP).
- **Remote servers with secrets** — see the commented `github` block in
  `vystak.yaml`: `${secret.NAME}` refs in `headers`/`env`/`args` resolve
  inside the container from declared `agent.secrets`.
- **Toolchain in the image** — stdio servers need their runtime in the
  container; this example's `Dockerfile` installs node for `npx`.

## Run it

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY
vystak apply
vystak-chat            # ask: "what files are in /docs?"
```

`sample-docs/` is copied to `/docs` in the image — the directory the
filesystem MCP server exposes.
