import pytest
from pydantic import ValidationError

from agentstack.schema.common import (
    ChannelType,
    McpTransport,
    NamedModel,
    WorkspaceType,
)


class TestNamedModel:
    def test_create_with_name(self):
        model = NamedModel(name="test")
        assert model.name == "test"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            NamedModel()

    def test_name_must_be_string(self):
        with pytest.raises(ValidationError):
            NamedModel(name=123)

    def test_empty_name_allowed(self):
        model = NamedModel(name="")
        assert model.name == ""


class TestWorkspaceType:
    def test_sandbox(self):
        assert WorkspaceType.SANDBOX == "sandbox"

    def test_persistent(self):
        assert WorkspaceType.PERSISTENT == "persistent"

    def test_mounted(self):
        assert WorkspaceType.MOUNTED == "mounted"


class TestChannelType:
    def test_all_types(self):
        expected = {"api", "slack", "webhook", "voice", "cron", "widget"}
        actual = {ct.value for ct in ChannelType}
        assert actual == expected


class TestMcpTransport:
    def test_all_transports(self):
        expected = {"stdio", "sse", "streamable_http"}
        actual = {mt.value for mt in McpTransport}
        assert actual == expected
