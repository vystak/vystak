"""Tests for the Slack-only inviter helper."""

import pytest
from vystak_channel_slack.inviters import InviterStore


@pytest.mark.asyncio
async def test_inviter_round_trip(tmp_path):
    s = InviterStore(str(tmp_path / "inv.db"))
    assert await s.get_inviter("T1", "C1") is None
    await s.record_inviter("T1", "C1", "U_INVITER")
    assert await s.get_inviter("T1", "C1") == "U_INVITER"
