# vystak-panel

Control-panel UI for deployed Vystak agents — a Next.js 15 app over the
`vystak-channel-panel` REST + SSE API. Users, projects, and conversations
live in the channel; this app is the browser surface: a chat interface with
streaming markdown and tool-call visualization, project sharing, and admin
user management.

## Stack

- Next.js 15 (App Router, React 19, server components)
- Tailwind CSS v4 — theme tokens in `app/globals.css` (light/dark via
  `next-themes`)
- [shadcn/ui](https://ui.shadcn.com) primitives vendored under
  `components/ui/`
- [AI Elements](https://ai-sdk.dev/elements) chat components vendored under
  `components/ai-elements/` (conversation, message, tool, prompt-input) on
  AI SDK v5 (`useChat`, `UIMessage.parts`)
- NextAuth v5 — Google sign-in, plus optional email/password

## Running

```bash
cp .env.example .env.local   # then fill in values
pnpm install
pnpm dev                     # http://localhost:3000
```

Required environment (see `.env.example`):

| Variable | Purpose |
|---|---|
| `PANEL_API_URL` | Base URL of the deployed panel channel (e.g. `http://localhost:18100`) |
| `PANEL_SERVICE_TOKEN` | Service token the channel was deployed with |
| `AUTH_SECRET` | NextAuth session secret |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Google OAuth client |
| `PANEL_PASSWORD_AUTH` | Set to `1` to enable email/password sign-in alongside Google |

The backing deployment comes from `examples/docker-panel` (repo root):
`vystak apply` starts the panel channel and agents this UI talks to.

## Password sign-in

With `PANEL_PASSWORD_AUTH=1`, the sign-in page offers email + password in
addition to Google. Passwords are provisioned by admins from the Users page
(or via `PUT /api/users/{id}/password` on the channel); there is no
self-service reset. The first admin still bootstraps via Google or the
channel API. Password sign-in has no lockout or rate limiting — front the
panel with a rate-limiting reverse proxy if exposed beyond a trusted
network.

## Notes

- The `build` script is deliberately named `build:app` — repo CI runs
  `pnpm -r run build`, and this app must not participate.
- Tests: `pnpm test` (vitest — stream mapping, auth policy, part replay,
  formatting). Typecheck: `pnpm run typecheck`.
- Vendored `components/ui/*` and `components/ai-elements/*` are
  CLI-generated; regenerate via `npx shadcn@latest add …` rather than
  hand-editing.
