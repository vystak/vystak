# Subagents — Design

**Status:** approved for implementation
**Date:** 2026-04-25
**Owner:** anatoliy@ankosoftware.com

## Summary

Add a `subagents: list[Agent]` field to the `Agent` schema that

1. Auto-generates one `ask_<peer_name>(question)` LangChain `@tool` per declared peer, replacing today's hand-written `tools/ask_<peer>.py` boilerplate.
2. Acts as the authorisation surface for east-west calls — `VYSTAK_ROUTES_JSON` for an agent contains only its declared subagents.
3. Propagates the caller's `session_id` to every hop so each agent maintains a private, correlated conversation slice.

The 2026-04-13 multi-agent design listed "automatic A2A tool generation from peer discovery" as out of scope. This spec lifts that item.

## Goals

- One-line declaration replaces the 5–10 lines of `ask_agent()` tool boilerplate currently duplicated across `examples/multi-agent/`, `examples/docker-multi-chat-nats/`, and any production multi-agent setup.
- Restrictive route-table scoping gives every agent a real authorisation surface, mirroring `Channel.agents`.
- Session ids correlate hops without exposing the caller's chat history to the callee.

## Non-goals

- Per-relationship metadata (custom description, method allowlist, retry policy). Users wanting that customisation drop down to a manual `ask_agent()` tool.
- Hierarchy / shared lifecycle. Subagents stay top-level deployables; `subagents:` only governs who-can-call-whom.
- Typed / structured return values. Subagent calls remain `str -> str`, identical to today's `ask_agent()`.
- Subagent of a subagent as a separate concept. Transitive calls work because every hop's auto-generated tool propagates `session_id` via `metadata`; A → B → C is just B declaring C in its own `subagents:` list.

## Schema change

Add one field to `vystak.schema.agent.Agent`:

```python
class Agent(NamedModel):
    ...
    subagents: list["Agent"] = []
```

Self-referential. Pydantic handles forward refs the same way `Channel.agents` does today (model rebuild after class definition).

YAML form takes string names, resolved by the multi-document loader against the top-level `agents:` map:

```yaml
agents:
  - name: weather-agent
    instructions: Weather specialist.
    model: sonnet
    platform: local
    skills:
      - {name: weather, tools: [get_weather]}

  - name: assistant-agent
    instructions: Coordinate weather and time questions.
    model: sonnet
    platform: local
    subagents: [weather-agent, time-agent]
```

Python form passes `Agent` instances directly:

```python
assistant = vystak.Agent(
    name="assistant-agent",
    instructions="Coordinate weather and time questions.",
    subagents=[weather, time],
    ...
)
```

### Loader changes

`vystak.schema.multi_loader.load_multi_yaml` already does string→object resolution for channel agent refs (`_resolve_channel_agent_refs`). Add a parallel `_resolve_agent_subagent_refs` pass that runs after `agents_by_name` is built. Same error shape on unknown name:

```
Unknown agent 'foo' in agent 'assistant-agent' field 'subagents'.
Defined agents: assistant-agent, time-agent, weather-agent
```

Single-agent loader (`vystak.schema.loader.load_agent`) does not support subagents — they are inherently a multi-agent concept. Declaring `subagents:` in a single-document YAML errors with a pointer to the multi-document layout.

### Validation

- Every entry in `subagents` must resolve to an existing agent.
- Self-reference (`agent.subagents` containing the agent itself) is rejected at load time. Cycles between distinct agents (A → B → A) are allowed — the A2A envelope already correlates request/reply over arbitrary topologies.
- Two subagents with the same name are rejected (would collide on tool name).

## Codegen

For each entry in `agent.subagents`, `vystak-adapter-langchain/templates.py` emits one `@tool` into the generated server file. Tool name = `ask_<peer.name with - replaced by _>`. Body uses the existing `vystak.transport.ask_agent` helper.

Generated source (illustrative):

```python
@tool
async def ask_weather_agent(question: str, config: RunnableConfig) -> str:
    """Weather specialist. Use get_weather for real data. Answer concisely."""
    session_id = (config.get("configurable") or {}).get("thread_id")
    metadata = {"sessionId": session_id} if session_id else {}
    return await ask_agent("weather-agent", question, metadata=metadata)
```

LangChain's tool runtime injects `RunnableConfig` automatically when the parameter is type-annotated; no manual wiring needed in the adapter.

### Docstring

Pulled from the peer's `Agent.instructions` field. Truncation rules:

1. Take the first paragraph (split on first blank line).
2. Truncate to 200 chars; if truncation happens, append `…`.
3. If `instructions` is empty/None, fall back to a generic `f"Delegate to the {peer.name} agent."`.

The docstring is what the calling LLM sees as the tool's description and is therefore load-bearing for routing decisions. Users who need per-caller customisation use a manual `ask_agent()` tool instead.

### Tool name collisions

Auto-generated `ask_<peer>` tools and user-defined tools coexist under the same Python module. If a user-defined tool already shadows an auto-generated name (e.g., they have a `tools/ask_weather_agent.py` AND declare `subagents: [weather-agent]`), the loader rejects the configuration with:

```
Tool name conflict: 'ask_weather_agent' is auto-generated for subagent
'weather-agent' but also defined in tools/ask_weather_agent.py.
Remove one or rename the user-defined tool.
```

This forces explicit migration rather than silently overriding.

## Routing (restrictive)

`vystak.transport.routes.build_peer_routes(subject, peers)` is already per-subject — it returns a route table keyed by short peer names for one caller. The CLI currently passes "all agents in the project" as `peers`. Change: pass `subject.subagents` instead.

