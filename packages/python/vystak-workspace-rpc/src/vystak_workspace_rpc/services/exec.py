"""exec.* service — process execution with streaming stdout/stderr."""

import asyncio
import shutil
from pathlib import Path

from vystak_workspace_rpc.progress import ProgressEmitter


def register_exec(server, workspace_root: Path,
                  progress_emitter: ProgressEmitter) -> None:
    """Register exec.* handlers. progress_emitter forwards chunks to the
    JSON-RPC client as $/progress notifications."""
    root = Path(workspace_root).resolve()

    async def _stream_subprocess(argv: list[str], cwd: Path,
                                  env: dict | None, timeout_s: float | None) -> dict:
        import time

        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def drain(reader, channel: str):
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                await progress_emitter(channel, {"chunk": chunk.decode("utf-8",
                                                                       errors="replace")})

        drain_stdout = asyncio.create_task(drain(proc.stdout, "stdout"))
        drain_stderr = asyncio.create_task(drain(proc.stderr, "stderr"))

        try:
            if timeout_s is not None:
                await asyncio.wait_for(proc.wait(), timeout=timeout_s)
            else:
                await proc.wait()
        except TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            drain_stdout.cancel()
            drain_stderr.cancel()
            raise TimeoutError(f"Process exceeded timeout {timeout_s}s") from None

        await drain_stdout
        await drain_stderr
        duration_ms = int((time.time() - start) * 1000)
        return {"exit_code": proc.returncode, "duration_ms": duration_ms}

    async def run(params: dict) -> dict:
        cmd = params["cmd"]
        args = params.get("args", [])
        argv = [cmd] + list(args) if isinstance(cmd, str) else list(cmd)

        cwd_str = params.get("cwd", ".")
        cwd = (root / cwd_str).resolve()
        try:
            cwd.relative_to(root)
        except ValueError:
            raise ValueError(f"cwd '{cwd_str}' escapes workspace root") from None

        env = params.get("env")  # None = inherit
        timeout_s = params.get("timeout_s")
        return await _stream_subprocess(argv, cwd, env, timeout_s)

    async def shell(params: dict) -> dict:
        script = params["script"]
        cwd_str = params.get("cwd", ".")
        cwd = (root / cwd_str).resolve()
        try:
            cwd.relative_to(root)
        except ValueError:
            raise ValueError(f"cwd '{cwd_str}' escapes workspace root") from None
        timeout_s = params.get("timeout_s")
        return await _stream_subprocess(["sh", "-c", script], cwd, None, timeout_s)

    async def which(params: dict) -> str | None:
        found = shutil.which(params["name"])
        return found

    server.register("exec.run", run)
    server.register("exec.shell", shell)
    server.register("exec.which", which)
