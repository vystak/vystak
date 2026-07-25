# Vystak Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web control panel for deployed Vystak agents: a Python `panel` channel (API + DB + streaming, system of record) plus a separate Next.js app (Google auth, Vercel AI SDK chat UI).

**Architecture:** `vystak-channel-panel` is a real `ChannelPlugin` + `ChannelRuntime` (FastAPI) deployed via `vystak.yaml`; it owns users/projects/conversations/messages in SQLite and streams agent replies over plain SSE by calling each agent's OpenAI Responses API (`/v1/responses`, `previous_response_id` continuity). `packages/typescript/vystak-panel` is a Next.js 15 app (NOT a channel) using Auth.js (Google) and AI SDK v5 `useChat`; its server routes call the channel with a service token + `X-Panel-User` header and adapt the channel SSE into the AI SDK UI message stream.

**Tech Stack:** Python 3.11+ / FastAPI / httpx / aiosqlite; Next.js ^15, React ^19, `ai` ^5, `@ai-sdk/react` ^2, `next-auth` 5 beta, vitest.

**Spec:** `docs/superpowers/specs/2026-07-24-control-panel-design.md`. Two deliberate deviations (flag at review): (1) panel DB is hand-rolled aiosqlite (matching `vystak_channel_runtime/store.py` convention), not SQLAlchemy; Postgres backend deferred past v1. (2) Messages store plain text `content`, not AI-SDK parts JSON — agent output is text.

## Global Constraints

- Python ≥3.11; run `uv sync` after creating the new package (workspace glob `packages/python/*` picks it up).
- The four live CI gates must stay green: `just lint-python`, `just typecheck-typescript`, `just test-python`, `just test-typescript` (= `just ci-live`).
- **No source codegen** — the plugin emits only build artifacts (Dockerfile, requirements, JSON config); runnable code is the package itself, bundled by `DockerChannelNode`.
- `just typecheck-typescript` runs `pnpm -r run build` first — therefore `vystak-panel` must NOT have a `build` script (use `build:app` for real builds), or CI would run `next build` on every typecheck.
- `vystak-panel` package.json must have `"private": true` — release.yml runs `pnpm -r publish`.
- Secrets hygiene (public repo): tests use obvious fakes (`test-token`, `xoxb-test` style); examples use placeholders (`your-google-client-id`).
- Emails are normalized lowercase everywhere (store + API).
- Service auth on every channel API call: `Authorization: Bearer <PANEL_SERVICE_TOKEN>` (env) + `X-Panel-User: <email>` (acting user).
- Commit after every task (messages given per task).

---

### Task 1: `ChannelType.PANEL` + package skeleton + plugin

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/common.py:20-28` (ChannelType enum)
- Create: `packages/python/vystak-channel-panel/pyproject.toml`
- Create: `packages/python/vystak-channel-panel/README.md`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/__init__.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/plugin.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/server_template.py`
- Test: `packages/python/vystak-channel-panel/tests/test_plugin.py`

**Interfaces:**
- Consumes: `ChannelPlugin`, `FileBundle` from `vystak.providers.base`; `Channel`, `ChannelType`.
- Produces: `ChannelType.PANEL`; `PanelChannelPlugin` (registered on import); `DEFAULT_DB_PATH = "/data/panel.db"`; `PanelChannelConfig(port: int = 8080, db_path: str = DEFAULT_DB_PATH)`; bundle files `Dockerfile`, `requirements.txt`, `channel_config.json`, `routes.json`; entrypoint `python -m vystak_channel_panel`.

- [ ] **Step 1: Add enum member**

In `packages/python/vystak/src/vystak/schema/common.py`, inside `ChannelType`, after `CHAT = "chat"` add:

```python
    PANEL = "panel"
```

- [ ] **Step 2: Write the failing test**

`packages/python/vystak-channel-panel/tests/test_plugin.py` (mirrors `vystak-channel-chat/tests/test_plugin.py`):

```python
"""Tests for the PanelChannelPlugin — unit-level, no Docker required."""

import json

from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_channel_panel import PanelChannelPlugin


def _platform():
    docker = Provider(name="docker", type="docker")
    return Platform(name="local", type="docker", provider=docker)


def _channel(**overrides):
    base = {
        "name": "panel",
        "type": ChannelType.PANEL,
        "platform": _platform(),
    }
    base.update(overrides)
    return Channel(**base)


class TestPanelChannelPlugin:
    def test_plugin_metadata(self):
        plugin = PanelChannelPlugin()
        assert plugin.type == ChannelType.PANEL
        assert plugin.default_runtime_mode == RuntimeMode.SHARED
        assert plugin.agent_protocol == AgentProtocol.A2A_TURN

    def test_build_bundle_emits_expected_files(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        assert code.entrypoint == "python -m vystak_channel_panel"
        assert set(code.files.keys()) == {
            "Dockerfile",
            "requirements.txt",
            "channel_config.json",
            "routes.json",
        }

    def test_routes_baked_into_routes_json(self):
        resolved = {
            "weather-agent": {
                "canonical": "weather-agent.agents.default",
                "address": "http://vystak-weather-agent:8000/a2a",
            },
        }
        code = PanelChannelPlugin().build_bundle(_channel(), resolved)
        assert json.loads(code.files["routes.json"]) == resolved

    def test_channel_config_shape(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        cfg = json.loads(code.files["channel_config.json"])
        assert cfg["channel_type"] == "panel"
        assert cfg["agent_protocol"] == "a2a-turn"
        assert cfg["port"] == 8080
        assert cfg["db_path"] == "/data/panel.db"
        assert cfg["canonical_name"] == "panel.channels.default"
        assert "channel_package_version" in cfg
        assert "channel_runtime_version" in cfg

    def test_db_path_override(self):
        ch = _channel(config={"db_path": "/tmp/x.db"})
        cfg = json.loads(
            PanelChannelPlugin().build_bundle(ch, {}).files["channel_config.json"]
        )
        assert cfg["db_path"] == "/tmp/x.db"

    def test_plugin_emits_no_python_source(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        for path in code.files:
            assert not path.endswith(".py"), f"unexpected python source: {path}"

    def test_dockerfile_uses_python_311(self):
        code = PanelChannelPlugin().build_bundle(_channel(), {})
        assert "FROM python:3.11-slim" in code.files["Dockerfile"]

    def test_thread_name_format(self):
        name = PanelChannelPlugin().thread_name({"conversation_id": "abc"})
        assert name == "thread:panel:abc"


class TestAutoRegistration:
    def test_plugin_registered_on_import(self):
        from vystak.channels import get_plugin

        plugin = get_plugin(ChannelType.PANEL)
        assert isinstance(plugin, PanelChannelPlugin)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_plugin.py -v`
Expected: FAIL (collection error — package does not exist yet). If pytest can't even collect because the dir has no package, that counts as the failing state.

- [ ] **Step 4: Create the package**

