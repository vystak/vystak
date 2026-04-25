# Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Agent.subagents: list[Agent]` field that auto-generates `ask_<peer>` LangChain `@tool` wrappers, restricts each caller's `VYSTAK_ROUTES_JSON` to declared peers, and propagates `session_id` across hops.

**Architecture:** Pydantic forward-ref field on `Agent` (mirrors `Channel.agents`), a parallel string-resolution pass in `multi_loader.py`, a hash contribution, codegen of one `@tool` per declared peer using the existing `vystak.transport.ask_agent` helper with `metadata={"sessionId": ...}`, and a one-line change at the CLI's route-building call site so each agent's route table contains only its declared subagents.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, LangGraph/LangChain, ruff, pyright. `uv` workspace.

**Spec:** `docs/superpowers/specs/2026-04-25-subagents-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `packages/python/vystak/src/vystak/schema/agent.py` | Modify | Add `subagents: list["Agent"]` field + self-ref forward-rebuild + validators |
| `packages/python/vystak/src/vystak/schema/multi_loader.py` | Modify | New `_resolve_agent_subagent_refs` helper; second pass over agents |
| `packages/python/vystak/src/vystak/schema/loader.py` | Modify | Reject `subagents` key in single-document YAML with helpful error |
| `packages/python/vystak/src/vystak/hash/tree.py` | Modify | New `subagents` field on `AgentHashTree`; contribute to `root` |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` | Modify | New `_generate_subagent_tools` helper; splice into `generate_agent_py`; collision check |
| `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` | Modify | Change `build_routes_json(list(agents), ...)` → `build_routes_json(agent.subagents, ...)` (line 206) |
| `packages/python/vystak/tests/test_agent.py` | Modify | Field shape, default, validators |
| `packages/python/vystak/tests/test_multi_loader_subagents.py` | Create | String resolution + error paths |
| `packages/python/vystak/tests/test_loader_single_doc.py` | Create (or extend existing test) | Single-doc YAML rejects subagents |
| `packages/python/vystak/tests/test_tree.py` | Modify | Hash contribution semantics |
| `packages/python/vystak-adapter-langchain/tests/test_templates.py` | Modify | Generated code shape, docstring, session-id propagation, collision |
| `packages/python/vystak-cli/tests/test_apply_subagents.py` | Create | Restrictive route-table assembly |
| `examples/multi-agent/assistant/vystak.yaml` | Modify | Declare `subagents:`; remove unused tool refs from skills |
| `examples/multi-agent/assistant/tools/ask_weather_agent.py` | Delete | Auto-generated now |
| `examples/multi-agent/assistant/tools/ask_time_agent.py` | Delete | Auto-generated now |
| `examples/docker-multi-chat-nats/vystak.py` | Modify | Add `subagents=[weather_agent, time_agent]`; remove deprecated `routes=...` Channel field; switch Channel to `agents=[...]` |
| `examples/docker-multi-chat-nats/tools/ask_weather_agent.py` | Delete | Auto-generated now |
| `examples/docker-multi-chat-nats/tools/ask_time_agent.py` | Delete | Auto-generated now |
| `website/docs/concepts/multi-agent.md` | Modify | Lead with `subagents:`; manual `ask_agent()` becomes labelled escape hatch |

---

## Part A: Schema

### Task 1: Add `subagents` field to `Agent`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py:18-43`
- Test: `packages/python/vystak/tests/test_agent.py`

- [ ] **Step 1: Read existing Agent schema**

Read `packages/python/vystak/src/vystak/schema/agent.py` end-to-end so you understand the existing fields, validators, and `canonical_name` property.

- [ ] **Step 2: Write the failing tests**

Append to `packages/python/vystak/tests/test_agent.py`:

```python
def test_agent_subagents_defaults_to_empty_list():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    agent = Agent(
        name="solo",
        model=Model(
            name="m",
            provider=Provider(name="p", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
    )
    assert agent.subagents == []


def test_agent_subagents_accepts_agent_list():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    assistant = Agent(name="assistant-agent", model=m, subagents=[weather])
    assert len(assistant.subagents) == 1
    assert assistant.subagents[0].name == "weather-agent"
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
uv run pytest packages/python/vystak/tests/test_agent.py::test_agent_subagents_defaults_to_empty_list packages/python/vystak/tests/test_agent.py::test_agent_subagents_accepts_agent_list -v
```

Expected: both FAIL with `pydantic_core._pydantic_core.ValidationError: ... unexpected keyword 'subagents'` or similar.

- [ ] **Step 4: Add the field to `Agent`**

Edit `packages/python/vystak/src/vystak/schema/agent.py`. Inside the `Agent` class, add the field on the line right after `workspace: Workspace | None = None` (currently line 29):

```python
    subagents: list["Agent"] = []
```

After the class definition (i.e. after the `_assign_service_names` validator method ends — currently line 56), add a model rebuild call so the forward ref resolves:

```python
Agent.model_rebuild()
```

So the bottom of the file should look like:

```python
    @model_validator(mode="after")
    def _assign_service_names(self) -> Self:
        if self.sessions and not self.sessions.name:
            self.sessions.name = "sessions"
        if self.memory and not self.memory.name:
            self.memory.name = "memory"
        return self


Agent.model_rebuild()
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
uv run pytest packages/python/vystak/tests/test_agent.py::test_agent_subagents_defaults_to_empty_list packages/python/vystak/tests/test_agent.py::test_agent_subagents_accepts_agent_list -v
```

Expected: both PASS.

- [ ] **Step 6: Run the broader agent test suite to confirm no regression**

```bash
uv run pytest packages/python/vystak/tests/test_agent.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/agent.py packages/python/vystak/tests/test_agent.py
git commit -m "$(cat <<'EOF'
feat(schema): add Agent.subagents field

Forward-ref list[Agent] field that lets an agent declare which peers
it can call. Defaults to []. Foundation for auto-generated ask_<peer>
tools and restrictive route tables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Schema validators — reject self-reference and duplicate names

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/agent.py`
- Test: `packages/python/vystak/tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak/tests/test_agent.py`:

```python
def test_agent_subagent_self_reference_rejected():
    import pytest
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    a = Agent(name="solo", model=m)
    with pytest.raises(ValueError, match="cannot list itself"):
        a.subagents = [a]
        Agent.model_validate(a.model_dump())


def test_agent_subagent_duplicate_names_rejected():
    import pytest
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather1 = Agent(name="weather-agent", model=m)
    weather2 = Agent(name="weather-agent", model=m)
    with pytest.raises(ValueError, match="duplicate"):
        Agent(name="assistant", model=m, subagents=[weather1, weather2])
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run pytest packages/python/vystak/tests/test_agent.py::test_agent_subagent_self_reference_rejected packages/python/vystak/tests/test_agent.py::test_agent_subagent_duplicate_names_rejected -v
```

Expected: both FAIL — no validation logic exists yet.

- [ ] **Step 3: Add the validator**

Edit `packages/python/vystak/src/vystak/schema/agent.py`. Just after the `_assign_service_names` validator (and BEFORE the `Agent.model_rebuild()` call at file end), add:

```python
    @model_validator(mode="after")
    def _validate_subagents(self) -> Self:
        names = [s.name for s in self.subagents]
        if self.name in names:
            raise ValueError(
                f"Agent '{self.name}' cannot list itself in subagents."
            )
        seen: set[str] = set()
        for n in names:
            if n in seen:
                raise ValueError(
                    f"Agent '{self.name}' has duplicate subagent name '{n}'."
                )
            seen.add(n)
        return self
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
uv run pytest packages/python/vystak/tests/test_agent.py -v
```

Expected: all tests pass, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/agent.py packages/python/vystak/tests/test_agent.py
git commit -m "$(cat <<'EOF'
feat(schema): reject self-reference and duplicate names in Agent.subagents

Self-reference would cause infinite recursion at runtime; duplicate
names would collide on auto-generated tool names.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Multi-loader resolves subagent string references

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py:122-148`
- Test: `packages/python/vystak/tests/test_multi_loader_subagents.py` (create)

- [ ] **Step 1: Read existing multi_loader**

Read `packages/python/vystak/src/vystak/schema/multi_loader.py` end-to-end. Understand `_resolve_channel_agent_refs` (lines 37-67) — your new helper mirrors it.

- [ ] **Step 2: Write the failing tests**

Create `packages/python/vystak/tests/test_multi_loader_subagents.py`:

```python
"""Tests for subagent string-ref resolution in load_multi_yaml."""
import copy
import pytest
from vystak.schema.multi_loader import load_multi_yaml

BASE = {
    "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
    "platforms": {"local": {"type": "docker", "provider": "docker"}},
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"},
    },
    "agents": [
        {"name": "weather-agent", "model": "sonnet", "platform": "local"},
        {"name": "time-agent", "model": "sonnet", "platform": "local"},
        {
            "name": "assistant-agent",
            "model": "sonnet",
            "platform": "local",
            "subagents": ["weather-agent", "time-agent"],
        },
    ],
}


def test_subagent_string_refs_resolve_to_agent_objects():
    data = copy.deepcopy(BASE)
    agents, _channels, _vault = load_multi_yaml(data)
    assistant = next(a for a in agents if a.name == "assistant-agent")
    assert [s.name for s in assistant.subagents] == ["weather-agent", "time-agent"]
    weather_top = next(a for a in agents if a.name == "weather-agent")
    assert assistant.subagents[0] is weather_top  # identity, not just equality


def test_unknown_subagent_raises_with_helpful_message():
    data = copy.deepcopy(BASE)
    data["agents"][2]["subagents"] = ["weather-agent", "ghost-agent"]
    with pytest.raises(KeyError, match="ghost-agent"):
        load_multi_yaml(data)


def test_agent_without_subagents_field_loads_normally():
    data = copy.deepcopy(BASE)
    data["agents"][2].pop("subagents")
    agents, _channels, _vault = load_multi_yaml(data)
    assistant = next(a for a in agents if a.name == "assistant-agent")
    assert assistant.subagents == []
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
uv run pytest packages/python/vystak/tests/test_multi_loader_subagents.py -v
```

Expected: the first two FAIL — strings are not resolved (Pydantic raises on `subagents=["weather-agent"]` because the field expects `Agent` objects). The third may PASS.

- [ ] **Step 4: Add the resolver helper**

Edit `packages/python/vystak/src/vystak/schema/multi_loader.py`. After `_resolve_channel_agent_refs` (line 67), add a new helper:

```python
def _resolve_agent_subagent_refs(
    agent_data: dict,
    agents_by_name: dict,
) -> dict:
    """Resolve string subagent references on an agent block to Agent objects."""
    if "subagents" not in agent_data:
        return agent_data
    data = dict(agent_data)
    resolved = []
    for ref in data["subagents"]:
        if isinstance(ref, str):
            if ref not in agents_by_name:
                raise KeyError(
                    f"Unknown subagent '{ref}' in agent "
                    f"'{agent_data.get('name')}' field 'subagents'. "
                    f"Defined agents: {', '.join(sorted(agents_by_name))}"
                )
            resolved.append(agents_by_name[ref])
        else:
            resolved.append(ref)
    data["subagents"] = resolved
    return data
