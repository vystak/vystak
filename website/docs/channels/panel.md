---
title: Control Panel
sidebar_label: Control Panel
sidebar_position: 5
---

# Control panel channel

A **`type: panel`** channel deploys the control-panel API container — a
browser-facing management surface for your deployed agents. Paired with the
`vystak-panel` Next.js app, it gives every invited user:

- A **chat UI** with streaming markdown responses and live tool-call
  visualization (collapsible blocks showing each tool's arguments and
  result), replayed faithfully from history on reload
- **Projects** that group conversations and can be shared with teammates
  by email
- **Conversations** per agent — create, rename, delete, with titles
  auto-generated from the first message
- **User management** for admins: invite by email, deactivate/reactivate,
  and optional password provisioning
- **Google or email/password sign-in**, gated by an invite allow-list

The channel container owns all state (users, projects, conversations,
messages) in SQLite on a named volume, exposed as a REST + SSE API. The
Next.js UI is stateless and talks to it server-side with a shared service
token — browsers never reach the channel directly.

## Quick start

Declare the channel next to the agents it should route to
(`examples/docker-panel` is the full runnable version):

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

```bash
export PANEL_SERVICE_TOKEN=$(openssl rand -hex 32)
vystak apply
# Panel API now listens on http://localhost:18100
```

Then run the UI (from the Vystak repo, `packages/typescript/vystak-panel`):

```bash
cp .env.example .env.local   # PANEL_API_URL, PANEL_SERVICE_TOKEN, AUTH_* values
pnpm install
pnpm dev                     # http://localhost:3000
```

The first person to sign in becomes the admin and gets a default
**Personal** project; everyone else must be invited from the admin Users
page first.

## Sign-in options

**Google** (default): configure `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` in
the UI's environment. Sign-in is allow-list gated — an uninvited Google
account is rejected with a clear message.

**Email + password** (optional): set `PANEL_PASSWORD_AUTH=1` in the UI's
environment. Admins set each user's password from the Users page (or via
`PUT /api/users/{id}/password` on the channel API); users then sign in with
email + password alongside Google. Notes:

- Passwords are bcrypt-hashed in the channel's store; hashes never leave it.
- There is no self-service reset — an admin sets a new password.
- The first admin still bootstraps via Google (or the channel API directly);
  a password can't exist before its user does.
- There is no lockout or rate limiting — front the panel with a
  rate-limiting reverse proxy if it's exposed beyond a trusted network.

Password sign-in also gives **automation and QA agents** a way to drive the
panel headlessly — no OAuth flow required.

## How chat flows

```
Browser ── useChat ──▶ Next.js /api/chat ── SSE ──▶ panel channel ──▶ agent
                                                    (persists turn:
                                                     text + tool parts)
```

The channel calls the agent's OpenAI-compatible `/v1/responses` endpoint,
forwards text deltas and tool-call events over SSE, and persists the
completed turn — including an ordered list of text and tool parts — so a
reloaded conversation renders exactly like the live stream did.

## Configuration reference

| Channel `config` key | Default | Purpose |
|---|---|---|
| `port` | `18100` | Host port for the panel API |

| Channel secret | Purpose |
|---|---|
| `PANEL_SERVICE_TOKEN` | Shared secret between the channel and the UI backend; every API call requires it |

UI environment (`vystak-panel/.env.example`):

| Variable | Purpose |
|---|---|
| `PANEL_API_URL` | Panel channel base URL |
| `PANEL_SERVICE_TOKEN` | Must match the channel's secret |
| `AUTH_SECRET` | NextAuth session secret |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Google OAuth client |
| `PANEL_PASSWORD_AUTH` | `1` enables email/password sign-in |

## Admin API surface

All endpoints require `Authorization: Bearer <PANEL_SERVICE_TOKEN>`, plus
`X-Panel-User: <acting email>` for user-scoped calls:

- `GET /api/bootstrap` — acting user, routable agents, default project
- `POST /api/users` / `PATCH /api/users/{id}` — invite, role/status changes
  (the last active admin cannot be removed)
- `PUT /api/users/{id}/password` — set/replace a password (admin caller)
- `POST /api/auth/verify` — verify email + password (no `X-Panel-User`)
- `GET|POST /api/projects`, members subroutes — projects and sharing
- `GET|POST /api/projects/{id}/conversations`, `PATCH|DELETE
  /api/conversations/{id}` — conversation lifecycle
- `POST /api/conversations/{id}/messages` — send a message; the response is
  the SSE stream
