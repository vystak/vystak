"""Tool-output disk offload — large outputs go to a file, prompt sees a stub.

Pattern from Factory.ai / LangChain Deep Agents (2025-2026): keep dense
artifacts on disk; let the agent fetch slices via `read_offloaded`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OffloadConfig:
    root: Path
    threshold_bytes: int


@dataclass(frozen=True)
class OffloadResult:
    path: Path
    collapsed: str


def offload_tool_output(
    cfg: OffloadConfig,
    *,
    thread_id: str,
    tool_call_id: str,
    tool_name: str,
    content: str,
) -> OffloadResult | None:
    """Write content to disk and return a collapsed preview, or None if small."""
    if len(content.encode("utf-8")) <= cfg.threshold_bytes:
        return None
    dir_ = cfg.root / thread_id
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{tool_call_id}.txt"
    path.write_text(content)
    first_line = content.split("\n", 1)[0][:80]
    bytes_len = len(content.encode("utf-8"))
    collapsed = (
        f"[{tool_name}] OK ({bytes_len} bytes) | preview: {first_line}\n  → {path}"
    )
    return OffloadResult(path=path, collapsed=collapsed)


def read_offloaded_impl(
    path: str, *, offset: int = 0, length: int = 4000, root: Path | None = None,
) -> str:
    """Read a slice from an offloaded file. Path must live inside `root`."""
    p = Path(path).resolve()
    if root is not None:
        root_resolved = root.resolve()
        if not str(p).startswith(str(root_resolved)):
            raise ValueError(f"path {p} outside offload root {root_resolved}")
    with p.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        return fh.read(length)