```

- [ ] **Step 5: Wire the helper into the agent load loop**

The current `load_multi_yaml` builds agents in two phases. Subagents reference *other* agents, so we need a two-pass build: first construct each agent without `subagents`, build `agents_by_name`, then re-validate each agent with its `subagents` resolved.

Replace the `agents: list[Agent] = []` block (currently lines 122-147) with:

```python
    # Phase 1: build all agents without their `subagents` field so we have a
    # name → Agent map for cross-resolution.
    agent_data_list: list[dict] = []
    raw_subagents: dict[str, list] = {}
    for agent_data in data.get("agents", []):
        agent_data = dict(agent_data)

        model_ref = agent_data.get("model")
        if isinstance(model_ref, str):
            if model_ref not in models:
                raise KeyError(
                    f"Unknown model '{model_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined models: {', '.join(models.keys())}"
                )
            agent_data["model"] = models[model_ref]

        platform_ref = agent_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in agent "
                    f"'{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        # Stash subagents for phase 2, build agent without them so model_validate works.
        if "subagents" in agent_data:
            raw_subagents[agent_data["name"]] = agent_data.pop("subagents")
        agent_data_list.append(agent_data)

    agents: list[Agent] = [Agent.model_validate(d) for d in agent_data_list]
    agents_by_name = {a.name: a for a in agents}

    # Phase 2: re-attach subagents now that all agents exist.
    for agent in agents:
        if agent.name not in raw_subagents:
            continue
        resolved_payload = _resolve_agent_subagent_refs(
            {"name": agent.name, "subagents": raw_subagents[agent.name]},
            agents_by_name,
        )
        agent.subagents = resolved_payload["subagents"]
        # Re-run after-validators (self-reference + duplicate-name checks)
        Agent.model_validate(agent.model_dump())
```

Note: the final `Agent.model_validate(agent.model_dump())` call exercises the `_validate_subagents` validator from Task 2 against the now-populated list. We don't replace `agent` because Pydantic's `model_validate` would create new instances and break the identity guarantees other code (channels) relies on.

- [ ] **Step 6: Run the tests to confirm they pass**

```bash
uv run pytest packages/python/vystak/tests/test_multi_loader_subagents.py -v
```

Expected: all three PASS.

- [ ] **Step 7: Run the full multi_loader suite to confirm no regressions**

```bash
uv run pytest packages/python/vystak/tests/test_multi_loader.py packages/python/vystak/tests/test_multi_loader_slack.py packages/python/vystak/tests/test_multi_loader_vault.py packages/python/vystak/tests/test_multi_loader_workspace.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py packages/python/vystak/tests/test_multi_loader_subagents.py
git commit -m "$(cat <<'EOF'
feat(schema): resolve subagent string refs in load_multi_yaml

Two-phase agent build: construct agents without subagents, then
re-attach with cross-references resolved against the by-name map.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Single-document loader rejects `subagents`

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/loader.py`
- Test: `packages/python/vystak/tests/test_loader_single_doc.py` (create)

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak/tests/test_loader_single_doc.py`:

```python
"""Tests for single-document agent loader (loader.py)."""
import pytest
import yaml
from vystak.schema.loader import load_agent


def test_single_doc_yaml_rejects_subagents(tmp_path):
    yaml_path = tmp_path / "vystak.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "name": "lonely",
        "model": {
            "name": "m",
            "provider": {"name": "p", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
        "subagents": ["weather-agent"],
    }))
    with pytest.raises(ValueError, match="subagents.*multi-document"):
        load_agent(yaml_path)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest packages/python/vystak/tests/test_loader_single_doc.py -v
```

Expected: FAIL — the loader currently passes the dict to `Agent.model_validate` which raises a Pydantic error about string-not-Agent, not the targeted message.

- [ ] **Step 3: Add the rejection**

Edit `packages/python/vystak/src/vystak/schema/loader.py`. In `load_agent`, after parsing the YAML and BEFORE `Agent.model_validate(data)`, add:

```python
    if isinstance(data, dict) and "subagents" in data:
        raise ValueError(
            "subagents requires the multi-document YAML layout "
            "(top-level providers/platforms/models/agents/channels). "
            "See docs/concepts/multi-agent.md."
        )
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest packages/python/vystak/tests/test_loader_single_doc.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/loader.py packages/python/vystak/tests/test_loader_single_doc.py
git commit -m "$(cat <<'EOF'
feat(schema): single-doc loader rejects subagents with helpful pointer

Subagents are inherently multi-agent; single-doc YAML can't resolve
peer names. Error message points users at the multi-document layout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Part B: Hash

### Task 5: Hash contribution for `subagents`

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py:14-30, 110-162`
- Test: `packages/python/vystak/tests/test_tree.py`

- [ ] **Step 1: Read existing hash tree code**

Read `packages/python/vystak/src/vystak/hash/tree.py` end-to-end so you understand how each section contributes to `root`.

- [ ] **Step 2: Write the failing tests**

Append to `packages/python/vystak/tests/test_tree.py`:

```python
def test_adding_subagent_changes_caller_root_hash():
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    bare = Agent(name="assistant-agent", model=m)
    with_peer = Agent(name="assistant-agent", model=m, subagents=[weather])

    assert hash_agent(bare).root != hash_agent(with_peer).root


def test_reordering_subagents_does_not_change_caller_hash():
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    time = Agent(name="time-agent", model=m)
    a = Agent(name="assistant", model=m, subagents=[weather, time])
    b = Agent(name="assistant", model=m, subagents=[time, weather])

    assert hash_agent(a).root == hash_agent(b).root


def test_peer_hash_unchanged_when_added_as_subagent():
    """Adding a peer to a caller does not affect the peer's own hash."""
    from vystak.hash.tree import hash_agent
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    weather_alone_root = hash_agent(weather).root

    # Build a caller that references it; weather's own hash must not change.
    _assistant = Agent(name="assistant", model=m, subagents=[weather])
    assert hash_agent(weather).root == weather_alone_root
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
uv run pytest packages/python/vystak/tests/test_tree.py::test_adding_subagent_changes_caller_root_hash packages/python/vystak/tests/test_tree.py::test_reordering_subagents_does_not_change_caller_hash packages/python/vystak/tests/test_tree.py::test_peer_hash_unchanged_when_added_as_subagent -v
```

Expected: the first two FAIL (no hash contribution); the third PASS by coincidence (still right behavior to lock in).

- [ ] **Step 4: Add `subagents` to `AgentHashTree`**

Edit `packages/python/vystak/src/vystak/hash/tree.py`. Add `subagents: str` to `AgentHashTree` (after `transport: str`, before `# v1 Secret Manager additions`):

```python
@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    transport: str
    subagents: str
    # v1 Secret Manager additions
    workspace_identity: str
    grants: str
    root: str
```

- [ ] **Step 5: Add a helper `_hash_subagents`**

