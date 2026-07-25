"""PanelChannelPlugin — control-panel API channel."""

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, FileBundle
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class PanelChannelConfig(BaseModel):
    """Optional config for a panel channel."""

    port: int = 8100
    db_path: str = "/data/panel.db"


class PanelChannelPlugin(ChannelPlugin):
    """Control-panel API channel.

    One FastAPI container that owns the panel DB (users, projects,
    conversations, messages) and exposes a REST + SSE API consumed by the
    vystak-panel Next.js app. Talks to agents via their OpenAI Responses API.
    """

    type = ChannelType.PANEL
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = PanelChannelConfig

    def build_bundle(
        self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
    ) -> FileBundle:
        from vystak_channel_runtime import channel_package_version, runtime_version

        from vystak_channel_panel.server_template import DOCKERFILE, REQUIREMENTS

        channel.channel_package_version = channel_package_version("vystak-channel-panel")
        channel.channel_runtime_version = runtime_version()

        channel_config = {
            "channel_type": "panel",
            "agent_protocol": "a2a-turn",
            "agents": [a.name for a in channel.agents],
            "default_agent": channel.default_agent.name if channel.default_agent else None,
            "port": 8080,
            "db_path": channel.config.get("db_path", "/data/panel.db"),
            "state": (
                channel.state.model_dump(exclude_none=True)
                if channel.state is not None else None
            ),
            "canonical_name": channel.canonical_name,
            "channel_package_version": channel.channel_package_version,
            "channel_runtime_version": channel.channel_runtime_version,
            "delivery_port": int(channel.config.get("delivery_port", 9999)),
            "transport_type": (
                channel.platform.transport.type
                if channel.platform and getattr(channel.platform, "transport", None)
                else "http"
            ),
        }
        return FileBundle(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(resolved_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_panel",
        )

    def provision_nodes(self, channel: Channel, platform: Platform) -> list["Provisionable"]:
        # The Docker provider's apply_channel builds the DockerChannelNode.
        return []

    def thread_name(self, event: dict) -> str:
        return f"thread:panel:{event.get('conversation_id', 'unknown')}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
