# Panel Password Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin-provisioned password login for the control panel, enabled by `PANEL_PASSWORD_AUTH=1` on the Next app, per `docs/superpowers/specs/2026-07-25-panel-password-auth-design.md`.

**Architecture:** Passwords live in the panel channel's users store (bcrypt hash, schema v3). The channel exposes an admin-gated set-password endpoint and a service-token-gated verify endpoint. The Next app conditionally registers a NextAuth Credentials provider whose `authorize` delegates to the channel; the existing allow-list `signIn` callback governs both providers unchanged.

**Tech Stack:** Python 3.11+ / FastAPI / aiosqlite / `bcrypt` (new dep); Next.js 15 / next-auth 5 beta.

## Global Constraints

- The four live gates stay green after every task: `just lint-python`, `just typecheck-typescript`, `just test-python`, `just test-typescript`.
- **Never run `just fmt-python`** (reformats ~197 unrelated files).
- No `build` script in `packages/typescript/vystak-panel/package.json` (only `build:app`).
- Public repo: test passwords are obvious fakes (`testpass-…`); examples use placeholders.
- With `PANEL_PASSWORD_AUTH` unset, the sign-in page and provider list are byte-identical to today.
- The password hash never appears in any API response: every user-shaped payload derives `has_password` and drops the hash at the store boundary.
- `POST /api/auth/verify` returns the identical `{"ok": false, "user": null}` body for wrong-password, unknown-email, no-password-set, and deactivated-user.
- Minimum password length 8, enforced channel-side (422).
- Working-tree caution: unrelated dirty files exist (`examples/docker-panel/_vystak/*`, `next-env.d.ts`). Stage only files this plan names; never `git add -A` at repo root.
- Python test baseline: `uv run pytest packages/python/vystak-channel-panel/ -v` currently passes; one pre-existing repo-wide `UserWarning` about `Workspace.copy` appears in full-suite runs — any *additional* warning is a finding.

---

### Task 1: Store layer — schema v3, bcrypt helpers, `has_password`

**Files:**
- Modify: `packages/python/vystak-channel-panel/pyproject.toml` (add `bcrypt>=4.0` to dependencies)
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/models.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/store.py`
- Test: `packages/python/vystak-channel-panel/tests/test_store_passwords.py` (new)
- Test: `packages/python/vystak-channel-panel/tests/test_store_migrations.py` (extend)

**Interfaces:**
- Consumes: existing `_write()` / `_migrate()` machinery, `PanelUser` model.
- Produces:
  - `PanelUser.has_password: bool = False`
  - `SqlitePanelStore.set_user_password(user_id: str, password: str) -> bool` (False = no such user)
  - `SqlitePanelStore.verify_user_password(email: str, password: str) -> PanelUser | None`
  - `SCHEMA_VERSION = 3`; `users.password_hash TEXT` nullable column on fresh and migrated DBs
  - `_user_from_row` used by all user readers — `has_password` derived, hash never in a `PanelUser`.

- [ ] **Step 1: Add the dependency**

In `packages/python/vystak-channel-panel/pyproject.toml`, add `"bcrypt>=4.0"` to the `dependencies` list, then:

```bash
uv sync
```

- [ ] **Step 2: Write the failing tests** — `tests/test_store_passwords.py`. Follow the fixture style of the existing store tests (check `tests/conftest.py` / `test_store_conversations.py` for the established store fixture; if none fits, build the store locally as below):

```python
"""Password hashing/verification on the panel store."""

from __future__ import annotations

import pytest

from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


async def test_set_and_verify_roundtrip(store):
    user = await store.create_user("alice@example.com")
    assert await store.set_user_password(user.id, "testpass-alice-1") is True
    verified = await store.verify_user_password("alice@example.com", "testpass-alice-1")
    assert verified is not None
    assert verified.id == user.id
    assert verified.has_password is True