In the same file, after `_hash_transport` (currently ending at line 107), add:

```python
def _hash_subagents(agent: Agent) -> str:
    """Contribute declared subagent identities to the agent hash.

    Order-insensitive (sorted) — declaring [weather, time] and [time, weather]
    produces the same hash. Uses canonical_name so namespace changes propagate.
    """
    if not agent.subagents:
        return _hash_str(None)
    names = sorted(peer.canonical_name for peer in agent.subagents)
    return hashlib.sha256("|".join(names).encode()).hexdigest()
```

- [ ] **Step 6: Wire `subagents` into `hash_agent`**

Modify `hash_agent` (currently line 110). Add a `subagents` line in the section computations (after `transport = _hash_transport(agent)`):

```python
    subagents = _hash_subagents(agent)
```

In the `sections = "|".join([...])` list, add `subagents` BEFORE `workspace_identity`:

```python
    sections = "|".join(
        [
            brain,
            skills,
            mcp_servers,
            workspace,
            resources,
            secrets,
            sessions,
            memory,
            services,
            transport,
            subagents,
            workspace_identity,
            grants,
        ]
    )
```

In the final `AgentHashTree(...)` constructor at the function bottom, add `subagents=subagents` between `transport=transport` and `workspace_identity=...`.

- [ ] **Step 7: Run the tests to confirm they pass**

```bash
uv run pytest packages/python/vystak/tests/test_tree.py -v
```

Expected: all pass, including the three new ones.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py packages/python/vystak/tests/test_tree.py
git commit -m "$(cat <<'EOF'
feat(hash): contribute subagent canonical names to AgentHashTree

Sorted contribution so list order is not load-bearing. Adding or
removing a subagent rebuilds the caller; peers stay untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Part C: Codegen

### Task 6: Generate `ask_<peer>` tools per declared subagent

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py:63-200`
- Test: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Read existing codegen entry points**

Read `templates.py` lines 63-400 (helpers + `generate_agent_py`). Note where imports are emitted (line 215+), where tool stubs are emitted (line 270+), and where `tools_list` is built into `create_react_agent(...)` (line 391+).

- [ ] **Step 2: Write the failing tests**

Append to `packages/python/vystak-adapter-langchain/tests/test_templates.py`:

```python
def test_subagents_generates_ask_tool_per_peer():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="Weather specialist. Use get_weather for real data.",
        model=m,
    )
    time = Agent(name="time-agent", instructions="Time specialist.", model=m)
    assistant = Agent(
        name="assistant-agent",
        model=m,
        subagents=[weather, time],
    )

    code = generate_agent_py(assistant)
    assert "async def ask_weather_agent(" in code
    assert "async def ask_time_agent(" in code
    # Imports
    assert "from vystak.transport import ask_agent" in code
    assert "from langchain_core.runnables import RunnableConfig" in code
    # Session-id propagation
    assert "thread_id" in code
    assert "metadata={'sessionId': session_id}" in code or 'metadata={"sessionId": session_id}' in code
    # Wired into the react agent
    assert "ask_weather_agent" in code.split("create_react_agent")[-1]


def test_subagents_docstring_pulled_from_instructions():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="Weather specialist. Use get_weather for real data.",
        model=m,
    )
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "Weather specialist." in code


def test_subagents_docstring_first_paragraph_only():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="First paragraph here.\n\nSecond paragraph not in docstring.",
        model=m,
    )
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "First paragraph here." in code
    assert "Second paragraph" not in code


def test_subagents_docstring_fallback_when_instructions_empty():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)  # no instructions
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "Delegate to the weather-agent agent." in code


def test_no_subagents_no_codegen_change():
    """If subagents is empty, no ask_ tool is emitted and no extra imports added."""
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    bare = Agent(name="solo", model=m)
    code = generate_agent_py(bare)
    assert "ask_agent" not in code
    assert "from vystak.transport" not in code
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py -k "subagents or no_subagents" -v
```

Expected: 4 of 5 FAIL (the `test_no_subagents_no_codegen_change` should pass on current code).

- [ ] **Step 4: Add the docstring helper and tool generator**

Edit `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`. After `_generate_tool_stubs` (currently line 75), add two helpers:

```python
def _docstring_from_instructions(peer: Agent) -> str:
    """Derive a tool docstring from the peer agent's instructions field."""
    instructions = peer.instructions or ""
    first_para = instructions.split("\n\n", 1)[0].strip()
    if not first_para:
        return f"Delegate to the {peer.name} agent."
    if len(first_para) > 200:
        return first_para[:200].rstrip() + "…"
    return first_para


def _generate_subagent_tools(agent: Agent) -> str:
    """Emit one async @tool wrapper per declared subagent."""
    if not agent.subagents:
        return ""
    blocks = []
    for peer in agent.subagents:
        tool_name = f"ask_{peer.name.replace('-', '_')}"
        docstring = _docstring_from_instructions(peer).replace('"""', '\\"\\"\\"')
        block = (
            "@tool\n"
            f"async def {tool_name}(question: str, config: RunnableConfig) -> str:\n"
            f'    """{docstring}"""\n'
            f"    session_id = (config.get('configurable') or {{}}).get('thread_id')\n"
            "    metadata = {'sessionId': session_id} if session_id else {}\n"
            f"    return await ask_agent({peer.name!r}, question, metadata=metadata)"
        )
        blocks.append(block)
    return "\n\n\n".join(blocks)


def _subagent_tool_names(agent: Agent) -> list[str]:
    """Tool function names that the subagent codegen emits."""
    return [f"ask_{p.name.replace('-', '_')}" for p in agent.subagents]
```

- [ ] **Step 5: Splice generated tools and imports into `generate_agent_py`**

Still in `templates.py`, edit `generate_agent_py`. Make these changes:

(a) Right after the existing `tool_stubs = _generate_tool_stubs(stub_tool_names)` line (currently ~line 198), add:

```python
    subagent_tool_code = _generate_subagent_tools(agent)
    subagent_tool_names = _subagent_tool_names(agent)
    all_tool_names = found_tool_names + stub_tool_names + subagent_tool_names
