"""Pins the heartbeat scheduler's per-channel delivery port.

Regression coverage for two bugs fixed alongside Task 17's release-cell
audit:

1. `apply_scheduler`'s `channel_addresses` used to hardcode port 9999 for
   every channel, but `ChatChannelRuntime` (and `PanelChannelRuntime`)
   mount `/deliver` onto their own main FastAPI app — which
   `DockerChannelNode` always runs on `container_port` 8080 — instead of
   the default `ChannelRuntime` sidecar receiver on `delivery_port`
   (9999 default), which Slack/Discord/any non-overriding channel
   actually uses.
2. Same bug, other branch: the fix above still keyed on `ChannelType`
   alone, ignoring that Slack/Discord's `delivery_port` is user
   config-overridable (`ChannelRuntime._start_http_delivery_receiver`
   reads `int(self.config.get("delivery_port", 9999))`, and the
   slack/discord plugins pass `channel.config` straight through). A
   Slack channel declared with `config: {delivery_port: 9500}` listens
   on 9500, but the provider was still addressing `:9999`.
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
        chat = Channel(name="hbchat", type=ChannelType.CHAT, platform=_platform())
        assert _heartbeat_delivery_port(chat) == 8080

    def test_panel_delivers_on_main_app_port(self):
        panel = Channel(name="control", type=ChannelType.PANEL, platform=_platform())
        assert _heartbeat_delivery_port(panel) == 8080

    def test_slack_delivers_on_default_sidecar_port_without_config(self):
        slack = Channel(name="ops", type=ChannelType.SLACK, platform=_platform())
        assert _heartbeat_delivery_port(slack) == 9999

    def test_discord_delivers_on_default_sidecar_port_without_config(self):
        discord = Channel(name="ops", type=ChannelType.DISCORD, platform=_platform())
        assert _heartbeat_delivery_port(discord) == 9999

    def test_slack_honors_user_configured_delivery_port(self):
        """Slack's runtime reads `int(self.config.get("delivery_port",
        9999))` from the same `channel.config` dict the user declares —
        so a non-default value must be honored here too, not just the
        9999 fallback."""
        slack = Channel(
            name="ops",
            type=ChannelType.SLACK,
            platform=_platform(),
            config={"delivery_port": 9500},
        )
        assert _heartbeat_delivery_port(slack) == 9500

    def test_chat_ignores_delivery_port_config(self):
        """Chat's plugin always emits `"port": 8080` in the bundled
        config and its runtime never reads `delivery_port` at all — a
        `delivery_port` in `channel.config` (if a user set one, e.g. by
        copy-pasting a Slack channel's config) must not be honored."""
        chat = Channel(
            name="hbchat",
            type=ChannelType.CHAT,
            platform=_platform(),
            config={"delivery_port": 9500},
        )
        assert _heartbeat_delivery_port(chat) == 8080


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

    def test_slack_channel_with_custom_delivery_port(self, provider, mock_docker_client):
        agent = Agent(
            name="hbagent",
            framework="langchain-python",
            default_model=_model(),
            schedules=[ScheduledTask(name="d", cron="0 9 * * 1")],
        )
        slack = Channel(
            name="ops",
            type=ChannelType.SLACK,
            platform=_platform(),
            config={"delivery_port": 9500},
        )

        with (
            patch("vystak_heartbeat.plugin.build_bundle") as mock_build_bundle,
            patch("vystak.provisioning.ProvisionGraph") as MockGraph,
        ):
            MockGraph.return_value = MagicMock()
            provider.apply_scheduler([agent], [slack])

        _, kwargs = mock_build_bundle.call_args
        assert kwargs["channel_addresses"] == {
            slack.canonical_name: "http://vystak-channel-ops:9500",
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