Result: an agent's `VYSTAK_ROUTES_JSON` contains exactly the peers it declared. A call to `ask_agent("undeclared", ...)` (whether auto-generated or hand-written) hits the existing "unknown peer" error from the transport client.

Channels are unaffected — they continue to inject the full `Channel.agents` list into their own route table.

### Migration impact on manual tools

Existing manual `ask_agent("foo", ...)` calls only work if `foo` is also declared in `subagents`. There is no fallback flag to restore the old "all peers reachable everywhere" behavior. The migration path for existing examples (see below) is mechanical.

## Session propagation

The A2A envelope already carries `metadata.sessionId`. Today nobody populates it from the calling agent's runtime context.

Generated tool reads the active LangGraph `thread_id` from `RunnableConfig` and passes it to the peer. Receiving agent's `A2AHandler` uses `metadata.sessionId` as the LangGraph thread id for its own checkpointer.

Properties:

- Same id correlates conversations across agents (e.g., assistant calls weather-agent twice in the same Slack thread → weather-agent sees both calls under one thread).
- Each agent's session store is private. Caller never sees subagent's chain-of-thought; subagent never sees caller's chat with the human.
- Sub-subagent calls (B calls C from inside its tool execution) inherit the id transitively — `_current_session_id()` returns the value B is currently running under.
- Caller without an active session id → metadata is empty → subagent creates an ephemeral thread for that call.

No new state machinery. Single-line additions in two places:

- `vystak.transport.client.AgentClient.ask` already accepts a `metadata` kwarg.
- `vystak-adapter-langchain/a2a.py` `A2AHandler` already plumbs `metadata.sessionId` to LangGraph's `configurable.thread_id`.

This design just connects the two ends.

## Hashing

`vystak.hash.tree.AgentHashTree` contributes a sorted list of subagent canonical names:

```python
sorted(peer.canonical_name for peer in agent.subagents)
```

Sorted because list order is not semantically meaningful — declaring `[weather, time]` and `[time, weather]` should produce the same hash.

Adding or removing a subagent rebuilds the caller only. The peer's hash is unchanged because no field on the peer changes.

## CLI

No new commands. `vystak status` does not surface subagents in its default output (subagent topology is encoded in route tables and visible there if needed); the existing `vystak plan` diff naturally surfaces the schema change as part of the agent's body.

## Migration of existing artefacts

Three deliverables ship with the implementation:

1. **`examples/multi-agent/`** — delete `assistant/tools/ask_weather_agent.py` and `assistant/tools/ask_time_agent.py`; add `subagents: [weather-agent, time-agent]` to assistant-agent's `vystak.yaml`.
2. **`examples/docker-multi-chat-nats/`** — same refactor: drop the assistant's manual `ask_*_agent` tool files, declare `subagents:` in the agent's Python definition.
3. **`website/docs/concepts/multi-agent.md`** — rewrite the "Specialist + coordinator" section to lead with `subagents:`. Move the manual `ask_agent()` pattern to a clearly labelled "Escape hatch: hand-written delegation tools" section explaining when to use it (per-caller docstring customisation, routing logic, parameter shaping).

Production users running on `main` adopt the new shape on next deploy: declare `subagents:` and remove their `tools/ask_*_agent.py` files. Until they do, their manual tools keep working as long as the peer name is also in their `subagents` list — the new validator forces them to declare what they call.

## Test plan

Per-package coverage that mirrors how the feature is used:

- **`vystak`**:
  - `tests/schema/test_agent.py` — `Agent.subagents` field accepts list, defaults `[]`, rejects non-list.
  - `tests/schema/test_multi_loader.py` — string refs resolve to objects; unknown peer name raises with helpful message; self-reference rejected.
  - `tests/hash/test_tree.py` — adding a subagent changes caller hash; reordering doesn't change caller hash; peer's hash unchanged.

- **`vystak-adapter-langchain`**:
  - `tests/test_templates.py` — generated code contains one `ask_<peer>` tool per subagent; tool body has `metadata.sessionId` propagation; docstring drawn from peer's `instructions` and truncated; collision with user-defined tool errors.

- **`vystak-cli` (or wherever the routes are built)**:
  - Restrictive route table contains only declared subagents for each caller.

- **Release tier (Docker)**:
  - One new release cell `D9_docker_subagents_chat_http`: deploy three agents (assistant, weather, time) where assistant declares both peers; verify `vystak/assistant-agent` answers both "what's the weather in Tokyo" and "what time is it" in a single chat session, and that session id propagates (assistant queried twice keeps continuity for the peer).

## Open questions

None — the two confirmations from brainstorming (instructions-as-docstring, restrictive routing applied retroactively to manual `ask_agent()` calls) are locked in.

## Rollout

One PR — schema + loader + codegen + hash + route-table + tests + example migrations + doc rewrite. The feature is small enough that splitting it across PRs would create more thrash than value (the example migrations and doc rewrite directly demonstrate the schema and codegen changes).

No flag, no opt-in: the feature is additive (new field, default empty list) and the route-table change is a behavior change that needs migration, but the migration is one line per existing multi-agent example and is shipped in the same PR.

## See also

- `docs/superpowers/specs/2026-04-13-multi-agent-deploy-design.md` — original multi-agent design that listed peer-driven tool generation as out of scope.
- `docs/superpowers/specs/2026-04-19-transport-abstraction-design.md` — `ask_agent()` and `build_peer_routes()` plumbing this feature builds on.
- `examples/multi-agent/` — existing manual delegation pattern.
- `website/docs/concepts/multi-agent.md` — user-facing narrative that lands with this change.
