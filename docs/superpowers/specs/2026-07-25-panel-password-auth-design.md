# Panel Password Sign-In — Design

**Date:** 2026-07-25
**Packages:** `packages/python/vystak-channel-panel`, `packages/typescript/vystak-panel`
**Status:** Approved design ("password auth only, admin-provisioned")

## Goal

Add password login to the control panel as a first-class, configurable
sign-in method alongside Google — usable by self-hosted deployments without
Google OAuth setup, and by automated agents (QA) that cannot complete an
OAuth flow. Passwords are provisioned by admins; there is no self-service.

## Non-goals (YAGNI)

- Self-service password set/change/reset, email flows, invite links.
- Rate limiting / lockout: the verify endpoint is reachable only through the
  panel channel's service-token auth (called server-side by the Next app),
  never directly from browsers. Noted as a known limitation if the channel
  is ever exposed publicly.
- Password complexity rules beyond a minimum length of 8 (channel-enforced).
- Changing the first-admin bootstrap: the setup flow (first Google sign-in
  creates the admin) is unchanged. A password cannot exist before its user
  row does; the first admin arrives via Google or via the channel API
  directly (service token + `/api/setup`).

## Enable switch

`PANEL_PASSWORD_AUTH=1` in the **Next app's** environment enables:
- the Credentials provider in `auth.ts`, and
- the email/password form on `/signin`.

Unset (default), the sign-in surface and provider list are byte-identical to
today. The panel channel's endpoints exist unconditionally (harmless without
the flag — nothing calls them, and they still require the service token).

## Panel channel (Python) — storage and verification

### Schema migration v2 → v3

`store.py`'s existing `_migrate()` machinery (introduced with
`SCHEMA_VERSION = 2`) gains:

- `SCHEMA_VERSION = 3`
- v3 step: `ALTER TABLE users ADD COLUMN password_hash TEXT` — nullable,
  guarded by a `PRAGMA table_info(users)` column check exactly like the v2
  `messages.parts` step, because live volumes exist.
- Fresh-DB `_SCHEMA` includes the column directly.

The hash never leaves the store layer in user-shaped payloads: `PanelUser`
serialization gains `has_password: bool` (derived), never the hash itself.

### Hashing

`bcrypt` (new dependency of `vystak-channel-panel`), default work factor.
Hash/verify go through two small store helpers so the algorithm is one place:
`set_user_password(user_id, password)` and
`verify_user_password(email, password) -> PanelUser | None`.
Verification uses `bcrypt.checkpw` (constant-time). A user with
`password_hash IS NULL`, an unknown email, or `status != 'active'` all
verify as `None` — indistinguishable to the caller.

### Endpoints (both behind existing service-token auth)

- `PUT /api/users/{user_id}/password`, body `{"password": str}`.
  Caller identity from `X-Panel-User` must be an **active admin** (same
  guard as existing user-management routes). Rejects password shorter than
  8 chars with 422. Returns 204. Setting a password overwrites any prior one.
- `POST /api/auth/verify`, body `{"email": str, "password": str}` →
  `{"ok": bool, "user": {...} | null}`. `ok=true` only for an active user
  with a matching hash; every failure mode returns the same
  `{"ok": false, "user": null}` shape. Requires the service token but no
  `X-Panel-User` (it is the authentication step itself).
- `GET /api/users` rows gain `has_password`.

## Next app (TypeScript)

### `auth.ts`

- Providers array becomes conditional: `[Google, ...(passwordAuthEnabled ? [Credentials({...})] : [])]`
  where `passwordAuthEnabled = process.env.PANEL_PASSWORD_AUTH === '1'`.
- The Credentials provider's `authorize({email, password})` calls the new
  `verifyPassword(email, password)` from `lib/panel.ts` and returns
  `{email, name, image}` from the verified user, or `null`.
- The existing `signIn` callback runs unchanged for both providers — the
  allow-list policy (`evaluateSignIn`) and `PanelUnavailable` handling stay
  authoritative. (For credentials logins the user necessarily exists, so
  the `setup` branch will not trigger; `allow` is decided by the same
  bootstrap check as Google.)

### `lib/panel.ts`

- `verifyPassword(email, password)` → POST `/api/auth/verify`, returns the
  parsed `{ok, user}` (service token attached, `user` header null).
- `setUserPassword(email, userId, password)` → PUT
  `/api/users/{userId}/password`.

### `/signin` page

When the flag is enabled, the card shows — above the existing Google
button, separated by an "or" divider — an email + password form submitting
to a server action that calls
`signIn('credentials', { email, password, redirectTo: '/' })`.
New error mapping: NextAuth's `CredentialsSignin` error code renders an
Alert "Invalid email or password." All existing error cases unchanged.
With the flag off, the page renders exactly as today.

### Admin Users page

- Every row — including the admin's own — gains a
  "Set password" button opening a Dialog with a single password input
  (min length 8, `autocomplete="new-password"`) submitting to a new server
  action `setUserPasswordAction(userId, formData)`.
- Rows show a subtle indicator when `has_password` is true (e.g. a muted
  key icon or "password" badge next to the role badge).

### Types

`PanelUser` in `lib/types.ts` gains `has_password: boolean` (the channel
now always sends it).

## Security notes

- The hash never appears in any API response or log; the password value is
  never logged and exists transiently in the action/endpoint bodies only.
- Verify responses are shape-identical across failure modes.
- The channel endpoints add no new public surface: the service token gate is
  unchanged, and browsers never talk to the channel directly.
- Public repo: tests use obvious fake passwords (`testpass-…`), examples use
  placeholders.

## Testing (TDD on the Python side)

Python (`vystak-channel-panel/tests/`):
- Migration: build a v2-shaped DB (with `schema_version = 2` and no
  `password_hash` column), run `connect()`, assert column exists, version 3,
  existing rows intact, double-connect idempotent.
- Store: set/verify roundtrip; wrong password → None; unknown email → None;
  deactivated user with valid password → None; `has_password` reflects
  state; overwrite replaces the old hash.
- Routes: non-admin caller of PUT password → 403; short password → 422;
  verify endpoint returns identical body shape for wrong-password vs
  no-such-user; happy path returns the user payload without any hash field.

TypeScript: existing suites untouched. The sign-in error mapping and
`authorize` are thin; covered by typecheck. (If a pure helper emerges for
mapping NextAuth error codes to copy, it gets a vitest case.)

## Examples / docs

- `packages/typescript/vystak-panel/.env.example`: add `PANEL_PASSWORD_AUTH`
  with a comment explaining the flag.
- `examples/docker-panel`: README note (or `.env.example` if present) that
  password login is enabled by setting the flag on the panel app and
  passwords are set from the admin Users page.

## Operational precondition

`store.py` (and other panel-channel files) carry **uncommitted changes**
from the in-flight tool-call visualization branch work. Implementation must
not start until those are committed or stashed; the first implementation
task re-checks `git status` for the touched files and stops if dirty.
