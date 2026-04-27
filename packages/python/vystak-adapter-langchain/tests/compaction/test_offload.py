import pytest
from vystak_adapter_langchain.compaction.offload import (
    OffloadConfig,
    offload_tool_output,
    read_offloaded_impl,
)


def test_offload_returns_path_and_preview(tmp_path):
    cfg = OffloadConfig(root=tmp_path, threshold_bytes=100)
    result = offload_tool_output(
        cfg, thread_id="t1", tool_call_id="tc1", tool_name="read_file",
        content="x" * 5000,
    )
    assert result.path.exists()
    assert result.collapsed.startswith("[read_file] OK (")
    assert " bytes)" in result.collapsed
    assert "→ " in result.collapsed


def test_offload_skips_below_threshold(tmp_path):
    cfg = OffloadConfig(root=tmp_path, threshold_bytes=10_000)
    result = offload_tool_output(
        cfg, thread_id="t1", tool_call_id="tc1", tool_name="read_file",
        content="small",
    )
    assert result is None


def test_read_offloaded_returns_slice(tmp_path):
    target = tmp_path / "t1" / "tc1.txt"
    target.parent.mkdir(parents=True)
    target.write_text("0123456789" * 100)
    out = read_offloaded_impl(str(target), offset=10, length=5)
    assert out == "01234"


def test_read_offloaded_path_traversal_rejected(tmp_path):
    cfg = OffloadConfig(root=tmp_path, threshold_bytes=10)
    with pytest.raises(ValueError, match="path"):
        read_offloaded_impl("/etc/passwd", root=cfg.root)