`packages/python/vystak-channel-panel/pyproject.toml` (mirror of chat's):

```toml
[project]
name = "vystak-channel-panel"
dynamic = ["version"]
description = "Vystak panel channel — control-panel API with streaming, users, projects, and sessions"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [
    { name = "Anatoliy Kolodkin", email = "11351966+akolodkin@users.noreply.github.com" },
]
keywords = ["vystak", "channel", "panel", "control-panel", "agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "vystak>=0.1.0",
    "vystak-channel-runtime>=0.1.0",
]

[project.urls]
Homepage = "https://vystak.dev"
Repository = "https://github.com/vystak/vystak"

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_channel_panel"]

[tool.uv.sources]
vystak = { workspace = true }
vystak-channel-runtime = { workspace = true }

[tool.hatch.version]
source = "vcs"
raw-options = {root = "../../.."}
```

`README.md`: two sentences — what the panel channel is, pointer to the spec doc.

`src/vystak_channel_panel/__init__.py`:

```python
"""Vystak panel channel plugin — auto-registers on import."""

from vystak.channels import register_plugin

from vystak_channel_panel.plugin import PanelChannelConfig, PanelChannelPlugin

__version__ = "0.1.0"

_plugin = PanelChannelPlugin()
register_plugin(_plugin)


__all__ = ["PanelChannelConfig", "PanelChannelPlugin"]
```

`src/vystak_channel_panel/server_template.py`:

```python
"""Build-time artifacts for the panel channel container.

The runnable code is the `vystak_channel_panel` package itself.
DockerChannelNode bundles that package's source plus vystak +
vystak-channel-runtime + transports via COPY . .;
PYTHONPATH=/app makes them importable.
"""

from __future__ import annotations

REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
pydantic>=2.0
pyyaml>=6.0
aiosqlite>=0.20
asyncpg>=0.29
nats-py>=2.6
croniter>=2.0
psycopg[binary]>=3.0
opentelemetry-api>=1.27
opentelemetry-sdk>=1.27
opentelemetry-exporter-otlp-proto-grpc>=1.27
opentelemetry-instrumentation-fastapi>=0.48b0
opentelemetry-instrumentation-httpx>=0.48b0
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/vystak
COPY . .
RUN cp channel_config.json routes.json /etc/vystak/ 2>/dev/null || true
ENV VYSTAK_CONFIG_DIR=/etc/vystak PYTHONPATH=/app PORT=8080
CMD ["python", "-m", "vystak_channel_panel"]
"""
```

`src/vystak_channel_panel/plugin.py`:

```python
"""PanelChannelPlugin — control-panel API channel."""

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel
from vystak.providers.base import ChannelPlugin, FileBundle
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


class PanelChannelConfig(BaseModel):
    """Optional config for a panel channel."""

    port: int = 8100
    db_path: str = "/data/panel.db"


class PanelChannelPlugin(ChannelPlugin):
    """Control-panel API channel.

    One FastAPI container that owns the panel DB (users, projects,
    conversations, messages) and exposes a REST + SSE API consumed by the
    vystak-panel Next.js app. Talks to agents via their OpenAI Responses API.
    """

    type = ChannelType.PANEL
    default_runtime_mode = RuntimeMode.SHARED
    agent_protocol = AgentProtocol.A2A_TURN
    config_schema = PanelChannelConfig

    def build_bundle(
        self, channel: Channel, resolved_routes: dict[str, dict[str, str]]
    ) -> FileBundle:
        from vystak_channel_runtime import channel_package_version, runtime_version

        from vystak_channel_panel.server_template import DOCKERFILE, REQUIREMENTS

        channel.channel_package_version = channel_package_version("vystak-channel-panel")
        channel.channel_runtime_version = runtime_version()

        channel_config = {
            "channel_type": "panel",
            "agent_protocol": "a2a-turn",
            "agents": [a.name for a in channel.agents],
            "default_agent": channel.default_agent.name if channel.default_agent else None,
            "port": 8080,
            "db_path": channel.config.get("db_path", "/data/panel.db"),
            "state": (
                channel.state.model_dump(exclude_none=True)
                if channel.state is not None else None
            ),
            "canonical_name": channel.canonical_name,
            "channel_package_version": channel.channel_package_version,
            "channel_runtime_version": channel.channel_runtime_version,
            "delivery_port": int(channel.config.get("delivery_port", 9999)),
            "transport_type": (
                channel.platform.transport.type
                if channel.platform and getattr(channel.platform, "transport", None)
                else "http"
            ),
        }
        return FileBundle(
            files={
                "Dockerfile": DOCKERFILE,
                "requirements.txt": REQUIREMENTS,
                "channel_config.json": json.dumps(channel_config, indent=2),
                "routes.json": json.dumps(resolved_routes, indent=2),
            },
            entrypoint="python -m vystak_channel_panel",
        )

    def provision_nodes(self, channel: Channel, platform: Platform) -> list["Provisionable"]:
        # The Docker provider's apply_channel builds the DockerChannelNode.
        return []

    def thread_name(self, event: dict) -> str:
        return f"thread:panel:{event.get('conversation_id', 'unknown')}"

    def health_check(self, deployment: dict) -> str:
        return "ok" if deployment.get("running") else "down"
```

- [ ] **Step 5: Sync workspace and run tests**

Run: `uv sync && uv run pytest packages/python/vystak-channel-panel/tests/test_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Lint + full python tests**

Run: `just lint-python && just test-python`
Expected: clean / all pass

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/common.py packages/python/vystak-channel-panel uv.lock
git commit -m "feat(panel): ChannelType.PANEL + vystak-channel-panel plugin skeleton"
```

---

### Task 2: Provider, CLI, and release wiring

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/cli.py:8-10`
- Modify: `packages/python/vystak-cli/pyproject.toml:28-30` and `:56-58`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py:118-129` and `:180-186`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` (`destroy_channel` — the `delete_channel_data` volume-removal condition must cover PANEL as well as SLACK, matching the creation condition above)
- Modify: `.github/workflows/release.yml:76-79`

**Interfaces:**
- Consumes: `PanelChannelPlugin` auto-registration (Task 1).
- Produces: `vystak apply` can resolve/deploy `type: panel` channels; panel containers get the `vystak_channel_panel` source bundled and a `/data` state volume (`vystak-<name>-state`).

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-channel-panel/tests/test_plugin.py`:

```python
class TestCliRegistration:
    def test_cli_import_registers_panel_plugin(self):
        """Importing the CLI must register the panel plugin. Runs in a fresh
        interpreter: in-process, this test module's own top-level import of
        vystak_channel_panel would have already registered it, hiding a
        missing side-effect import in cli.py."""
        import subprocess
        import sys

        code = (
            "import vystak_cli.cli;"
            "from vystak.channels import get_plugin;"
            "from vystak.schema.common import ChannelType;"
            "print(type(get_plugin(ChannelType.PANEL)).__name__)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        assert out.stdout.strip() == "PanelChannelPlugin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_plugin.py::TestCliRegistration -v`
Expected: FAIL — `CalledProcessError`; the subprocess raises `KeyError: No plugin registered for channel type 'panel'` because cli.py does not import the package yet.

- [ ] **Step 3: Wire the CLI import**

In `packages/python/vystak-cli/src/vystak_cli/cli.py`, after the discord import add:

```python
import vystak_channel_panel  # noqa: F401 — registers ChannelType.PANEL plugin
```

In `packages/python/vystak-cli/pyproject.toml` add to `dependencies` (alphabetical, after `vystak-channel-discord`):

```toml
    "vystak-channel-panel>=0.1.0",
```

and to `[tool.uv.sources]`:

```toml
vystak-channel-panel = { workspace = true }
```

- [ ] **Step 4: Bundle panel source + state volume in DockerChannelNode**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py`, in the bundle-modules switch (after the DISCORD branch, ~line 129):

```python
            elif self._channel.type == ChannelType.PANEL:
                import vystak_channel_panel

                _bundle_mods.append(vystak_channel_panel)
```

And change the Slack state-volume condition (~line 180) to include PANEL (panel persists `/data/panel.db`):

```python
            if self._channel.type in (ChannelType.SLACK, ChannelType.PANEL):
```

(Comment above it: update "Slack channels" to "Slack and panel channels".)

- [ ] **Step 5: Add to the PyPI publish list**

In `.github/workflows/release.yml`, in the `for pkg in` list, after `vystak-channel-discord \` add:

```
                     vystak-channel-panel \
```

- [ ] **Step 6: Verify**

Run: `uv sync && just lint-python && just test-python`
Expected: clean / all pass

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak-cli packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py .github/workflows/release.yml packages/python/vystak-channel-panel/tests/test_plugin.py uv.lock
git commit -m "feat(panel): wire panel channel into CLI registration, docker bundling, release publish list"
```

---

### Task 3: Panel models + store — schema, users, settings

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/models.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Test: `packages/python/vystak-channel-panel/tests/test_store_users.py`

**Interfaces:**
- Produces (models.py, all Pydantic BaseModel):
  - `PanelUser(id: str, email: str, name: str = "", image: str = "", role: str, status: str = "active", created_at: str)`
  - `Project(id: str, name: str, owner_id: str, is_default: bool = False, created_at: str)`
  - `Conversation(id: str, project_id: str, creator_id: str, agent_name: str, title: str = "", last_response_id: str | None = None, created_at: str, updated_at: str)`
  - `PanelMessage(id: str, conversation_id: str, role: str, content: str, response_id: str | None = None, created_at: str)`
- Produces (store.py): `SqlitePanelStore(db_path: str | Path)` with `async connect() -> None` (opens + creates schema), `async close()`, and this task's methods:
  - `async count_users() -> int`
  - `async create_user(email: str, *, name: str = "", image: str = "", role: str = "member") -> PanelUser`
  - `async get_user_by_email(email: str) -> PanelUser | None`
  - `async get_user(user_id: str) -> PanelUser | None`
  - `async list_users() -> list[PanelUser]`
  - `async update_user(user_id: str, *, role: str | None = None, status: str | None = None) -> PanelUser | None`
  - `async get_setting(key: str) -> str | None`, `async set_setting(key: str, value: str) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_store_users.py` (root pyproject sets `asyncio_mode = "auto"`, so plain `async def` tests run):

```python
"""SqlitePanelStore — users + settings."""

import pytest

from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


async def test_count_users_empty(store):
    assert await store.count_users() == 0


async def test_create_and_get_user(store):
    u = await store.create_user("Admin@Example.com", name="Ada", role="admin")
    assert u.email == "admin@example.com"  # normalized lowercase
    assert u.role == "admin"
    assert u.status == "active"
    got = await store.get_user_by_email("ADMIN@example.COM")
    assert got is not None and got.id == u.id
    assert await store.get_user(u.id) == got


async def test_duplicate_email_rejected(store):
    await store.create_user("a@example.com")
    with pytest.raises(Exception):
        await store.create_user("a@example.com")


async def test_list_and_update_user(store):
    u = await store.create_user("a@example.com")
    assert [x.id for x in await store.list_users()] == [u.id]
    updated = await store.update_user(u.id, role="admin", status="deactivated")
    assert updated.role == "admin" and updated.status == "deactivated"
    assert await store.update_user("missing", role="admin") is None


async def test_settings_round_trip(store):
    assert await store.get_setting("k") is None
    await store.set_setting("k", "v")
    await store.set_setting("k", "v2")
    assert await store.get_setting("k") == "v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_users.py -v`
Expected: FAIL — `ModuleNotFoundError: vystak_channel_panel.store`

- [ ] **Step 3: Implement models + store**

`src/vystak_channel_panel/models.py`:

```python
"""Panel domain models."""

from __future__ import annotations

from pydantic import BaseModel


class PanelUser(BaseModel):
    id: str
    email: str
    name: str = ""
    image: str = ""
    role: str  # "admin" | "member"
    status: str = "active"  # "active" | "deactivated"
    created_at: str


class Project(BaseModel):
    id: str
    name: str
    owner_id: str
    is_default: bool = False
    created_at: str


class Conversation(BaseModel):
    id: str
    project_id: str
    creator_id: str
    agent_name: str
    title: str = ""
    last_response_id: str | None = None
    created_at: str
    updated_at: str


class PanelMessage(BaseModel):
    id: str
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    response_id: str | None = None
    created_at: str
```

`src/vystak_channel_panel/store.py` (this task: schema + users + settings; later tasks append methods):

```python
"""SqlitePanelStore — panel system-of-record (users, projects, conversations)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from vystak_channel_panel.models import Conversation, PanelMessage, PanelUser, Project

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    last_response_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    response_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class SqlitePanelStore:
    """All panel state in one SQLite file (named /data volume in-container)."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "store not connected"
        return self._db

    # --- users ------------------------------------------------------------

    async def count_users(self) -> int:
        async with self.db.execute("SELECT COUNT(*) AS n FROM users") as cur:
            row = await cur.fetchone()
        return int(row["n"])

    async def create_user(
        self, email: str, *, name: str = "", image: str = "", role: str = "member"
    ) -> PanelUser:
        user = PanelUser(
            id=_new_id(),
            email=email.strip().lower(),
            name=name,
            image=image,
            role=role,
            created_at=_now(),
        )
        await self.db.execute(
            "INSERT INTO users (id, email, name, image, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user.id, user.email, user.name, user.image, user.role, user.status,
             user.created_at),
        )
        await self.db.commit()
        return user

    async def get_user_by_email(self, email: str) -> PanelUser | None:
        async with self.db.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ) as cur:
            row = await cur.fetchone()
        return PanelUser(**dict(row)) if row else None

    async def get_user(self, user_id: str) -> PanelUser | None:
        async with self.db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return PanelUser(**dict(row)) if row else None

    async def list_users(self) -> list[PanelUser]:
        async with self.db.execute(
            "SELECT * FROM users ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()
        return [PanelUser(**dict(r)) for r in rows]

    async def update_user(
        self, user_id: str, *, role: str | None = None, status: str | None = None
    ) -> PanelUser | None:
        # One statement, not two conditional ones: a partial update that
        # raises midway (e.g. a CHECK violation on the second column) leaves
        # the first write uncommitted but pending, and the next unrelated
        # commit() silently adopts it. COALESCE keeps the same contract —
        # a None argument leaves that column unchanged.
        await self.db.execute(
            "UPDATE users SET role = COALESCE(?, role), status = COALESCE(?, status) "
            "WHERE id = ?",
            (role, status, user_id),
        )
        await self.db.commit()
        return await self.get_user(user_id)

    # --- settings ---------------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.db.commit()
```

Note: `PanelUser(**dict(row))` works because SQLite returns `is_default`-style ints only on projects (handled in Task 4); users columns map 1:1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_users.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel/src/vystak_channel_panel/models.py packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py packages/python/vystak-channel-panel/tests/test_store_users.py
git commit -m "feat(panel): panel models + sqlite store (users, settings)"
```

---

### Task 4: Store — projects, members, default project

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Test: `packages/python/vystak-channel-panel/tests/test_store_projects.py`

**Interfaces:**
- Produces (appended to `SqlitePanelStore`):
  - `async create_project(name: str, owner_id: str, *, is_default: bool = False) -> Project`
  - `async get_project(project_id: str) -> Project | None`
  - `async list_projects_for_user(user_id: str) -> list[Project]` (owned OR member)
  - `async delete_project(project_id: str) -> None` (cascades members, conversations, messages)
  - `async add_member(project_id: str, user_id: str) -> None` (idempotent)
  - `async remove_member(project_id: str, user_id: str) -> None`
  - `async list_members(project_id: str) -> list[PanelUser]`
  - `async user_can_access_project(project_id: str, user_id: str) -> bool` (owner or member)
  - `async ensure_default_project(user_id: str) -> Project` (create-once "Personal")

- [ ] **Step 1: Write the failing test**

`tests/test_store_projects.py`:

```python
"""SqlitePanelStore — projects, members, default project."""

import pytest

from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def users(store):
    a = await store.create_user("a@example.com", role="admin")
    b = await store.create_user("b@example.com")
    return a, b


async def test_create_get_list(store, users):
    a, b = users
    p = await store.create_project("Research", a.id)
    assert (await store.get_project(p.id)).name == "Research"
    assert [x.id for x in await store.list_projects_for_user(a.id)] == [p.id]
    assert await store.list_projects_for_user(b.id) == []


async def test_membership_visibility(store, users):
    a, b = users
    p = await store.create_project("Shared", a.id)
    assert not await store.user_can_access_project(p.id, b.id)
    await store.add_member(p.id, b.id)
    await store.add_member(p.id, b.id)  # idempotent
    assert await store.user_can_access_project(p.id, b.id)
    assert [x.id for x in await store.list_projects_for_user(b.id)] == [p.id]
    assert {u.email for u in await store.list_members(p.id)} == {"b@example.com"}
    await store.remove_member(p.id, b.id)
    assert not await store.user_can_access_project(p.id, b.id)


async def test_owner_always_has_access(store, users):
    a, _ = users
    p = await store.create_project("Mine", a.id)
    assert await store.user_can_access_project(p.id, a.id)


async def test_ensure_default_project_idempotent(store, users):
    a, _ = users
    p1 = await store.ensure_default_project(a.id)
    p2 = await store.ensure_default_project(a.id)
    assert p1.id == p2.id
    assert p1.is_default and p1.name == "Personal"


async def test_delete_project_cascades(store, users):
    a, b = users
    p = await store.create_project("Doomed", a.id)
    await store.add_member(p.id, b.id)
    c = await store.create_conversation(p.id, a.id, "agent-x")
    await store.add_message(c.id, "user", "hi")
    await store.delete_project(p.id)
    assert await store.get_project(p.id) is None
    assert await store.list_members(p.id) == []
    assert await store.list_conversations(p.id) == []
    assert await store.list_messages(c.id) == []
```

(The last test uses Task 5 methods — write it now, mark it with `@pytest.mark.skip(reason="conversations land in next task")`, and remove the skip in Task 5.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_projects.py -v`
Expected: FAIL — `AttributeError: create_project`

- [ ] **Step 3: Implement**

Append to `SqlitePanelStore`:

```python
    # --- projects ---------------------------------------------------------

    async def create_project(
        self, name: str, owner_id: str, *, is_default: bool = False
    ) -> Project:
        project = Project(
            id=_new_id(),
            name=name,
            owner_id=owner_id,
            is_default=is_default,
            created_at=_now(),
        )
        await self.db.execute(
            "INSERT INTO projects (id, name, owner_id, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project.id, project.name, project.owner_id,
             int(project.is_default), project.created_at),
        )
        await self.db.commit()
        return project

    async def get_project(self, project_id: str) -> Project | None:
        async with self.db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._project_from_row(row) if row else None

    @staticmethod
    def _project_from_row(row) -> Project:
        d = dict(row)
        d["is_default"] = bool(d["is_default"])
        return Project(**d)

    async def list_projects_for_user(self, user_id: str) -> list[Project]:
        async with self.db.execute(
            "SELECT DISTINCT p.* FROM projects p "
            "LEFT JOIN project_members m ON m.project_id = p.id "
            "WHERE p.owner_id = ? OR m.user_id = ? "
            "ORDER BY p.created_at",
            (user_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
        return [self._project_from_row(r) for r in rows]

    async def delete_project(self, project_id: str) -> None:
        await self.db.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE project_id = ?)",
            (project_id,),
        )
        await self.db.execute(
            "DELETE FROM conversations WHERE project_id = ?", (project_id,)
        )
        await self.db.execute(
            "DELETE FROM project_members WHERE project_id = ?", (project_id,)
        )
        await self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await self.db.commit()

    async def add_member(self, project_id: str, user_id: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO project_members (project_id, user_id) "
            "VALUES (?, ?)",
            (project_id, user_id),
        )
        await self.db.commit()

    async def remove_member(self, project_id: str, user_id: str) -> None:
        await self.db.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        await self.db.commit()

    async def list_members(self, project_id: str) -> list[PanelUser]:
        async with self.db.execute(
            "SELECT u.* FROM users u "
            "JOIN project_members m ON m.user_id = u.id "
            "WHERE m.project_id = ? ORDER BY u.created_at",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [PanelUser(**dict(r)) for r in rows]

    async def user_can_access_project(self, project_id: str, user_id: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM projects p "
            "LEFT JOIN project_members m "
            "  ON m.project_id = p.id AND m.user_id = ? "
            "WHERE p.id = ? AND (p.owner_id = ? OR m.user_id IS NOT NULL)",
            (user_id, project_id, user_id),
        ) as cur:
            return await cur.fetchone() is not None

    async def ensure_default_project(self, user_id: str) -> Project:
        async with self.db.execute(
            "SELECT * FROM projects WHERE owner_id = ? AND is_default = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return self._project_from_row(row)
        return await self.create_project("Personal", user_id, is_default=True)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_projects.py -v`
Expected: PASS (cascade test SKIPPED)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): store projects, members, default project"
```

---

### Task 5: Store — conversations + messages

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Modify: `packages/python/vystak-channel-panel/tests/test_store_projects.py` (remove the skip)
- Test: `packages/python/vystak-channel-panel/tests/test_store_conversations.py`

**Interfaces:**
- Produces (appended to `SqlitePanelStore`):
  - `async create_conversation(project_id: str, creator_id: str, agent_name: str, *, title: str = "") -> Conversation`
  - `async get_conversation(conversation_id: str) -> Conversation | None`
  - `async list_conversations(project_id: str) -> list[Conversation]` (newest `updated_at` first)
  - `async update_conversation(conversation_id: str, *, title: str | None = None, last_response_id: str | None = None) -> Conversation | None` (also bumps `updated_at`)
  - `async delete_conversation(conversation_id: str) -> None` (cascades messages)
  - `async add_message(conversation_id: str, role: str, content: str, *, response_id: str | None = None) -> PanelMessage` (bumps conversation `updated_at`)
  - `async list_messages(conversation_id: str) -> list[PanelMessage]` (oldest first)

- [ ] **Step 1: Write the failing test**

`tests/test_store_conversations.py`:

```python
"""SqlitePanelStore — conversations + messages."""

