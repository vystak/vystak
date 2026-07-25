# Vystak Control Panel — Design

**Date:** 2026-07-24
**Status:** Approved (brainstorming complete)

## Summary

A web control panel for talking to deployed Vystak agents: create conversations,
see and resume previous sessions, organize work into shareable projects, with
Google sign-in and DB-backed user management.

Two deliverables:

1. **`vystak-channel-panel`** (Python, `packages/python/vystak-channel-panel`) —
   a real channel plugin + `ChannelRuntime` on FastAPI. Deployed via
   `vystak.yaml` like any channel (one container). It is the system of record:
   owns the panel database, exposes a REST + SSE API for the UI, and talks to
   agents over the existing protocol (OpenAI Responses API with
   `previous_response_id` continuity) using the channel runtime's agent-call
   plumbing.
2. **`vystak-panel`** (TypeScript, `packages/typescript/vystak-panel`) — a
   Next.js app, deployed independently (Vercel, container, laptop — anywhere
   that can reach the channel). Auth.js with the Google provider; chat UI built
   on the Vercel AI SDK (`useChat`). **The UI is not a channel** — it is a
   client of the panel channel's API.

Scope is **chat workspace only**: no deploy/apply/destroy/logs/ops surface in
v1. Ops management stays in the CLI.

## Architecture

```
vystak.yaml:
  channels:
    - name: panel
      type: panel
      agents: [researcher, coder]        # bound agents = what the panel can talk to
      config: { port: 8100 }
      secrets: [PANEL_SERVICE_TOKEN]

[Next.js app: vystak-panel]            [panel channel container: FastAPI]
  Auth.js (Google sign-in)               REST + SSE API  (/api/*)
  useChat ─▶ /app chat route ──────────▶ conversations / messages / stream
  admin pages ─▶ users, projects         panel DB (users, projects, convs, msgs)
        ▲ service token + user email        │ ChannelRuntime agent-call pipeline
                                            ▼
                                        agent /v1/responses (SSE, previous_response_id)
```

- **Agent discovery:** the channel's bound agents (`agents:` in the channel
  declaration) become the panel's agent list, exposed to the UI via the API.
  No Docker-label querying at runtime; the provider injects agent routes into
  the channel config at deploy time, as for other channels.
- **The panel bypasses `vystak-channel-chat`** — that router is non-streaming;
  the streaming surface is each agent's own `/v1/responses`.

## Channel API (Python — system of record)

FastAPI service, `ChannelRuntime` subclass, `RuntimeMode.SHARED` (one shared
container). All endpoints under `/api/`. Every request must carry:

- `Authorization: Bearer <PANEL_SERVICE_TOKEN>` — shared secret proving the
  caller is the trusted Next.js backend (delivered to the channel via
  `vystak.yaml` channel secrets, and to Next.js via its env).
- `X-Panel-User: <email>` — the acting user's Google-verified email (asserted
  by the Next.js backend after Auth.js sign-in). The channel authorizes every
  request against its own users table; unknown/deactivated email → 403.

Endpoint groups:

- **Auth/bootstrap:** `GET /api/bootstrap` — returns `setup_required` (users
  table empty), current user record (role), and bound-agent list.
  `POST /api/setup` — registers the first user as `admin`; only valid while
  the users table is empty (single-flight guarded).
- **Users (admin only):** list / add (email + role) / deactivate / promote.
- **Projects:** CRUD; membership add/remove (sharing = adding members).
  Every user gets a personal default project created on first sign-in.
  Visibility: owner or member.
- **Conversations:** list within a project, create (choose agent), rename,
  delete. Fields include `agent_name`, `last_response_id`.
- **Messages:** `GET` history for a conversation;
  `POST /api/conversations/{id}/messages` — persists the user message, calls
  the bound agent's `/v1/responses` with `stream: true` and the stored
  `previous_response_id`, and responds with **plain SSE** (frontend-agnostic):
  `delta` (text chunk), `done` (final message id + new `response_id`),
  `error`. On completion the assistant message and new `last_response_id`
  are persisted.

