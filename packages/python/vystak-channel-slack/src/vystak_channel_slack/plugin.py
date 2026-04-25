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
        self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
    ) -> GeneratedCode:
        # Build channel_config.json — shape consumed by server.py at runtime.
        agent_names = [a.name for a in channel.agents]
        default_agent_name = channel.default_agent.name if channel.default_agent else None

        # Per-channel-id overrides (string → override config dict).
        channel_overrides: dict[str, dict] = {}
        for ch_id, ov in channel.channel_overrides.items():
            channel_overrides[ch_id] = {
                "agent": ov.agent.name if ov.agent else None,
                "system_prompt": ov.system_prompt,
                "tools": ov.tools,
                "skills": ov.skills,
                "users": ov.users,
                "require_mention": ov.require_mention,
            }

        # State service config — serialised as {"type": "sqlite", "path": "..."}
        # so the runtime can reconstruct via Service(**config["state"]).
        state_cfg: dict | None = None
        if channel.state is not None:
            state_cfg = channel.state.model_dump(exclude_none=True)

        channel_config = {
            "agents": agent_names,
            "group_policy": channel.group_policy.value
            if hasattr(channel.group_policy, "value")
            else channel.group_policy,
            "dm_policy": channel.dm_policy.value
            if hasattr(channel.dm_policy, "value")
            else channel.dm_policy,
            "allow_from": list(channel.allow_from),
            "allow_bots": channel.allow_bots,
            "channel_overrides": channel_overrides,
            "default_agent": default_agent_name,
            "route_authority": channel.route_authority,
            "welcome_on_invite": channel.welcome_on_invite,
            "welcome_message": channel.welcome_message,
            "reply_to_mode": channel.reply_to_mode,
            "thread_require_explicit_mention": channel.thread_require_explicit_mention,
            "state": state_cfg,
        }

        return GeneratedCode(
            files={
                "server.py": SERVER_PY,
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "routes.json": json.dumps(resolved_routes, indent=2),
                "channel_config.json": json.dumps(channel_config, indent=2),
            },
            entrypoint="server.py",
        )

    def provision_nodes(self, channel: Channel, platform: Platform) -> list[Provisionable]:
        # Platform provider wraps GeneratedCode in its native container node.
        return []

    def thread_name(self, event: dict) -> str:
        channel = event.get("channel") or "dm"
        thread = event.get("thread_ts") or event.get("ts") or "root"
        return f"thread:slack:{channel}:{thread}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