import pytest

from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def project(store):
    user = await store.create_user("a@example.com", role="admin")
    proj = await store.create_project("P", user.id)
    return user, proj


async def test_create_and_list(store, project):
    user, proj = project
    c1 = await store.create_conversation(proj.id, user.id, "weather-agent")
    c2 = await store.create_conversation(proj.id, user.id, "time-agent", title="T")
    assert c1.title == "" and c2.title == "T"
    listed = await store.list_conversations(proj.id)
    assert {c.id for c in listed} == {c1.id, c2.id}


async def test_update_title_and_response_id(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    updated = await store.update_conversation(
        c.id, title="Hello", last_response_id="resp_1"
    )
    assert updated.title == "Hello"
    assert updated.last_response_id == "resp_1"
    assert updated.updated_at >= c.updated_at
    assert await store.update_conversation("missing", title="x") is None


async def test_messages_round_trip_ordered(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    m1 = await store.add_message(c.id, "user", "hi")
    m2 = await store.add_message(c.id, "assistant", "hello!", response_id="resp_1")
    msgs = await store.list_messages(c.id)
    assert [m.id for m in msgs] == [m1.id, m2.id]
    assert msgs[1].response_id == "resp_1"


async def test_add_message_bumps_conversation_updated_at(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    await store.add_message(c.id, "user", "hi")
    got = await store.get_conversation(c.id)
    assert got.updated_at >= c.updated_at


async def test_delete_conversation_cascades(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    await store.add_message(c.id, "user", "hi")
    await store.delete_conversation(c.id)
    assert await store.get_conversation(c.id) is None
    assert await store.list_messages(c.id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_store_conversations.py -v`
Expected: FAIL — `AttributeError: create_conversation`

- [ ] **Step 3: Implement**

Append to `SqlitePanelStore`:

```python
    # --- conversations ----------------------------------------------------

    async def create_conversation(
        self, project_id: str, creator_id: str, agent_name: str, *, title: str = ""
    ) -> Conversation:
        now = _now()
        conv = Conversation(
            id=_new_id(),
            project_id=project_id,
            creator_id=creator_id,
            agent_name=agent_name,
            title=title,
            created_at=now,
            updated_at=now,
        )
        await self.db.execute(
            "INSERT INTO conversations "
            "(id, project_id, creator_id, agent_name, title, last_response_id, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conv.id, conv.project_id, conv.creator_id, conv.agent_name,
             conv.title, conv.last_response_id, conv.created_at, conv.updated_at),
        )
        await self.db.commit()
        return conv

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ) as cur:
            row = await cur.fetchone()
        return Conversation(**dict(row)) if row else None

    async def list_conversations(self, project_id: str) -> list[Conversation]:
        async with self.db.execute(
            "SELECT * FROM conversations WHERE project_id = ? "
            "ORDER BY updated_at DESC",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [Conversation(**dict(r)) for r in rows]

    async def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        last_response_id: str | None = None,
    ) -> Conversation | None:
        # Single statement: a multi-statement partial update that raises
        # midway leaves an uncommitted write the next unrelated commit()
        # would silently adopt (see the update_user fix in Task 3).
        # COALESCE preserves the partial-update contract — a None argument
        # leaves that column unchanged.
        await self.db.execute(
            "UPDATE conversations SET title = COALESCE(?, title), "
            "last_response_id = COALESCE(?, last_response_id), updated_at = ? "
            "WHERE id = ?",
            (title, last_response_id, _now(), conversation_id),
        )
        await self.db.commit()
        return await self.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> None:
        # Multi-statement write — use the store's _write() helper so a
        # mid-sequence failure rolls back instead of leaving pending
        # statements for the next unrelated commit() to adopt (Task 4).
        async with self._write() as db:
            await db.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            await db.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )

    # --- messages ---------------------------------------------------------

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        response_id: str | None = None,
    ) -> PanelMessage:
        msg = PanelMessage(
            id=_new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            response_id=response_id,
            created_at=_now(),
        )
        # Insert + bump in one transaction via _write() (Task 4): a message
        # must never persist without its conversation's updated_at bump.
        async with self._write() as db:
            await db.execute(
                "INSERT INTO messages "
                "(id, conversation_id, role, content, response_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (msg.id, msg.conversation_id, msg.role, msg.content,
                 msg.response_id, msg.created_at),
            )
            await db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (msg.created_at, conversation_id),
            )
        return msg

    async def list_messages(self, conversation_id: str) -> list[PanelMessage]:
        async with self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [PanelMessage(**dict(r)) for r in rows]
```

Remove the `@pytest.mark.skip` from `test_delete_project_cascades` in `tests/test_store_projects.py`.

- [ ] **Step 4: Run all panel tests**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v`
Expected: PASS (including the un-skipped cascade test)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): store conversations + messages"
```

---

### Task 6: ResponsesClient — streaming agent client

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/responses_client.py`
- Test: `packages/python/vystak-channel-panel/tests/test_responses_client.py`

**Interfaces:**
- Consumes: agent `/v1/responses` SSE wire shape (`response.output_text.delta`, `response.completed`, `response.failed`, `data: [DONE]`) — see `_vystak/runtime/openai/responses.py` and `vystak-chat/src/vystak_chat/client.py`.
- Produces:
  - `PanelStreamEvent(type: Literal["token", "done", "error"], text: str = "", response_id: str = "")` (Pydantic)
  - `class ResponsesClient(timeout_s: float = 300.0)` with `stream_message(base_url: str, text: str, *, previous_response_id: str | None, user_id: str | None = None, project_id: str | None = None) -> AsyncIterator[PanelStreamEvent]`
  - `def agent_base_url(route_entry: dict | str) -> str` — takes a `routes.json` entry (`{"address": "http://…:8000/a2a"}` or bare string), strips a trailing `/a2a`.

- [ ] **Step 1: Write the failing test**

`tests/test_responses_client.py` (httpx MockTransport — no network):

```python
"""ResponsesClient — SSE parsing against a mocked /v1/responses."""

import json

import httpx

from vystak_channel_panel.responses_client import (
    PanelStreamEvent,
    ResponsesClient,
    agent_base_url,
)


def _sse_body(*payloads: dict | str) -> str:
    out = []
    for p in payloads:
        data = p if isinstance(p, str) else json.dumps(p)
        out.append(f"data: {data}\n\n")
    return "".join(out)


def _mock_client(body: str, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            status_code, content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _collect(client: ResponsesClient) -> list[PanelStreamEvent]:
    return [
        ev
        async for ev in client.stream_message(
            "http://agent:8000", "hi", previous_response_id=None
        )
    ]


async def test_tokens_then_done():
    body = _sse_body(
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_text.delta", "delta": "Hel"},
        {"type": "response.output_text.delta", "delta": "lo"},
        {"type": "response.completed", "response": {"id": "resp_1"}},
        "[DONE]",
    )
    client = ResponsesClient(http_client=_mock_client(body))
    events = await _collect(client)
    assert [e.type for e in events] == ["token", "token", "done"]
    assert "".join(e.text for e in events if e.type == "token") == "Hello"
    assert events[-1].response_id == "resp_1"


async def test_failed_event_maps_to_error():
    body = _sse_body(
        {"type": "response.failed",
         "response": {"id": "resp_1", "status": "failed",
                      "error": {"message": "boom"}}},
        "[DONE]",
    )
    client = ResponsesClient(http_client=_mock_client(body))
    events = await _collect(client)
    assert events[-1].type == "error"
    assert "boom" in events[-1].text


async def test_http_error_maps_to_error():
    client = ResponsesClient(http_client=_mock_client("", status_code=503))
    events = await _collect(client)
    assert events == [
        PanelStreamEvent(type="error", text="agent returned 503")
    ]


async def test_previous_response_id_forwarded():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, content=_sse_body("[DONE]").encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = ResponsesClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    async for _ in client.stream_message(
        "http://agent:8000", "hi",
        previous_response_id="resp_9", user_id="u1", project_id="p1",
    ):
        pass
    assert captured["previous_response_id"] == "resp_9"
    assert captured["user_id"] == "u1"
    assert captured["project_id"] == "p1"


def test_agent_base_url_strips_a2a():
    assert agent_base_url({"address": "http://x:8000/a2a"}) == "http://x:8000"
    assert agent_base_url({"address": "http://x:8000"}) == "http://x:8000"
    assert agent_base_url("http://x:8000/a2a") == "http://x:8000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_responses_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/vystak_channel_panel/responses_client.py`:

```python
"""Streaming client for an agent's OpenAI Responses API (/v1/responses)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from pydantic import BaseModel


class PanelStreamEvent(BaseModel):
    type: Literal["token", "done", "error"]
    text: str = ""
    response_id: str = ""


def agent_base_url(route_entry: dict | str) -> str:
    """Resolve a routes.json entry to the agent's HTTP root.

    routes.json addresses point at the A2A endpoint
    (http://vystak-<agent>:8000/a2a); the Responses API lives at the root.
    """
    address = (
        route_entry.get("address", "") if isinstance(route_entry, dict)
        else route_entry
    )
    return address.rstrip("/").removesuffix("/a2a")


class ResponsesClient:
    """POST /v1/responses with stream=true; yields typed panel events.

    Session continuity is the Responses contract: pass the conversation's
    stored id as previous_response_id; the agent uses it as its LangGraph
    thread_id. An id unknown to the agent (e.g. after a redeploy with a
    fresh session store) starts an empty thread under the same id — it
    does not error.
    """

    def __init__(
        self,
        timeout_s: float = 300.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_s
        self._http_client = http_client

    async def stream_message(
        self,
        base_url: str,
        text: str,
        *,
        previous_response_id: str | None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> AsyncIterator[PanelStreamEvent]:
        body = {
            "model": "",
            "input": text,
            "previous_response_id": previous_response_id,
            "store": True,
            "stream": True,
            "user_id": user_id,
            "project_id": project_id,
        }
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._http_client is None
        closing = False
        try:
            async with client.stream(
                "POST", f"{base_url.rstrip('/')}/v1/responses", json=body,
                timeout=self._timeout,
            ) as resp:
                try:
                    if resp.status_code != 200:
                        yield PanelStreamEvent(
                            type="error", text=f"agent returned {resp.status_code}"
                        )
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        event_type = data.get("type", "")
                        if event_type == "response.output_text.delta":
                            yield PanelStreamEvent(
                                type="token", text=data.get("delta", "")
                            )
                        elif event_type == "response.completed":
                            yield PanelStreamEvent(
                                type="done",
                                response_id=data.get("response", {}).get("id", ""),
                            )
                        elif event_type == "response.failed":
                            err = (
                                data.get("response", {}).get("error", {})
                                .get("message", "agent stream failed")
                            )
                            yield PanelStreamEvent(type="error", text=err)
                except GeneratorExit:
                    # Consumer abandoned the stream (browser disconnect on the
                    # Task 11 SSE route). Flag it so a close-time transport
                    # error below can't try to yield while we're closing.
                    closing = True
                    raise
        except httpx.HTTPError as exc:
            if closing:
                # __aexit__ raised while GeneratorExit was propagating and
                # replaced it as the in-flight exception. Yielding here would
                # raise "async generator ignored GeneratorExit" out of aclose().
                return
            yield PanelStreamEvent(type="error", text=f"agent unreachable: {exc}")
        finally:
            if owns_client:
                await client.aclose()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_responses_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): streaming ResponsesClient for agent /v1/responses"
```

---

### Task 7: Runtime + FastAPI app skeleton — auth deps, bootstrap, setup, entrypoint

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/runtime.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/app.py`
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/__main__.py`
- Test: `packages/python/vystak-channel-panel/tests/conftest.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_bootstrap.py`

**Interfaces:**
- Consumes: `ChannelRuntime` (vystak-channel-runtime), `SqlitePanelStore` (Tasks 3–5), `ResponsesClient` (Task 6), `launch` (vystak-channel-runtime launcher).
- Produces:
  - `PanelChannelRuntime(config, routes, store, panel_store=None, responses_client=None)` — `ChannelRuntime` subclass; `panel_store: SqlitePanelStore` and `responses_client: ResponsesClient` attributes; `start()` connects the store, builds the app, serves uvicorn on `config["port"]`.
  - `build_app(rt: PanelChannelRuntime) -> FastAPI` with `GET /health`, `GET /api/bootstrap`, `POST /api/setup`; auth dependencies `service_auth` (Bearer vs `PANEL_SERVICE_TOKEN` env) and `current_user` (X-Panel-User → active `PanelUser` | 403 `"not invited"`).
  - Bootstrap response JSON: `{"setup_required": bool, "user": {...}|null, "agents": [str], "default_project_id": str|null}`.
  - Test fixtures in conftest: `panel_rt` (runtime with tmp sqlite store + fake routes), `api` (httpx AsyncClient over ASGITransport with valid service token), `as_user(email)` header helper.

- [ ] **Step 1: Write the conftest + failing test**

`tests/conftest.py`:

