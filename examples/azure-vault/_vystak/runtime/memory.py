"""MemoryManager — long-term memory recall and save/forget sentinel handling."""

import uuid
from typing import Any

SAVE_SENTINEL = "__SAVE_MEMORY__|"
FORGET_SENTINEL = "__FORGET_MEMORY__|"


class MemoryManager:
    def __init__(self, agent: Any, store: Any) -> None:
        self.agent = agent
        self.store = store

    async def recall(
        self,
        *,
        user_id: str,
        query: str = "",
        project_id: str = "default",
    ) -> list[str]:
        scopes = [
            ("user", user_id),
            ("project", project_id),
            ("global", "global"),
        ]
        out: list[str] = []
        for ns in scopes:
            results = await self.store.asearch(ns, query)
            for r in results:
                content = r.value.get("content") if isinstance(r.value, dict) else str(r.value)
                out.append(f"[{ns[0]}/{r.key}] {content}")
        return out

    async def handle_tool_output(
        self,
        output: str,
        *,
        user_id: str,
        project_id: str = "default",
    ) -> bool:
        if output.startswith(SAVE_SENTINEL):
            _, scope, content = output.split("|", 2)
            ns = self._namespace_for(scope, user_id=user_id, project_id=project_id)
            await self.store.aput(ns, str(uuid.uuid4()), {"content": content})
            return True
        if output.startswith(FORGET_SENTINEL):
            memory_id = output[len(FORGET_SENTINEL):]
            for scope in ("user", "project", "global"):
                ns = self._namespace_for(scope, user_id=user_id, project_id=project_id)
                await self.store.adelete(ns, memory_id)
            return True
        return False

    @staticmethod
    def _namespace_for(scope: str, *, user_id: str, project_id: str) -> tuple[str, str]:
        if scope == "user":
            return ("user", user_id)
        if scope == "project":
            return ("project", project_id)
        return ("global", "global")
