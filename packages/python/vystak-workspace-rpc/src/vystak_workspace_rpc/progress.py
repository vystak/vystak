"""Progress notification helper for streaming responses.

Handlers receive a progress_emitter callable they invoke with a channel
name (e.g. 'stdout') and a data dict. The framework forwards these as
JSON-RPC $/progress notifications back to the client.
"""

from collections.abc import Awaitable, Callable

ProgressEmitter = Callable[[str, dict], Awaitable[None]]
