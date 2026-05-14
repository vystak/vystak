# MCP Integration Refresh

**Date:** 2026-05-13
**Status:** Approved (brainstorming → planning)

## Motivation

The current MCP integration has skeleton support but several gaps:

1. **No Claude-style ergonomics.** Users have to set an explicit `transport` enum and pre-split `command`/`args`. Copy-pasting from a Claude Desktop `mcpServers` block doesn't work.
2. **Only shipped example is broken.** `examples/mcp-files/vystak.yaml` puts the full shell line in `command` (`command: npx -y @modelcontextprotocol/server-filesystem /docs`). The MCP client would `execvp` that literal string and fail. Nobody has run this end-to-end.
3. **Runtime ↔ schema mismatch.** Schema enum is `streamable_http`; the runtime's adapter wiring matches `"http"`. Streamable HTTP servers silently fall through with no tools attached.
4. **`env`/`headers` are dropped.** The runtime only forwards `command/args` (stdio) or `url` (remote). Authentication-bearing remote servers don't work.
5. **No secret references.** `env`/`headers` are plaintext. Real MCPs (GitHub, Notion, etc.) need credentials; today users would have to bake them into the YAML.
6. **`install` is a Dockerfile RUN escape hatch.** Awkward, repo-specific, unnecessary for the common `npx -y` / `uvx` cases.
7. **MCP wiring is locked inside the LangChain template.** Future Mastra (or any other) framework template would have to duplicate the contract.

## Goals

- Accept Claude-style MCP config: copy-paste-compatible field names (`command`, `args`, `url`, `env`, `headers`), transport inferred from shape.
- Support both local stdio (npx, uvx, docker, arbitrary executable) and remote HTTP/SSE MCPs.
- Allow `${secret.NAME}` references anywhere a string value appears in MCP config (args, env, headers); resolve against the existing `agent.secrets` system at runtime inside the container.
- Move MCP normalization out of the LangChain template into framework-agnostic core so future templates reuse it.
- Maintain support for both YAML and Python (code-first) agent definitions.

## Non-goals

- Live MCP server integration tests in CI.
- A `vystak mcp add/list/remove` CLI (out of scope by user choice; YAML and Python definitions are the source of truth).
- Project-level / user-level scoped MCP config (à la `.mcp.json` precedence) — agent-scoped only.
- A shared `mcp_presets` pool for cross-agent reuse.
- Replacing `langchain-mcp-adapters` with the raw `mcp` SDK.
- Mastra adapter — currently a stub; this spec preserves the boundary it would consume but does not implement it.
- Backward compatibility with the old schema. `transport` becomes optional, `install` is removed, `command` becomes executable-only. The single shipped example is updated; out-of-tree configs (none known) would hit clean validation errors.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  vystak.schema.mcp.McpServer          (Pydantic contract)        │
│    - shape validation (command XOR url, etc.)                    │
│    - transport inference                                         │
│  vystak.schema.agent.Agent                                       │
│    - cross-validates ${secret.NAME} refs against agent.secrets   │
└────────────────────────┬────────────────────────────────────────┘
                         │ list[McpServer]
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  vystak.mcp.config.normalize()        (framework-agnostic)       │
│    - list[McpServer] → list[McpConnectionSpec]                   │
│    - resolves transport, structures stdio vs remote, optionally  │
│      interpolates secrets                                        │
│  vystak.secrets.interpolate.interpolate()                        │
│    - substitutes ${secret.X} in str/dict/list given a lookup     │
└────────────────────────┬────────────────────────────────────────┘
                         │ list[McpConnectionSpec]
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Per-framework wrapper (one per template)                        │
│  LangChain (Python):                                             │
│    _vystak/runtime/mcp.py → MultiServerMCPClient(...).get_tools()│
│  Mastra (TS, future):                                            │
│    adapter emits Mastra TS config from the same specs at codegen │
└─────────────────────────────────────────────────────────────────┘
```

**Boundaries:**
- `vystak.schema.mcp` — user-facing shape.
- `vystak.mcp.config` — normalization. No framework deps.
- `vystak.secrets.interpolate` — reusable; not MCP-specific.
- Each framework template owns its own wrapper.

Provider codegen (Docker / Azure) keeps the same role: detect commands in `mcp_servers` that need extra toolchain (`npx` → node, `uvx` → uv) and layer them into the base image.

## Components

### `vystak.schema.mcp` (revised)

```python
from typing import Self
from pydantic import model_validator
from vystak.schema.common import McpTransport, NamedModel