```python
"""Shared fixtures for panel channel API tests."""

import httpx
import pytest

from vystak_channel_panel.responses_client import ResponsesClient
from vystak_channel_panel.store import SqlitePanelStore

SERVICE_TOKEN = "test-service-token"

ROUTES = {
    "weather-agent": {
        "canonical": "weather-agent.agents.default",
        "address": "http://vystak-weather-agent:8000/a2a",
    },
    "time-agent": {
        "canonical": "time-agent.agents.default",
        "address": "http://vystak-time-agent:8000/a2a",
    },
}


@pytest.fixture
async def panel_rt(tmp_path, monkeypatch):
    from vystak_channel_runtime.store import MemoryChannelStore

    from vystak_channel_panel.runtime import PanelChannelRuntime

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)
    panel_store = SqlitePanelStore(tmp_path / "panel.db")
    await panel_store.connect()
    rt = PanelChannelRuntime(
        config={"channel_type": "panel", "port": 8080},
        routes=ROUTES,
        store=MemoryChannelStore(),
        panel_store=panel_store,
        responses_client=ResponsesClient(),
    )
    yield rt
    await panel_store.close()


@pytest.fixture
async def api(panel_rt):
    from vystak_channel_panel.app import build_app

    app = build_app(panel_rt)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://panel",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    ) as client:
        yield client
```

(No shared `as_user` in conftest — `--import-mode=importlib` makes cross-module test imports unreliable; each test file defines the two-line helper itself.)

`tests/test_api_bootstrap.py` (each API test file defines its own `as_user` helper — root pytest runs `--import-mode=importlib`, so do NOT import from conftest):

```python
"""Bootstrap + first-run setup + service auth."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def test_health_no_auth(api):
    resp = await api.get("/health")
    assert resp.status_code == 200


async def test_missing_service_token_rejected(panel_rt):
    import httpx

    from vystak_channel_panel.app import build_app

    transport = httpx.ASGITransport(app=build_app(panel_rt))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://panel"
    ) as bare:
        resp = await bare.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert resp.status_code == 401


async def test_wrong_service_token_rejected(panel_rt):
    import httpx

    from vystak_channel_panel.app import build_app

    transport = httpx.ASGITransport(app=build_app(panel_rt))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://panel",
        headers={"Authorization": "Bearer wrong"},
    ) as bad:
        resp = await bad.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert resp.status_code == 401


async def test_bootstrap_setup_required_when_no_users(api):
    resp = await api.get("/api/bootstrap", headers=as_user("first@example.com"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["setup_required"] is True
    assert body["user"] is None
    assert body["agents"] == ["weather-agent", "time-agent"]
    assert body["default_project_id"] is None


async def test_setup_creates_admin_and_closes(api):
    resp = await api.post(
        "/api/setup",
        json={"email": "First@Example.com", "name": "First", "image": ""},
        headers=as_user("First@Example.com"),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert resp.json()["user"]["email"] == "first@example.com"

    # second setup attempt is rejected
    again = await api.post(
        "/api/setup",
        json={"email": "second@example.com", "name": "", "image": ""},
        headers=as_user("second@example.com"),
    )
    assert again.status_code == 409


async def test_bootstrap_known_user_gets_default_project(api):
    await api.post(
        "/api/setup",
        json={"email": "a@example.com", "name": "A", "image": ""},
        headers=as_user("a@example.com"),
    )
    resp = await api.get("/api/bootstrap", headers=as_user("a@example.com"))
    body = resp.json()
    assert body["setup_required"] is False
    assert body["user"]["email"] == "a@example.com"
    assert body["default_project_id"] is not None
    # idempotent
    again = await api.get("/api/bootstrap", headers=as_user("a@example.com"))
    assert again.json()["default_project_id"] == body["default_project_id"]


async def test_bootstrap_unknown_user_after_setup(api):
    await api.post(
        "/api/setup",
        json={"email": "a@example.com", "name": "A", "image": ""},
        headers=as_user("a@example.com"),
    )
    resp = await api.get("/api/bootstrap", headers=as_user("stranger@example.com"))
    body = resp.json()
    assert body["setup_required"] is False
    assert body["user"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: vystak_channel_panel.runtime`

- [ ] **Step 3: Implement runtime**

`src/vystak_channel_panel/runtime.py`:

```python
"""PanelChannelRuntime — FastAPI control-panel API on the channel lifecycle."""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import FastAPI
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import AgentReply, InboundEvent, SkipEvent

from vystak_channel_panel.plugin import DEFAULT_DB_PATH
from vystak_channel_panel.responses_client import ResponsesClient
from vystak_channel_panel.store import SqlitePanelStore

logger = logging.getLogger("vystak.channel.panel")


class PanelChannelRuntime(ChannelRuntime):
    """Serves the panel REST + SSE API.

    Unlike chat/slack, requests do not flow through handle_event — the
    FastAPI routes call the panel store + ResponsesClient directly (the
    A2A pipeline's request/reply bridge can't represent an SSE response).
    ChannelRuntime is still the base for lifecycle, config, store, and
    delivery-receiver plumbing.
    """

    def __init__(
        self,
        *,
        panel_store: SqlitePanelStore | None = None,
        responses_client: ResponsesClient | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.panel_store = panel_store or SqlitePanelStore(
            self.config.get("db_path", DEFAULT_DB_PATH)
        )
        self.responses_client = responses_client or ResponsesClient()
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._owns_store = panel_store is None

    # --- ChannelRuntime abstract hooks (unused request path) --------------

    def parse_event(self, raw_event: Any) -> InboundEvent:
        raise SkipEvent("panel does not use the handle_event pipeline")

    async def post_reply(
        self, event: InboundEvent, route: str, reply: AgentReply
    ) -> None:
        return None

    async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
        # TODO(heartbeat): no push surface yet; heartbeat delivery would
        # append to a conversation once the panel grows one per heartbeat.
        logger.warning(
            "panel deliver_message: no push mechanism; thread_id=%s text_len=%d",
            thread_id, len(text),
        )

    async def _start_delivery_receiver(self) -> None:
        @self._app.post("/deliver")
        async def _deliver(payload: dict):
            await self._on_inbound_delivery(payload)
            return {"ok": True}

    async def _stop_delivery_receiver(self) -> None:
        return None

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        from vystak_channel_panel.app import build_app

        if self._owns_store:
            await self.panel_store.connect()
        self._app = build_app(self)
        port = int(self.config.get("port", 8080))
        cfg = uvicorn.Config(self._app, host="0.0.0.0", port=port, log_level="info")
        self._server = uvicorn.Server(cfg)
        await self._start_delivery_receiver()
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._owns_store:
            await self.panel_store.close()
```

- [ ] **Step 4: Implement app (skeleton + bootstrap/setup)**

`src/vystak_channel_panel/app.py`:

```python
"""FastAPI app for the panel channel — REST + SSE API."""

from __future__ import annotations

import os
import secrets as py_secrets
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from vystak_channel_runtime.telemetry import instrument_app

from vystak_channel_panel.models import PanelUser

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class SetupIn(BaseModel):
    email: str
    name: str = ""
    image: str = ""


def build_app(rt: "PanelChannelRuntime") -> FastAPI:
    app = FastAPI(title="vystak-channel-panel")
    instrument_app(
        app,
        service_name=os.environ.get("OTEL_SERVICE_NAME", "vystak-channel-panel"),
    )

    def service_auth(request: Request) -> None:
        expected = os.environ.get("PANEL_SERVICE_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        token = supplied.removeprefix("Bearer ").strip()
        if not expected or not py_secrets.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="invalid service token")

    def acting_email(request: Request) -> str:
        email = request.headers.get("x-panel-user", "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="missing X-Panel-User")
        return email

    async def current_user(
        request: Request, _: None = Depends(service_auth)
    ) -> PanelUser:
        user = await rt.panel_store.get_user_by_email(acting_email(request))
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="not invited")
        return user

    async def admin_user(user: PanelUser = Depends(current_user)) -> PanelUser:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="admin only")
        return user

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    async def bootstrap(
        request: Request, _: None = Depends(service_auth)
    ) -> dict:
        email = acting_email(request)
        setup_required = await rt.panel_store.count_users() == 0
        user = await rt.panel_store.get_user_by_email(email)
        if user is not None and user.status != "active":
            user = None
        default_project_id = None
        if user is not None:
            project = await rt.panel_store.ensure_default_project(user.id)
            default_project_id = project.id
        return {
            "setup_required": setup_required,
            "user": user.model_dump() if user else None,
            "agents": list(rt.routes.keys()),
            "default_project_id": default_project_id,
        }

    @app.post("/api/setup")
    async def setup(
        request: Request, body: SetupIn, _: None = Depends(service_auth)
    ) -> dict:
        # The UI backend asserts the Google-verified email in the header; the
        # body must not be able to disagree with it.
        if acting_email(request) != body.email.strip().lower():
            raise HTTPException(
                status_code=400, detail="X-Panel-User must match the body email"
            )
        # Atomic single-flight claim. A count-then-create check is NOT enough:
        # two concurrent requests with different emails both pass the count
        # (users.email UNIQUE does not collide) and both become admin —
        # reproduced during Task 7's review. claim_setup_admin inserts the
        # 'setup_complete' settings row under its primary key inside one
        # _write() transaction along with the user and default project, so a
        # second caller raises IntegrityError and nothing partial persists.
        try:
            user = await rt.panel_store.claim_setup_admin(
                body.email, name=body.name, image=body.image
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="setup already completed"
            ) from None
        return {"user": user.model_dump()}

    from vystak_channel_panel.routes_registry import mount_routes

    mount_routes(app, rt, current_user, admin_user)
    return app
```

Also create the (initially empty) route mounter `src/vystak_channel_panel/routes_registry.py`:

```python
"""Mounts resource routers onto the panel app. Extended by later tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


def mount_routes(app: FastAPI, rt: "PanelChannelRuntime", current_user, admin_user) -> None:
    # Tasks 8-11 add users/projects/conversations/messages routes here.
    return None
```

`src/vystak_channel_panel/__main__.py`:

```python
"""Panel channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch

from vystak_channel_panel.runtime import PanelChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes_path = cfg_dir / "routes.json"
    routes = json.loads(routes_path.read_text()) if routes_path.exists() else {}
    launch(PanelChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
```

Note: `launch()` calls `runtime_cls(config=..., routes=..., store=...)` — the keyword-only `panel_store`/`responses_client` default to production instances, so this works unchanged.

- [ ] **Step 5: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
just lint-python
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): runtime + FastAPI app with service auth, bootstrap, first-run setup"
```

---

### Task 8: Users admin endpoints

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_users.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_registry.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_users.py`

**Interfaces:**
- Consumes: `admin_user` dependency (Task 7), store user methods (Task 3).
- Produces HTTP API:
  - `GET /api/users` → `{"users": [PanelUser…]}` (admin)
  - `POST /api/users` body `{"email", "role"?}` → `{"user": …}`; 409 duplicate (admin)
  - `PATCH /api/users/{user_id}` body `{"role"?, "status"?}` → `{"user": …}`; 404 unknown (admin)

- [ ] **Step 1: Write the failing test**

`tests/test_api_users.py`:

```python
"""Admin user management."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _setup_admin(api, email="admin@example.com"):
    await api.post(
        "/api/setup",
        json={"email": email, "name": "A", "image": ""},
        headers=as_user(email),
    )
    return email


async def test_member_cannot_manage_users(api):
    admin = await _setup_admin(api)
    await api.post(
        "/api/users", json={"email": "m@example.com"}, headers=as_user(admin)
    )
    resp = await api.get("/api/users", headers=as_user("m@example.com"))
    assert resp.status_code == 403


async def test_admin_add_list_update(api):
    admin = await _setup_admin(api)
    created = await api.post(
        "/api/users",
        json={"email": "New@Example.com", "role": "member"},
        headers=as_user(admin),
    )
    assert created.status_code == 200
    uid = created.json()["user"]["id"]
    assert created.json()["user"]["email"] == "new@example.com"

    listed = await api.get("/api/users", headers=as_user(admin))
    assert {u["email"] for u in listed.json()["users"]} == {
        "admin@example.com", "new@example.com",
    }

    updated = await api.patch(
        f"/api/users/{uid}", json={"status": "deactivated"}, headers=as_user(admin)
    )
    assert updated.json()["user"]["status"] == "deactivated"

    # deactivated user is locked out
    resp = await api.get("/api/bootstrap", headers=as_user("new@example.com"))
    assert resp.json()["user"] is None


async def test_duplicate_add_conflict(api):
    admin = await _setup_admin(api)
    await api.post(
        "/api/users", json={"email": "x@example.com"}, headers=as_user(admin)
    )
    dup = await api.post(
        "/api/users", json={"email": "x@example.com"}, headers=as_user(admin)
    )
    assert dup.status_code == 409


async def test_patch_unknown_user_404(api):
    admin = await _setup_admin(api)
    resp = await api.patch(
        "/api/users/nope", json={"role": "admin"}, headers=as_user(admin)
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_users.py -v`
Expected: FAIL — 404s (routes not mounted)

- [ ] **Step 3: Implement**

`src/vystak_channel_panel/routes_users.py`:

```python
"""Admin user-management routes."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class UserCreateIn(BaseModel):
    email: str
    role: str = "member"


class UserPatchIn(BaseModel):
    role: str | None = None
    status: str | None = None


def build_users_router(rt: "PanelChannelRuntime", admin_user) -> APIRouter:
    router = APIRouter(prefix="/api/users")

    @router.get("")
    async def list_users(_: PanelUser = Depends(admin_user)) -> dict:
        return {"users": [u.model_dump() for u in await rt.panel_store.list_users()]}

    @router.post("")
    async def add_user(
        body: UserCreateIn, _: PanelUser = Depends(admin_user)
    ) -> dict:
        if body.role not in ("admin", "member"):
            raise HTTPException(status_code=422, detail="invalid role")
        # Cheap fast path; the UNIQUE constraint is the authoritative guard.
        # Check-then-create alone races: two concurrent invites of the same
        # email both pass the check and the loser's IntegrityError surfaces
        # as a 500 instead of a 409.
        if await rt.panel_store.get_user_by_email(body.email) is not None:
            raise HTTPException(status_code=409, detail="user already exists")
        try:
            user = await rt.panel_store.create_user(body.email, role=body.role)
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="user already exists"
            ) from None
        return {"user": user.model_dump()}

    @router.patch("/{user_id}")
    async def patch_user(
        user_id: str, body: UserPatchIn, _: PanelUser = Depends(admin_user)
    ) -> dict:
        if body.role is not None and body.role not in ("admin", "member"):
            raise HTTPException(status_code=422, detail="invalid role")
        if body.status is not None and body.status not in ("active", "deactivated"):
            raise HTTPException(status_code=422, detail="invalid status")
        user = await rt.panel_store.update_user(
            user_id, role=body.role, status=body.status
        )
        if user is None:
            raise HTTPException(status_code=404, detail="unknown user")
        return {"user": user.model_dump()}

    return router
```