```

Replace the existing `all_tool_names = found_tool_names + stub_tool_names` line (currently line 199) with the line above. The existing `tools_list = ", ".join(all_tool_names) if all_tool_names else ""` (line 200) keeps working unchanged.

(b) Where `from langchain_core.tools import tool` is conditionally imported (currently line 219-220):

```python
    if stub_tool_names or session_store:
        lines.append("from langchain_core.tools import tool")
```

Replace with:

```python
    if stub_tool_names or session_store or subagent_tool_code:
        lines.append("from langchain_core.tools import tool")
```

(c) Add new imports immediately after that `tool` import block. After line 233 (`lines.append("from langgraph.prebuilt import create_react_agent")`):

```python
    if subagent_tool_code:
        lines.append("from langchain_core.runnables import RunnableConfig")
        lines.append("from vystak.transport import ask_agent")
```

(d) Emit the generated tool block. After the `if tool_stubs:` block (currently lines 270-273), add:

```python
    if subagent_tool_code:
        lines.append("")
        lines.append("# Auto-generated subagent delegation tools")
        lines.append(subagent_tool_code)
```

- [ ] **Step 6: Run the tests to confirm they pass**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py -k "subagents or no_subagents" -v
```

Expected: all 5 PASS.

- [ ] **Step 7: Run the broader templates suite to confirm no regressions**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
feat(adapter-langchain): generate ask_<peer> tools from Agent.subagents

Emits one @tool per declared subagent. Tool body propagates the active
LangGraph thread_id as A2A metadata.sessionId so each peer maintains a
private, correlated conversation slice keyed by the same id.

Docstring is pulled from the peer's instructions (first paragraph,
200-char cap), falling back to a generic delegate message when empty.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Tool name collision detection

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py:160-200`
- Test: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_templates.py`:

```python
def test_subagent_tool_name_collision_with_user_tool_raises():
    import pytest
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)
    assistant = Agent(name="assistant", model=m, subagents=[weather])

    # User has a real tool that shadows the auto-generated subagent tool name.
    with pytest.raises(ValueError, match="ask_weather_agent"):
        generate_agent_py(
            assistant,
            found_tool_names=["ask_weather_agent"],
            stub_tool_names=[],
        )
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::test_subagent_tool_name_collision_with_user_tool_raises -v
```

Expected: FAIL — no collision check yet.

- [ ] **Step 3: Add the collision check**

In `templates.py` `generate_agent_py`, immediately after computing `subagent_tool_names` (added in Task 6 step 5(a)) and BEFORE building `all_tool_names`, add:

```python
    collisions = set(subagent_tool_names) & set(found_tool_names + stub_tool_names)
    if collisions:
        raise ValueError(
            f"Tool name conflict: {sorted(collisions)} are auto-generated "
            f"for subagents but also defined as user tools. "
            f"Remove the user tool or rename it."
        )
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
uv run pytest packages/python/vystak-adapter-langchain/tests/test_templates.py::test_subagent_tool_name_collision_with_user_tool_raises -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py packages/python/vystak-adapter-langchain/tests/test_templates.py
git commit -m "$(cat <<'EOF'
feat(adapter-langchain): detect tool-name collision with subagent codegen

Forces explicit migration when a user-defined tool shadows an
auto-generated ask_<peer> name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Part D: Routing

### Task 8: CLI passes subject's `subagents` to route builder

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py:198-208`
- Test: `packages/python/vystak-cli/tests/test_apply_subagents.py` (create)

- [ ] **Step 1: Read the existing CLI route-building code**

Read `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` lines 180-225. The relevant block computes `peer_routes` for each agent in the deploy loop.

- [ ] **Step 2: Write the failing test**

Create `packages/python/vystak-cli/tests/test_apply_subagents.py`:

```python
"""Tests that restrictive routing scopes VYSTAK_ROUTES_JSON to declared subagents."""
import json
from unittest.mock import MagicMock, patch

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.transport import HttpConfig, Transport


def _build_agents():
    docker_provider = Provider(name="docker", type="docker")
    anthropic = Provider(name="anthropic", type="anthropic")
    transport = Transport(name="default-http", type="http", config=HttpConfig())
    platform = Platform(
        name="local", type="docker", provider=docker_provider, transport=transport,
    )
    model = Model(
        name="m", provider=anthropic, model_name="claude-sonnet-4-20250514",
    )
    weather = Agent(name="weather-agent", model=model, platform=platform)
    time = Agent(name="time-agent", model=model, platform=platform)
    assistant = Agent(
        name="assistant-agent", model=model, platform=platform,
        subagents=[weather, time],
    )
    return weather, time, assistant


def test_routes_for_solo_agent_only_contain_declared_subagents():
    """Weather agent declares no subagents — its route table is empty."""
    from vystak_provider_docker.transport_wiring import build_routes_json, get_transport_plugin

    weather, _time, _assistant = _build_agents()
    plugin = get_transport_plugin("http")
    routes = json.loads(build_routes_json(weather.subagents, plugin, weather.platform))
    assert routes == {}


def test_routes_for_caller_contain_only_declared_peers():
    """Assistant declares [weather, time] — its route table contains both, nothing more."""
    from vystak_provider_docker.transport_wiring import build_routes_json, get_transport_plugin

    _weather, _time, assistant = _build_agents()
    plugin = get_transport_plugin("http")
    routes = json.loads(build_routes_json(assistant.subagents, plugin, assistant.platform))
    assert set(routes.keys()) == {"weather-agent", "time-agent"}
```

- [ ] **Step 3: Run the tests to confirm they currently FAIL or PASS**

```bash
uv run pytest packages/python/vystak-cli/tests/test_apply_subagents.py -v
```

Expected: BOTH PASS (since `build_routes_json` already accepts a list — this is just verifying the helper does the right thing when called with `agent.subagents`. The behavioural change happens at the CLI call site, which we change next.)

- [ ] **Step 4: Change the CLI call site**

Edit `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`. At the existing line:

```python
                peer_routes = build_routes_json(list(agents), plugin, agent.platform)
```

