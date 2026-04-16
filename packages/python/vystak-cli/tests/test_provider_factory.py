"""Tests for provider_factory.get_provider()."""

from unittest.mock import MagicMock, patch

import pytest


def _make_agent(provider_type="docker"):
    agent = MagicMock()
    agent.name = "test-agent"
    if provider_type is None:
        agent.platform = None
    else:
        agent.platform = MagicMock()
        agent.platform.provider.type = provider_type
        agent.platform.config = {}
        agent.platform.provider.config = {}
    return agent


class TestGetProvider:
    @patch("vystak_cli.provider_factory.DockerProvider", create=True)
    def test_docker_provider_explicit(self, _mock_docker_cls):
        from vystak_cli.provider_factory import get_provider

        with patch(
            "vystak_cli.provider_factory.DockerProvider",
            create=True,
        ):
            agent = _make_agent("docker")
            provider = get_provider(agent)
            # Should return a DockerProvider instance
            from vystak_provider_docker import DockerProvider

            assert isinstance(provider, DockerProvider)

    def test_docker_provider_when_platform_is_none(self):
        from vystak_cli.provider_factory import get_provider

        agent = _make_agent(None)
        provider = get_provider(agent)
        from vystak_provider_docker import DockerProvider

        assert isinstance(provider, DockerProvider)

    def test_azure_provider(self):
        from vystak_cli.provider_factory import get_provider

        agent = _make_agent("azure")
        provider = get_provider(agent)
        from vystak_provider_azure import AzureProvider

        assert isinstance(provider, AzureProvider)

    def test_unknown_provider_raises(self):
        from vystak_cli.provider_factory import get_provider

        agent = _make_agent("gcp")
        with pytest.raises(ValueError, match="Unknown provider type"):
            get_provider(agent)

    def test_error_message_includes_type(self):
        from vystak_cli.provider_factory import get_provider

        agent = _make_agent("aws")
        with pytest.raises(ValueError, match="aws"):
            get_provider(agent)
