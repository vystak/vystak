# docker-panel-durable — durable execution across an agent container restart

Deploys one agent (`durable-agent`) plus the `panel` channel over the NATS
transport. The agent's only tool, `slow_step`, sleeps 20 seconds per call and
the agent is instructed to call it four times in sequence — a single turn
takes roughly 80 seconds end to end. That's a wide enough window to kill the
agent container by hand mid-turn and watch durable/checkpointed execution do
its job: the turn resumes from the last committed step instead of being lost,
and the panel's browser view lands on the committed prefix instead of
duplicating text.

## How durable execution applies here

The agent container checkpoints turn progress to `/data` (a per-agent Docker
volume, `vystak-agent-durable-agent-data`, that survives container restarts)
and appends to a turn journal as each step commits. On container start, the
runtime rescans that journal for any turn left `in_progress` and re-drives it
from the last committed checkpoint rather than the beginning. The NATS bridge
publishes a `vystak.turn.rewind` control event when this happens, so any panel
session still attached to that turn truncates its local view to the same
point the backend resumed from — no duplicated tool calls or duplicated
reply text.

## This example cannot run concurrently with `examples/docker-panel` or `examples/docker-panel-nats`

All three bind host port 18100 and deploy an unnamespaced
`vystak-channel-panel` container. Destroy one before deploying another.

## Deploy the stack

    cd examples/docker-panel-durable
    cp .env.example .env   # fill in your real ANTHROPIC_API_KEY
    export PANEL_SERVICE_TOKEN=$(openssl rand -hex 24)
    vystak apply

The panel API is now at http://localhost:18100 (try `GET /health`).

## Run the control panel UI

The UI is the `vystak-panel` Next.js app (not deployed by `vystak apply`):

    cd ../../packages/typescript/vystak-panel   # from examples/docker-panel-durable
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

## Walkthrough: restart mid-run and watch the turn survive

This is the manual verification for durable/checkpointed execution — there is
no automated test for the browser-facing behavior, so do this by hand once
after deploying:

1. In the panel UI, start a new conversation with `durable-agent` and send:

       run the four-step job

   The agent starts calling `slow_step` with `label="one"`, `"two"`,
   `"three"`, `"four"` in order. Each call takes ~20s, so you have roughly
   80 seconds total before the reply lands. The panel shows the turn as
   in-progress (streaming/pending) while steps run.

2. Partway through — after you've seen at least one `slow_step` call
   complete (watch the tool-call entries appear in the panel), but before the
   turn finishes — restart the agent container from another terminal:

       docker restart vystak-durable-agent

   This is a hard kill of the agent process mid-turn, including whatever
   `slow_step` call was in flight when the container went down.

3. Watch the browser. You should observe:

   - The panel does **not** show an error or a dropped turn. The in-progress
     indicator may blip briefly while the container restarts and the panel's
     SSE stream reconnects, but the turn stays live.
   - The transcript **resets to the committed prefix**: any `slow_step` calls
     that had already completed and been checkpointed before the restart stay
     in the transcript exactly once. The in-flight call that was killed mid-
     sleep is *not* shown as complete — it gets re-driven from the beginning
     of that step, not resumed mid-sleep (the underlying `asyncio.sleep` call
     itself has no checkpoint).
   - No duplicate text. Because the panel truncates to the same seq the
     backend rewound to (via the `vystak.turn.rewind` event on the NATS
     bridge), you should never see a step's result rendered twice, and you
     should never see two different final replies.

4. After the restart, the agent finishes the remaining steps and the turn
   completes normally with a single final reply — the same as if the
   container had never restarted, just delayed by however long the container
   took to come back up plus the re-driven step.

If you restart *after* the turn has already completed and the final reply is
visible, there's nothing to observe — restart again on a fresh "run the
four-step job" turn, earlier in the run.

## Tear down

    vystak destroy