### Data model (channel DB)

SQLite on a named volume by default; Postgres as a config option reusing the
existing Postgres node pattern (mirrors agent `sessions.engine`). Async
SQLAlchemy.

- `users` — id, email (unique), name, image, role (`admin` | `member`),
  status (`active` | `deactivated`), created_at
- `projects` — id, name, owner_id, is_default, created_at
- `project_members` — project_id, user_id
- `conversations` — id, project_id, creator_id, agent_name, title,
  last_response_id, created_at, updated_at
- `messages` — id, conversation_id, role, parts (JSON), response_id,
  created_at
- `settings` — key/value (`setup_complete`, …)

## Next.js app (UI)

- **Auth:** Auth.js v5, Google provider. `signIn` callback calls the channel's
  bootstrap/authorize path — sign-in completes only for emails known to the
  channel (or during first-run setup, when the first account becomes admin).
  Google OAuth client id/secret live in the Next.js env.
- **Chat:** Vercel AI SDK `useChat`. The Next.js chat route calls the channel's
  message endpoint (service token + user email) and adapts the channel's plain
  SSE into the AI SDK UI message stream using the SDK's stream helpers
  (`createUIMessageStream`), so the Python side never encodes a
  Vercel-specific protocol.
- **UX:** sidebar with project switcher → conversation list (newest first).
  New conversation → agent picker (from bound agents). Resume → history from
  the channel DB renders, next message continues via `previous_response_id`.
  Auto-title from the first user message. Admin area: Users page; per-project
  Members dialog for sharing.

## First-run setup & user management

1. Channel DB has no users → `GET /api/bootstrap` returns `setup_required`.
2. Next.js shows a setup screen: "Sign in with Google to become the
   administrator." The first Google account to complete sign-in is registered
   as `admin` via `POST /api/setup` (the Google sign-in itself proves the
   email — no email pre-typing).
3. Admin adds further users by email (+ role) in the Users page; those users
   can then sign in with Google.

## Error handling

- **Agent unreachable:** SSE `error` event → inline error in chat with retry;
  the user message is already persisted, nothing is lost.
- **Stale `previous_response_id`** (agent redeployed with a fresh session
  store): the channel drops the stale id, retries as a new thread, and the UI
  surfaces "session expired on agent — continuing as a new thread."
- **Auth failures:** unknown email → clear "not invited" screen; service-token
  mismatch → 401 (deployment misconfiguration, logged loudly).

## Testing & definition of done

- **Python:** plugin tests matching sibling channels (bundle emission, config
  generation, provision nodes, registry registration); API tests for authz,
  setup single-flight, project visibility, stream persistence. A
  `release_smoke`/`release_integration` cell later (deploy → verify →
  destroy).
- **TypeScript:** vitest for route/adapter/DB-client logic. `pnpm -r run test`
  and the other three live CI gates (`just ci-live`) stay green.
- **Example (repo convention — part of DoD):** `examples/docker-panel` with a
  deployable `vystak.yaml` (agents + panel channel) and a README noting the
  Next.js app runs alongside (`pnpm dev` pointed at the deployed channel URL),
  since `vystak apply` deploys only the channel.

## Decisions log

| Decision | Choice |
|---|---|
| Scope v1 | Chat workspace only; no ops surface |
| Backend | Python channel plugin (`ChannelType.PANEL`), FastAPI, system of record |
| UI | Separate Next.js app; **not** a channel; Vercel AI SDK |
| Agent protocol | Direct `/v1/responses` streaming; `previous_response_id` continuity; chat-channel router bypassed |
| Auth | Google via Auth.js in Next.js; channel authorizes via users table; service token + user-email header between the two |
| Users | DB-backed; first-run setup makes first sign-in admin; admin manages users |
| Projects | Panel-DB entities, user-created, shareable via members; personal default project per user |
| DB | SQLite default / Postgres option, async SQLAlchemy |
| Streaming contract | Channel emits plain SSE; Next.js adapts to AI SDK UI message stream |
