"""Tests for vystak.transport.idempotency + A2AHandler dedup."""

from __future__ import annotations

import asyncio

import pytest
from vystak.transport import (
    A2AEvent,
    A2AHandler,
    A2AMessage,
    A2AResult,
    IdempotencyCache,
    extract_idempotency_key,
)


class TestIdempotencyCache:
    def test_put_and_get_within_ttl(self):
        cache: IdempotencyCache[str] = IdempotencyCache(ttl_seconds=60)
        cache.put("key-1", "value-1")
        assert cache.get("key-1") == "value-1"

    def test_miss_returns_none(self):
        cache: IdempotencyCache[str] = IdempotencyCache()
        assert cache.get("nope") is None

    def test_expired_entry_returns_none_and_is_cleaned(self):
        cache: IdempotencyCache[str] = IdempotencyCache(ttl_seconds=0.01)
        cache.put("key-1", "value-1")
        # Sleep briefly — the entry should expire.
        import time

        time.sleep(0.05)
        assert cache.get("key-1") is None
        assert len(cache) == 0

    def test_overwrite_extends_ttl(self):
        cache: IdempotencyCache[str] = IdempotencyCache(ttl_seconds=0.05)
        cache.put("key-1", "value-1")
        cache.put("key-1", "value-2")
        # Second put refreshed the entry.
        assert cache.get("key-1") == "value-2"

    def test_clear(self):
        cache: IdempotencyCache[str] = IdempotencyCache()
        cache.put("a", "1")
        cache.put("b", "2")
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert len(cache) == 0


class TestExtractIdempotencyKey:
    def test_snake_case(self):
        assert extract_idempotency_key({"idempotency_key": "abc"}) == "abc"

    def test_camel_case(self):
        assert extract_idempotency_key({"idempotencyKey": "abc"}) == "abc"

    def test_snake_wins_over_camel(self):
        # If both are present, the snake_case variant wins (lookup order).
        md = {"idempotency_key": "snake", "idempotencyKey": "camel"}
        assert extract_idempotency_key(md) == "snake"

    def test_missing(self):
        assert extract_idempotency_key({}) is None

    def test_empty_string_is_none(self):
        assert extract_idempotency_key({"idempotency_key": ""}) is None

    def test_non_string_is_none(self):
        assert extract_idempotency_key({"idempotency_key": 42}) is None


class TestA2AHandlerIdempotency:
    def _handler_with_cache(self, ttl: float = 60):
        calls = {"n": 0}

        async def one_shot(msg: A2AMessage, metadata):
            calls["n"] += 1
            text = msg.parts[0].get("text", "")
            return f"reply[{calls['n']}]:{text}"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="n/a", final=True)

        cache = IdempotencyCache[A2AResult](ttl_seconds=ttl)
        handler = A2AHandler(
            one_shot=one_shot,
            streaming=streaming,
            idempotency_cache=cache,
        )
        return handler, calls, cache

    @pytest.mark.asyncio
    async def test_no_key_no_dedup(self):
        """Without an idempotency_key, every dispatch runs the agent."""
        handler, calls, _cache = self._handler_with_cache()
        msg1 = A2AMessage.from_text("hi")
        msg2 = A2AMessage.from_text("hi")
        r1 = await handler.dispatch(msg1, {})
        r2 = await handler.dispatch(msg2, {})
        assert calls["n"] == 2
        assert r1.text == "reply[1]:hi"
        assert r2.text == "reply[2]:hi"

    @pytest.mark.asyncio
    async def test_same_key_deduped(self):
        """Same idempotency_key: second call returns cached result."""
        handler, calls, _cache = self._handler_with_cache()
        md = {"idempotency_key": "req-1"}
        msg1 = A2AMessage.from_text("hi", metadata=md)
        msg2 = A2AMessage.from_text("hi", metadata=md)
        r1 = await handler.dispatch(msg1, {})
        r2 = await handler.dispatch(msg2, {})
        assert calls["n"] == 1
        assert r1.text == "reply[1]:hi"
        assert r2.text == r1.text
        # correlation_id comes from the first message (cached result
        # carries the cid of the run that produced it).
        assert r2.correlation_id == r1.correlation_id

    @pytest.mark.asyncio
    async def test_different_keys_run_separately(self):
        """Different idempotency_keys both run the agent."""
        handler, calls, _cache = self._handler_with_cache()
        r1 = await handler.dispatch(
            A2AMessage.from_text("a", metadata={"idempotency_key": "k-1"}), {}
        )
        r2 = await handler.dispatch(
            A2AMessage.from_text("b", metadata={"idempotency_key": "k-2"}), {}
        )
        assert calls["n"] == 2
        assert r1.text == "reply[1]:a"
        assert r2.text == "reply[2]:b"

    @pytest.mark.asyncio
    async def test_expired_cache_reruns(self):
        """After TTL, the same key reruns the agent."""
        handler, calls, _cache = self._handler_with_cache(ttl=0.01)
        md = {"idempotency_key": "req-1"}
        await handler.dispatch(A2AMessage.from_text("hi", metadata=md), {})
        await asyncio.sleep(0.05)
        await handler.dispatch(A2AMessage.from_text("hi", metadata=md), {})
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_key_in_dispatch_metadata_also_works(self):
        """Idempotency_key can arrive on the message OR on the dispatch metadata."""
        handler, calls, _cache = self._handler_with_cache()
        # Key on the dispatch metadata, not the message.
        r1 = await handler.dispatch(A2AMessage.from_text("hi"), {"idempotency_key": "k-1"})
        r2 = await handler.dispatch(A2AMessage.from_text("hi"), {"idempotency_key": "k-1"})
        assert calls["n"] == 1
        assert r1.text == r2.text

    @pytest.mark.asyncio
    async def test_exception_not_cached(self):
        """A failed dispatch does NOT dedup future retries."""
        attempts = {"n": 0}

        async def flaky(msg, metadata):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("boom")
            return "eventually worked"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="n/a", final=True)

        cache = IdempotencyCache[A2AResult]()
        handler = A2AHandler(one_shot=flaky, streaming=streaming, idempotency_cache=cache)

        msg = A2AMessage.from_text("hi", metadata={"idempotency_key": "k-1"})
        with pytest.raises(RuntimeError, match="boom"):
            await handler.dispatch(msg, {})

        # Retry the same key — should run again (failures not cached).
        result = await handler.dispatch(msg, {})
        assert result.text == "eventually worked"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_no_cache_passes_through(self):
        """Handler without a cache behaves exactly as before."""

        async def one_shot(msg, metadata):
            return "ok"

        async def streaming(msg, metadata):
            yield A2AEvent(type="final", text="n/a", final=True)

        handler = A2AHandler(one_shot=one_shot, streaming=streaming)
        msg = A2AMessage.from_text("hi", metadata={"idempotency_key": "k-1"})
        r = await handler.dispatch(msg, {})
        assert r.text == "ok"