In `routes_registry.py`, replace the body of `mount_routes` with:

```python
    from vystak_channel_panel.routes_users import build_users_router

    app.include_router(build_users_router(rt, admin_user))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): admin user management endpoints"
```

---

### Task 9: Projects + members endpoints

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_projects.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_registry.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_projects.py`

**Interfaces:**
- Produces HTTP API (all require `current_user`):
  - `GET /api/projects` → `{"projects": […]}` (visible = owned or member)
  - `POST /api/projects` body `{"name"}` → `{"project": …}`
  - `DELETE /api/projects/{id}` → 204 (owner only; 400 for default project)
  - `GET /api/projects/{id}/members` → `{"members": [PanelUser…]}` (visible)
  - `POST /api/projects/{id}/members` body `{"email"}` → 204 (owner only; member must be an existing user; 404 unknown email)
  - `DELETE /api/projects/{id}/members/{user_id}` → 204 (owner only)
- Produces helper used by Task 10/11: `async require_project_access(rt, project_id, user) -> Project` (404 unknown, 403 not visible) exported from `routes_projects.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_api_projects.py`:

```python
"""Projects + sharing."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _two_users(api):
    await api.post(
        "/api/setup",
        json={"email": "owner@example.com", "name": "O", "image": ""},
        headers=as_user("owner@example.com"),
    )
    await api.post(
        "/api/users", json={"email": "guest@example.com"},
        headers=as_user("owner@example.com"),
    )
    return "owner@example.com", "guest@example.com"


async def test_create_and_list_visible_only(api):
    owner, guest = await _two_users(api)
    created = await api.post(
        "/api/projects", json={"name": "Research"}, headers=as_user(owner)
    )
    assert created.status_code == 200

    owner_list = await api.get("/api/projects", headers=as_user(owner))
    names = {p["name"] for p in owner_list.json()["projects"]}
    assert names == {"Personal", "Research"}  # default project + created

    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert {p["name"] for p in guest_list.json()["projects"]} == set()

    # bootstrap creates guest's default project lazily
    await api.get("/api/bootstrap", headers=as_user(guest))
    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert {p["name"] for p in guest_list.json()["projects"]} == {"Personal"}


async def test_sharing_flow(api):
    owner, guest = await _two_users(api)
    pid = (
        await api.post(
            "/api/projects", json={"name": "Shared"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]

    add = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": guest},
        headers=as_user(owner),
    )
    assert add.status_code == 204

    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert "Shared" in {p["name"] for p in guest_list.json()["projects"]}

    members = await api.get(
        f"/api/projects/{pid}/members", headers=as_user(guest)
    )
    assert {m["email"] for m in members.json()["members"]} == {guest}

    # only owner can manage members
    deny = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": owner},
        headers=as_user(guest),
    )
    assert deny.status_code == 403

    uid = members.json()["members"][0]["id"]
    rm = await api.delete(
        f"/api/projects/{pid}/members/{uid}", headers=as_user(owner)
    )
    assert rm.status_code == 204
    guest_list = await api.get("/api/projects", headers=as_user(guest))
    assert "Shared" not in {p["name"] for p in guest_list.json()["projects"]}


async def test_add_unknown_member_404(api):
    owner, _ = await _two_users(api)
    pid = (
        await api.post(
            "/api/projects", json={"name": "P"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]
    resp = await api.post(
        f"/api/projects/{pid}/members",
        json={"email": "nobody@example.com"},
        headers=as_user(owner),
    )
    assert resp.status_code == 404


async def test_delete_project_rules(api):
    owner, guest = await _two_users(api)
    boot = await api.get("/api/bootstrap", headers=as_user(owner))
    default_pid = boot.json()["default_project_id"]

    pid = (
        await api.post(
            "/api/projects", json={"name": "Doomed"}, headers=as_user(owner)
        )
    ).json()["project"]["id"]

    assert (
        await api.delete(f"/api/projects/{default_pid}", headers=as_user(owner))
    ).status_code == 400
    # Deterministically 403, not 404: require_project_access finds the project
    # first, then rejects on visibility. Accepting 404 here would let a broken
    # ordering (404-on-invisible) pass silently.
    assert (
        await api.delete(f"/api/projects/{pid}", headers=as_user(guest))
    ).status_code == 403
    assert (
        await api.delete(f"/api/projects/{pid}", headers=as_user(owner))
    ).status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_projects.py -v`
Expected: FAIL — 404s

- [ ] **Step 3: Implement**

`src/vystak_channel_panel/routes_projects.py`:

```python
"""Project + membership routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser, Project

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class ProjectCreateIn(BaseModel):
    name: str


class MemberAddIn(BaseModel):
    email: str


async def require_project_access(
    rt: "PanelChannelRuntime", project_id: str, user: PanelUser
) -> Project:
    project = await rt.panel_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown project")
    if not await rt.panel_store.user_can_access_project(project_id, user.id):
        raise HTTPException(status_code=403, detail="no access to project")
    return project


async def require_project_owner(
    rt: "PanelChannelRuntime", project_id: str, user: PanelUser
) -> Project:
    project = await require_project_access(rt, project_id, user)
    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="owner only")
    return project


def build_projects_router(rt: "PanelChannelRuntime", current_user) -> APIRouter:
    router = APIRouter(prefix="/api/projects")

    @router.get("")
    async def list_projects(user: PanelUser = Depends(current_user)) -> dict:
        projects = await rt.panel_store.list_projects_for_user(user.id)
        return {"projects": [p.model_dump() for p in projects]}

    @router.post("")
    async def create_project(
        body: ProjectCreateIn, user: PanelUser = Depends(current_user)
    ) -> dict:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name required")
        project = await rt.panel_store.create_project(name, user.id)
        return {"project": project.model_dump()}

    @router.delete("/{project_id}", status_code=204)
    async def delete_project(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        project = await require_project_owner(rt, project_id, user)
        if project.is_default:
            raise HTTPException(
                status_code=400, detail="cannot delete default project"
            )
        await rt.panel_store.delete_project(project_id)
        return Response(status_code=204)

    @router.get("/{project_id}/members")
    async def list_members(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_project_access(rt, project_id, user)
        members = await rt.panel_store.list_members(project_id)
        return {"members": [m.model_dump() for m in members]}

    @router.post("/{project_id}/members", status_code=204)
    async def add_member(
        project_id: str, body: MemberAddIn, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_project_owner(rt, project_id, user)
        member = await rt.panel_store.get_user_by_email(body.email)
        if member is None:
            raise HTTPException(status_code=404, detail="unknown user email")
        await rt.panel_store.add_member(project_id, member.id)
        return Response(status_code=204)

    @router.delete("/{project_id}/members/{user_id}", status_code=204)
    async def remove_member(
        project_id: str, user_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_project_owner(rt, project_id, user)
        await rt.panel_store.remove_member(project_id, user_id)
        return Response(status_code=204)

    return router
```

In `routes_registry.py` `mount_routes`, add:

```python
    from vystak_channel_panel.routes_projects import build_projects_router

    app.include_router(build_projects_router(rt, current_user))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): project CRUD + member sharing endpoints"
```

---

### Task 10: Conversations + message-history endpoints

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_conversations.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_registry.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_conversations.py`

**Interfaces:**
- Consumes: `require_project_access` (Task 9).
- Produces HTTP API (all `current_user`-gated; conversation access = access to its project):
  - `GET /api/projects/{project_id}/conversations` → `{"conversations": […]}`
  - `POST /api/projects/{project_id}/conversations` body `{"agent_name", "title"?}` → `{"conversation": …}`; 422 if `agent_name` not in `rt.routes`
  - `PATCH /api/conversations/{conv_id}` body `{"title"}` → `{"conversation": …}`
  - `DELETE /api/conversations/{conv_id}` → 204
  - `GET /api/conversations/{conv_id}/messages` → `{"messages": […]}`
- Produces helper for Task 11: `async require_conversation_access(rt, conv_id, user) -> Conversation` exported from `routes_conversations.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_api_conversations.py`:

```python
"""Conversations + message history."""


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


async def _ready(api):
    await api.post(
        "/api/setup",
        json={"email": "o@example.com", "name": "O", "image": ""},
        headers=as_user("o@example.com"),
    )
    boot = await api.get("/api/bootstrap", headers=as_user("o@example.com"))
    return "o@example.com", boot.json()["default_project_id"]


async def test_create_requires_known_agent(api):
    owner, pid = await _ready(api)
    bad = await api.post(
        f"/api/projects/{pid}/conversations",
        json={"agent_name": "ghost-agent"},
        headers=as_user(owner),
    )
    assert bad.status_code == 422


async def test_create_list_rename_delete(api):
    owner, pid = await _ready(api)
    created = await api.post(
        f"/api/projects/{pid}/conversations",
        json={"agent_name": "weather-agent"},
        headers=as_user(owner),
    )
    assert created.status_code == 200
    cid = created.json()["conversation"]["id"]

    listed = await api.get(
        f"/api/projects/{pid}/conversations", headers=as_user(owner)
    )
    assert [c["id"] for c in listed.json()["conversations"]] == [cid]

    renamed = await api.patch(
        f"/api/conversations/{cid}", json={"title": "Weather chat"},
        headers=as_user(owner),
    )
    assert renamed.json()["conversation"]["title"] == "Weather chat"

    assert (
        await api.delete(f"/api/conversations/{cid}", headers=as_user(owner))
    ).status_code == 204
    listed = await api.get(
        f"/api/projects/{pid}/conversations", headers=as_user(owner)
    )
    assert listed.json()["conversations"] == []


async def test_messages_history_visibility(api):
    owner, pid = await _ready(api)
    await api.post(
        "/api/users", json={"email": "s@example.com"}, headers=as_user(owner)
    )
    cid = (
        await api.post(
            f"/api/projects/{pid}/conversations",
            json={"agent_name": "weather-agent"},
            headers=as_user(owner),
        )
    ).json()["conversation"]["id"]

    # stranger (not in project) cannot read
    deny = await api.get(
        f"/api/conversations/{cid}/messages", headers=as_user("s@example.com")
    )
    assert deny.status_code == 403

    ok = await api.get(
        f"/api/conversations/{cid}/messages", headers=as_user(owner)
    )
    assert ok.status_code == 200
    assert ok.json()["messages"] == []


async def test_unknown_conversation_404(api):
    owner, _ = await _ready(api)
    resp = await api.get(
        "/api/conversations/nope/messages", headers=as_user(owner)
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_conversations.py -v`
Expected: FAIL — 404s

- [ ] **Step 3: Implement**

`src/vystak_channel_panel/routes_conversations.py`:

```python
"""Conversation + message-history routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from vystak_channel_panel.models import Conversation, PanelUser
from vystak_channel_panel.routes_projects import require_project_access

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime


class ConversationCreateIn(BaseModel):
    agent_name: str
    title: str = ""


class ConversationPatchIn(BaseModel):
    title: str


async def require_conversation_access(
    rt: "PanelChannelRuntime", conv_id: str, user: PanelUser
) -> Conversation:
    conv = await rt.panel_store.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="unknown conversation")
    await require_project_access(rt, conv.project_id, user)
    return conv


def build_conversations_router(
    rt: "PanelChannelRuntime", current_user
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/projects/{project_id}/conversations")
    async def list_conversations(
        project_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_project_access(rt, project_id, user)
        convs = await rt.panel_store.list_conversations(project_id)
        return {"conversations": [c.model_dump() for c in convs]}

    @router.post("/projects/{project_id}/conversations")
    async def create_conversation(
        project_id: str,
        body: ConversationCreateIn,
        user: PanelUser = Depends(current_user),
    ) -> dict:
        await require_project_access(rt, project_id, user)
        if body.agent_name not in rt.routes:
            raise HTTPException(
                status_code=422,
                detail=f"unknown agent: {body.agent_name}",
            )
        conv = await rt.panel_store.create_conversation(
            project_id, user.id, body.agent_name, title=body.title
        )
        return {"conversation": conv.model_dump()}

    @router.patch("/conversations/{conv_id}")
    async def rename_conversation(
        conv_id: str,
        body: ConversationPatchIn,
        user: PanelUser = Depends(current_user),
    ) -> dict:
        await require_conversation_access(rt, conv_id, user)
        conv = await rt.panel_store.update_conversation(conv_id, title=body.title)
        if conv is None:
            # Deleted between the access check and the update — same 404
            # detail as require_conversation_access, so the two are
            # indistinguishable to the client (and not a 500).
            raise HTTPException(status_code=404, detail="unknown conversation")
        return {"conversation": conv.model_dump()}

    @router.delete("/conversations/{conv_id}", status_code=204)
    async def delete_conversation(
        conv_id: str, user: PanelUser = Depends(current_user)
    ) -> Response:
        await require_conversation_access(rt, conv_id, user)
        await rt.panel_store.delete_conversation(conv_id)
        return Response(status_code=204)

    @router.get("/conversations/{conv_id}/messages")
    async def list_messages(
        conv_id: str, user: PanelUser = Depends(current_user)
    ) -> dict:
        await require_conversation_access(rt, conv_id, user)
        msgs = await rt.panel_store.list_messages(conv_id)
        return {"messages": [m.model_dump() for m in msgs]}

    return router
```

In `routes_registry.py` `mount_routes`, add:

```python
    from vystak_channel_panel.routes_conversations import build_conversations_router

    app.include_router(build_conversations_router(rt, current_user))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): conversation CRUD + message history endpoints"
```

---

### Task 11: Streaming message endpoint (SSE)

**Files:**
- Create: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_messages.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_registry.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_messages_stream.py`

**Interfaces:**
- Consumes: `require_conversation_access` (Task 10), `rt.responses_client.stream_message` + `agent_base_url` (Task 6).
- Produces: `POST /api/conversations/{conv_id}/messages` body `{"text"}` → `text/event-stream` of `data: <json>` lines:
  - `{"type": "delta", "text": "…"}` per token
  - `{"type": "done", "message_id": "…", "response_id": "…", "title": "…"}` once (assistant message + `last_response_id` persisted; auto-title applied)
  - `{"type": "error", "message": "…"}` on agent failure (user message stays persisted)
- Wire contract consumed verbatim by the Next.js adapter (Task 13).

- [ ] **Step 1: Write the failing test**

`tests/test_api_messages_stream.py`:

```python
"""Streaming message endpoint — fake ResponsesClient, no network."""

import json


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}

from vystak_channel_panel.responses_client import PanelStreamEvent


class FakeResponsesClient:
    def __init__(self, events, capture=None):
        self._events = events
        self.capture = capture if capture is not None else {}

    async def stream_message(
        self, base_url, text, *, previous_response_id, user_id=None, project_id=None
    ):
        self.capture.update(
            base_url=base_url, text=text,
            previous_response_id=previous_response_id,
            user_id=user_id, project_id=project_id,
        )
        for ev in self._events:
            yield ev


def _parse_sse(payload: str) -> list[dict]:
    out = []
    for line in payload.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


async def _ready(api):
    await api.post(
        "/api/setup",
        json={"email": "o@example.com", "name": "O", "image": ""},
        headers=as_user("o@example.com"),
    )
    boot = await api.get("/api/bootstrap", headers=as_user("o@example.com"))
    pid = boot.json()["default_project_id"]
    cid = (
        await api.post(
            f"/api/projects/{pid}/conversations",
            json={"agent_name": "weather-agent"},
            headers=as_user("o@example.com"),
        )
    ).json()["conversation"]["id"]
    return "o@example.com", pid, cid


async def test_stream_persists_and_replies(api, panel_rt):
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Hel"),
        PanelStreamEvent(type="token", text="lo"),
        PanelStreamEvent(type="done", response_id="resp_42"),
    ])
    panel_rt.responses_client = fake

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "What is the weather in Kyiv today?"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[-1]["response_id"] == "resp_42"
    assert events[-1]["title"] == "What is the weather in Kyiv today?"

    # base_url derived from routes.json with /a2a stripped; ids threaded
    assert fake.capture["base_url"] == "http://vystak-weather-agent:8000"
    assert fake.capture["previous_response_id"] is None
    assert fake.capture["project_id"] == pid

    # persistence: user + assistant rows, last_response_id set
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "What is the weather in Kyiv today?"),
        ("assistant", "Hello"),
    ]
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] == "resp_42"

    # second turn passes previous_response_id
    panel_rt.responses_client = FakeResponsesClient(
        [PanelStreamEvent(type="done", response_id="resp_42")],
        capture=fake.capture,
    )
    await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "and tomorrow?"},
        headers=as_user(owner),
    )
    assert fake.capture["previous_response_id"] == "resp_42"


