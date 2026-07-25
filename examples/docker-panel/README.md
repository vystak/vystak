# docker-panel — control panel over two agents

Deploys two agents (weather, time) plus the `panel` channel: the control-panel
API container (users, projects, conversations, SSE streaming).

## Deploy the stack

    cd examples/docker-panel
    cp .env.example .env   # fill in your real ANTHROPIC_API_KEY
    export PANEL_SERVICE_TOKEN=$(openssl rand -hex 24)
    vystak apply

The panel API is now at http://localhost:18100 (try `GET /health`).

## Run the control panel UI

The UI is the `vystak-panel` Next.js app (not deployed by `vystak apply`):

    cd ../../packages/typescript/vystak-panel   # from examples/docker-panel
    cp .env.example .env.local   # fill in:
    #   PANEL_API_URL=http://localhost:18100
    #   PANEL_SERVICE_TOKEN=<same value as above>
    #   AUTH_SECRET=$(openssl rand -base64 32)
    #   AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET from your Google OAuth client
    pnpm --filter vystak-panel dev

Open http://localhost:3000 — the first Google account to sign in becomes the
admin; invite others from /admin/users.

## Password sign-in

To enable email+password authentication alongside Google OAuth, set
`PANEL_PASSWORD_AUTH=1` in the panel app's environment (`.env.local`). The
first admin still bootstraps via Google (or the channel API); after that, any
admin can set passwords for other users from the admin Users page. Users can
then sign in with email and password instead of Google.

Password sign-in has no lockout or rate limiting; if the panel is exposed
beyond a trusted network, front it with a reverse proxy that rate-limits
`/signin`.

## Tear down

    vystak destroy