class McpServer(NamedModel):
    # Local stdio process
    command: str | None = None          # executable only, e.g. "npx", "uvx", "docker"
    args: list[str] = []
    env: dict[str, str] = {}

    # Remote HTTP/SSE
    url: str | None = None
    headers: dict[str, str] = {}

    # Optional override; otherwise inferred:
    #   command set → stdio
    #   url set     → streamable_http
    transport: McpTransport | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        if self.command and self.url:
            raise ValueError(...)       # see Error handling
        if not self.command and not self.url:
            raise ValueError(...)
        if self.command and " " in self.command:
            raise ValueError(...)
        if self.headers and not self.url:
            raise ValueError(...)
        if self.env and not self.command:
            raise ValueError(...)
        if self.transport is not None:
            inferred = McpTransport.STDIO if self.command else McpTransport.STREAMABLE_HTTP
            if self.transport == McpTransport.STDIO and not self.command:
                raise ValueError(...)
            if self.transport in (McpTransport.SSE, McpTransport.STREAMABLE_HTTP) and not self.url:
                raise ValueError(...)
        return self
```

- `install` removed.
- `transport` becomes optional.
- `command` must not contain whitespace (catches the current broken example).
- `env`/`headers` typed as `dict[str, str]` (not loose `dict`).

### `vystak.schema.agent.Agent` (extended)

Add one model_validator:

```python
@model_validator(mode="after")
def _validate_mcp_secret_refs(self) -> Self:
    """Every ${secret.X} in mcp_servers must be declared in agent.secrets."""
    declared = {s.name for s in self.secrets}
    for mcp in self.mcp_servers:
        for path, value in _walk_strings(mcp):
            for name in _SECRET_RE.findall(value):
                if name not in declared:
                    raise ValueError(
                        f"mcp_servers[{mcp.name}].{path} references undeclared "
                        f"secret '{name}'; add to agent.secrets"
                    )
    return self
```

(`_walk_strings` and `_SECRET_RE` may be imported from `vystak.secrets.interpolate` to share the regex.)

### `vystak.mcp.config` (new module)

```python
from dataclasses import dataclass, field
from typing import Callable
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer
from vystak.secrets.interpolate import interpolate


@dataclass(frozen=True)
class McpConnectionSpec:
    name: str
    transport: McpTransport             # always concrete
    # stdio
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    # remote
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def normalize(
    servers: list[McpServer],
    secret_lookup: Callable[[str], str] | None = None,
) -> list[McpConnectionSpec]:
    """Infer transport, build connection specs, optionally interpolate secrets.

    secret_lookup=None preserves ${secret.X} literals (useful for codegen-time
    consumers that emit framework code with their own secret machinery).
    """
```

- Pure function. No I/O.
- Transport inferred when not explicit; explicit value honored.
- When `secret_lookup` is provided, all string refs in `args`/`env`/`headers` are substituted via `interpolate`.

### `vystak.secrets.interpolate` (new module within existing `vystak.secrets` package)

The `vystak.secrets` package already exists with a `get(name) -> str` runtime helper backed by `os.environ` (raises `SecretNotAvailableError`, a `KeyError` subclass). Add `interpolate.py` alongside it.

```python
import re
from typing import Callable, TypeVar

SECRET_RE = re.compile(r"\$\{secret\.([A-Z][A-Z0-9_]*)\}")

T = TypeVar("T")

def interpolate(value: T, lookup: Callable[[str], str] = None) -> T:
    """Walk str/dict/list/tuple, substitute ${secret.NAME} via lookup.
    If lookup is None, defaults to vystak.secrets.get.
    Raises SecretNotAvailableError (KeyError) if a referenced name has no value."""