async def test_agent_error_keeps_user_message(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"]) for m in msgs] == ["user"]


async def test_truncated_stream_still_persists_streamed_text(api, panel_rt):
    """Agent stream ends with no terminal event (only `data: [DONE]`).
    The text the user already watched stream must not vanish on reload."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="par"),
        PanelStreamEvent(type="token", text="tial"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    assert [e["type"] for e in _parse_sse(resp.text)] == ["delta", "delta", "done"]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hello?"),
        ("assistant", "partial"),
    ]


async def test_empty_text_rejected(api):
    owner, pid, cid = await _ready(api)
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "   "},
        headers=as_user(owner),
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-channel-panel/tests/test_api_messages_stream.py -v`
Expected: FAIL — 404 (route not mounted)

- [ ] **Step 3: Implement**

`src/vystak_channel_panel/routes_messages.py`:

```python
"""Streaming message route — the panel's core chat surface."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser
from vystak_channel_panel.responses_client import agent_base_url
from vystak_channel_panel.routes_conversations import require_conversation_access

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime

logger = logging.getLogger("vystak.channel.panel.messages")

_TITLE_MAX = 60


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class MessageIn(BaseModel):
    text: str


def build_messages_router(rt: "PanelChannelRuntime", current_user) -> APIRouter:
    router = APIRouter(prefix="/api/conversations")

    @router.post("/{conv_id}/messages")
    async def post_message(
        conv_id: str, body: MessageIn, user: PanelUser = Depends(current_user)
    ) -> StreamingResponse:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="text required")
        conv = await require_conversation_access(rt, conv_id, user)
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )
        base_url = agent_base_url(route_entry)

        await rt.panel_store.add_message(conv_id, "user", text)
        title = conv.title
        if not title:
            title = text[:_TITLE_MAX]
            await rt.panel_store.update_conversation(conv_id, title=title)

        async def gen():
            parts: list[str] = []
            done_seen = False
            try:
                async for ev in rt.responses_client.stream_message(
                    base_url,
                    text,
                    previous_response_id=conv.last_response_id,
                    user_id=user.id,
                    project_id=conv.project_id,
                ):
                    if ev.type == "token":
                        parts.append(ev.text)
                        yield _sse({"type": "delta", "text": ev.text})
                    elif ev.type == "done":
                        done_seen = True
                        msg = await rt.panel_store.add_message(
                            conv_id, "assistant", "".join(parts),
                            response_id=ev.response_id,
                        )
                        await rt.panel_store.update_conversation(
                            conv_id, last_response_id=ev.response_id
                        )
                        yield _sse({
                            "type": "done",
                            "message_id": msg.id,
                            "response_id": ev.response_id,
                            "title": title,
                        })
                    elif ev.type == "error":
                        done_seen = True
                        yield _sse({"type": "error", "message": ev.text})
                if not done_seen and parts:
                    # Truncated agent stream: `data: [DONE]` arrived with no
                    # preceding response.completed/failed, so ResponsesClient
                    # yields no terminal event. Persist what we streamed —
                    # otherwise the user watches text appear and finds it gone
                    # on reload. last_response_id is left untouched: no new
                    # agent-side response id was confirmed.
                    msg = await rt.panel_store.add_message(
                        conv_id, "assistant", "".join(parts),
                    )
                    yield _sse({
                        "type": "done",
                        "message_id": msg.id,
                        "response_id": conv.last_response_id or "",
                        "title": title,
                    })
            except Exception as exc:  # noqa: BLE001 — stream must not raise
                logger.exception("panel stream failed for conv=%s", conv_id)
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
```

In `routes_registry.py` `mount_routes`, add:

```python
    from vystak_channel_panel.routes_messages import build_messages_router

    app.include_router(build_messages_router(rt, current_user))
```

- [ ] **Step 4: Run all python gates**

Run: `uv run pytest packages/python/vystak-channel-panel/ -v && just lint-python && just test-python`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-channel-panel
git commit -m "feat(panel): SSE streaming message endpoint with persistence + auto-title"
```

---

### Task 12: Next.js app scaffold (`vystak-panel`)

**Files:**
- Create: `packages/typescript/vystak-panel/package.json`
- Create: `packages/typescript/vystak-panel/tsconfig.json`
- Create: `packages/typescript/vystak-panel/next.config.ts`
- Create: `packages/typescript/vystak-panel/next-env.d.ts`
- Create: `packages/typescript/vystak-panel/vitest.config.ts`
- Create: `packages/typescript/vystak-panel/.env.example`
- Create: `packages/typescript/vystak-panel/app/layout.tsx`
- Create: `packages/typescript/vystak-panel/app/page.tsx`
- Create: `packages/typescript/vystak-panel/app/globals.css`

**Interfaces:**
- Produces: pnpm workspace member `vystak-panel` (private). Scripts: `dev`, `build:app` (NOT `build` — see Global Constraints), `start`, `test` (`vitest run --passWithNoTests`), `typecheck` (`tsc --noEmit`). Env contract: `PANEL_API_URL`, `PANEL_SERVICE_TOKEN`, `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`.

- [ ] **Step 1: Create the package files**

`package.json`:

```json
{
  "name": "vystak-panel",
  "version": "0.1.0",
  "private": true,
  "description": "Vystak control panel UI — Next.js app over the panel channel API",
  "scripts": {
    "dev": "next dev",
    "build:app": "next build",
    "start": "next start",
    "test": "vitest run --passWithNoTests",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@ai-sdk/react": "^2.0.0",
    "ai": "^5.0.0",
    "next": "^15.3.0",
    "next-auth": "5.0.0-beta.29",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.7.0",
    "vitest": "^3.0.0"
  }
}
```

`tsconfig.json` (standalone — does NOT extend `../tsconfig.base.json`, which targets library builds):

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

`next.config.ts`:

```ts
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {};

export default nextConfig;
```

`next-env.d.ts`:

```ts
/// <reference types="next" />
/// <reference types="next/image-types/global" />

// NOTE: This file should not be edited
// see https://nextjs.org/docs/app/api-reference/config/typescript for more information.
```

`vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
  },
});
```

`.env.example`:

```
# Panel channel API (deployed by `vystak apply`)
PANEL_API_URL=http://localhost:18100
PANEL_SERVICE_TOKEN=your-shared-service-token

# Auth.js
AUTH_SECRET=your-auth-secret-generate-with-openssl-rand
AUTH_GOOGLE_ID=your-google-client-id.apps.googleusercontent.com
AUTH_GOOGLE_SECRET=your-google-client-secret
```

`app/globals.css`:

```css
:root {
  color-scheme: light dark;
  font-family: ui-sans-serif, system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; }
```

`app/layout.tsx`:

```tsx
import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Vystak Panel',
  description: 'Control panel for deployed Vystak agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

`app/page.tsx` (placeholder until Task 15 replaces it with the redirect flow):

```tsx
export default function Home() {
  return <main style={{ padding: 24 }}>Vystak Panel</main>;
}
```

- [ ] **Step 2: Install and verify gates**

Run: `pnpm install && just test-typescript && just typecheck-typescript`
Expected: install OK; vitest passes with no tests; typecheck clean. Confirm `pnpm -r run build` (inside typecheck-typescript) does NOT build vystak-panel (no `build` script).

- [ ] **Step 3: Commit**

```bash
git add packages/typescript/vystak-panel pnpm-lock.yaml
git commit -m "feat(panel-ui): Next.js app scaffold (workspace member, gates green)"
```

---

### Task 13: Panel API client lib + SSE→UI-message-stream adapter

**Files:**
- Create: `packages/typescript/vystak-panel/lib/types.ts`
- Create: `packages/typescript/vystak-panel/lib/panel.ts`
- Create: `packages/typescript/vystak-panel/lib/stream.ts`
- Test: `packages/typescript/vystak-panel/tests/stream.test.ts`

**Interfaces:**
- Consumes: channel API JSON + SSE shapes (Tasks 7–11); `UIMessageChunk` from `ai`.
- Produces (lib/types.ts): `PanelUser { id; email; name; image; role: 'admin' | 'member'; status: 'active' | 'deactivated'; created_at }`, `Project { id; name; owner_id; is_default; created_at }`, `Conversation { id; project_id; creator_id; agent_name; title; last_response_id: string | null; created_at; updated_at }`, `PanelMessage { id; conversation_id; role: 'user' | 'assistant'; content; response_id: string | null; created_at }`, `Bootstrap { setup_required: boolean; user: PanelUser | null; agents: string[]; default_project_id: string | null }`.
- Produces (lib/panel.ts, server-only): `panelFetch(user: string | null, path: string, init?: RequestInit): Promise<Response>` plus typed helpers `getBootstrap(email)`, `setupAdmin({email, name, image})`, `listProjects(email)`, `createProject(email, name)`, `deleteProject(email, id)`, `listMembers(email, id)`, `addMember(email, id, memberEmail)`, `removeMember(email, id, userId)`, `listUsers(email)`, `addUser(email, newEmail, role)`, `patchUser(email, userId, patch)`, `listConversations(email, projectId)`, `createConversation(email, projectId, agentName)`, `deleteConversation(email, convId)`, `listMessages(email, convId)`, `streamConversationMessage(email, convId, text): Promise<Response>`.
- Produces (lib/stream.ts): `panelStreamToUIChunks(body: ReadableStream<Uint8Array>): ReadableStream<UIMessageChunk>`.

- [ ] **Step 1: Write the failing test**

`tests/stream.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { panelStreamToUIChunks } from '../lib/stream';

function sseBody(...payloads: (object | string)[]): ReadableStream<Uint8Array> {
  const text = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}\n\n`)
    .join('');
  return new Blob([text]).stream() as ReadableStream<Uint8Array>;
}

async function collect(stream: ReadableStream<unknown>): Promise<unknown[]> {
  const out: unknown[] = [];
  const reader = stream.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    out.push(value);
  }
  return out;
}

describe('panelStreamToUIChunks', () => {
  it('maps deltas to a text part between start and finish', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          { type: 'delta', text: 'Hel' },
          { type: 'delta', text: 'lo' },
          { type: 'done', message_id: 'm1', response_id: 'r1', title: 'T' },
        ),
      ),
    );
    expect(chunks).toEqual([
      { type: 'start' },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'Hel' },
      { type: 'text-delta', id: 'panel-text', delta: 'lo' },
      { type: 'text-end', id: 'panel-text' },
      { type: 'finish' },
    ]);
  });

  it('maps error events to error chunks', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(sseBody({ type: 'error', message: 'boom' })),
    );
    expect(chunks[0]).toEqual({ type: 'start' });
    expect(chunks).toContainEqual({ type: 'error', errorText: 'boom' });
    expect(chunks[chunks.length - 1]).toEqual({ type: 'finish' });
  });

  it('done without any delta still emits valid start/finish', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody({ type: 'done', message_id: 'm1', response_id: 'r1', title: '' }),
      ),
    );
    expect(chunks).toEqual([{ type: 'start' }, { type: 'finish' }]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter vystak-panel test`
Expected: FAIL — cannot resolve `../lib/stream`

- [ ] **Step 3: Implement**

`lib/types.ts`:

```ts
export interface PanelUser {
  id: string;
  email: string;
  name: string;
  image: string;
  role: 'admin' | 'member';
  status: 'active' | 'deactivated';
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  owner_id: string;
  is_default: boolean;
  created_at: string;
}

export interface Conversation {
  id: string;
  project_id: string;
  creator_id: string;
  agent_name: string;
  title: string;
  last_response_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PanelMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  response_id: string | null;
  created_at: string;
}

export interface Bootstrap {
  setup_required: boolean;
  user: PanelUser | null;
  agents: string[];
  default_project_id: string | null;
}
```

