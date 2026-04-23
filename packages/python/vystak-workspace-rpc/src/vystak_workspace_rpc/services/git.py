"""git.* service — thin wrapper over the git CLI."""

import asyncio
from pathlib import Path


def register_git(server, workspace_root: Path) -> None:
    root = Path(workspace_root).resolve()

    async def _git(args: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

    async def _ensure_repo() -> None:
        code, _, _ = await _git(["rev-parse", "--is-inside-work-tree"])
        if code != 0:
            raise RuntimeError(f"{root} is not a git repo")

    async def status(params: dict) -> dict:
        await _ensure_repo()
        code, branch_out, _ = await _git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_out.strip() if code == 0 else "HEAD"

        code, out, _ = await _git(["status", "--porcelain"])
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []
        for line in out.splitlines():
            if not line:
                continue
            xy, _, path = line.partition(" ")
            # porcelain format: XY path, where X = staged state, Y = unstaged
            x = line[0]
            y = line[1]
            path = line[3:].strip()
            if x == "?" and y == "?":
                untracked.append(path)
            else:
                if x != " ":
                    staged.append(path)
                if y != " ":
                    unstaged.append(path)
        return {
            "branch": branch,
            "dirty": bool(staged or unstaged or untracked),
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }

    async def log(params: dict) -> list[dict]:
        await _ensure_repo()
        limit = params.get("limit", 10)
        path = params.get("path")
        args = ["log", f"-{limit}", "--pretty=format:%H%x00%an%x00%ad%x00%s",
                "--date=iso"]
        if path:
            args += ["--", path]
        code, out, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git log failed: {err}")
        result = []
        for line in out.splitlines():
            if not line:
                continue
            parts = line.split("\x00")
            if len(parts) < 4:
                continue
            result.append({
                "sha": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
        return result

    async def diff(params: dict) -> str:
        await _ensure_repo()
        args = ["diff"]
        if params.get("staged"):
            args.append("--cached")
        if params.get("path"):
            args += ["--", params["path"]]
        code, out, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git diff failed: {err}")
        return out

    async def add(params: dict) -> None:
        await _ensure_repo()
        paths = params.get("paths", [])
        code, _, err = await _git(["add", *paths])
        if code != 0:
            raise RuntimeError(f"git add failed: {err}")
        return None

    async def commit(params: dict) -> dict:
        await _ensure_repo()
        args = ["commit", "-m", params["message"]]
        if params.get("author"):
            args += ["--author", params["author"]]
        code, _, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git commit failed: {err}")
        code, sha, _ = await _git(["rev-parse", "HEAD"])
        return {"sha": sha.strip()}

    async def branch(params: dict) -> str:
        await _ensure_repo()
        code, out, err = await _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            raise RuntimeError(f"git branch failed: {err}")
        return out.strip()

    server.register("git.status", status)
    server.register("git.log", log)
    server.register("git.diff", diff)
    server.register("git.add", add)
    server.register("git.commit", commit)
    server.register("git.branch", branch)
