# Transport Abstraction — Plan B (NATS JetStream)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a NATS JetStream transport as the second concrete implementation under the Transport abstraction shipped by Plan A. End-to-end: users can set `Platform(..., transport=Transport(type="nats"))` and deploy to Docker; the NATS server is provisioned as a container; agents and channels dispatch A2A traffic over NATS queue-group subscriptions instead of HTTP.

**Tech Stack:** Python 3.11+, `nats-py` (asyncio client), NATS Server 2.10 (JetStream-enabled), Docker.

**Prerequisites:** Plan A merged or on the same branch. Plan A provides `Transport` ABC, `A2AHandler`, `AgentClient`, `TransportPlugin`, `HttpTransport` as the reference concrete.

---

## Design recap (from the spec)

From `docs/superpowers/specs/2026-04-19-transport-abstraction-design.md`:

- **Addressing.** `NatsTransport.resolve_address(canonical_name)` returns `{prefix}.{ns}.agents.{name}.tasks`. Default prefix `"vystak"`. Stream replies use `.stream` suffix or a per-call reply inbox.
- **Replication.** `NatsTransport.serve()` joins a **queue group** named after the agent so load-balancing across replicas is one-of-N. Required.
- **Reply correlation.** Per-call reply inbox (`_INBOX.{uuid}`). Caller subscribes before sending; only the calling replica receives the reply. Required.
- **Streaming.** `supports_streaming = True`. Native streaming via the reply inbox receiving multiple messages until a terminal `A2AEvent(final=True)`.
- **Config.** `NatsConfig(jetstream=True, subject_prefix="vystak", max_message_size_mb=1)`.
- **Provisioning.** `NatsServerNode` = a Docker container running `nats:2.10-alpine` with JetStream enabled, persistent volume for stream durability. BYO path plumbs an external URL.

---

## Task structure

6 tasks. Each ends in one commit.

| Task | Scope |
|---|---|
| 1 | Scaffold `vystak-transport-nats` package |
| 2 | `NatsTransport` — client-side send/stream/serve; passes TransportContract |
| 3 | `NatsTransportPlugin` — env contract, listener code, provisioning node builder |
| 4 | Docker provider integration — register plugin, add `NatsServerNode`, plumb through `apply()` |
| 5 | Generated server template — emit NATS branch in `_build_transport_from_env()` |
| 6 | Example + end-to-end verification — `examples/docker-multi-chat-nats/` |

---

## Task 1: Scaffold `vystak-transport-nats` package

**Files:**
- Create: `packages/python/vystak-transport-nats/pyproject.toml`
- Create: `packages/python/vystak-transport-nats/src/vystak_transport_nats/__init__.py`
- Create: `packages/python/vystak-transport-nats/README.md`
- Create: `packages/python/vystak-transport-nats/tests/__init__.py`

- [ ] **Step 1:** Copy the structure of `packages/python/vystak-transport-http/` as template. Manifest:

```toml
[project]
name = "vystak-transport-nats"
version = "0.1.0"
description = "NATS JetStream transport for Vystak east-west A2A traffic"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "vystak",
    "nats-py>=2.6",
    "pydantic>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_transport_nats"]

[tool.uv.sources]
vystak = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2:** `__init__.py`:

```python
"""NATS JetStream transport for Vystak."""

__all__: list[str] = []  # populated in Task 2
```

- [ ] **Step 3:** `README.md`: one paragraph summary. "Concrete `Transport` using NATS JetStream for east-west A2A traffic. Queue-group load balancing across replicas; per-call reply inbox for correlation."

- [ ] **Step 4:** `uv sync --all-packages`; verify `uv run python -c "import vystak_transport_nats"` works.

- [ ] **Step 5:** `just lint-python && just test-python` green.

- [ ] **Step 6:** Commit:

```
feat(transport-nats): scaffold vystak-transport-nats package