`lib/panel.ts`:

```ts
import 'server-only';
import type {
  Bootstrap,
  Conversation,
  PanelMessage,
  PanelUser,
  Project,
} from './types';

const API_URL = () => process.env.PANEL_API_URL ?? 'http://localhost:18100';
const TOKEN = () => process.env.PANEL_SERVICE_TOKEN ?? '';

export async function panelFetch(
  user: string | null,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${TOKEN()}`);
  if (user) headers.set('X-Panel-User', user);
  if (init.body) headers.set('Content-Type', 'application/json');
  return fetch(`${API_URL()}${path}`, { ...init, headers, cache: 'no-store' });
}

async function json<T>(user: string | null, path: string, init?: RequestInit): Promise<T> {
  const resp = await panelFetch(user, path, init);
  if (!resp.ok) throw new Error(`panel API ${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

export const getBootstrap = (email: string) =>
  json<Bootstrap>(email, '/api/bootstrap');

// The channel requires X-Panel-User on /api/setup and rejects a body email
// that disagrees with it, so the acting email is sent as the user here — it
// must not be null.
export const setupAdmin = (body: { email: string; name: string; image: string }) =>
  json<{ user: PanelUser }>(body.email, '/api/setup', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const listProjects = (email: string) =>
  json<{ projects: Project[] }>(email, '/api/projects');

export const createProject = (email: string, name: string) =>
  json<{ project: Project }>(email, '/api/projects', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

export const deleteProject = (email: string, id: string) =>
  panelFetch(email, `/api/projects/${id}`, { method: 'DELETE' });

export const listMembers = (email: string, id: string) =>
  json<{ members: PanelUser[] }>(email, `/api/projects/${id}/members`);

export const addMember = (email: string, id: string, memberEmail: string) =>
  panelFetch(email, `/api/projects/${id}/members`, {
    method: 'POST',
    body: JSON.stringify({ email: memberEmail }),
  });

export const removeMember = (email: string, id: string, userId: string) =>
  panelFetch(email, `/api/projects/${id}/members/${userId}`, {
    method: 'DELETE',
  });

export const listUsers = (email: string) =>
  json<{ users: PanelUser[] }>(email, '/api/users');

export const addUser = (email: string, newEmail: string, role: string) =>
  panelFetch(email, '/api/users', {
    method: 'POST',
    body: JSON.stringify({ email: newEmail, role }),
  });

export const patchUser = (
  email: string,
  userId: string,
  patch: { role?: string; status?: string },
) =>
  panelFetch(email, `/api/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const listConversations = (email: string, projectId: string) =>
  json<{ conversations: Conversation[] }>(
    email,
    `/api/projects/${projectId}/conversations`,
  );

export const createConversation = (
  email: string,
  projectId: string,
  agentName: string,
) =>
  json<{ conversation: Conversation }>(
    email,
    `/api/projects/${projectId}/conversations`,
    { method: 'POST', body: JSON.stringify({ agent_name: agentName }) },
  );

export const deleteConversation = (email: string, convId: string) =>
  panelFetch(email, `/api/conversations/${convId}`, { method: 'DELETE' });

export const listMessages = (email: string, convId: string) =>
  json<{ messages: PanelMessage[] }>(
    email,
    `/api/conversations/${convId}/messages`,
  );

export const streamConversationMessage = (
  email: string,
  convId: string,
  text: string,
) =>
  panelFetch(email, `/api/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
```

Add `server-only` to dependencies:

Run: `pnpm --filter vystak-panel add server-only`

`lib/stream.ts` (no `server-only` import — it must stay unit-testable):

```ts
import type { UIMessageChunk } from 'ai';

const TEXT_ID = 'panel-text';

/**
 * Adapt the panel channel's plain SSE ({type: delta|done|error}) into the
 * AI SDK UI message stream chunks consumed by useChat. The Python side
 * stays protocol-neutral; this is the only Vercel-specific encoding.
 */
export function panelStreamToUIChunks(
  body: ReadableStream<Uint8Array>,
): ReadableStream<UIMessageChunk> {
  const decoder = new TextDecoder();
  let buffer = '';
  let textOpen = false;

  return new ReadableStream<UIMessageChunk>({
    async start(controller) {
      controller.enqueue({ type: 'start' });
      const reader = body.getReader();
      const handleLine = (line: string) => {
        if (!line.startsWith('data: ')) return;
        let payload: { type?: string; text?: string; message?: string };
        try {
          payload = JSON.parse(line.slice(6));
        } catch {
          return;
        }
        if (payload.type === 'delta') {
          if (!textOpen) {
            controller.enqueue({ type: 'text-start', id: TEXT_ID });
            textOpen = true;
          }
          controller.enqueue({
            type: 'text-delta',
            id: TEXT_ID,
            delta: payload.text ?? '',
          });
        } else if (payload.type === 'error') {
          if (textOpen) {
            controller.enqueue({ type: 'text-end', id: TEXT_ID });
            textOpen = false;
          }
          controller.enqueue({
            type: 'error',
            errorText: payload.message ?? 'stream error',
          });
        }
        // 'done' carries persistence ids the UI refetches via the API.
      };
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) handleLine(line.trim());
        }
        if (buffer.trim()) handleLine(buffer.trim());
      } finally {
        if (textOpen) controller.enqueue({ type: 'text-end', id: TEXT_ID });
        controller.enqueue({ type: 'finish' });
        controller.close();
      }
    },
  });
}
```

- [ ] **Step 4: Run tests + typecheck**

Run: `pnpm --filter vystak-panel test && just typecheck-typescript`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel pnpm-lock.yaml
git commit -m "feat(panel-ui): typed panel API client + SSE to UI-message-stream adapter"
```

---

### Task 14: Auth.js — Google sign-in, setup flow, sign-in page

**Files:**
- Create: `packages/typescript/vystak-panel/lib/auth-policy.ts`
- Create: `packages/typescript/vystak-panel/auth.ts`
- Create: `packages/typescript/vystak-panel/app/api/auth/[...nextauth]/route.ts`
- Create: `packages/typescript/vystak-panel/app/signin/page.tsx`
- Test: `packages/typescript/vystak-panel/tests/auth-policy.test.ts`

**Interfaces:**
- Consumes: `getBootstrap`, `setupAdmin` (Task 13).
- Produces: `auth.ts` exports `{ handlers, auth, signIn, signOut }` (Auth.js v5). Pure decision fn `evaluateSignIn(bootstrap: Bootstrap): 'setup' | 'allow' | 'deny'` in `lib/auth-policy.ts`. Sign-in rule: `setup` when `setup_required`; `allow` when `user` non-null (channel already filters inactive to null); else `deny`. Session strategy JWT; `session.user.email` is the identity every server call uses.

- [ ] **Step 1: Write the failing test**

`tests/auth-policy.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { evaluateSignIn } from '../lib/auth-policy';
import type { Bootstrap } from '../lib/types';

const base: Bootstrap = {
  setup_required: false,
  user: null,
  agents: [],
  default_project_id: null,
};

const user = {
  id: 'u1',
  email: 'a@example.com',
  name: 'A',
  image: '',
  role: 'member' as const,
  status: 'active' as const,
  created_at: '2026-01-01T00:00:00Z',
};

describe('evaluateSignIn', () => {
  it('first ever sign-in claims setup', () => {
    expect(evaluateSignIn({ ...base, setup_required: true })).toBe('setup');
  });
  it('known active user allowed', () => {
    expect(evaluateSignIn({ ...base, user })).toBe('allow');
  });
  it('unknown user denied after setup', () => {
    expect(evaluateSignIn(base)).toBe('deny');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter vystak-panel test`
Expected: FAIL — cannot resolve `../lib/auth-policy`

- [ ] **Step 3: Implement**

`lib/auth-policy.ts`:

```ts
import type { Bootstrap } from './types';

export type SignInDecision = 'setup' | 'allow' | 'deny';

/** Channel is the authority: bootstrap.user is null for unknown or
 * deactivated emails, so 'allow' means an active invited user. */
export function evaluateSignIn(bootstrap: Bootstrap): SignInDecision {
  if (bootstrap.setup_required) return 'setup';
  return bootstrap.user !== null ? 'allow' : 'deny';
}
```

`auth.ts`:

```ts
import NextAuth from 'next-auth';
import Google from 'next-auth/providers/google';
import { evaluateSignIn } from '@/lib/auth-policy';
import { getBootstrap, setupAdmin } from '@/lib/panel';

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: 'jwt' },
  pages: { signIn: '/signin' },
  callbacks: {
    async signIn({ user }) {
      const email = user.email?.toLowerCase();
      if (!email) return false;
      const bootstrap = await getBootstrap(email);
      const decision = evaluateSignIn(bootstrap);
      if (decision === 'setup') {
        await setupAdmin({
          email,
          name: user.name ?? '',
          image: user.image ?? '',
        });
        return true;
      }
      return decision === 'allow';
    },
  },
});
```

`app/api/auth/[...nextauth]/route.ts`:

```ts
import { handlers } from '@/auth';

export const { GET, POST } = handlers;
```

`app/signin/page.tsx`:

```tsx
import { redirect } from 'next/navigation';
import { auth, signIn } from '@/auth';

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const session = await auth();
  if (session?.user?.email) redirect('/');
  const { error } = await searchParams;
  return (
    <main style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
      <form
        action={async () => {
          'use server';
          await signIn('google', { redirectTo: '/' });
        }}
      >
        <h1>Vystak Panel</h1>
        <p>Sign in with your invited Google account.</p>
        {error === 'AccessDenied' && (
          <p style={{ color: 'crimson' }}>
            This Google account has not been invited. Ask an administrator to
            add your email.
          </p>
        )}
        <button type="submit">Sign in with Google</button>
      </form>
    </main>
  );
}
```

(Auth.js redirects rejected sign-ins back to the `pages.signIn` route with `?error=AccessDenied` — this is the spec's "not invited" screen.)

- [ ] **Step 4: Run tests + typecheck**

Run: `pnpm --filter vystak-panel test && just typecheck-typescript`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel
git commit -m "feat(panel-ui): Google sign-in via Auth.js with channel-backed authorization + first-run setup"
```

---

### Task 15: App shell — projects sidebar, conversations, server actions

**Files:**
- Create: `packages/typescript/vystak-panel/app/actions.ts`
- Modify: `packages/typescript/vystak-panel/app/page.tsx` (redirect to default project)
- Create: `packages/typescript/vystak-panel/app/p/[projectId]/layout.tsx`
- Create: `packages/typescript/vystak-panel/app/p/[projectId]/page.tsx`
- Create: `packages/typescript/vystak-panel/components/sidebar.tsx`
- Create: `packages/typescript/vystak-panel/components/new-conversation.tsx`

**Interfaces:**
- Consumes: `auth()` (Task 14), panel client (Task 13).
- Produces: `/` redirects → `/signin` (no session), or `/p/<default_project_id>`; project page lists conversations + new-conversation form; sidebar shows projects + create-project form. Server actions: `createProjectAction(formData)`, `createConversationAction(projectId, formData)` (redirects to `/p/{projectId}/c/{id}`), `deleteConversationAction(projectId, convId)`. All actions re-derive the email from `auth()` — never trust client-passed identity.

- [ ] **Step 1: Implement**

`app/actions.ts`:

```ts
'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import {
  addMember,
  addUser,
  createConversation,
  createProject,
  deleteConversation,
  patchUser,
  removeMember,
} from '@/lib/panel';

async function requireEmail(): Promise<string> {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  return email;
}

export async function createProjectAction(formData: FormData) {
  const email = await requireEmail();
  const name = String(formData.get('name') ?? '').trim();
  if (!name) return;
  const { project } = await createProject(email, name);
  redirect(`/p/${project.id}`);
}

export async function createConversationAction(
  projectId: string,
  formData: FormData,
) {
  const email = await requireEmail();
  const agentName = String(formData.get('agent') ?? '');
  if (!agentName) return;
  const { conversation } = await createConversation(email, projectId, agentName);
  redirect(`/p/${projectId}/c/${conversation.id}`);
}

export async function deleteConversationAction(
  projectId: string,
  convId: string,
) {
  const email = await requireEmail();
  await deleteConversation(email, convId);
  revalidatePath(`/p/${projectId}`);
}

export async function addMemberAction(projectId: string, formData: FormData) {
  const email = await requireEmail();
  const memberEmail = String(formData.get('email') ?? '').trim();
  if (memberEmail) await addMember(email, projectId, memberEmail);
  revalidatePath(`/p/${projectId}`);
}

export async function removeMemberAction(projectId: string, userId: string) {
  const email = await requireEmail();
  await removeMember(email, projectId, userId);
  revalidatePath(`/p/${projectId}`);
}

export async function addUserAction(formData: FormData) {
  const email = await requireEmail();
  const newEmail = String(formData.get('email') ?? '').trim();
  const role = String(formData.get('role') ?? 'member');
  if (newEmail) await addUser(email, newEmail, role);
  revalidatePath('/admin/users');
}

export async function setUserStatusAction(userId: string, status: string) {
  const email = await requireEmail();
  await patchUser(email, userId, { status });
  revalidatePath('/admin/users');
}
```

`app/page.tsx` (replace placeholder):

```tsx
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { getBootstrap } from '@/lib/panel';

export default async function Home() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user || !bootstrap.default_project_id) redirect('/signin');
  redirect(`/p/${bootstrap.default_project_id}`);
}
```

`components/sidebar.tsx`:

```tsx
import Link from 'next/link';
import { createProjectAction } from '@/app/actions';
import type { PanelUser, Project } from '@/lib/types';

export function Sidebar({
  projects,
  activeProjectId,
  user,
}: {
  projects: Project[];
  activeProjectId: string;
  user: PanelUser;
}) {
  return (
    <nav style={{ width: 240, borderRight: '1px solid #ccc', padding: 12 }}>
      <h2 style={{ fontSize: 16 }}>Projects</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {projects.map(p => (
          <li key={p.id} style={{ margin: '4px 0' }}>
            <Link
              href={`/p/${p.id}`}
              style={{ fontWeight: p.id === activeProjectId ? 700 : 400 }}
            >
              {p.name}
            </Link>
          </li>
        ))}
      </ul>
      <form action={createProjectAction}>
        <input name="name" placeholder="New project" required />
        <button type="submit">Add</button>
      </form>
      {user.role === 'admin' && (
        <p>
          <Link href="/admin/users">Manage users</Link>
        </p>
      )}
    </nav>
  );
}
```

`components/new-conversation.tsx`:

```tsx
import { createConversationAction } from '@/app/actions';

export function NewConversation({
  projectId,
  agents,
}: {
  projectId: string;
  agents: string[];
}) {
  const action = createConversationAction.bind(null, projectId);
  return (
    <form action={action} style={{ display: 'flex', gap: 8 }}>
      <select name="agent" required defaultValue="">
        <option value="" disabled>
          Choose an agent…
        </option>
        {agents.map(a => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      <button type="submit">New conversation</button>
    </form>
  );
}
```

`app/p/[projectId]/layout.tsx`:

```tsx
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { Sidebar } from '@/components/sidebar';
import { getBootstrap, listProjects } from '@/lib/panel';

export default async function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin');
  const { projects } = await listProjects(email);
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar
        projects={projects}
        activeProjectId={projectId}
        user={bootstrap.user}
      />
      <main style={{ flex: 1, padding: 16 }}>{children}</main>
    </div>
  );
}
```

`app/p/[projectId]/page.tsx`:

```tsx
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { NewConversation } from '@/components/new-conversation';
import { getBootstrap, listConversations } from '@/lib/panel';

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const [bootstrap, { conversations }] = await Promise.all([
    getBootstrap(email),
    listConversations(email, projectId),
  ]);
  return (
    <div>
      <NewConversation projectId={projectId} agents={bootstrap.agents} />
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {conversations.map(c => (
          <li key={c.id} style={{ margin: '8px 0' }}>
            <Link href={`/p/${projectId}/c/${c.id}`}>
              {c.title || '(untitled)'}{' '}
              <small>· {c.agent_name}</small>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Verify gates**

Run: `pnpm --filter vystak-panel test && just typecheck-typescript`
Expected: PASS / clean

- [ ] **Step 3: Commit**

```bash
git add packages/typescript/vystak-panel
git commit -m "feat(panel-ui): app shell — projects sidebar, conversation list, server actions"
```

---

### Task 16: Chat — /api/chat route + useChat component

**Files:**
- Create: `packages/typescript/vystak-panel/app/api/chat/route.ts`
- Create: `packages/typescript/vystak-panel/components/chat.tsx`
- Create: `packages/typescript/vystak-panel/app/p/[projectId]/c/[convId]/page.tsx`

**Interfaces:**
- Consumes: `streamConversationMessage`, `listMessages` (Task 13), `panelStreamToUIChunks` (Task 13), `auth` (Task 14).
- Produces: `POST /api/chat` body `{ conversationId: string, text: string }` → AI SDK UI message stream response. `Chat` client component: `useChat` + `DefaultChatTransport` with `prepareSendMessagesRequest` sending `{conversationId, text}`; history preloaded from the channel DB via `messages` prop.

- [ ] **Step 1: Implement the route**

`app/api/chat/route.ts`:

```ts
import { createUIMessageStreamResponse } from 'ai';
import { auth } from '@/auth';
import { streamConversationMessage } from '@/lib/panel';
import { panelStreamToUIChunks } from '@/lib/stream';

export async function POST(req: Request) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });

  const { conversationId, text } = (await req.json()) as {
    conversationId?: string;
    text?: string;
  };
  if (!conversationId || !text?.trim()) {
    return new Response('conversationId and text required', { status: 400 });
  }

  const upstream = await streamConversationMessage(email, conversationId, text);
  if (!upstream.ok || !upstream.body) {
    return new Response(`panel channel error: ${upstream.status}`, {
      status: 502,
    });
  }
  return createUIMessageStreamResponse({
    stream: panelStreamToUIChunks(upstream.body),
  });
}
```

- [ ] **Step 2: Implement the chat component**

`components/chat.tsx`:

```tsx
'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';
import type { UIMessage } from 'ai';

