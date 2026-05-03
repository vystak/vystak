"""Tests for Discord thread + forum detection."""

from dataclasses import dataclass

from vystak_channel_discord.threads import (
    is_forum_channel,
    is_thread_channel,
    should_respond_in_thread,
)


@dataclass
class _FakeEnum:
    """Mimic discord.ChannelType — an enum-like object with a `.name` attribute."""

    name: str


def test_is_thread_channel():
    assert is_thread_channel("thread") is True
    assert is_thread_channel("forum") is False
    assert is_thread_channel("text") is False


def test_is_forum_channel():
    assert is_forum_channel("forum") is True
    assert is_forum_channel("thread") is False


def test_should_respond_in_thread_when_no_explicit_required():
    assert should_respond_in_thread(
        require_explicit_mention=False, mentions_bot=False, is_in_thread=True
    ) is True


def test_should_not_respond_in_thread_when_explicit_required_and_no_mention():
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=False, is_in_thread=True
    ) is False


def test_should_respond_in_thread_when_explicit_required_with_mention():
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=True, is_in_thread=True
    ) is True


def test_top_level_message_always_routes_through_authorize_pipeline():
    # When NOT in a thread, this helper returns True; the runtime's
    # `mentions_bot`/policy checks govern whether to actually respond.
    assert should_respond_in_thread(
        require_explicit_mention=True, mentions_bot=False, is_in_thread=False
    ) is True


def test_is_thread_channel_accepts_discord_enum_public_thread():
    assert is_thread_channel(_FakeEnum("public_thread")) is True


def test_is_thread_channel_accepts_discord_enum_private_thread():
    assert is_thread_channel(_FakeEnum("private_thread")) is True


def test_is_thread_channel_rejects_text_enum():
    assert is_thread_channel(_FakeEnum("text")) is False


def test_is_forum_channel_accepts_discord_enum_forum():
    assert is_forum_channel(_FakeEnum("forum")) is True


def test_is_forum_channel_accepts_discord_enum_media():
    assert is_forum_channel(_FakeEnum("media")) is True


def test_helpers_handle_none_safely():
    assert is_thread_channel(None) is False
    assert is_forum_channel(None) is False