Empty scaffold for NATS JetStream transport. Implementation lands in
follow-up commits. Dependency on nats-py>=2.6 (asyncio client).
```

---

## Task 2: `NatsTransport` concrete

**Files:**
- Create: `packages/python/vystak-transport-nats/src/vystak_transport_nats/transport.py`
- Modify: `packages/python/vystak-transport-nats/src/vystak_transport_nats/__init__.py`
- Create: `packages/python/vystak-transport-nats/tests/test_nats_transport.py`

**Semantics:**

- Constructor: `NatsTransport(url: str, subject_prefix: str = "vystak", jetstream: bool = True)`. URL like `"nats://localhost:4222"`.
- `type = "nats"`, `supports_streaming = True`.
- `resolve_address(canonical_name)` → `"{prefix}.{ns}.agents.{name}.tasks"` — parses canonical name via `parse_canonical_name`.
- `send_task(agent, msg, metadata, timeout)`:
  1. Lazily connect NATS on first call; cache connection.
  2. Build A2A JSON-RPC envelope (same shape as HttpTransport's `_build_payload`).
  3. Use `nc.request(subject, payload, timeout)` — NATS handles reply inbox automatically.
  4. Parse reply via the same `_parse_result` logic as HTTP.
- `stream_task(agent, msg, metadata, timeout)`:
  1. Create a unique reply inbox: `_INBOX.{uuid4}`.
  2. Subscribe to the inbox *before* publishing.
  3. Publish the request with the reply field set to the inbox.
  4. Async-iterate received messages on the inbox; parse each as `A2AEvent`; stop on `final=True` or after the first batch with timeout.
- `serve(canonical_name, handler)`:
  1. Lazily connect.
  2. Subscribe to the agent's subject with `queue=f"agents.{slug(name)}"` for queue-group load balancing.
  3. For each message: parse envelope, call `handler.dispatch_stream` if the method is `tasks/sendSubscribe` else `handler.dispatch`. Publish reply events back to `msg.reply` subject.
  4. This method runs forever; the caller (agent's FastAPI startup task) runs it under `asyncio.create_task`.

- [ ] **Step 1:** Write failing tests. Most can be unit tests with a mock NATS connection, but at least one integration test with a live NATS container — mark with `@pytest.mark.docker` to opt in.

Template for the transport (target shape):

```python
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import nats
from nats.aio.client import Client as NATSClient

from vystak.transport import (
    A2AEvent, A2AMessage, A2AResult, AgentRef, Transport,
)
from vystak.transport.base import A2AHandlerProtocol
from vystak.transport.naming import parse_canonical_name, slug