export function Chat({
  conversationId,
  initialMessages,
  agentName,
}: {
  conversationId: string;
  initialMessages: UIMessage[];
  agentName: string;
}) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, error } = useChat({
    id: conversationId,
    messages: initialMessages,
    transport: new DefaultChatTransport({
      api: '/api/chat',
      prepareSendMessagesRequest({ messages }) {
        const last = messages[messages.length - 1];
        const text = last.parts
          .filter(p => p.type === 'text')
          .map(p => p.text)
          .join('');
        return { body: { conversationId, text } };
      },
    }),
  });

  return (
    <div style={{ maxWidth: 720 }}>
      <p>
        <small>Talking to {agentName}</small>
      </p>
      {messages.map(message => (
        <div key={message.id} style={{ margin: '12px 0' }}>
          <strong>{message.role === 'user' ? 'You' : agentName}: </strong>
          {message.parts.map((part, i) =>
            part.type === 'text' ? (
              <span key={i} style={{ whiteSpace: 'pre-wrap' }}>
                {part.text}
              </span>
            ) : null,
          )}
        </div>
      ))}
      {error && (
        <p style={{ color: 'crimson' }}>Agent error: {error.message}</p>
      )}
      <form
        onSubmit={e => {
          e.preventDefault();
          if (!input.trim() || status !== 'ready') return;
          sendMessage({ text: input });
          setInput('');
        }}
      >
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Message the agent…"
          style={{ width: '80%' }}
        />
        <button type="submit" disabled={status !== 'ready'}>
          Send
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Implement the conversation page**

`app/p/[projectId]/c/[convId]/page.tsx`:

```tsx
import { redirect } from 'next/navigation';
import type { UIMessage } from 'ai';
import { auth } from '@/auth';
import { Chat } from '@/components/chat';
import { listConversations, listMessages } from '@/lib/panel';

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ projectId: string; convId: string }>;
}) {
  const { projectId, convId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');

  const [{ conversations }, { messages }] = await Promise.all([
    listConversations(email, projectId),
    listMessages(email, convId),
  ]);
  const conversation = conversations.find(c => c.id === convId);
  if (!conversation) redirect(`/p/${projectId}`);

  const initialMessages: UIMessage[] = messages.map(m => ({
    id: m.id,
    role: m.role,
    parts: [{ type: 'text', text: m.content }],
  }));

  return (
    <Chat
      conversationId={convId}
      initialMessages={initialMessages}
      agentName={conversation.agent_name}
    />
  );
}
```

- [ ] **Step 4: Verify gates**

Run: `pnpm --filter vystak-panel test && just typecheck-typescript && just test-typescript`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/vystak-panel
git commit -m "feat(panel-ui): streaming chat via useChat over the panel channel"
```

---

### Task 17: Admin users page + project members panel

**Files:**
- Create: `packages/typescript/vystak-panel/app/admin/users/page.tsx`
- Create: `packages/typescript/vystak-panel/components/members.tsx`
- Modify: `packages/typescript/vystak-panel/app/p/[projectId]/page.tsx` (mount members panel)

**Interfaces:**
- Consumes: `listUsers`, `addUserAction`, `setUserStatusAction`, `listMembers`, `addMemberAction`, `removeMemberAction` (Tasks 13/15).
- Produces: `/admin/users` (admin-gated in page, channel enforces server-side anyway); members panel on the project page (owner-only mutations enforced by the channel; UI shows it to everyone with access).

- [ ] **Step 1: Implement**

`app/admin/users/page.tsx`:

```tsx
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { addUserAction, setUserStatusAction } from '@/app/actions';
import { getBootstrap, listUsers } from '@/lib/panel';

export default async function UsersPage() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (bootstrap.user?.role !== 'admin') redirect('/');
  const { users } = await listUsers(email);

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Users</h1>
      <form action={addUserAction} style={{ display: 'flex', gap: 8 }}>
        <input name="email" type="email" placeholder="person@example.com" required />
        <select name="role" defaultValue="member">
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button type="submit">Invite</button>
      </form>
      <table style={{ marginTop: 16, width: '100%' }}>
        <tbody>
          {users.map(u => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.role}</td>
              <td>{u.status}</td>
              <td>
                <form
                  action={setUserStatusAction.bind(
                    null,
                    u.id,
                    u.status === 'active' ? 'deactivated' : 'active',
                  )}
                >
                  <button type="submit">
                    {u.status === 'active' ? 'Deactivate' : 'Reactivate'}
                  </button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
```

`components/members.tsx`:

```tsx
import { addMemberAction, removeMemberAction } from '@/app/actions';
import type { PanelUser } from '@/lib/types';

export function Members({
  projectId,
  members,
}: {
  projectId: string;
  members: PanelUser[];
}) {
  const add = addMemberAction.bind(null, projectId);
  return (
    <section style={{ marginTop: 24 }}>
      <h3 style={{ fontSize: 14 }}>Shared with</h3>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {members.map(m => (
          <li key={m.id}>
            {m.email}{' '}
            <form
              action={removeMemberAction.bind(null, projectId, m.id)}
              style={{ display: 'inline' }}
            >
              <button type="submit">Remove</button>
            </form>
          </li>
        ))}
      </ul>
      <form action={add} style={{ display: 'flex', gap: 8 }}>
        <input name="email" type="email" placeholder="Share by email" required />
        <button type="submit">Share</button>
      </form>
    </section>
  );
}
```

In `app/p/[projectId]/page.tsx`, extend the Promise.all to also fetch members and render `<Members projectId={projectId} members={members} />` after the conversation list:

```tsx
import { Members } from '@/components/members';
import { getBootstrap, listConversations, listMembers } from '@/lib/panel';
// …
  const [bootstrap, { conversations }, { members }] = await Promise.all([
    getBootstrap(email),
    listConversations(email, projectId),
    listMembers(email, projectId),
  ]);
// … after the </ul>:
      <Members projectId={projectId} members={members} />
```

- [ ] **Step 2: Verify gates**

Run: `pnpm --filter vystak-panel test && just typecheck-typescript`
Expected: PASS / clean

- [ ] **Step 3: Commit**

```bash
git add packages/typescript/vystak-panel
git commit -m "feat(panel-ui): admin user management + project sharing UI"
```

---

### Task 18: Example, docs, and final verification

**Files:**
- Create: `examples/docker-panel/vystak.py`
- Create: `examples/docker-panel/README.md`
- Copy: `examples/docker-multi-chat/{Dockerfile,requirements.txt,server.py,pyproject.toml,tools/,_vystak/}` → `examples/docker-panel/`
- Modify: `CLAUDE.md` (package lists)

**Interfaces:** none new — end-to-end wiring of everything above.

- [ ] **Step 1: Create the example**

```bash
mkdir -p examples/docker-panel
cp -R examples/docker-multi-chat/Dockerfile examples/docker-multi-chat/requirements.txt \
      examples/docker-multi-chat/server.py examples/docker-multi-chat/pyproject.toml \
      examples/docker-multi-chat/tools examples/docker-multi-chat/_vystak \
      examples/docker-panel/
```

`examples/docker-panel/vystak.py` (same two agents as docker-multi-chat, panel channel instead of chat — copy the provider/platform/model/agent blocks from `examples/docker-multi-chat/vystak.py` verbatim, then replace the channel with):

```python
panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={"port": 18100},
    agents=[weather_agent, time_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
```

(Also update the module docstring: the panel API listens on http://localhost:18100; the Next.js UI connects to it.)

`examples/docker-panel/README.md`:

```markdown
# docker-panel — control panel over two agents

Deploys two agents (weather, time) plus the `panel` channel: the control-panel
API container (users, projects, conversations, SSE streaming).

## Deploy the stack

    export ANTHROPIC_API_KEY=sk-ant-...
    export PANEL_SERVICE_TOKEN=$(openssl rand -hex 24)
    vystak apply

The panel API is now at http://localhost:18100 (try `GET /health`).

## Run the control panel UI

The UI is the `vystak-panel` Next.js app (not deployed by `vystak apply`):

    cd packages/typescript/vystak-panel
    cp .env.example .env.local   # fill in:
    #   PANEL_API_URL=http://localhost:18100
    #   PANEL_SERVICE_TOKEN=<same value as above>
    #   AUTH_SECRET=$(openssl rand -base64 32)
    #   AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET from your Google OAuth client
    pnpm --filter vystak-panel dev

Open http://localhost:3000 — the first Google account to sign in becomes the
admin; invite others from /admin/users.

## Tear down

    vystak destroy
```

- [ ] **Step 2: Verify the example loads and plans**

Run: `cd examples/docker-panel && uv run vystak plan && cd ../..`
Expected: plan output lists both agents and the `panel` channel; no errors. (Full `vystak apply` verification needs Docker + real keys — do it if the daemon is available.)

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`:
- Channels list: add `- **`vystak-channel-panel`** — control-panel REST + SSE API (users, projects, conversations); consumed by the `vystak-panel` Next.js app.`
- TS packages line: amend to note `vystak-panel` is a real Next.js app (the other TS packages remain stubs).
- Examples paragraph: add `docker-panel` (control panel).

- [ ] **Step 4: Full verification — all four live gates**

Run: `just ci-live`
Expected: `lint-python`, `typecheck-typescript`, `test-python`, `test-typescript` all pass.

- [ ] **Step 5: Commit**

```bash
git add examples/docker-panel CLAUDE.md
git commit -m "feat(panel): docker-panel example + docs"
```

---

## Deferred (explicitly out of this plan)

- Postgres backend for the panel store (spec lists it as an option; the `state` service plumbing exists when needed).
- `release_smoke` cell for the panel channel (add `test_panel_smoke.py` under `vystak-provider-docker/tests/release/` in a follow-up).
- Azure provider support for the panel channel (`ChannelType.PANEL` branch in ACA nodes).
- Heartbeat delivery into panel conversations (`deliver_message` is a logged no-op, same as chat).