(currently line 206) replace with:

```python
                peer_routes = build_routes_json(agent.subagents, plugin, agent.platform)
```

This is the only behavior change needed — the helper signature stays the same; we just feed it the per-subject peer list.

- [ ] **Step 5: Run the apply unit tests to confirm no regressions**

```bash
uv run pytest packages/python/vystak-cli/tests/ -v
```

Expected: existing tests pass; new `test_apply_subagents.py` tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/apply.py packages/python/vystak-cli/tests/test_apply_subagents.py
git commit -m "$(cat <<'EOF'
feat(cli): scope VYSTAK_ROUTES_JSON to each agent's declared subagents

Restrictive routing — calls to ask_agent() resolve only against the
caller's declared subagents. Undeclared peers raise the existing
'unknown peer' error from the transport client.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Part E: Migrations

### Task 9: Migrate `examples/multi-agent/assistant/`

**Files:**
- Modify: `examples/multi-agent/assistant/vystak.yaml`
- Delete: `examples/multi-agent/assistant/tools/ask_weather_agent.py`
- Delete: `examples/multi-agent/assistant/tools/ask_time_agent.py`

- [ ] **Step 1: Read current state**

```bash
cat examples/multi-agent/assistant/vystak.yaml
ls examples/multi-agent/assistant/tools/
```

The current YAML lists `ask_weather_agent` and `ask_time_agent` in the assistant's `skills.tools` and the corresponding files exist in `tools/`.

Note: this example is single-agent-per-directory style — each agent has its own `vystak.yaml`. Subagents require multi-document YAML. So this migration **converts the directory layout to a single multi-document YAML** at `examples/multi-agent/vystak.yaml` covering all three agents.

- [ ] **Step 2: Create the consolidated multi-document YAML**

Create `examples/multi-agent/vystak.yaml`:

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker}

models:
  minimax:
    provider: anthropic
    model_name: MiniMax-M2.7
    parameters:
      temperature: 0.3
      anthropic_api_url: https://api.minimax.io/anthropic

