from vystak.schema.common import WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.workspace import Workspace


class TestWorkspace:
    def test_sandbox(self):
        ws = Workspace(name="dev", type=WorkspaceType.SANDBOX)
        assert ws.type == WorkspaceType.SANDBOX
        assert ws.filesystem is False
        assert ws.terminal is False
        assert ws.network is True
        assert ws.persist is False

    def test_sandbox_with_capabilities(self):
        ws = Workspace(
            name="dev", type=WorkspaceType.SANDBOX, filesystem=True, terminal=True, timeout="30m"
        )
        assert ws.filesystem is True
        assert ws.terminal is True
        assert ws.timeout == "30m"

    def test_persistent_with_path(self):
        ws = Workspace(
            name="research",
            type=WorkspaceType.PERSISTENT,
            persist=True,
            path="research/{agent}/",
            max_size="100mb",
        )
        assert ws.persist is True
        assert ws.path == "research/{agent}/"

    def test_mounted_with_provider(self):
        provider = Provider(name="gdrive", type="google-drive")
        ws = Workspace(
            name="docs", type=WorkspaceType.MOUNTED, provider=provider, path="/shared/invoices/"
        )
        assert ws.provider.name == "gdrive"

    def test_type_optional(self):
        # Spec 1: `type` is now optional (deprecated). Bare workspace is valid.
        ws = Workspace(name="dev")
        assert ws.type is None
        assert ws.persistence == "volume"

    def test_serialization_roundtrip(self):
        ws = Workspace(name="dev", type=WorkspaceType.SANDBOX, filesystem=True, terminal=True)
        data = ws.model_dump()
        restored = Workspace.model_validate(data)
        assert restored == ws
