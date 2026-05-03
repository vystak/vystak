"""Slack store tests — generic ChannelStore tests live in vystak-channel-runtime;
this file only covers Slack-specific inviter tracking."""

import pytest
from vystak_channel_slack.inviters import InviterStore


@pytest.mark.asyncio
async def test_inviter_record_then_retrieve(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    await s.record_inviter("T1", "C1", "U_INV")
    assert await s.get_inviter("T1", "C1") == "U_INV"


@pytest.mark.asyncio
async def test_inviter_returns_none_when_absent(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    assert await s.get_inviter("T1", "C1") is None
