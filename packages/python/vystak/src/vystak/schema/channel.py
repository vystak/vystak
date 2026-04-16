"""Channel model — I/O adapter for agent communication."""

from vystak.schema.common import ChannelType, NamedModel


class Channel(NamedModel):
    """An I/O adapter that connects users to an agent."""

    type: ChannelType
    config: dict = {}


from vystak.schema.gateway import ChannelProvider


class SlackChannel(NamedModel):
    """A Slack channel binding — routes Slack events to an agent."""

    provider: ChannelProvider
    channels: list[str] = []
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True
