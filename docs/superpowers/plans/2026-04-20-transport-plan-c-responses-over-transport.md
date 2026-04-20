# Transport — Plan C (OpenAI Responses API over transport)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Route the OpenAI Responses API (`POST /v1/responses`, `GET /v1/responses/{id}`, streaming) through the Vystak transport abstraction. Today the channel byte-proxies via httpx, which silently uses HTTP even when the platform transport is NATS. Plan C makes Responses API east-west traffic obey the configured transport: NATS deployments dispatch Responses over NATS subjects; HTTP deployments continue to use HTTP but via the transport abstraction (not raw httpx).

**Tech Stack:** Python 3.11+, Pydantic v2, Vystak transport ABC from Plans A+B.

**Prerequisites:** Plans A and B merged or on the same branch.

---

## Design

### New A2A-adjacent methods (JSON-RPC envelope reused)

Transports already carry JSON-RPC envelopes for `tasks/send` / `tasks/sendSubscribe`. We add three peer methods:

- `responses/create` — one-shot. Params: `{request: CreateResponseRequest}`. Result: `ResponseObject`.
- `responses/createStream` — streaming. Params same. Result: stream of chunks matching the OpenAI event shapes (`response.created`, `response.output_text.delta`, `response.completed`, etc.).
- `responses/get` — one-shot. Params: `{response_id: str}`. Result: `ResponseObject | null`.

Wire formats are the existing JSON-RPC envelope carried over whichever transport. No new protocol.

### New `Transport` ABC methods

To keep the typing clear and avoid a generic `request(method, ...)` API, add three typed methods:

```python
class Transport(ABC):
    # ... existing send_task, stream_task, serve ...

    @abstractmethod
    async def create_response(
        self, agent: AgentRef, request: dict, metadata: dict,
        *, timeout: float,
    ) -> dict: ...

    async def create_response_stream(
        self, agent: AgentRef, request: dict, metadata: dict,
        *, timeout: float,
    ) -> AsyncIterator[dict]:
        # Default: call create_response, yield a single terminal chunk.
        # Transports with streaming override natively.
        result = await self.create_response(agent, request, metadata, timeout=timeout)
        yield {"type": "response.completed", "response": result}

    @abstractmethod
    async def get_response(
        self, agent: AgentRef, response_id: str,
        *, timeout: float,
    ) -> dict | None: ...
```