```

- Generic over str / dict / list / tuple. Returns same type.
- Lookup contract: `name -> value`, raises `KeyError` on miss (existing `SecretNotAvailableError` from `vystak.secrets.get` already satisfies this).
- Non-matching strings pass through.
- Lowercase / malformed refs are left as literals (documented; matches existing `Secret` naming convention `[A-Z][A-Z0-9_]*`).

### LangChain template wrapper

`packages/python/vystak-template-langchain-python/_vystak/runtime/mcp.py` becomes:

```python
import sys
from typing import Any
from vystak.mcp.config import normalize, McpConnectionSpec
from vystak.schema.common import McpTransport
from vystak.secrets import get as lookup_secret

async def attach_mcp_servers(agent: Any) -> list[Any]:
    servers = getattr(agent, "mcp_servers", []) or []
    if not servers:
        return []

    client_cls = _resolve_client_cls()
    if client_cls is None:
        return []

    specs = normalize(servers, secret_lookup=lookup_secret)
    config = {s.name: _to_langchain_config(s) for s in specs}
    return await client_cls(config).get_tools()


def _to_langchain_config(s: McpConnectionSpec) -> dict:
    if s.transport == McpTransport.STDIO:
        return {
            "transport": "stdio",
            "command": s.command,
            "args": list(s.args),
            "env": dict(s.env),
        }
    return {
        "transport": s.transport.value,    # "sse" or "streamable_http"
        "url": s.url,
        "headers": dict(s.headers),
    }


def _resolve_client_cls() -> Any | None:
    """Allow test patching via this module; fall back to importing the real one."""
    module = sys.modules[__name__]
    cls = getattr(module, "MultiServerMCPClient", None)
    if cls is not None:
        return cls
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        return None
    return MultiServerMCPClient
```

Fixes the current `streamable_http` ↔ `"http"` mismatch, forwards `env`/`headers` properly, and resolves secrets before handing to the adapter.

### Provider codegen changes

**`packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`** (around lines 147–167):

- Delete the `install_cmds` / `mcp_installs` machinery and the `f"{mcp_installs}"` line in the Dockerfile composition.
- Extend the toolchain sniff to cover both `npx` and `uvx`:
  ```python
  needs_node = False
  needs_uv = False
  for mcp in self._agent.mcp_servers:
      if mcp.command == "npx":
          needs_node = True
      elif mcp.command == "uvx":
          needs_uv = True
  ```
  (Sniff `mcp.command` only — it's the executable now, not the whole line.)
- Generate the corresponding RUN line(s):
  - `needs_node` → `RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*\n` (existing).
  - `needs_uv` → `RUN pip install --no-cache-dir uv\n`.

**`packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py`** (around lines 480–504): same changes.

### Hash tree

`vystak.hash.tree.AgentHashTree.mcp_servers` is unchanged. It already hashes `agent.mcp_servers` via `_hash_list`. Because Pydantic doesn't serialize unset fields, removing `install` naturally falls out. `${secret.X}` literals are hashed as literals (token rotation never triggers redeploy).

### Example fix

`examples/mcp-files/vystak.yaml`:

```yaml
mcp_servers:
  - name: filesystem
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /docs]
  # Remote variant (commented documentation):
  # - name: github
  #   url: https://api.githubcopilot.com/mcp
  #   headers:
  #     Authorization: Bearer ${secret.GITHUB_TOKEN}
