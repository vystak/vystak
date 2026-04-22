"""Project search tool — uses ripgrep inside the workspace."""

import subprocess


def search_project(pattern: str, max_results: int = 50) -> list[str]:
    """Search for pattern in /workspace/ using ripgrep. Returns matching file paths."""
    result = subprocess.run(
        ["rg", "--files-with-matches", pattern, "/workspace/"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"rg failed: {result.stderr}")
    paths = [line for line in result.stdout.splitlines() if line]
    return paths[:max_results]
