"""ResponsesClient — SSE parsing against a mocked /v1/responses."""

import json

import httpx
from vystak_channel_panel.responses_client import (
    PanelStreamEvent,
    ResponsesClient,
    agent_base_url,
)


def _sse_body(*payloads: dict | str) -> str:
    out = []
    for p in payloads:
        data = p if isinstance(p, str) else json.dumps(p)
        out.append(f"data: {data}\n\n")
    return "".join(out)


def _mock_client(body: str, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            status_code, content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _collect(client: ResponsesClient) -> list[PanelStreamEvent]:
    return [
        ev
        async for ev in client.stream_message(
            "http://agent:8000", "hi", previous_response_id=None
        )
    ]


async def test_tokens_then_done():
    body = _sse_body(
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_text.delta", "delta": "Hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {"type": "response.completed", "response": {"id": "resp_1"}},
        "[DONE]",
    )
    client = ResponsesClient(http_client=_mock_client(body))
    events = await _collect(client)
    assert [e.type for e in events] == ["token", "token", "done"]
    assert "".join(e.text for e in events if e.type == "token") == "Hello"
    assert events[-1].response_id == "resp_1"


async def test_failed_event_maps_to_error():
    body = _sse_body(
        {"type": "response.failed",
         "response": {"id": "resp_1", "status": "failed",
                      "error": {"message": "boom"}}},
        "[DONE]",
    )
    client = ResponsesClient(http_client=_mock_client(body))
    events = await _collect(client)
    assert events[-1].type == "error"
    assert "boom" in events[-1].text


async def test_http_error_maps_to_error():
    client = ResponsesClient(http_client=_mock_client("", status_code=503))
    events = await _collect(client)
    assert events == [
        PanelStreamEvent(type="error", text="agent returned 503")
    ]


async def test_previous_response_id_forwarded():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, content=_sse_body("[DONE]").encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = ResponsesClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    async for _ in client.stream_message(
        "http://agent:8000", "hi",
        previous_response_id="resp_9", user_id="u1", project_id="p1",
    ):
        pass
    assert captured["previous_response_id"] == "resp_9"
    assert captured["user_id"] == "u1"
    assert captured["project_id"] == "p1"


def test_agent_base_url_strips_a2a():
    assert agent_base_url({"address": "http://x:8000/a2a"}) == "http://x:8000"
    assert agent_base_url({"address": "http://x:8000"}) == "http://x:8000"
    assert agent_base_url("http://x:8000/a2a") == "http://x:8000"


class _ExplodingOnCloseStream(httpx.AsyncByteStream):
    """A response body whose aclose() raises, simulating a transport error
    surfacing while __aexit__ tears down a mid-transfer stream."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def __aiter__(self):
        yield self._payload

    async def aclose(self) -> None:
        raise httpx.ReadError("connection reset during teardown")


async def test_aclose_during_abandonment_does_not_raise():
    """Regression: consumer abandons the stream (GeneratorExit) while the
    transport's close also raises httpx.HTTPError. Before the fix, the
    close-time error replaced the propagating GeneratorExit, was caught by
    the broad `except httpx.HTTPError`, and the handler tried to `yield` —
    illegal during generator close — raising
    `RuntimeError: async generator ignored GeneratorExit`.
    """
    payload = _sse_body(
        {"type": "response.output_text.delta", "delta": "Hel"},
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_ExplodingOnCloseStream(payload),
            headers={"content-type": "text/event-stream"},
        )

    client = ResponsesClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    agen = client.stream_message(
        "http://agent:8000", "hi", previous_response_id=None
    )
    first = await agen.__anext__()
    assert first.type == "token"

    await agen.aclose()  # must not raise


async def test_owned_client_is_closed_after_stream():
    """No http_client is injected: stream_message must create its own
    httpx.AsyncClient and close it when the stream completes."""
    closed = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_sse_body("[DONE]").encode(),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)

    class _TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

        async def aclose(self) -> None:
            closed["count"] += 1
            await super().aclose()

    import vystak_channel_panel.responses_client as responses_client_module

    monkeypatch_target = responses_client_module.httpx.AsyncClient
    responses_client_module.httpx.AsyncClient = _TrackingAsyncClient
    try:
        client = ResponsesClient()
        events = [
            ev
            async for ev in client.stream_message(
                "http://agent:8000", "hi", previous_response_id=None
            )
        ]
    finally:
        responses_client_module.httpx.AsyncClient = monkeypatch_target

    assert events == []
    assert closed["count"] == 1


async def test_injected_client_is_not_closed():
    """An injected http_client is owned by the caller and must survive the
    call to stream_message."""
    closed = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_sse_body("[DONE]").encode(),
            headers={"content-type": "text/event-stream"},
        )

    injected = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    original_aclose = injected.aclose

    async def _tracking_aclose():
        closed["count"] += 1
        await original_aclose()

    injected.aclose = _tracking_aclose

    client = ResponsesClient(http_client=injected)
    async for _ in client.stream_message(
        "http://agent:8000", "hi", previous_response_id=None
    ):
        pass

    assert closed["count"] == 0
    await injected.aclose()
