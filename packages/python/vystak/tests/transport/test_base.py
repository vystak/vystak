"""Tests for the Transport ABC contract."""

from __future__ import annotations

import pytest
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
    Transport,
)
from vystak.transport.base import (
    A2AHandlerProtocol,
    ServerDispatcherProtocol,
)


class FakeTransport(Transport):
    """Minimal concrete Transport for testing ABC behaviour."""

    type = "fake"
    supports_streaming = False

    def __init__(self) -> None:
        self.sent: list[tuple[AgentRef, A2AMessage]] = []
        self.served: list[str] = []

    def resolve_address(self, canonical_name: str) -> str:
        return f"fake://{canonical_name}"

    async def send_task(
        self,
        agent: AgentRef,
        message: A2AMessage,
        metadata: dict,
        *,
        timeout: float,
    ) -> A2AResult:
        self.sent.append((agent, message))
        return A2AResult(text="ack", correlation_id=message.correlation_id)

    async def serve(self, canonical_name: str, handler: A2AHandlerProtocol) -> None:
        self.served.append(canonical_name)

    async def create_response(self, agent, request, metadata, *, timeout):
        return {"id": "resp-fake", "created_at": 0, "model": "fake"}

    async def get_response(self, agent, response_id, *, timeout):
        return None


class TestTransport:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Transport()

    def test_concrete_subclass(self):
        t = FakeTransport()
        assert t.type == "fake"
        assert t.supports_streaming is False

    @pytest.mark.asyncio
    async def test_send_task(self):
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi", correlation_id="c-1")
        result = await t.send_task(ref, msg, {}, timeout=5)
        assert result.text == "ack"
        assert result.correlation_id == "c-1"

    @pytest.mark.asyncio
    async def test_default_stream_task_degrades(self):
        """A non-streaming transport's stream_task() yields one terminal event."""
        t = FakeTransport()
        ref = AgentRef(canonical_name="x.agents.default")
        msg = A2AMessage.from_text("hi")
        events: list[A2AEvent] = []
        async for ev in t.stream_task(ref, msg, {}, timeout=5):
            events.append(ev)
        assert len(events) == 1
        assert events[0].final is True
        assert events[0].type == "final"
        assert events[0].text == "ack"

    def test_resolve_address(self):
        t = FakeTransport()
        assert t.resolve_address("x.agents.prod") == "fake://x.agents.prod"


class TestResponsesAPIContract:
    @pytest.mark.asyncio
    async def test_create_response_default_raises(self):
        """Transport without overrides raises NotImplementedError on create_response."""

        class Minimal(Transport):
            type = "minimal"

            def resolve_address(self, canonical_name: str) -> str:
                return "fake"

            async def send_task(self, *a, **kw):
                pass

            async def serve(self, *a, **kw):
                pass

        t = Minimal()
        ref = AgentRef(canonical_name="a.agents.default")
        with pytest.raises(NotImplementedError):
            await t.create_response(ref, {}, {}, timeout=5)

    @pytest.mark.asyncio
    async def test_create_response_stream_degradation(self):
        """Default create_response_stream calls create_response and yields a
        single terminal chunk."""

        class OneShotOnly(Transport):
            type = "oneshot"
            supports_streaming = False

            def resolve_address(self, canonical_name: str) -> str:
                return "fake"

            async def send_task(self, *a, **kw):
                pass

            async def serve(self, *a, **kw):
                pass

            async def create_response(self, agent, request, metadata, *, timeout):
                return {"id": "resp-1", "output": [{"content": "hello"}]}

            async def get_response(self, agent, response_id, *, timeout):
                return None

        t = OneShotOnly()
        ref = AgentRef(canonical_name="a.agents.default")
        chunks = [c async for c in t.create_response_stream(ref, {}, {}, timeout=5)]
        assert len(chunks) == 1
        assert chunks[0]["type"] == "response.completed"
        assert chunks[0]["response"]["id"] == "resp-1"

    @pytest.mark.asyncio
    async def test_get_response_default_raises(self):
        """Transport without overrides raises NotImplementedError on get_response."""

        class Minimal(Transport):
            type = "minimal2"

            def resolve_address(self, canonical_name: str) -> str:
                return "fake"

            async def send_task(self, *a, **kw):
                pass

            async def serve(self, *a, **kw):
                pass

        t = Minimal()
        ref = AgentRef(canonical_name="a.agents.default")
        with pytest.raises(NotImplementedError):
            await t.get_response(ref, "some-id", timeout=5)

    @pytest.mark.asyncio
    async def test_get_response_returns_none_for_unknown(self):
        """Concrete implementation returning None for unknown IDs is honored."""

        class WithGet(Transport):
            type = "g"

            def resolve_address(self, canonical_name: str) -> str:
                return "fake"

            async def send_task(self, *a, **kw):
                pass

            async def serve(self, *a, **kw):
                pass

            async def create_response(self, *a, **kw):
                return {}

            async def get_response(self, agent, response_id, *, timeout):
                return None if response_id == "missing" else {"id": response_id}

        t = WithGet()
        ref = AgentRef(canonical_name="a.agents.default")
        assert await t.get_response(ref, "missing", timeout=5) is None
        assert (await t.get_response(ref, "resp-1", timeout=5))["id"] == "resp-1"

    def test_server_dispatcher_protocol_is_runtime_checkable(self):
        """ServerDispatcherProtocol is @runtime_checkable."""
        # An object without the methods is not an instance.
        assert not isinstance(object(), ServerDispatcherProtocol)

    def test_server_dispatcher_protocol_accepts_compliant_stub(self):
        """A minimal class implementing all five methods satisfies the protocol."""

        class _Stub:
            async def dispatch_a2a(self, message, metadata):
                return A2AResult(text="x", correlation_id="c")

            def dispatch_a2a_stream(self, message, metadata):
                async def _g():
                    yield A2AEvent(type="final", text="x", final=True)

                return _g()

            async def dispatch_responses_create(self, request, metadata):
                return {"id": "r"}

            def dispatch_responses_create_stream(self, request, metadata):
                async def _g():
                    yield {"type": "response.completed"}

                return _g()

            async def dispatch_responses_get(self, response_id):
                return None

        stub = _Stub()
        assert isinstance(stub, ServerDispatcherProtocol)
