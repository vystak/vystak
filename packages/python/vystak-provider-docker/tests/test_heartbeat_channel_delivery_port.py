"""Pins the heartbeat scheduler's per-channel-type delivery port.

Regression coverage for the bug fixed alongside Task 17's release-cell
audit: `apply_scheduler`'s `channel_addresses` used to hardcode port 9999
for every channel, but `ChatChannelRuntime` (and `PanelChannelRuntime`)
mount `/deliver` onto their own main FastAPI app — which
`DockerChannelNode` always runs on `container_port` 8080 — instead of the
default `ChannelRuntime` sidecar receiver on `delivery_port` (9999),
which Slack/Discord/any non-overriding channel actually uses.
"""

from unittest.mock import MagicMock, patch

import pytest
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel, ChannelType
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.schedule import ScheduledTask
from vystak_provider_docker.provider import DockerProvider, _heartbeat_delivery_port


@pytest.fixture()
def mock_docker_client():
    with patch("vystak_provider_docker.provider.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.DockerException = type("DockerException", (Exception,), {})
        mock_docker.errors.APIError = type("APIError", (Exception,), {})
        yield client, mock_docker.errors


@pytest.fixture()
def provider(mock_docker_client):
    return DockerProvider()


def _model():
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-20250514",
    )


def _platform():
    return Platform(name="local", type="docker", provider=Provider(name="docker", type="docker"))


class TestHeartbeatDeliveryPortHelper:
    """Direct unit coverage of the port-selection rule."""

    def test_chat_delivers_on_main_app_port(self):
        assert _heartbeat_delivery_port(ChannelType.CHAT) == 8080

    def test_panel_delivers_on_main_app_port(self):
        assert _heartbeat_delivery_port(ChannelType.PANEL) == 8080

    def test_slack_delivers_on_default_sidecar_port(self):
        assert _heartbeat_delivery_port(ChannelType.SLACK) == 9999

    def test_discord_delivers_on_default_sidecar_port(self):
        assert _heartbeat_delivery_port(ChannelType.DISCORD) == 9999


class TestChannelAddressesWiring:
    """End-to-end: apply_scheduler must build channel_addresses with the
    correct per-channel-type port, not a blanket 9999."""

    def test_chat_channel_gets_port_8080(self, provider, mock_docker_client):
        agent = Agent(
            name="hbagent",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="d", cron="0 9 * * 1")],
        )
        chat = Channel(name="hbchat", type=ChannelType.CHAT, platform=_platform())

        with (
            patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle,
            patch("vystak.provisioning.ProvisionGraph") as MockGraph,
        ):
            MockGraph.return_value = MagicMock()
            provider.apply_scheduler([agent], [chat])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["channel_addresses"] == {
            chat.canonical_name: "http://vystak-channel-hbchat:8080",
        }

    def test_slack_channel_keeps_port_9999(self, provider, mock_docker_client):
        agent = Agent(
            name="hbagent",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="d", cron="0 9 * * 1")],
        )
        slack = Channel(name="ops", type=ChannelType.SLACK, platform=_platform())

        with (
            patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle,
            patch("vystak.provisioning.ProvisionGraph") as MockGraph,
        ):
            MockGraph.return_value = MagicMock()
            provider.apply_scheduler([agent], [slack])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["channel_addresses"] == {
            slack.canonical_name: "http://vystak-channel-ops:9999",
        }

    def test_mixed_channels_each_get_their_own_port(self, provider, mock_docker_client):
        agent = Agent(
            name="hbagent",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="d", cron="0 9 * * 1")],
        )
        chat = Channel(name="hbchat", type=ChannelType.CHAT, platform=_platform())
        slack = Channel(name="ops", type=ChannelType.SLACK, platform=_platform())
        panel = Channel(name="control", type=ChannelType.PANEL, platform=_platform())

        with (
            patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle,
            patch("vystak.provisioning.ProvisionGraph") as MockGraph,
        ):
            MockGraph.return_value = MagicMock()
            provider.apply_scheduler([agent], [chat, slack, panel])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["channel_addresses"] == {
            chat.canonical_name: "http://vystak-channel-hbchat:8080",
            slack.canonical_name: "http://vystak-channel-ops:9999",
            panel.canonical_name: "http://vystak-channel-control:8080",
        }
