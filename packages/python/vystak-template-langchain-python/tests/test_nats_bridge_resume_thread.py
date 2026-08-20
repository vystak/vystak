"""Tests for `responses/resumeThread` — thread-keyed resume for
A2A-originated turns (no detached-journal row; see nats_bridge.py's
`_handle_resume_thread`)."""

import json

import pytest


@pytest.mark.asyncio
async def test_resume_thread_returns_final_text(bridge_factory):
    bridge = bridge_factory(
        sse_events=[
            {"type": "response.output_text.delta", "delta": "step done. "},
            {"type": "response.output_text.delta", "delta": "All good."},
            {"type": "response.completed", "response": {"id": "resp_1"}},
        ],
    )
    await bridge._handle_envelope_for_test(
        {
            "id": 9,
            "method": "responses/resumeThread",
            "params": {"thread_id": "resp_1", "resume": {"approved": True}},
        },
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["result"] == {"text": "step done. All good."}
    # the resume POST carried thread_id + resume
    resume_posts = [r for r in bridge.requests if r["path"] == "/v1/_vystak/resume"]
    assert resume_posts and resume_posts[-1]["json"] == {
        "thread_id": "resp_1",
        "resume": {"approved": True},
    }


@pytest.mark.asyncio
async def test_resume_thread_requires_thread_id(bridge_factory):
    bridge = bridge_factory()
    await bridge._handle_envelope_for_test(
        {"id": 9, "method": "responses/resumeThread", "params": {}},
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_resume_thread_reports_http_failure(bridge_factory):
    # A real non-200 from /v1/_vystak/resume (not a monkeypatched method) —
    # exercises the actual raise_for_status() path on a streaming response.
    bridge = bridge_factory(resume_status=500)
    await bridge._handle_envelope_for_test(
        {
            "id": 9,
            "method": "responses/resumeThread",
            "params": {"thread_id": "resp_1", "resume": None},
        },
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32000
    assert "resume failed" in reply["error"]["message"]


@pytest.mark.asyncio
async def test_resume_thread_reports_consumption_failure(bridge_factory):
    bridge = bridge_factory()

    async def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("connection refused")

    bridge._resume_and_collect_text = _boom
    await bridge._handle_envelope_for_test(
        {
            "id": 9,
            "method": "responses/resumeThread",
            "params": {"thread_id": "resp_1", "resume": None},
        },
        "reply.inbox",
    )
    reply = json.loads(bridge.replies[-1])
    assert reply["error"]["code"] == -32000
    assert "resume failed" in reply["error"]["message"]
