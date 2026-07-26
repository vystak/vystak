"""Agent-side scheduling tools — thin client of the platform scheduler API.

Follows the workspace/subagents/mcp builder pattern: returns [] when the
deploy didn't wire scheduling (env unset), and tools return error strings
rather than raising so the LLM turn survives a scheduler outage.

`CURRENT_TURN_METADATA` is the single source of truth for "where did this
turn originate" — the a2a executor sets it from the incoming message's
metadata at the top of `execute()`, before running the graph, so any tool
call made during that turn can read it. `schedule_task(deliver_here=True)`
reads `channel_canonical`/`thread_id` from it to target scheduled-task
results back at the conversation that asked for them.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

import httpx
from langchain_core.tools import tool

CURRENT_TURN_METADATA: ContextVar[dict | None] = ContextVar(
    "vystak_turn_metadata", default=None
)


def build_schedule_tools(agent: Any) -> list[Any]:
    base_url = os.environ.get("VYSTAK_SCHEDULER_URL")
    canonical = os.environ.get("VYSTAK_AGENT_CANONICAL")
    if not base_url or not canonical:
        return []

    def _client() -> httpx.Client:
        return httpx.Client(base_url=base_url, timeout=10)

    @tool
    def schedule_task(
        name: str,
        cron: str | None = None,
        at: str | None = None,
        every: str | None = None,
        prompt: str | None = None,
        timezone: str = "UTC",
        deliver_here: bool = True,
    ) -> str:
        """Create a scheduled task for yourself. Exactly one of cron (5-field
        cron), at (ISO-8601 one-shot), or every ('30s'/'20m'/'2h'/'1d') must be
        set. `prompt` is what you will be asked when it fires. With
        deliver_here=True your reply is delivered back to this conversation."""
        body: dict = {
            "agent": canonical,
            "name": name,
            "timezone": timezone,
            "created_by": f"agent:{canonical}",
        }
        for k, v in (
            ("cron", cron), ("at", at), ("every", every), ("prompt", prompt),
        ):
            if v is not None:
                body[k] = v
        note = ""
        if deliver_here:
            meta = CURRENT_TURN_METADATA.get() or {}
            if meta.get("channel_canonical") and meta.get("thread_id"):
                body["target_channel"] = meta["channel_canonical"]
                body["target_thread"] = meta["thread_id"]
            else:
                note = (
                    " (no originating channel/thread known — results will "
                    "be logged, not delivered)"
                )
        try:
            with _client() as c:
                resp = c.post("/tasks", json=body)
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        if resp.status_code != 201:
            return f"failed ({resp.status_code}): {resp.text}"
        return f"scheduled task {resp.json()['id']}{note}"

    @tool
    def list_scheduled_tasks() -> str:
        """List your own scheduled tasks (active and past)."""
        try:
            with _client() as c:
                resp = c.get("/tasks", params={"agent": canonical})
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        rows = resp.json().get("tasks", [])
        if not rows:
            return "no scheduled tasks"
        return "\n".join(
            f"{r['id']} {r['name']} [{r['status']}] "
            f"{r['task'].get('cron') or r['task'].get('at') or r['task'].get('every')} "
            f"next={r['next_fire_at'] or '-'}"
            for r in rows
        )

    @tool
    def cancel_scheduled_task(task_id: str) -> str:
        """Cancel one of your scheduled tasks by id."""
        try:
            with _client() as c:
                got = c.get(f"/tasks/{task_id}")
                if got.status_code == 200 and got.json()["agent"] != canonical:
                    return "not your task"
                resp = c.delete(f"/tasks/{task_id}")
        except httpx.HTTPError as e:
            return f"scheduler unreachable: {e}"
        if resp.status_code != 204:
            return f"failed ({resp.status_code}): {resp.text}"
        return "cancelled"

    return [schedule_task, list_scheduled_tasks, cancel_scheduled_task]
