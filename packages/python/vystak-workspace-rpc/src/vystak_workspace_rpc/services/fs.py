"""fs.* service — file operations rooted at the workspace directory.

All paths are resolved relative to the workspace root. Attempts to
escape via `..` or absolute paths outside the root raise ValueError.
"""

import difflib
import shutil
from pathlib import Path


def register_fs(server, workspace_root: Path) -> None:
    """Register fs.* handlers on the given JsonRpcServer."""
    root = Path(workspace_root).resolve()

    def _resolve(path: str) -> Path:
        p = (root / path).resolve()
        try:
            p.relative_to(root)
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves outside workspace root {root}"
            ) from None
        return p

    async def read_file(params: dict) -> str:
        encoding = params.get("encoding", "utf-8")
        return _resolve(params["path"]).read_text(encoding=encoding)

    async def write_file(params: dict) -> None:
        p = _resolve(params["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        encoding = params.get("encoding", "utf-8")
        p.write_text(params["content"], encoding=encoding)
        if "mode" in params:
            p.chmod(int(params["mode"], 8) if isinstance(params["mode"], str)
                    else params["mode"])
        return None

    async def append_file(params: dict) -> None:
        p = _resolve(params["path"])
        encoding = params.get("encoding", "utf-8")
        with p.open("a", encoding=encoding) as fh:
            fh.write(params["content"])
        return None

    async def delete_file(params: dict) -> None:
        p = _resolve(params["path"])
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return None

    async def list_dir(params: dict) -> list[dict]:
        p = _resolve(params["path"])
        entries = []
        for entry in sorted(p.iterdir()):
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
        return entries

    async def stat(params: dict) -> dict:
        p = _resolve(params["path"])
        s = p.stat()
        return {
            "type": "directory" if p.is_dir() else "file",
            "size": s.st_size,
            "mtime": s.st_mtime,
            "permissions": oct(s.st_mode & 0o777),
        }

    async def exists(params: dict) -> bool:
        try:
            return _resolve(params["path"]).exists()
        except ValueError:
            return False

    async def mkdir(params: dict) -> None:
        p = _resolve(params["path"])
        p.mkdir(parents=bool(params.get("parents", False)), exist_ok=True)
        return None

    async def move(params: dict) -> None:
        src = _resolve(params["src"])
        dst = _resolve(params["dst"])
        shutil.move(str(src), str(dst))
        return None

    async def edit(params: dict) -> dict:
        p = _resolve(params["path"])
        old = params["old_str"]
        new = params["new_str"]
        content = p.read_text()
        if old not in content:
            raise ValueError(f"old_str not found in {params['path']}")
        updated = content.replace(old, new, 1)  # one replacement by default
        p.write_text(updated)
        diff = "\n".join(difflib.unified_diff(
            content.splitlines(), updated.splitlines(),
            fromfile=params["path"], tofile=params["path"], lineterm="",
        ))
        return {"diff": diff}

    server.register("fs.readFile", read_file)
    server.register("fs.writeFile", write_file)
    server.register("fs.appendFile", append_file)
    server.register("fs.deleteFile", delete_file)
    server.register("fs.listDir", list_dir)
    server.register("fs.stat", stat)
    server.register("fs.exists", exists)
    server.register("fs.mkdir", mkdir)
    server.register("fs.move", move)
    server.register("fs.edit", edit)
