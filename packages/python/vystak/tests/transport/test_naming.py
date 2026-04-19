"""Tests for transport naming helpers."""

import pytest
from vystak.transport.naming import (
    canonical_agent_name,
    parse_canonical_name,
    slug,
)


class TestSlug:
    def test_lowercase(self):
        assert slug("TimeAgent") == "timeagent"

    def test_spaces_to_hyphens(self):
        assert slug("my agent") == "my-agent"

    def test_underscores_to_hyphens(self):
        assert slug("my_agent") == "my-agent"

    def test_dots_to_hyphens(self):
        assert slug("my.agent.prod") == "my-agent-prod"

    def test_strips_illegal(self):
        assert slug("my/agent!") == "myagent"

    def test_collapses_runs(self):
        assert slug("my---agent") == "my-agent"

    def test_strips_leading_trailing(self):
        assert slug("-my-agent-") == "my-agent"

    def test_truncates_at_63(self):
        long = "a" * 100
        assert len(slug(long)) == 63

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            slug("")

    def test_only_illegal_raises(self):
        with pytest.raises(ValueError):
            slug("!!!")


class TestCanonicalAgentName:
    def test_explicit_namespace(self):
        assert canonical_agent_name("time-agent", "prod") == "time-agent.agents.prod"

    def test_default_namespace(self):
        assert canonical_agent_name("time-agent") == "time-agent.agents.default"

    def test_none_namespace(self):
        assert canonical_agent_name("time-agent", None) == "time-agent.agents.default"


class TestParseCanonicalName:
    def test_basic(self):
        name, kind, ns = parse_canonical_name("time-agent.agents.prod")
        assert (name, kind, ns) == ("time-agent", "agents", "prod")

    def test_channel(self):
        name, kind, ns = parse_canonical_name("chat.channels.default")
        assert (name, kind, ns) == ("chat", "channels", "default")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_canonical_name("notcanonical")

    def test_wrong_kind_position_raises(self):
        with pytest.raises(ValueError):
            parse_canonical_name("a.b.c.d")
