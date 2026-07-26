"""vystak schedules — manage runtime scheduled tasks via the scheduler API."""

import json
import os

import click
import httpx

DEFAULT_URL = "http://127.0.0.1:9797"


def _client() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("VYSTAK_SCHEDULER_URL", DEFAULT_URL), timeout=10)


def _die(resp: httpx.Response) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    click.echo(f"error: {detail}", err=True)
    raise SystemExit(1)


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Issue a request against the scheduler API.

    Improvement over the task brief: the brief only wires the
    connection-refused catch into ``list``; every subcommand talks to the
    same best-effort local scheduler process, so a stopped scheduler should
    produce the same friendly message everywhere. This shared helper
    centralizes that catch for all six subcommands.
    """
    try:
        with _client() as c:
            return c.request(method, path, **kwargs)
    except httpx.ConnectError:
        click.echo(
            "scheduler is not running — is anything deployed with schedules?",
            err=True,
        )
        raise SystemExit(1) from None


@click.group()
def schedules():
    """Manage scheduled tasks (declarative tasks are read-only here)."""


@schedules.command("list")
@click.option("--agent", default=None)
@click.option("--all", "show_all", is_flag=True, help="Include completed/missed/cancelled.")
def list_cmd(agent, show_all):
    resp = _request("GET", "/tasks", params={k: v for k, v in {"agent": agent}.items() if v})
    if resp.status_code != 200:
        _die(resp)
    rows = resp.json()["tasks"]
    if not show_all:
        rows = [r for r in rows if r["status"] == "active"]
    for r in rows:
        shape = r["task"].get("cron") or r["task"].get("at") or r["task"].get("every")
        click.echo(
            f"{r['id'][:8]}  {r['agent']:<30} {r['name']:<20} "
            f"{r['source']:<11} {r['status']:<9} {shape}  "
            f"next={r['next_fire_at'] or '-'}"
        )


@schedules.command("add")
@click.option("--agent", required=True, help="Agent canonical_name.")
@click.option("--name", required=True)
@click.option("--cron", default=None)
@click.option("--at", "at_", default=None, help="ISO-8601 one-shot time.")
@click.option("--every", default=None, help="e.g. 30s, 20m, 2h, 1d.")
@click.option("--timezone", default="UTC")
@click.option("--prompt", default=None)
@click.option("--channel", "target_channel", default=None)
@click.option("--thread", "target_thread", default=None)
def add_cmd(agent, name, cron, at_, every, timezone, prompt, target_channel, target_thread):
    body = {
        "agent": agent,
        "name": name,
        "cron": cron,
        "at": at_,
        "every": every,
        "timezone": timezone,
        "prompt": prompt,
        "target_channel": target_channel,
        "target_thread": target_thread,
        "created_by": "cli",
    }
    body = {k: v for k, v in body.items() if v is not None}
    resp = _request("POST", "/tasks", json=body)
    if resp.status_code != 201:
        _die(resp)
    click.echo(resp.json()["id"])


@schedules.command("show")
@click.argument("task_id")
def show_cmd(task_id):
    resp = _request("GET", f"/tasks/{task_id}")
    if resp.status_code != 200:
        _die(resp)
    click.echo(json.dumps(resp.json(), indent=2))


def _patch(task_id: str, payload: dict) -> None:
    resp = _request("PATCH", f"/tasks/{task_id}", json=payload)
    if resp.status_code != 200:
        _die(resp)
    click.echo("ok")


@schedules.command("pause")
@click.argument("task_id")
def pause_cmd(task_id):
    _patch(task_id, {"enabled": False})


@schedules.command("resume")
@click.argument("task_id")
def resume_cmd(task_id):
    _patch(task_id, {"enabled": True})


@schedules.command("remove")
@click.argument("task_id")
def remove_cmd(task_id):
    resp = _request("DELETE", f"/tasks/{task_id}")
    if resp.status_code != 204:
        _die(resp)
    click.echo("removed")