agents:
  - name: weather-agent
    instructions: |
      You are a weather specialist agent. When asked about weather,
      use the get_weather tool to fetch real data. Return concise,
      factual weather reports. You serve other agents via A2A protocol.
    model: minimax
    platform: local
    skills:
      - {name: weather, tools: [get_weather]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: time-agent
    instructions: |
      You are a time specialist agent. When asked about time,
      use the get_time tool. Return concise, factual responses.
    model: minimax
    platform: local
    skills:
      - {name: time, tools: [get_time]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: assistant-agent
    instructions: |
      You are a helpful general-purpose assistant.
      When the user asks about weather, use ask_weather_agent.
      When the user asks about time, use ask_time_agent.
      If the user asks about BOTH weather and time, call BOTH tools at the same time.
    model: minimax
    platform: local
    subagents: [weather-agent, time-agent]
    secrets:
      - {name: ANTHROPIC_API_KEY}
```

- [ ] **Step 3: Move tool files to a single shared `tools/` directory**

```bash
mkdir -p examples/multi-agent/tools
git mv examples/multi-agent/weather/tools/get_weather.py examples/multi-agent/tools/get_weather.py
git mv examples/multi-agent/time/tools/get_time.py examples/multi-agent/tools/get_time.py
```

- [ ] **Step 4: Delete the old per-directory configs and now-obsolete delegation tool files**

```bash
git rm examples/multi-agent/assistant/tools/ask_weather_agent.py
git rm examples/multi-agent/assistant/tools/ask_time_agent.py
git rm examples/multi-agent/assistant/tools/requirements.txt
git rm examples/multi-agent/assistant/vystak.yaml
git rm examples/multi-agent/weather/vystak.yaml
git rm examples/multi-agent/time/vystak.yaml
git rm -r examples/multi-agent/assistant/
git rm -r examples/multi-agent/weather/
git rm -r examples/multi-agent/time/
```

If the `gateway/` subdirectory exists and is unrelated to subagents, leave it alone.

- [ ] **Step 5: Verify the consolidated example loads**

```bash
uv run python -c "
from vystak.schema.multi_loader import load_multi_yaml
import yaml
data = yaml.safe_load(open('examples/multi-agent/vystak.yaml'))
agents, channels, _vault = load_multi_yaml(data)
assistant = next(a for a in agents if a.name == 'assistant-agent')
print(f'assistant-agent.subagents: {[s.name for s in assistant.subagents]}')
"
```

Expected output: `assistant-agent.subagents: ['weather-agent', 'time-agent']`

- [ ] **Step 6: Commit**

```bash
git add examples/multi-agent/
git commit -m "$(cat <<'EOF'
refactor(examples/multi-agent): consolidate to multi-doc YAML with subagents

Three per-directory configs collapsed to a single examples/multi-agent/
vystak.yaml that declares all three agents and uses Agent.subagents on
the coordinator. Manual ask_*_agent tool files deleted — they are now
auto-generated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Migrate `examples/docker-multi-chat-nats/`

**Files:**
- Modify: `examples/docker-multi-chat-nats/vystak.py`
- Delete: `examples/docker-multi-chat-nats/tools/ask_weather_agent.py`
- Delete: `examples/docker-multi-chat-nats/tools/ask_time_agent.py`

- [ ] **Step 1: Read current state**

```bash
cat examples/docker-multi-chat-nats/vystak.py
```

Note the channel uses the deprecated `routes=[ast.RouteRule(...)]` shape; switch it to `agents=[...]` while we're here (the channel's `_reject_routes` validator already rejects the old shape, so the example is currently broken — fixing it is in scope).

- [ ] **Step 2: Rewrite `vystak.py`**

Replace the entire file with:

```python
"""Docker multi-agent + chat channel example (NATS transport).

Mirror of examples/docker-multi-chat, but with Transport(type="nats") declared
on the platform. Same three agents (weather, time, coordinator) + same chat
channel — A2A traffic flows over NATS JetStream queue-group subscriptions
instead of HTTP. Point any OpenAI-compatible client at http://localhost:18080
and switch agents via the `model` field:

    model="vystak/weather-agent"   -> routed to the weather agent (over NATS)
    model="vystak/time-agent"      -> routed to the time agent (over NATS)
    model="vystak/assistant-agent" -> routed to the coordinator (over NATS)

The coordinator declares `subagents=[weather_agent, time_agent]` so its
generated server gets `ask_weather_agent` and `ask_time_agent` tools that
delegate via Vystak's transport — no manual ask_*_agent.py files needed.

Reads from env (with defaults that target the MiniMax Anthropic-compat
endpoint):

    ANTHROPIC_API_KEY       -  model credential (required at runtime)
    ANTHROPIC_API_URL       -  Anthropic-compatible endpoint
    ANTHROPIC_MODEL_NAME    -  model identifier for that endpoint
"""

import os

import vystak as ast

MODEL_NAME = os.environ.get("ANTHROPIC_MODEL_NAME", "MiniMax-M2.7")
API_URL = os.environ.get("ANTHROPIC_API_URL", "https://api.minimax.io/anthropic")

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="multi-nats",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True, subject_prefix="vystak-nats"),
    ),
)

sonnet = ast.Model(
    name="llm",
    provider=anthropic,
    model_name=MODEL_NAME,
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
    parameters={
        "temperature": 0.3,
        "anthropic_api_url": API_URL,
    },
)

weather_agent = ast.Agent(
    name="weather-agent",
    instructions=(
        "You are a weather specialist. Use get_weather for real data. "
        "Answer concisely with current conditions only."
    ),
    model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=["get_weather"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

time_agent = ast.Agent(
    name="time-agent",
    instructions=(
        "You are a time specialist. Use get_time to report the current "
        "UTC time. Keep replies one sentence."
    ),
    model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

# Coordinator declares its peers via subagents — the langchain adapter
# auto-generates ask_weather_agent and ask_time_agent tools.
assistant_agent = ast.Agent(
    name="assistant-agent",
    instructions=(
        "You are a coordinator. For weather questions call ask_weather_agent; "
        "for time questions call ask_time_agent. When the user asks about "
        "both (e.g. 'what is the weather and time'), call both tools and "
        "synthesise a single concise reply."
    ),
    model=sonnet,
    platform=platform,
    subagents=[weather_agent, time_agent],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 18080},
    agents=[weather_agent, time_agent, assistant_agent],
)
```

- [ ] **Step 3: Delete the now-obsolete delegation tool files**

```bash
git rm examples/docker-multi-chat-nats/tools/ask_weather_agent.py
git rm examples/docker-multi-chat-nats/tools/ask_time_agent.py
```

- [ ] **Step 4: Verify the example loads**

```bash
uv run python -c "
from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location('vystak_example', 'examples/docker-multi-chat-nats/vystak.py')
m = module_from_spec(spec); spec.loader.exec_module(m)
print(f'assistant subagents: {[s.name for s in m.assistant_agent.subagents]}')
print(f'chat agents: {[a.name for a in m.chat.agents]}')
"
```

Expected:
```
assistant subagents: ['weather-agent', 'time-agent']
chat agents: ['weather-agent', 'time-agent', 'assistant-agent']
```

- [ ] **Step 5: Commit**

```bash
git add examples/docker-multi-chat-nats/
git commit -m "$(cat <<'EOF'
refactor(examples/docker-multi-chat-nats): adopt subagents + drop deprecated routes

Coordinator now declares peers via subagents=[weather_agent, time_agent].
Chat channel switched from removed RouteRule list to agents=[...]. Manual
ask_*_agent.py tool files deleted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Rewrite `website/docs/concepts/multi-agent.md`

**Files:**
- Modify: `website/docs/concepts/multi-agent.md`

- [ ] **Step 1: Read current doc**

```bash
cat website/docs/concepts/multi-agent.md
```

Note the structure: tabs throughout, "Specialist + coordinator" section currently shows manual `ask_agent()` tools.

- [ ] **Step 2: Replace the "Specialist + coordinator" section**

Edit `website/docs/concepts/multi-agent.md`. Find the "## Specialist + coordinator" heading and replace its body (everything until "## Channel fan-out") with:

```markdown
## Specialist + coordinator

The simplest pattern: a coordinator declares its peers via `subagents:`. Vystak auto-generates an `ask_<peer>` tool for each one — no hand-written delegation files, no manual `ask_agent()` calls.

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker}

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514

