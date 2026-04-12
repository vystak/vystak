"""Channel model — I/O adapter for agent communication."""

from agentstack.schema.common import ChannelType, NamedModel


class Channel(NamedModel):
    """An I/O adapter that connects users to an agent."""

    type: ChannelType
    config: dict = {}
