"""Build an a2a-sdk AgentCard from a vystak Agent.

The SDK's AgentCard (protobuf) is the authoritative shape, but this template
serves a card that ALSO carries v0.3 compat fields (`url`, `preferredTransport`,
`protocolVersion`) at the top level — required by older clients (vystak-channel-runtime,
vystak-chat) that read `card['url']` instead of `card['supportedInterfaces'][0].url`.

The compat fields are only emitted by `agent_card_to_dict` when at least one
interface declares a legacy protocol version (>=0.3 and <1.0), so we tag the
single JSON-RPC interface with `0.3.0`.
"""

from typing import Any

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill


def build_agent_card(agent: Any, base_url: str) -> AgentCard:
    """Build an AgentCard advertising one JSON-RPC interface at base_url + /a2a."""
    rpc_url = base_url.rstrip("/") + "/a2a"
    return AgentCard(
        name=agent.name,
        description=(agent.instructions or "").strip(),
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id=s.name,
                name=s.name,
                description=getattr(s, "description", "") or "",
                tags=[],
            )
            for s in agent.skills
        ],
        supported_interfaces=[
            AgentInterface(
                url=rpc_url,
                protocol_binding="JSONRPC",
                # 0.3.0 lets agent_card_to_dict emit the legacy
                # `url`/`preferredTransport`/`protocolVersion` fields that
                # vystak-channel-runtime + vystak-chat depend on.
                protocol_version="0.3.0",
            )
        ],
    )
