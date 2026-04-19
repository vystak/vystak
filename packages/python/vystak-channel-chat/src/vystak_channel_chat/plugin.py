"""ChatChannelPlugin — OpenAI-compatible unified chat endpoint."""

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, GeneratedCode
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

from vystak_channel_chat.server_template import DOCKERFILE, REQUIREMENTS, SERVER_PY

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class ChatChannelConfig(BaseModel):
    """Optional config for a chat channel."""

    port: int = 8080


class ChatChannelPlugin(ChannelPlugin):
    """OpenAI-compatible unified chat endpoint.

    Spins up a single FastAPI container that exposes /v1/chat/completions
    and routes to agents by name (model="vystak/<agent-name>").
    """

    type = ChannelType.CHAT
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = ChatChannelConfig

    def generate_code(
        self, channel: Channel, resolved_routes: dict[str, str]
    ) -> GeneratedCode:
        routes_json = json.dumps(resolved_routes, indent=2)
        return GeneratedCode(
            files={
                "server.py": SERVER_PY,
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "routes.json": routes_json,
            },
            entrypoint="server.py",
        )

    def provision_nodes(
        self, channel: Channel, platform: Platform
    ) -> list["Provisionable"]:
        # Platform provider builds the actual DockerChannelNode from GeneratedCode.
        # Returning empty here keeps the plugin platform-agnostic; the Docker
        # provider's apply_channel wires things up.
        return []

    def thread_name(self, event: dict) -> str:
        session = event.get("session_id") or event.get("id") or "unknown"
        return f"thread:chat:{event.get('channel', 'default')}:{session}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
