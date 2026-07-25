"""Shared LangChain message-content flattening.

LangChain's AIMessage(Chunk).content becomes a list of typed blocks instead
of a plain string whenever the underlying provider returns extended-thinking
or tool-use blocks (e.g. Anthropic:
[{"type": "thinking", ...}, {"type": "text", ...}, ...]). Every wire
protocol this runtime speaks — the A2A `Message.parts[*].text` shape and the
OpenAI-compatible `delta`/`text` fields — requires a plain string, so both
paths flatten through this single helper.
"""

from typing import Any


def flatten_content(content: Any) -> str:
    """Flatten LangChain message content into a plain string.

    Anthropic extended-thinking returns content as a list of typed blocks
    [{"type": "thinking", ...}, {"type": "text", ...}, ...]. Both the A2A
    wire and the OpenAI-compatible wire expect a string, so concatenate
    `text` blocks and drop thinking/tool_use.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
            elif isinstance(block, str):
                out.append(block)
        return "".join(out)
    return str(content)