(`request` and `result` are plain dicts here — each transport's wire layer serializes them. We keep the Pydantic `CreateResponseRequest` / `ResponseObject` types inside the generated agent, not in `vystak.transport`, to avoid coupling the transport core to OpenAI schema evolution.)

### New server-side handler

The generated agent server currently has `/v1/responses` as inline FastAPI route logic. Plan C extracts this into a `ResponsesHandler` class (similar in shape to `A2AHandler`) that the FastAPI route *and* the transport listener both call into.

The transport listener routes based on JSON-RPC `method`:
- `tasks/send` / `tasks/sendSubscribe` → `A2AHandler`
- `responses/create` / `responses/createStream` / `responses/get` → `ResponsesHandler`

Both `A2AHandler` and `ResponsesHandler` implement a small common protocol consumed by the listener. A thin `ServerDispatcher` holds both and routes by method name.

### Channel-side

Chat channel's `/v1/responses` handler drops httpx and calls `AgentClient.create_response()` / `create_response_stream()` / `get_response()`. These are new `AgentClient` methods that delegate to the active transport.

For `response_id` ownership:
- The agent owns the response (same as today). `store=true` persists on the agent side.
- The channel still maintains `_RESPONSE_OWNERS: dict[response_id, agent_name]` for `GET /v1/responses/{id}` routing.
- GET dispatches `responses/get` to the owner agent over the transport.

Streaming:
- Channel receives `AsyncIterator[dict]` from `AgentClient.create_response_stream()`.
- Re-emits each chunk as an SSE event to the client.

---

## Tasks

7 tasks. Each ends in one commit.

| Task | Scope |
|---|---|
| 1 | `Transport` ABC gains `create_response` / `create_response_stream` / `get_response` |
| 2 | `HttpTransport` implements the three methods (moves existing channel httpx logic into the transport) |
| 3 | `NatsTransport` implements the three methods via NATS request/reply + reply inbox streaming |
| 4 | `ResponsesHandler` class — extract /v1/responses agent logic into a reusable class; generated server uses it for FastAPI AND transport listener dispatch |
| 5 | `AgentClient` gains `create_response` / `create_response_stream` / `get_response` methods |
| 6 | Chat channel `/v1/responses` migrates from httpx to `AgentClient` |
| 7 | End-to-end verification over NATS |

---

## Task 1: Transport ABC — Responses API methods

**Files:**
- Modify: `packages/python/vystak/src/vystak/transport/base.py` — add three new abstract methods + default `create_response_stream` degradation.
- Modify: `packages/python/vystak/tests/transport/test_base.py` — add tests for the new ABC contract.

- [ ] **Step 1:** Extend `Transport` with the three methods per the design above. `create_response` and `get_response` are `@abstractmethod`. `create_response_stream` has a default that calls `create_response` and yields one terminal chunk (same degradation pattern as `stream_task`).

- [ ] **Step 2:** Update `A2AHandlerProtocol` (rename to `ServerDispatcherProtocol`? — no, keep name for now but add to it) OR introduce a new protocol. Simplest: `Transport.serve()`'s `handler` parameter changes to accept a broader interface with both A2A and Responses dispatch methods. Define a new `ServerDispatcherProtocol`:

  ```python
  @runtime_checkable
  class ServerDispatcherProtocol(Protocol):
      async def dispatch_a2a(self, message: A2AMessage, metadata: dict) -> A2AResult: ...
      async def dispatch_a2a_stream(self, message: A2AMessage, metadata: dict) -> AsyncIterator[A2AEvent]: ...
      async def dispatch_responses_create(self, request: dict, metadata: dict) -> dict: ...
      async def dispatch_responses_create_stream(self, request: dict, metadata: dict) -> AsyncIterator[dict]: ...
      async def dispatch_responses_get(self, response_id: str) -> dict | None: ...
  ```

  Keep `A2AHandlerProtocol` as a deprecated alias / subset for backward compat during the transition.

- [ ] **Step 3:** Tests:
  - `test_create_response_abstract` — abstract method can't be called without override.
  - `test_create_response_stream_degradation` — default impl yields single terminal chunk wrapping the one-shot result.
  - `test_get_response_abstract` — abstract.

- [ ] **Step 4:** `just lint-python && just test-python` green.

- [ ] **Step 5:** Commit:

```
feat(transport): Transport ABC — Responses API methods

Adds create_response, create_response_stream, get_response to the
Transport ABC. ServerDispatcherProtocol extends the handler contract
to cover both A2A and Responses dispatch. create_response_stream has
a default degradation (one-shot + terminal chunk) matching stream_task.
```

---

## Task 2: HttpTransport — Responses API methods

**Files:**
- Modify: `packages/python/vystak-transport-http/src/vystak_transport_http/transport.py`
- Modify: `packages/python/vystak-transport-http/tests/test_http_transport.py`

- [ ] **Step 1:** Implement the three methods. For HTTP, we already know the agent's base URL (from `routes[canonical_name]`). The methods call `client.post("{agent_url_base}/v1/responses", ...)` directly, extracting the response body.

  The existing `HttpTransport.resolve_address` returns `{base}/a2a` (A2A endpoint). We need the base URL for Responses. Two options:
  - Derive from A2A URL by stripping `/a2a`.
  - Store the base separately in `routes` (change the shape).

  Simpler: derive. Plan A's format is consistent — `http://vystak-{name}:8000/a2a`. Stripping `/a2a` gives the base. For future transports that use different paths, refactor later.

- [ ] **Step 2:** Streaming — `create_response_stream` consumes SSE from the agent's `/v1/responses?stream=true` endpoint and yields parsed chunks. Mirror the existing `stream_task` SSE parsing pattern.

- [ ] **Step 3:** Tests: extend `TestHttpTransportBasics` + contract tests if applicable.

- [ ] **Step 4:** Gates green.

- [ ] **Step 5:** Commit:

```
feat(transport-http): HttpTransport implements Responses API methods

create_response/create_response_stream/get_response directly POST/GET
on the agent's /v1/responses endpoint via httpx. Mirrors what the chat
channel's current byte-proxy does, but encapsulated inside the transport
so callers don't bypass the abstraction.
```

---

## Task 3: NatsTransport — Responses API methods

**Files:**
- Modify: `packages/python/vystak-transport-nats/src/vystak_transport_nats/transport.py`
- Modify: `packages/python/vystak-transport-nats/tests/test_nats_transport.py`

- [ ] **Step 1:** Implement `create_response`:

  ```python
  async def create_response(self, agent, request, metadata, *, timeout):
      nc = await self._connect()
      subject = self.resolve_address(agent.canonical_name)
      payload = self._build_rpc_envelope("responses/create", {"request": request}, metadata)
      reply = await nc.request(subject, payload, timeout=timeout)
      body = json.loads(reply.data)
      return body.get("result", {})
  ```

- [ ] **Step 2:** Implement `get_response` similarly:

  ```python
  async def get_response(self, agent, response_id, *, timeout):
      ...
      payload = self._build_rpc_envelope("responses/get", {"response_id": response_id}, {})
      reply = await nc.request(subject, payload, timeout=timeout)
      body = json.loads(reply.data)
      result = body.get("result")
      return result if result else None  # null response → None
  ```

- [ ] **Step 3:** Implement `create_response_stream` via the existing reply-inbox pattern used by `stream_task`. Each chunk from the agent is published to the reply inbox as a JSON message; the caller iterates and yields.

  End-of-stream signal: the agent publishes a final chunk with `"type": "response.completed"` and then stops publishing. The caller sees that type and returns.

- [ ] **Step 4:** Refactor: extract the reply-inbox streaming pattern into a private helper shared by `stream_task` and `create_response_stream`. DRY.

- [ ] **Step 5:** Unit tests + Docker-marked integration test extensions.

- [ ] **Step 6:** Gates green.

- [ ] **Step 7:** Commit:

```
feat(transport-nats): NatsTransport implements Responses API methods

create_response and get_response use NATS request/reply. create_response_stream
uses the same _INBOX reply subject pattern as stream_task; the agent publishes
OpenAI response-stream chunks until the terminal response.completed event.

Extracts the reply-inbox streaming into a private helper shared by stream_task
and create_response_stream.
```

---

## Task 4: ResponsesHandler — extract from generated server

**Files:**
- Create: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py`
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/test_templates.py`

This is the largest task. The current generated `server.py` has ~200 lines of `/v1/responses` route logic. Plan C extracts it into a `ResponsesHandler` class emitted in the generated source.

- [ ] **Step 1:** `responses.py` emits a `ResponsesHandler` class as a Python source string (similar to how `a2a.py` emits `A2AHandler`). The class encapsulates:
  - `async def create(request: dict, metadata: dict) -> dict` — runs the agent with `store=request.get("store", True)`, returns `ResponseObject.model_dump()`.
  - `async def create_stream(request: dict, metadata: dict) -> AsyncIterator[dict]` — yields SSE chunks in OpenAI response-stream shape.
  - `async def get(response_id: str) -> dict | None` — looks up stored response.

- [ ] **Step 2:** Rework the FastAPI `/v1/responses` routes emitted in `templates.py` to delegate to the handler instance:

  ```python
  # Emitted:
  _responses_handler = ResponsesHandler(
      graph=graph, checkpointer=checkpointer, store=store,
  )

  @app.post("/v1/responses")
  async def create_response_route(request: CreateResponseRequest):
      if request.stream:
          return StreamingResponse(...)  # iterates _responses_handler.create_stream
      body = await _responses_handler.create(request.model_dump(), metadata={})
      return JSONResponse(body)

  @app.get("/v1/responses/{response_id}")
  async def get_response_route(response_id: str):
      body = await _responses_handler.get(response_id)
      if body is None:
          return JSONResponse({"error": ...}, status_code=404)
      return JSONResponse(body)
  ```

- [ ] **Step 3:** Generated server constructs both `A2AHandler` and `ResponsesHandler`, wraps in a `ServerDispatcher`, and passes to `_transport.serve(canonical_name, dispatcher)`.

- [ ] **Step 4:** Update the transport listener implementations (both Http (no-op) and NATS) to receive the `ServerDispatcher` and route by JSON-RPC method.

- [ ] **Step 5:** Regression tests: the generated server still parses, existing endpoints still work, new paths exist.

- [ ] **Step 6:** Gates green.

- [ ] **Step 7:** Commit:

```
feat(langchain-adapter): ResponsesHandler extracted + generated server dispatches

Generated server.py no longer inlines /v1/responses logic. ResponsesHandler
(emitted as a class in the generated source) owns the create/create_stream/get
semantics; the FastAPI /v1/responses routes are thin adapters.

Generated server constructs a ServerDispatcher wrapping both A2AHandler and
ResponsesHandler. Transport.serve receives the dispatcher; NATS listener
routes inbound messages by JSON-RPC method to the right handler branch.
```

---

## Task 5: AgentClient — Responses API methods

**Files:**
- Modify: `packages/python/vystak/src/vystak/transport/client.py`
- Modify: `packages/python/vystak/tests/transport/test_client.py`

- [ ] **Step 1:** Add three methods:

  ```python
  class AgentClient:
      # ... existing send_task, stream_task ...

      async def create_response(
          self, agent: str, request: dict, *,
          metadata: dict | None = None, timeout: float = 60,
      ) -> dict:
          ref = self._resolve(agent)
          return await self._transport.create_response(
              ref, request, metadata or {}, timeout=timeout
          )

      async def create_response_stream(
          self, agent: str, request: dict, *,
          metadata: dict | None = None, timeout: float = 60,
      ) -> AsyncIterator[dict]:
          ref = self._resolve(agent)
          async for chunk in self._transport.create_response_stream(
              ref, request, metadata or {}, timeout=timeout
          ):
              yield chunk

      async def get_response(
          self, agent: str, response_id: str, *, timeout: float = 60,
      ) -> dict | None:
          ref = self._resolve(agent)
          return await self._transport.get_response(
              ref, response_id, timeout=timeout
          )
  ```

- [ ] **Step 2:** Tests using a `FakeTransport` — verify method delegation.

- [ ] **Step 3:** Gates green.

- [ ] **Step 4:** Commit:

```
feat(transport): AgentClient — Responses API methods

create_response, create_response_stream, get_response delegate to the
active transport. Short-name → canonical-name resolution reuses the
existing _resolve path.
```

---

## Task 6: Chat channel /v1/responses migration

**Files:**
- Modify: `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py`
- Modify: `packages/python/vystak-channel-chat/tests/test_plugin.py`

- [ ] **Step 1:** Replace the httpx-based `/v1/responses` POST handler with `AgentClient.create_response()` / `create_response_stream()`.

  Streaming path: currently the channel proxies SSE byte-by-byte from agent to client. New path: channel iterates `AgentClient.create_response_stream` and re-emits each chunk as SSE to the client. Chunk shape is already OpenAI-compatible; just serialize and stream.

- [ ] **Step 2:** `/v1/responses/{id}` GET uses `AgentClient.get_response(owner_agent, response_id)`. `_RESPONSE_OWNERS` in-memory dict stays.

- [ ] **Step 3:** `httpx` is no longer needed for A2A paths. Check if any remaining use exists; if not, drop from REQUIREMENTS.

- [ ] **Step 4:** Update channel tests; regression-test the marker tests.

- [ ] **Step 5:** Gates green.

- [ ] **Step 6:** Commit:

```
refactor(channel-chat): /v1/responses via AgentClient, dropping httpx byte-proxy

Chat channel's Responses API endpoints now route through AgentClient
instead of raw httpx. On NATS deployments, Responses traffic flows over
NATS subjects; on HTTP deployments, HttpTransport continues to POST
/v1/responses on the agent but via the transport abstraction.

Drops httpx from channel REQUIREMENTS — all east-west traffic is now
transport-routed.
```

---

## Task 7: End-to-end verification

- [ ] **Step 1:** Redeploy `examples/docker-multi-chat-nats` (3 agents, NATS transport).

- [ ] **Step 2:** Hit `/v1/responses` directly via curl — non-streaming:

  ```bash
  curl -s -X POST http://localhost:18080/v1/responses \
    -H 'Content-Type: application/json' \
    -d '{"model":"vystak/weather-agent","input":"weather in Tokyo?","store":true}'
  ```
  Expect a valid ResponseObject. Verify NATS logs show activity, agent logs show NO `/v1/responses` HTTP POST.

- [ ] **Step 3:** Streaming:

  ```bash
  curl -N -s -X POST http://localhost:18080/v1/responses \
    -H 'Content-Type: application/json' \
    -d '{"model":"vystak/time-agent","input":"time?","stream":true}'
  ```
  Expect SSE event stream with OpenAI Response types.

- [ ] **Step 4:** GET:

  ```bash
  # Use the response_id from Step 2's body
  curl -s http://localhost:18080/v1/responses/resp-XXXXX
  ```

- [ ] **Step 5:** Run `vystak-chat` REPL (the original failing client). Verify it connects and streams replies over NATS.

- [ ] **Step 6:** Kill the NATS server container and verify ALL east-west traffic fails (no HTTP fallback):

  ```bash
  docker stop vystak-nats
  # All four paths (chat completions, responses, streaming, get-by-id) fail.
  ```

- [ ] **Step 7:** Teardown.

---

## Final CI gate

- [ ] `just ci` — live gates green.
- [ ] Inspect overall branch: Plans A+B+C commits.
- [ ] Ready to merge/PR.
