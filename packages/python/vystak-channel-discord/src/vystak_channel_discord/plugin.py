"""DiscordChannelPlugin — build-time codegen (configs + Dockerfile only)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, GeneratedCode
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

from vystak_channel_discord.server_template import DOCKERFILE, REQUIREMENTS

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class DiscordChannelConfig(BaseModel):
    """Optional config for a Discord channel."""

    port: int = 8080
    application_id: str | None = None
    register_slash_commands: bool = True


class DiscordChannelPlugin(ChannelPlugin):
    """Discord channel — gateway runner, one container per declaration."""

    type = ChannelType.DISCORD
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = DiscordChannelConfig

    def generate_code(
        self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
    ) -> GeneratedCode:
        from vystak_channel_runtime import channel_package_version, runtime_version

        channel.channel_package_version = channel_package_version("vystak-channel-discord")
        channel.channel_runtime_version = runtime_version()

        agent_names = [a.name for a in channel.agents]
        default_agent_name = (
            channel.default_agent.name if channel.default_agent else None
        )
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

        state_cfg: dict | None = None
        if channel.state is not None:
            state_cfg = channel.state.model_dump(exclude_none=True)

        # Discord defaults to streaming so the typing indicator auto-refreshes
        # for the whole turn duration. Override with `config: {agent_protocol:
        # a2a-turn}` for one-shot mode.
        agent_protocol = channel.config.get("agent_protocol", "a2a-stream")
        channel_config: dict = {
            "channel_type": "discord",
            "agent_protocol": agent_protocol,
            "agents": agent_names,
            "default_agent": default_agent_name,
            "group_policy": (
                channel.group_policy.value
                if hasattr(channel.group_policy, "value") else channel.group_policy
            ),
            "dm_policy": (
                channel.dm_policy.value
                if hasattr(channel.dm_policy, "value") else channel.dm_policy
            ),
            "allow_from": list(channel.allow_from),
            "allow_bots": channel.allow_bots,
            "channel_overrides": channel_overrides,
            "route_authority": channel.route_authority,
            "welcome_on_invite": channel.welcome_on_invite,
            "welcome_message": channel.welcome_message,
            "thread": {
                "history_scope": channel.thread.history_scope,
                "initial_history_limit": channel.thread.initial_history_limit,
                "inherit_parent": channel.thread.inherit_parent,
                "require_explicit_mention": channel.thread.require_explicit_mention,
            },
            "register_slash_commands": bool(
                channel.config.get("register_slash_commands", True)
            ),
            "port": int(channel.config.get("port", 8080)),
            "application_id": channel.config.get("application_id"),
            "state": state_cfg,
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

        from vystak_channel_runtime.heartbeat import (
            enrich_routes_with_heartbeat,
        )
        enriched_routes = enrich_routes_with_heartbeat(channel, resolved_routes)

        return GeneratedCode(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(enriched_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_discord",
        )

    def provision_nodes(
        self, channel: Channel, platform: Platform
    ) -> list[Provisionable]:
        return []

    def thread_name(self, event: dict) -> str:
        guild = event.get("guild_id") or "dm"
        channel_id = event.get("channel_id") or "0"
        thread = event.get("thread_id") or event.get("message_id") or "root"
        return f"thread:discord:{guild}:{channel_id}:{thread}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
