"""Abstract base class for channel provider runners."""

from abc import ABC, abstractmethod


class ChannelProviderRunner(ABC):
    """Manages a bot connection and dispatches events to the router."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...