class NatsTransport(Transport):
    type = "nats"
    supports_streaming = True

    def __init__(
        self,
        url: str,
        *,
        subject_prefix: str = "vystak",
        jetstream: bool = True,
    ) -> None:
        self._url = url
        self._subject_prefix = subject_prefix
        self._jetstream = jetstream
        self._nc: NATSClient | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> NATSClient:
        async with self._lock:
            if self._nc is None or self._nc.is_closed:
                self._nc = await nats.connect(self._url)
            return self._nc

    def resolve_address(self, canonical_name: str) -> str:
        name, kind, ns = parse_canonical_name(canonical_name)
        return f"{self._subject_prefix}.{slug(ns)}.{kind}.{slug(name)}.tasks"

    def _build_envelope(self, method: str, message: A2AMessage, metadata: dict) -> bytes:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "id": message.correlation_id,
                "message": {"role": message.role, "parts": message.parts},
                "metadata": {**message.metadata, **metadata},
            },
        }
        return json.dumps(payload).encode()

    async def send_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> A2AResult:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        payload = self._build_envelope("tasks/send", message, metadata)
        try:
            reply = await nc.request(subject, payload, timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise TimeoutError(f"NATS request to {subject} timed out after {timeout}s") from e
        body = json.loads(reply.data)
        return self._parse_result(body, message.correlation_id)

    async def stream_task(
        self, agent: AgentRef, message: A2AMessage, metadata: dict, *, timeout: float,
    ) -> AsyncIterator[A2AEvent]:
        nc = await self._connect()
        subject = self.resolve_address(agent.canonical_name)
        inbox = f"_INBOX.{uuid.uuid4().hex}"
        sub = await nc.subscribe(inbox)
        try:
            payload = self._build_envelope("tasks/sendSubscribe", message, metadata)
            await nc.publish(subject, payload, reply=inbox)
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"NATS stream from {subject} timed out")
                msg = await asyncio.wait_for(sub.next_msg(), timeout=remaining)
                event = A2AEvent.model_validate(json.loads(msg.data))
                yield event
                if event.final:
                    return
        finally:
            await sub.unsubscribe()

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        nc = await self._connect()
        subject = self.resolve_address(canonical_name)
        _, _, _ = parse_canonical_name(canonical_name)  # validate
        name, _, _ = parse_canonical_name(canonical_name)
        queue_group = f"agents.{slug(name)}"

        async def on_message(msg):
            try:
                body = json.loads(msg.data)
                method = body.get("method", "tasks/send")
                params = body.get("params", {})
                m = A2AMessage(
                    role=params.get("message", {}).get("role", "user"),
                    parts=params.get("message", {}).get("parts", []),
                    correlation_id=params.get("id", str(uuid.uuid4())),
                    metadata=params.get("metadata", {}),
                )
                metadata = params.get("metadata", {})
                if method == "tasks/sendSubscribe":
                    async for event in handler.dispatch_stream(m, metadata):
                        await nc.publish(msg.reply, event.model_dump_json().encode())
                else:
                    result = await handler.dispatch(m, metadata)
                    reply_body = {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "status": {"message": {"parts": [{"text": result.text}]}},
                            "correlation_id": result.correlation_id,
                        },
                    }
                    await nc.publish(msg.reply, json.dumps(reply_body).encode())
            except Exception as e:
                if msg.reply:
                    err = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}
                    await nc.publish(msg.reply, json.dumps(err).encode())

        await nc.subscribe(subject, queue=queue_group, cb=on_message)
        # Block forever; caller runs this under asyncio.create_task
        while True:
            await asyncio.sleep(3600)

    def _parse_result(self, body: dict, fallback_cid: str) -> A2AResult:
        result = body.get("result", {}) or {}
        parts = result.get("status", {}).get("message", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return A2AResult(
            text=text,
            correlation_id=result.get("correlation_id") or fallback_cid,
            metadata={},
        )
```

- [ ] **Step 2:** Unit tests covering `resolve_address`, `_build_envelope`, `_parse_result` (with a mocked nats client where needed).

- [ ] **Step 3:** Docker-marked integration test that subclasses `TransportContract`, spins up a real NATS server via `docker.from_env()`, and runs the contract tests. Similar to `HttpTransport`'s `TestHttpTransport(TransportContract)` in `packages/python/vystak-transport-http/tests/test_http_transport.py` but using a live NATS container as the broker.

- [ ] **Step 4:** Update `__init__.py` to export `NatsTransport`.

- [ ] **Step 5:** `just lint-python && just test-python` green (non-docker suite). Docker suite opt-in; only run if NATS container image is pullable.

- [ ] **Step 6:** Commit:

```
feat(transport-nats): NatsTransport concrete using nats-py

Implements the Transport ABC against NATS JetStream:
- send_task: nc.request with auto-generated reply inbox.
- stream_task: unique _INBOX subject + subscribe-before-publish; yields
  A2AEvents until one with final=True.
- serve: queue-group subscription for replica load balancing + reply
  publishing.
- resolve_address: derives {prefix}.{ns}.agents.{name}.tasks from
  canonical name.

Opt-in Docker integration test runs the shared TransportContract suite
against a live NATS server container.
```

---

## Task 3: `NatsTransportPlugin`

**Files:**
- Create: `packages/python/vystak-transport-nats/src/vystak_transport_nats/plugin.py`
- Modify: `packages/python/vystak-transport-nats/src/vystak_transport_nats/__init__.py`
- Create: `packages/python/vystak-transport-nats/tests/test_nats_plugin.py`

- [ ] **Step 1:** `NatsTransportPlugin` implements the `TransportPlugin` ABC:

```python
from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport
from vystak.schema.agent import Agent
from vystak.transport.naming import parse_canonical_name, slug


class NatsTransportPlugin(TransportPlugin):
    type = "nats"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        # The Docker provider constructs the actual NatsServerNode; this
        # plugin just signals that a broker is needed. The provider
        # checks `plugin.type == "nats"` and knows to add its own
        # NatsServerNode with platform-specific config.
        return []

    def generate_env_contract(self, transport: Transport, context: dict) -> dict[str, str]:
        # context may include a resolved NATS URL from the provider's
        # provisioning step. For v1 Docker: "nats://vystak-nats:4222".
        env = {"VYSTAK_TRANSPORT_TYPE": "nats"}
        if "nats_url" in context:
            env["VYSTAK_NATS_URL"] = context["nats_url"]
        if transport.config and getattr(transport.config, "subject_prefix", None):
            env["VYSTAK_NATS_SUBJECT_PREFIX"] = transport.config.subject_prefix
        return env

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        # The generated server template's _build_transport_from_env already
        # handles the "nats" branch (see Task 5). Nothing extra to inject.
        return None

    def resolve_address_for(self, agent: Agent, platform: Platform) -> str:
        # Matches NatsTransport.resolve_address.
        prefix = "vystak"
        if platform.transport and platform.transport.config:
            prefix = getattr(platform.transport.config, "subject_prefix", prefix)
        ns = slug(platform.namespace or "default")
        return f"{prefix}.{ns}.agents.{slug(agent.name)}.tasks"
```

- [ ] **Step 2:** Tests — basic `type == "nats"`, `generate_env_contract` returns correct env vars, `resolve_address_for` produces expected subject.

- [ ] **Step 3:** `__init__.py` exports both `NatsTransport` and `NatsTransportPlugin`.

- [ ] **Step 4:** Gates green.

- [ ] **Step 5:** Commit:

```
feat(transport-nats): NatsTransportPlugin

Registers the NATS transport with providers. Emits
VYSTAK_TRANSPORT_TYPE=nats + VYSTAK_NATS_URL + VYSTAK_NATS_SUBJECT_PREFIX
into agent and channel container environments. resolve_address_for
produces canonical subjects matching NatsTransport.resolve_address.
```

---

## Task 4: Docker provider integration

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/nats_server.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/transport_wiring.py` — register nats plugin
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — conditionally add `NatsServerNode` to the graph when the agent's platform uses NATS; pass `nats_url` into the plugin's context when generating env contract

- [ ] **Step 1:** `NatsServerNode`:

```python
"""NatsServerNode — runs nats:2.10-alpine with JetStream as a container."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class NatsServerNode(Provisionable):
    IMAGE = "nats:2.10-alpine"
    CONTAINER_NAME = "vystak-nats"

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "nats-server"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def provision(self, context: dict) -> ProvisionResult:
        import docker.errors

        network = context["network"].info["network"]
        try:
            existing = self._client.containers.get(self.CONTAINER_NAME)
            if existing.status != "running":
                existing.start()
        except docker.errors.NotFound:
            self._client.images.pull(self.IMAGE)
            self._client.containers.run(
                self.IMAGE,
                name=self.CONTAINER_NAME,
                detach=True,
                command=["-js", "-sd", "/data"],  # enable JetStream with persistent store
                network=network.name,
                ports={"4222/tcp": 4222},
                volumes={"vystak-nats-data": {"bind": "/data", "mode": "rw"}},
                labels={"vystak.service": "nats"},
            )
        return ProvisionResult(
            name=self.name,
            success=True,
            info={"url": f"nats://{self.CONTAINER_NAME}:4222"},
        )

    def destroy(self) -> None:
        import docker.errors
        try:
            c = self._client.containers.get(self.CONTAINER_NAME)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
```

- [ ] **Step 2:** Register in `transport_wiring._TRANSPORT_PLUGINS`:

```python
from vystak_transport_nats import NatsTransportPlugin

_TRANSPORT_PLUGINS: dict[str, type[TransportPlugin]] = {
    "http": HttpTransportPlugin,
    "nats": NatsTransportPlugin,
}
```

- [ ] **Step 3:** In `DockerProvider.apply()`, when `self._agent.platform.transport.type == "nats"`, add `NatsServerNode(self._client)` to the graph before agent/channel nodes. Then thread `nats_url="nats://vystak-nats:4222"` into the env via the DockerAgentNode. This means `DockerAgentNode` needs to accept `nats_url` (or a generic `extra_env: dict`) kwarg, or the provider sets it on the agent container env dict directly.

Simplest path: provider computes `transport_env = {VYSTAK_TRANSPORT_TYPE: "nats", VYSTAK_NATS_URL: "nats://vystak-nats:4222"}` and merges into `DockerAgentNode.provision()`'s env. Extend `DockerAgentNode` with `extra_env: dict[str, str] | None = None` kwarg.

- [ ] **Step 4:** Same for `DockerChannelNode`.

- [ ] **Step 5:** Update the CLI `apply.py` to also wire NATS agents (currently it's `provider.type == "docker"` Docker-only for peer_routes — NATS doesn't need peer routes as URLs because `NatsTransport.resolve_address` is fully deterministic from canonical names). Leave `peer_routes=None` for NATS agents; transport handles subject derivation.

- [ ] **Step 6:** Provider tests + gates green.

- [ ] **Step 7:** Commit:

```
feat(provider-docker): NATS transport integration

- NatsServerNode runs nats:2.10-alpine with JetStream enabled on the
  shared vystak-net network.
- _TRANSPORT_PLUGINS registers NatsTransportPlugin for type="nats".
- DockerProvider.apply() adds NatsServerNode when an agent's platform
  uses NATS; injects VYSTAK_TRANSPORT_TYPE=nats + VYSTAK_NATS_URL into
  the container env via a new extra_env kwarg on DockerAgentNode /
  DockerChannelNode.
- CLI doesn't compute peer_routes for NATS agents — canonical-name
  subject derivation is deterministic inside NatsTransport.
```

---

## Task 5: Generated server template — NATS branch

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` — extend `_build_transport_from_env()` emission to handle `"nats"`.

Also: the channel server templates (`vystak-channel-chat`, `vystak-channel-slack`) have the same bootstrap; they need the same branch. Apply consistently.

- [ ] **Step 1:** In the emitted `_build_transport_from_env()` function, add a NATS branch:

```python
# Emitted into generated server.py:
def _build_transport_from_env():
    transport_type = _os.environ.get("VYSTAK_TRANSPORT_TYPE", "http")
    if transport_type == "http":
        from vystak_transport_http import HttpTransport
        return HttpTransport(routes=_http_routes)
    if transport_type == "nats":
        from vystak_transport_nats import NatsTransport
        url = _os.environ["VYSTAK_NATS_URL"]
        prefix = _os.environ.get("VYSTAK_NATS_SUBJECT_PREFIX", "vystak")
        return NatsTransport(url=url, subject_prefix=prefix)
    raise RuntimeError(f"unsupported VYSTAK_TRANSPORT_TYPE={transport_type}")
```

- [ ] **Step 2:** The channel server templates' `_build_transport_from_env` is identical in shape. Update both (`packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py` and `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py`) with the same NATS branch.

- [ ] **Step 3:** Docker provider's channel node also needs to bundle `vystak_transport_nats` source into the container (same pattern as `vystak_transport_http`):

```python
# In DockerAgentNode and DockerChannelNode, extend the bundling loop:
try:
    import vystak_transport_nats  # optional
    _modules = (vystak, vystak_transport_http, vystak_transport_nats)
except ImportError:
    _modules = (vystak, vystak_transport_http)
```

Actually simpler: always bundle both since both are workspace packages and always installed via `uv sync`. Just update the list.

- [ ] **Step 4:** Generated server test: add `test_generated_server_bootstrap_has_nats_branch` that asserts the NATS branch is emitted.

- [ ] **Step 5:** Gates green.

- [ ] **Step 6:** Commit:

```
feat(langchain-adapter,channel): generated transport bootstrap handles NATS

- Generated agent server.py's _build_transport_from_env now branches on
  VYSTAK_TRANSPORT_TYPE=nats and constructs a NatsTransport.
- Channel server templates (chat + slack) get the same branch.
- Docker agent + channel nodes bundle vystak_transport_nats source into
  the build context so NatsTransport is importable at runtime.
```

---

## Task 6: Example + end-to-end verification

**Files:**
- Create: `examples/docker-multi-chat-nats/vystak.py`
- Create: `examples/docker-multi-chat-nats/README.md`
- Create: `examples/docker-multi-chat-nats/tools/get_time.py` (symlink or copy)
- Create: `examples/docker-multi-chat-nats/tools/get_weather.py` (symlink or copy)

- [ ] **Step 1:** Copy `examples/docker-multi-chat/` to `examples/docker-multi-chat-nats/`. Modify `vystak.py` to declare the NATS transport:

```python
# Only the platform declaration changes:
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
```

Everything else — agents, channel, tools — is identical.

- [ ] **Step 2:** Add `examples/docker-multi-chat-nats/README.md` explaining: deploy with `vystak apply`, verify NATS is provisioned, hit the chat endpoint, watch a NATS-native deployment work.

- [ ] **Step 3:** End-to-end smoke test. This is manual but the checklist is:

```bash
# From the worktree root:
set -a; source /path/to/.env; set +a
uv run vystak apply --file examples/docker-multi-chat-nats/vystak.py

# Expected: vystak-nats, vystak-time-agent, vystak-weather-agent,
# vystak-channel-chat all running.
docker ps | grep vystak

# Expected: agent env shows VYSTAK_TRANSPORT_TYPE=nats + VYSTAK_NATS_URL
docker exec vystak-time-agent env | grep VYSTAK_

# Expected: OpenAI-compatible response that routed over NATS (not HTTP).
curl -s http://localhost:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/time-agent","messages":[{"role":"user","content":"what time?"}]}'

# Watch NATS activity to confirm:
docker exec vystak-nats nats stream ls  # if nats CLI is available

uv run vystak destroy --file examples/docker-multi-chat-nats/vystak.py
```

- [ ] **Step 4:** Commit:

```
feat(example): docker-multi-chat-nats — NATS transport end-to-end

Mirrors docker-multi-chat but declares Transport(type="nats") on the
platform. Deploys the NATS server, two agents, and a chat channel all
wired to dispatch A2A traffic over NATS queue-group subscriptions
instead of HTTP.
```

---

## Final CI gate

- [ ] Run `just ci` — all four live gates green.
- [ ] Review the overall branch: Plan A + Plan B commits. Expect ~5-6 new commits on top of Plan A's 39.
- [ ] Ready to merge/PR.