```

(Add `GITHUB_TOKEN` to `secrets:` if uncommenting.)

## Data flow

### `vystak plan` / `apply`

1. CLI loader → `Agent` Pydantic instance.
2. `McpServer._validate_shape()` enforces command-XOR-url and friends.
3. `Agent._validate_mcp_secret_refs()` asserts every `${secret.X}` is declared in `agent.secrets`.
4. `AgentHashTree` hashes `mcp_servers` (literal refs included; secrets-as-names, not secrets-as-values).
5. Provider node materializes the Dockerfile. Sniffs `mcp.command` for `npx` / `uvx` to layer the toolchain.
6. Container starts. Secrets are populated in container env (existing mechanism: env passthrough, vault-shim, or workspace identity).

### Agent process startup (inside the container)

1. Template entrypoint calls `attach_mcp_servers(agent)`.
2. Wrapper calls `vystak.mcp.config.normalize(agent.mcp_servers, secret_lookup=_lookup_secret)`.
3. `normalize` infers transport, builds `McpConnectionSpec`s, runs `interpolate` over each spec's `args`/`env`/`headers` using `_lookup_secret`.
4. `lookup_secret(name)` (the existing `vystak.secrets.get`) reads from `os.environ`; raises `SecretNotAvailableError` if missing → propagates as a clean startup error.
5. Wrapper translates each spec into the dict shape `langchain-mcp-adapters` wants.
6. `MultiServerMCPClient(config).get_tools()` spawns/connects and returns tools.

### Mastra adapter at codegen time (future, not implemented here)

1. Calls `normalize(servers, secret_lookup=None)` — keeps `${secret.X}` literal.
2. Emits TypeScript that constructs Mastra's MCP config, with refs translated to `process.env.X` (or Mastra's secret API).

**Key invariant:** secret values never enter the hash, image layers, or `vystak plan` output. Resolution happens inside the running container only.

## Error handling

| Error | Where caught | Message |
|---|---|---|
| Both `command` and `url` set | `McpServer._validate_shape` | `mcp_servers[<name>]: set exactly one of 'command' or 'url'` |
| Neither set | same | `mcp_servers[<name>]: must set 'command' (stdio) or 'url' (remote)` |
| `command` contains whitespace | same | `mcp_servers[<name>].command must be just the executable (got '<value>'); pass arguments via 'args'` |
| `headers` set without `url` | same | `mcp_servers[<name>]: 'headers' only valid with 'url'` |
| `env` set without `command` | same | `mcp_servers[<name>]: 'env' only valid with 'command'` |
| Explicit `transport: stdio` with no `command` | same | `mcp_servers[<name>]: transport 'stdio' requires 'command'` |
| Explicit `transport: sse` / `streamable_http` with no `url` | same | `mcp_servers[<name>]: transport '<t>' requires 'url'` |
| `${secret.X}` not in `agent.secrets` | `Agent._validate_mcp_secret_refs` | `mcp_servers[<name>].<path> references undeclared secret '<X>'; add to agent.secrets` |
| Malformed secret ref (e.g. `${secret.lowercase}`) | `interpolate` regex doesn't match | silent passthrough (documented; matches existing `Secret` naming convention) |
| Secret declared but missing at container runtime | `vystak.secrets.get` (`SecretNotAvailableError`) | `Secret '<X>' is not available in this container. Declare it on the Agent / Workspace / Channel that uses it.` |
| MCP server spawn failure (npx fetch, URL unreachable) | `langchain-mcp-adapters` | propagated; tools list partial or empty; existing behavior |
| `langchain-mcp-adapters` not installed | `_resolve_client_cls` | returns `[]`; agent runs without MCP tools (existing behavior) |

Two validation layers: per-server shape (in `McpServer`), and cross-field references (in `Agent`). Mirrors how `Agent` already validates subagents and model uniqueness.

## Testing

### `packages/python/vystak/tests/test_mcp.py` (extend existing)

- Shape: command-XOR-url, both-set rejects, neither-set rejects, whitespace-in-command rejects, headers-without-url rejects, env-without-command rejects.
- Transport inference: `command` only → STDIO; `url` only → STREAMABLE_HTTP; explicit `transport: sse` with `url` honored; explicit `transport: sse` with `command` rejects.
- Default `args=[]`, `env={}`, `headers={}`.
- Serialization roundtrip (existing) passes.

### `packages/python/vystak/tests/test_secrets_interpolate.py` (new)

- String interpolation: `"Bearer ${secret.X}"` → `"Bearer abc"`.
- Multiple refs in one string.
- Dict and list recursion (and nested).
- Non-matching string returned unchanged.
- Missing secret raises `KeyError`.
- Lowercase / malformed refs left literal.
- Identity for unrelated types (int, None).

### `packages/python/vystak/tests/test_mcp_config.py` (new)

- `normalize` returns one `McpConnectionSpec` per server.
- Transport inferred correctly per shape.
- With `secret_lookup=None`, `${secret.X}` literals preserved in args/env/headers.
- With a lookup, refs are substituted.
- Stdio spec has empty `headers={}`, `url=None`; HTTP spec has empty `env={}`, `command=None`.

### `packages/python/vystak/tests/test_agent.py` (extend)

- Agent with `${secret.GITHUB_TOKEN}` in mcp_servers but no matching `agent.secrets` → `ValidationError` with the expected message.
- Same ref *with* the secret declared → validates clean.

### `packages/python/vystak-template-langchain-python/tests/test_mcp.py` (rewrite)

- `attach_mcp_servers` with empty list → `[]`.
- Stdio server: fake `MultiServerMCPClient` captures config; assert `command`, `args`, `env` forwarded.
- Remote with `transport: streamable_http`: captured config has `transport: "streamable_http"`, `url`, `headers`.
- Remote with `transport: sse`: captured config has `transport: "sse"`.
- Secret interpolation: server with `${secret.X}` and a fake `_lookup_secret` returning `"abc"` — captured config has resolved value.

### Provider codegen

Add one targeted unit test per provider:

- `packages/python/vystak-provider-docker/tests/test_<existing>.py`: assert Dockerfile contains `nodejs` when an npx command is present and `uv` when a uvx command is present; assert no `RUN <install>` lines from a now-removed `install` field.
- `packages/python/vystak-provider-azure/tests/test_nodes.py`: same.

### Out of scope (explicit)

- Live MCP server spawn in CI.
- Mastra/TS adapter.
- CLI subcommands.
- `mcp_presets` / shared-pool scopes.
- Replacing `langchain-mcp-adapters` with the raw `mcp` SDK.

## Risks

- **`langchain-mcp-adapters` transport names drifting.** Today its remote transports are spelled `"sse"` and `"streamable_http"`. If a version bump renames them, the LangChain wrapper breaks. Mitigation: pin or add a thin compat shim in `_to_langchain_config`. Risk is low — the wrapper is small and isolated.
- **Secret resolution races.** If the container starts before all secrets are populated (e.g., vault-shim path), `_lookup_secret` raises and the agent fails to start. This is the same constraint that already governs `agent.secrets` consumption elsewhere; not new.
- **`${secret.X}` collision with other tooling.** Some MCP servers may take `${...}` placeholders themselves. The regex requires `secret.` namespace, which reduces collision but doesn't eliminate. If a real conflict surfaces, escape via doubled `$$` (future, only if needed — not in this spec).

## File-level summary

**New:**
- `packages/python/vystak/src/vystak/mcp/__init__.py`
- `packages/python/vystak/src/vystak/mcp/config.py`
- `packages/python/vystak/src/vystak/secrets/interpolate.py` (extends existing `vystak.secrets` package)
- `packages/python/vystak/tests/test_mcp_config.py`
- `packages/python/vystak/tests/test_secrets_interpolate.py`

**Modified:**
- `packages/python/vystak/src/vystak/schema/mcp.py` — schema revision (drop `install`, optional `transport`, validation).
- `packages/python/vystak/src/vystak/schema/agent.py` — add `_validate_mcp_secret_refs`.
- `packages/python/vystak/tests/test_mcp.py` — extend with shape + inference cases.
- `packages/python/vystak/tests/test_agent.py` — extend with secret-ref cases.
- `packages/python/vystak-template-langchain-python/_vystak/runtime/mcp.py` — rewrite using `vystak.mcp.config`.
- `packages/python/vystak-template-langchain-python/tests/test_mcp.py` — rewrite.
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` — drop `install`, extend toolchain sniff.
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py` — same.
- `packages/python/vystak-provider-docker/tests/...` — one assertion.
- `packages/python/vystak-provider-azure/tests/test_nodes.py` — one assertion.
- `examples/mcp-files/vystak.yaml` — fix command/args split; document remote variant.
