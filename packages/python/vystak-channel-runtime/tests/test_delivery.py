"""Tests for DeliveryRequest schema."""

from vystak_channel_runtime.delivery import DeliveryRequest


def test_delivery_request_round_trips():
    r = DeliveryRequest(thread_id="C1", text="hello", metadata={"a": 1})
    restored = DeliveryRequest.model_validate(r.model_dump())
    assert restored == r


def test_delivery_request_metadata_defaults_empty():
    r = DeliveryRequest(thread_id="C1", text="hello")
    assert r.metadata == {}