agents:
  - name: weather-agent
    instructions: You are a weather specialist. Use get_weather for real data.
    model: sonnet
    platform: local
    skills:
      - {name: weather, tools: [get_weather]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: time-agent
    instructions: You are a time specialist. Use get_time.
    model: sonnet
    platform: local
    skills:
      - {name: time, tools: [get_time]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: assistant-agent
    instructions: |
      You are a coordinator. For weather questions call ask_weather_agent;
      for time questions call ask_time_agent. When asked about both,
      call both tools and synthesise a single concise reply.
    model: sonnet
    platform: local
    subagents: [weather-agent, time-agent]
    secrets:
      - {name: ANTHROPIC_API_KEY}
```

</TabItem>
<TabItem value="python" label="Python">

```python
import vystak

docker = vystak.Provider(name="docker", type="docker")
anthropic = vystak.Provider(name="anthropic", type="anthropic")
local = vystak.Platform(name="local", type="docker", provider=docker)
sonnet = vystak.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

weather = vystak.Agent(
    name="weather-agent",
    instructions="You are a weather specialist. Use get_weather for real data.",
    model=sonnet,
    platform=local,
    skills=[vystak.Skill(name="weather", tools=["get_weather"])],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)

time = vystak.Agent(
    name="time-agent",
    instructions="You are a time specialist. Use get_time.",
    model=sonnet,
    platform=local,
    skills=[vystak.Skill(name="time", tools=["get_time"])],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)

assistant = vystak.Agent(
    name="assistant-agent",
    instructions=(
        "You are a coordinator. For weather questions call ask_weather_agent; "
        "for time questions call ask_time_agent. When asked about both, "
        "call both tools and synthesise a single concise reply."
    ),
    model=sonnet,
    platform=local,
    subagents=[weather, time],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)
```

</TabItem>
</Tabs>

`vystak apply` builds three containers, computes a per-caller route table (only the assistant can reach `weather-agent` and `time-agent` — the specialists can't reach each other unless they declare `subagents:` of their own), and the LangChain adapter generates two `@tool` functions on the coordinator:

```python
# generated — do not edit
@tool
async def ask_weather_agent(question: str, config: RunnableConfig) -> str:
    """You are a weather specialist. Use get_weather for real data."""
    session_id = (config.get('configurable') or {}).get('thread_id')
    metadata = {'sessionId': session_id} if session_id else {}
    return await ask_agent('weather-agent', question, metadata=metadata)
```

The tool's docstring is taken from the peer's `instructions` (first paragraph, 200-char cap), so the LLM sees what each peer does when picking which to call.

### Session continuity across hops

The coordinator's active session id propagates to every peer it calls via `metadata.sessionId`. The receiving agent uses that id as its own LangGraph `thread_id` — so each peer maintains a private, correlated conversation history under the same id. The coordinator never sees the peer's chain of thought; the peer never sees the coordinator's chat with the human; but a second call from the same Slack thread or chat session reaches the same per-peer thread and remembers what was said before.

Sub-subagent calls (e.g., a peer that itself declares `subagents:`) inherit the id transitively — every hop's auto-generated tool reads its current `thread_id` and propagates.

### Escape hatch: hand-written delegation tools

When the auto-generated docstring isn't right (e.g., per-caller customisation, parameter shaping, structured arguments beyond a single `question` string), drop a manual tool into `tools/` next to `vystak.yaml`:

```python
# tools/ask_weather_agent.py
from vystak.transport import ask_agent

async def ask_weather_agent(question: str, region: str = "global") -> str:
    """Ask the weather specialist, scoped to a region."""
    return await ask_agent(
        "weather-agent",
        f"[region={region}] {question}",
    )
```

The user-defined tool wins for that name. Two constraints to know:

1. **Subagent declaration is still required.** Restrictive routing means `ask_agent("weather-agent", ...)` only succeeds when the caller has `weather-agent` in its `subagents:` list. The auto-generated tool is what gets *replaced* by your hand-written version; the routing authorisation is unchanged.
2. **The langchain adapter raises if a user tool name collides with an auto-generated one** — that protects you from accidental shadowing. To override the auto-generated tool, drop it from `subagents:` and reference it manually via `ask_agent()` in your custom file (or rename your tool).
```

- [ ] **Step 3: Verify the dev server hot-reloads cleanly**

If `just docs-dev` is running:

```bash
# wait a couple seconds for hot reload, then:
curl -s http://localhost:3000/docs/concepts/multi-agent | grep -c "subagents"
```

Expected: a positive integer (the doc references `subagents` in multiple places).

If the dev server isn't running, start it: `just docs-dev`.

- [ ] **Step 4: Commit**

```bash
git add website/docs/concepts/multi-agent.md
git commit -m "$(cat <<'EOF'
docs(multi-agent): lead with subagents; manual ask_agent moves to escape hatch

Specialist + coordinator example now uses Agent.subagents. Manual
delegation tools are documented as a labelled fallback for cases
that need per-caller docstrings or non-trivial argument shaping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Part F: Verify

### Task 12: Run the full CI gate

**Files:** none

- [ ] **Step 1: Run the four live CI gates**

```bash
just lint-python
just test-python
just typecheck-typescript
just test-typescript
```

Expected: all four PASS. (Per `CLAUDE.md`, `lint-typescript` and `typecheck-python` are pre-existing CI failures unrelated to this work — do NOT attempt to fix them as part of this change.)

- [ ] **Step 2: Spot-check that no test was inadvertently skipped**

```bash
uv run pytest packages/python/ -v --co -q 2>&1 | grep -c "subagent"
```

Expected: a number ≥ the count of new tests we wrote across Tasks 1, 2, 3, 4, 5, 6, 7, 8 (~16 tests).

- [ ] **Step 3: If everything passes, the work is done**

No commit needed for this task — it's a verification gate.

If something fails, do **not** start fixing things in a new commit until you understand which task introduced the regression. Run `git log --oneline -20` to see your commit sequence and step backward through them with `git show <hash>` to localize the regression.

---

## Self-Review

After implementing all tasks, do a fresh-eyes pass on this plan against the spec.

**Spec coverage check:**

| Spec section | Plan task |
|---|---|
| `Agent.subagents: list["Agent"]` field | Task 1 |
| Self-reference + duplicate-name validators | Task 2 |
| Multi-loader string→object resolution | Task 3 |
| Single-doc loader rejects subagents | Task 4 |
| Hash contribution (sorted, peer hash unchanged) | Task 5 |
| Codegen `ask_<peer>` tool with sessionId propagation | Task 6 |
| Docstring from peer instructions; fallback when empty | Task 6 |
| Tool name collision detection | Task 7 |
| Restrictive `VYSTAK_ROUTES_JSON` per caller | Task 8 |
| Migrate `examples/multi-agent/` | Task 9 |
| Migrate `examples/docker-multi-chat-nats/` | Task 10 |
| Rewrite `website/docs/concepts/multi-agent.md` | Task 11 |

**Out of scope, intentionally:**

- Per-relationship metadata (description override) — spec excludes.
- Hierarchy / shared lifecycle — spec excludes.
- Typed return values — spec excludes.
- Release-tier test cell — defer to a separate PR; the unit-test coverage in Tasks 1–8 is the gate.

**Type-consistency spot check:**

- `subagent_tool_names` (Task 6 step 5(a)) and `_subagent_tool_names()` (Task 6 step 4) — same name. Good.
- `_generate_subagent_tools(agent)` — defined in Task 6 step 4, called in Task 6 step 5(a). Good.
- `_docstring_from_instructions(peer)` — defined and called only in Task 6. Good.
- `subagents` field on `AgentHashTree` — defined in Task 5 step 4, populated in Task 5 step 6. Good.
