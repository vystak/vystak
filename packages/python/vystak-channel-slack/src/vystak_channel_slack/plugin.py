"""SlackChannelPlugin — Socket Mode runner routing Slack events to agents."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, GeneratedCode
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

from vystak_channel_slack.server_template import DOCKERFILE, REQUIREMENTS, SERVER_PY

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class SlackChannelConfig(BaseModel):
    """Optional config for a Slack channel."""

    port: int = 8080


class SlackChannelPlugin(ChannelPlugin):
    """Slack Socket Mode channel — one container per declaration, N routes."""

    type = ChannelType.SLACK
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = SlackChannelConfig

    def generate_code(
        self, channel: Channel, resolved_routes: dict[str, str]
    ) -> GeneratedCode:
        rules = [
            {"match": rule.match, "agent": rule.agent}
            for rule in channel.routes
        ]
        return GeneratedCode(
            files={
                "server.py": SERVER_PY,
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "routes.json": json.dumps(resolved_routes, indent=2),
                "rules.json": json.dumps(rules, indent=2),
            },
            entrypoint="server.py",
        )

    def provision_nodes(
        self, channel: Channel, platform: Platform
    ) -> list[Provisionable]:
        # Platform provider wraps GeneratedCode in its native container node.
        return []

    def thread_name(self, event: dict) -> str:
        channel = event.get("channel") or "dm"
        thread = event.get("thread_ts") or event.get("ts") or "root"
        return f"thread:slack:{channel}:{thread}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