async def test_wrong_password_returns_none(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    assert await store.verify_user_password("alice@example.com", "wrongpass-000") is None


async def test_unknown_email_returns_none(store):
    assert await store.verify_user_password("ghost@example.com", "testpass-x") is None


async def test_no_password_set_returns_none(store):
    await store.create_user("alice@example.com")
    assert await store.verify_user_password("alice@example.com", "testpass-x") is None


async def test_deactivated_user_returns_none(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    await store.update_user(user.id, status="deactivated")
    assert await store.verify_user_password("alice@example.com", "testpass-alice-1") is None


async def test_overwrite_replaces_old_password(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-old-1")
    await store.set_user_password(user.id, "testpass-new-2")
    assert await store.verify_user_password("alice@example.com", "testpass-old-1") is None
    assert await store.verify_user_password("alice@example.com", "testpass-new-2") is not None


async def test_set_password_unknown_user_returns_false(store):
    assert await store.set_user_password("nope", "testpass-x-1") is False


async def test_hash_never_in_user_payloads(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    for u in (
        await store.get_user(user.id),
        await store.get_user_by_email("alice@example.com"),
        *(await store.list_users()),
    ):
        assert "password_hash" not in u.model_dump()
        assert u.has_password is True


async def test_verify_email_is_case_insensitive(store):
    user = await store.create_user("Alice@Example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    assert await store.verify_user_password("ALICE@example.com", "testpass-alice-1") is not None
```

Extend `tests/test_store_migrations.py` with a v2→v3 case (mirror the file's existing v1-shaped-DB construction style):

```python
async def test_migrates_v2_to_v3_adds_password_hash(tmp_path):
    """A v2 database (messages.parts present, users.password_hash absent,
    schema_version=2) gains the password_hash column without disturbing rows."""
    db_path = tmp_path / "panel.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        # v2 shape: users WITHOUT password_hash, messages WITH parts.
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL,
            response_id TEXT, parts TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings (key, value) VALUES ('schema_version', '2');
        INSERT INTO users (id, email, role, created_at)
            VALUES ('u1', 'admin@example.com', 'admin', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = SqlitePanelStore(db_path)
    await store.connect()
    try:
        async with store.db.execute("PRAGMA table_info(users)") as cur:
            columns = {row["name"] async for row in cur}
        assert "password_hash" in columns
        assert await store.get_setting("schema_version") == "3"
        user = await store.get_user("u1")
        assert user is not None and user.email == "admin@example.com"
        assert user.has_password is False
        # Idempotent: reconnecting is a no-op.
        await store.close()
        store2 = SqlitePanelStore(db_path)
        await store2.connect()
        assert await store2.get_setting("schema_version") == "3"
        await store2.close()
    finally:
        await store.close()
```

(Adjust the `finally` if the double-close pattern conflicts with the file's style — the assertions are the contract.)

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest packages/python/vystak-channel-panel/tests/test_store_passwords.py -v
```

Expected: FAIL — `set_user_password`/`verify_user_password`/`has_password` don't exist.

- [ ] **Step 4: Implement**

`models.py` — add to `PanelUser` after `created_at`:

```python
    has_password: bool = False
```

`store.py`:

1. `import bcrypt` (top-level, with the other imports) and add `SCHEMA_VERSION: int = 3`.
2. In `_SCHEMA`'s users table, after the `status` line add:

```sql
    password_hash TEXT,
```

(keep it before `created_at`; nullable, no default).

3. Extend `_migrate()` — after the existing `PRAGMA table_info(messages)` block add a users check, and add the second ALTER inside the existing `_write()` block (preserving the crash-safety comment's logic):

```python
        async with self.db.execute("PRAGMA table_info(users)") as cur:
            user_columns = {row["name"] async for row in cur}
        async with self._write() as db:
            if "parts" not in columns:
                await db.execute("ALTER TABLE messages ADD COLUMN parts TEXT")
            if "password_hash" not in user_columns:
                await db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            # (existing inlined schema_version upsert stays as-is)
```

4. Add `_user_from_row` and route ALL user readers through it — `get_user`, `get_user_by_email`, `list_users`, `list_members` currently do `PanelUser(**dict(row))`:

```python
    @staticmethod
    def _user_from_row(row) -> PanelUser:
        d = dict(row)
        # The hash never leaves the store layer: replaced by a derived flag.
        d["has_password"] = d.pop("password_hash", None) is not None
        return PanelUser(**d)
```

5. Add the two helpers in the users section (bcrypt is CPU-bound — keep it off the event loop):

```python
    async def set_user_password(self, user_id: str, password: str) -> bool:
        hashed = await asyncio.to_thread(
            bcrypt.hashpw, password.encode("utf-8"), bcrypt.gensalt()
        )
        async with self._write() as db:
            cur = await db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hashed.decode("ascii"), user_id),
            )
            rowcount = cur.rowcount
        return rowcount > 0

    async def verify_user_password(self, email: str, password: str) -> PanelUser | None:
        async with self.db.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        hashed = d.get("password_hash")
        if hashed is None or d.get("status") != "active":
            return None
        ok = await asyncio.to_thread(
            bcrypt.checkpw, password.encode("utf-8"), hashed.encode("ascii")
        )
        return self._user_from_row(row) if ok else None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest packages/python/vystak-channel-panel/ -v
```

Expected: new password tests + migration test pass; entire package suite green; no new warnings.

- [ ] **Step 6: Gates and commit**

```bash
just lint-python && just test-python
git add packages/python/vystak-channel-panel pyproject.toml uv.lock
git commit -m "feat(panel-channel): password storage — schema v3, bcrypt hash, has_password"
```

(`pyproject.toml`/`uv.lock` at root only if `uv sync` changed them; check `git status` first.)

---

### Task 2: Channel API — set-password and verify endpoints

**Files:**
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/routes_users.py`
- Modify: `packages/python/vystak-channel-panel/src/vystak_channel_panel/app.py`
- Test: `packages/python/vystak-channel-panel/tests/test_api_passwords.py` (new; follow the app/client fixture pattern of the existing API tests, e.g. the users-API test file)

**Interfaces:**
- Consumes: Task 1's store helpers; existing `service_auth` / `admin_user` dependencies.
- Produces:
  - `PUT /api/users/{user_id}/password` body `{"password": str}` → 204; 422 if len < 8; 404 unknown user; admin caller required (403 otherwise via existing dependency).
  - `POST /api/auth/verify` body `{"email": str, "password": str}` → `{"ok": bool, "user": dict | null}`; service token required, no `X-Panel-User`.
  - `GET /api/users` rows now carry `has_password` (free via Task 1's model change — assert it).

- [ ] **Step 1: Write the failing tests** — `tests/test_api_passwords.py`. Reuse the existing API-test fixtures (app + async client + seeded admin; read the sibling users-API test file first and mirror its setup). Cases, each an explicit test:

```python
# Sketch — adapt fixture names to the existing conftest. The assertions are the contract.

async def test_admin_sets_password_then_verify_ok(client, admin_headers, member_user):
    r = await client.put(
        f"/api/users/{member_user['id']}/password",
        json={"password": "testpass-m-123"}, headers=admin_headers,
    )
    assert r.status_code == 204
    r = await client.post(
        "/api/auth/verify",
        json={"email": member_user["email"], "password": "testpass-m-123"},
        headers=service_only_headers,   # Authorization: Bearer <token>, NO X-Panel-User
    )
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["user"]["email"] == member_user["email"]
    assert "password_hash" not in body["user"]

async def test_member_cannot_set_password(client, member_headers, admin_user):
    r = await client.put(
        f"/api/users/{admin_user['id']}/password",
        json={"password": "testpass-x-123"}, headers=member_headers,
    )
    assert r.status_code == 403

async def test_short_password_rejected(client, admin_headers, member_user):
    r = await client.put(
        f"/api/users/{member_user['id']}/password",
        json={"password": "short"}, headers=admin_headers,
    )
    assert r.status_code == 422

async def test_set_password_unknown_user_404(client, admin_headers):
    r = await client.put(
        "/api/users/nope/password",
        json={"password": "testpass-x-123"}, headers=admin_headers,
    )
    assert r.status_code == 404

async def test_verify_failure_modes_identical_shape(client, admin_headers, member_user):
    # set a real password first
    await client.put(f"/api/users/{member_user['id']}/password",
                     json={"password": "testpass-m-123"}, headers=admin_headers)
    wrong = await client.post("/api/auth/verify",
        json={"email": member_user["email"], "password": "wrongpass-000"},
        headers=service_only_headers)
    ghost = await client.post("/api/auth/verify",
        json={"email": "ghost@example.com", "password": "wrongpass-000"},
        headers=service_only_headers)
    assert wrong.status_code == ghost.status_code == 200
    assert wrong.json() == ghost.json() == {"ok": False, "user": None}

async def test_verify_requires_service_token(client):
    r = await client.post("/api/auth/verify",
        json={"email": "a@b.c", "password": "x"})   # no Authorization header
    assert r.status_code == 401

async def test_list_users_includes_has_password(client, admin_headers, member_user):
    await client.put(f"/api/users/{member_user['id']}/password",
                     json={"password": "testpass-m-123"}, headers=admin_headers)
    r = await client.get("/api/users", headers=admin_headers)
    users = {u["email"]: u for u in r.json()["users"]}
    assert users[member_user["email"]]["has_password"] is True
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest packages/python/vystak-channel-panel/tests/test_api_passwords.py -v
```

Expected: FAIL — 404/405 on the new endpoints.

- [ ] **Step 3: Implement**

`routes_users.py` — add model + route inside `build_users_router`:

```python
class PasswordSetIn(BaseModel):
    password: str
```

```python
    @router.put("/{user_id}/password", status_code=204)
    async def set_password(
        user_id: str, body: PasswordSetIn, _: PanelUser = Depends(admin_user)
    ) -> None:
        if len(body.password) < 8:
            raise HTTPException(
                status_code=422, detail="password must be at least 8 characters"
            )
        if not await rt.panel_store.set_user_password(user_id, body.password):
            raise HTTPException(status_code=404, detail="unknown user")
```

`app.py` — next to `/api/bootstrap` (service token only; this IS the authentication step, so no `X-Panel-User`):

```python
class VerifyIn(BaseModel):
    email: str
    password: str
```

```python
    @app.post("/api/auth/verify")
    async def verify_password(
        body: VerifyIn, _: None = Depends(service_auth)
    ) -> dict:
        user = await rt.panel_store.verify_user_password(body.email, body.password)
        return {"ok": user is not None, "user": user.model_dump() if user else None}
```

- [ ] **Step 4: Run tests, gates, commit**

```bash
uv run pytest packages/python/vystak-channel-panel/ -v   # all green, no new warnings
just lint-python && just test-python
git add packages/python/vystak-channel-panel
git commit -m "feat(panel-channel): set-password and verify endpoints"
```

---

### Task 3: Next app data layer + Credentials provider

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/types.ts`
- Modify: `packages/typescript/vystak-panel/lib/panel.ts`
- Modify: `packages/typescript/vystak-panel/auth.ts`
- Modify: `packages/typescript/vystak-panel/app/actions.ts`

**Interfaces:**
- Consumes: Task 2's endpoints; existing `panelFetch`/`json`/`ok` helpers, `requireEmail`.
- Produces:
  - `PanelUser.has_password: boolean` in `lib/types.ts`
  - `verifyPassword(email, password): Promise<{ ok: boolean; user: PanelUser | null }>`
  - `setUserPassword(email, userId, password): Promise<void>`
  - Credentials provider registered iff `process.env.PANEL_PASSWORD_AUTH === '1'`
  - `setUserPasswordAction(userId: string, formData: FormData)` server action (Task 4's admin dialog binds it).

- [ ] **Step 1: `lib/types.ts`** — in `PanelUser`, after `status`, add:

```ts
  has_password: boolean;
```

- [ ] **Step 2: `lib/panel.ts`** — add next to the other user functions:

```ts
export const setUserPassword = (email: string, userId: string, password: string) =>
  ok(email, `/api/users/${userId}/password`, {
    method: 'PUT',
    body: JSON.stringify({ password }),
  });

export const verifyPassword = (email: string, password: string) =>
  json<{ ok: boolean; user: PanelUser | null }>(null, '/api/auth/verify', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
```

(`null` user arg: the verify call is the authentication step — no `X-Panel-User` header, matching `panelFetch`'s existing null handling.)

- [ ] **Step 3: `auth.ts`** — full replacement of the providers wiring; callbacks unchanged:

```ts
import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';
import Google from 'next-auth/providers/google';
import { evaluateSignIn } from '@/lib/auth-policy';
import { getBootstrap, setupAdmin, verifyPassword } from '@/lib/panel';

export const passwordAuthEnabled = () =>
  process.env.PANEL_PASSWORD_AUTH === '1';

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google,
    ...(passwordAuthEnabled()
      ? [
          Credentials({
            credentials: { email: {}, password: {} },
            async authorize(credentials) {
              const email = String(credentials?.email ?? '')
                .trim()
                .toLowerCase();
              const password = String(credentials?.password ?? '');
              if (!email || !password) return null;
              // A channel outage surfaces as a failed login rather than a
              // crash; the Google path keeps its distinct PanelUnavailable
              // handling in the signIn callback below.
              let result;
              try {
                result = await verifyPassword(email, password);
              } catch {
                return null;
              }
              if (!result.ok || !result.user) return null;
              return {
                email: result.user.email,
                name: result.user.name,
                image: result.user.image,
              };
            },
          }),
        ]
      : []),
  ],
  session: { strategy: 'jwt' },
  pages: { signIn: '/signin', error: '/signin' },
  callbacks: {
    // ... existing signIn and jwt callbacks, byte-for-byte unchanged ...
  },
});
```

(Keep the existing `signIn`/`jwt` callback bodies exactly as they are — they run for both providers; for credentials logins the user necessarily exists, so `evaluateSignIn` lands on `allow`/deny and the `setup` branch cannot trigger.)

- [ ] **Step 4: `app/actions.ts`** — add import `setUserPassword` from `@/lib/panel`, and append:

```ts
export async function setUserPasswordAction(userId: string, formData: FormData) {
  const email = await requireEmail();
  const password = String(formData.get('password') ?? '');
  if (password.length < 8) return;
  await setUserPassword(email, userId, password);
  revalidatePath('/admin/users');
}
```

- [ ] **Step 5: Verify and commit**

```bash
cd packages/typescript/vystak-panel
pnpm run typecheck    # exit 0
pnpm run test         # 4 files / 28 tests passing
git add lib/types.ts lib/panel.ts auth.ts app/actions.ts
git commit -m "feat(panel): credentials provider and password data layer (flag-gated)"
```

---

### Task 4: UI — sign-in password form and admin set-password dialog

**Files:**
- Modify: `packages/typescript/vystak-panel/app/signin/page.tsx`
- Create: `packages/typescript/vystak-panel/components/set-password-dialog.tsx`
- Modify: `packages/typescript/vystak-panel/app/admin/users/page.tsx`

**Interfaces:**
- Consumes: `passwordAuthEnabled`, `signIn` from `@/auth`; `setUserPasswordAction(userId, formData)` (Task 3); shadcn `Dialog`/`Input`/`Button`/`Badge`; `KeyRoundIcon` from lucide.
- Produces: nothing consumed later.

- [ ] **Step 1: Sign-in page** — in `app/signin/page.tsx`:

Add imports: `passwordAuthEnabled` (from `@/auth`), `AuthError` (from `next-auth`), `redirect` is already imported, `Input` + `Separator` from ui.

Add the `CredentialsSignin` error case alongside the existing alerts (before the catch-all, and exclude it from the catch-all's condition):

```tsx
{error === 'CredentialsSignin' && (
  <Alert variant="destructive">
    <AlertCircleIcon />
    <AlertTitle>Sign-in failed</AlertTitle>
    <AlertDescription>Invalid email or password.</AlertDescription>
  </Alert>
)}
```

(Catch-all condition becomes `error && !['AccessDenied', 'PanelUnavailable', 'CredentialsSignin'].includes(error)`.)

Inside `CardContent`, above the Google form, gated on the flag:

```tsx
{passwordAuthEnabled() && (
  <>
    <form
      action={async formData => {
        'use server';
        try {
          await signIn('credentials', {
            email: formData.get('email'),
            password: formData.get('password'),
            redirectTo: '/',
          });
        } catch (error) {
          // signIn throws NEXT_REDIRECT on success — let it propagate.
          if (error instanceof AuthError) {
            redirect('/signin?error=CredentialsSignin');
          }
          throw error;
        }
      }}
      className="flex flex-col gap-3"
    >
      <Input name="email" type="email" placeholder="you@example.com" required />
      <Input
        name="password"
        type="password"
        placeholder="Password"
        autoComplete="current-password"
        required
      />
      <Button type="submit" className="w-full">
        Sign in
      </Button>
    </form>
    <div className="flex items-center gap-3">
      <Separator className="flex-1" />
      <span className="text-xs text-muted-foreground">or</span>
      <Separator className="flex-1" />
    </div>
  </>
)}
```

With the flag off, the rendered page is unchanged from today (the new error case can only be reached with the flag on).

- [ ] **Step 2: Create `components/set-password-dialog.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { setUserPasswordAction } from '@/app/actions';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { KeyRoundIcon } from 'lucide-react';

export function SetPasswordDialog({
  userId,
  email,
}: {
  userId: string;
  email: string;
}) {
  const [open, setOpen] = useState(false);
  const action = setUserPasswordAction.bind(null, userId);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <KeyRoundIcon /> Set password
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Set password</DialogTitle>
          <DialogDescription>
            Set a sign-in password for {email}. This replaces any existing
            password.
          </DialogDescription>
        </DialogHeader>
        <form
          action={async fd => {
            await action(fd);
            setOpen(false);
          }}
          className="flex gap-2"
        >
          <Input
            name="password"
            type="password"
            placeholder="Min 8 characters"
            minLength={8}
            autoComplete="new-password"
            autoFocus
            required
          />
          <Button type="submit">Save</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Admin users page** — in `app/admin/users/page.tsx`:

- Import `SetPasswordDialog` and `KeyRoundIcon`.
- Status cell: next to the status `Badge`, when `u.has_password`, render a muted indicator:

```tsx
{u.has_password && (
  <KeyRoundIcon
    className="ml-1.5 inline size-3.5 text-muted-foreground"
    aria-label="Password set"
  />
)}
```

- Actions cell: add `<SetPasswordDialog userId={u.id} email={u.email} />` for every row (own row included) before the deactivate/reactivate control; wrap the cell's children in a `flex items-center justify-end gap-2` container so the two controls sit side by side.

- [ ] **Step 4: Verify and commit**

```bash
cd packages/typescript/vystak-panel
pnpm run typecheck && pnpm run test && pnpm run build:app
git add app/signin/page.tsx app/admin/users/page.tsx components/set-password-dialog.tsx
git commit -m "feat(panel): password sign-in form and admin set-password dialog"
```

---

### Task 5: Examples, env docs, full verification

**Files:**
- Modify: `packages/typescript/vystak-panel/.env.example`
- Modify: `examples/docker-panel/README.md` (or create if absent — check first)

**Interfaces:** none.

- [ ] **Step 1: `.env.example`** — append:

```bash
# Enable email+password sign-in alongside Google (admin sets passwords from
# the Users page). Unset = Google only.
# PANEL_PASSWORD_AUTH=1
```

- [ ] **Step 2: Example docs** — check `ls examples/docker-panel/` for a README; add (or create a short README containing) a "Password sign-in" section: set `PANEL_PASSWORD_AUTH=1` in the panel app's environment, then an admin sets each user's password from the admin Users page; first admin still bootstraps via Google or the channel API.

- [ ] **Step 3: Full gates**

```bash
just lint-python && just test-python && just typecheck-typescript && just test-typescript
```

Expected: all four green.

- [ ] **Step 4: Commit**

```bash
git add packages/typescript/vystak-panel/.env.example examples/docker-panel/README.md
git commit -m "docs(panel): document PANEL_PASSWORD_AUTH flag"
```

- [ ] **Step 5: Report** — summarize against the spec; remaining manual verification: with the flag on and a password set, sign in with email+password in a browser (agent-driveable headlessly since no OAuth is involved), wrong-password shows "Invalid email or password", flag-off renders the old page.

---

## Self-review notes

- Spec coverage: schema/migration + hashing (T1), endpoints + `has_password` (T2), provider + data layer + action (T3), both UI surfaces + error case (T4), env/example docs + gates (T5). Non-goals honored: no reset flows, no rate limiting, bootstrap unchanged.
- Type consistency: `set_user_password(user_id, password) -> bool` (T1) matches T2's 404 branch; `verifyPassword` return shape (T3) matches T2's response; `setUserPasswordAction(userId, formData)` (T3) matches T4's `.bind(null, userId)`.
- The `authorize` catch-all maps channel outage to a failed login (documented in code); acceptable per spec's shape-uniformity requirement.
