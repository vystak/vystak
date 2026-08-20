---
title: Tool Approvals
sidebar_label: Tool Approvals
---

# Human-in-the-loop tool approvals

A tool a skill declares as gated pauses the agent turn — durably,
indefinitely — until a human clicks Approve or Deny in the panel or Slack.
Deny isn't an error: the turn continues, with the tool call short-circuited
to a denial string the model can reason about.

**v1 scope: skill tools only, Docker, panel + Slack, both transports.** MCP
tools aren't gateable — they attach via `McpServer`, not a skill's `tools`
list. No approver allowlist, no argument-conditional gating, no auto-deny
timeout, no Discord. Azure isn't part of this feature.

## Declaring a gate

```python
Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    needs_approval=["restart_service"],
)
```

`needs_approval` must be a subset of the skill's own `tools` — validated at
schema load time, so `vystak plan`/`vystak apply` fail fast on an unknown
tool name before anything deploys. It's part of the `Skill` object, hashed
like every other skill field: changing it changes the agent's deploy hash,
so `vystak apply` redeploys.

## How the gate works

The runtime wraps each gated tool so a call raises LangGraph's
`interrupt()` **before** the underlying function runs:

```python
interrupt({"kind": "tool_approval", "tool": name, "args": kwargs, "skill": skill_name})
```

This parks the turn instead of failing or completing — checkpointed
durably, same mechanism as [durable execution](./durable-execution). A
human's decision resumes the graph with:

```python
{"approved": bool, "decided_by": str, "note": str | None}
```

Approved runs the real tool. Denied short-circuits to
`"Denied by {decided_by}: {note or 'no reason given'}"` and the turn
continues — the agent typically explains why it couldn't proceed.

## Park is durable and indefinite

A parked turn has no deadline of its own — the panel's overall 15-minute
turn deadline excludes time spent parked, and a confirmed park keeps that
exclusion even through a status-check hiccup. Because the pause is a
checkpoint, not in-memory state: closing the browser tab, restarting the
agent container, or restarting a channel container (Slack buttons carry
their own route/thread payload) all leave the pending decision intact.

## First decision wins

If two people click Approve/Deny on the same card, only the first lands.
Over NATS the resume is rejected outright (`409`); over HTTP an in-flight
claim is taken atomically before any await, so the loser also gets `409`
(or `422` if the turn already moved on). The panel shows the loser an
inline error under the controls; Slack replies with an ephemeral
"already resolved" message.

## Surfaces

- **Panel** — an Awaiting Approval card in the transcript: tool name, args,
  an optional note field, Approve/Deny buttons. `decided_by` is filled in
  server-side from the authenticated user's email, not sent by the client.
- **Slack** — a Block Kit message with Approve/Deny buttons. A click edits
  the message to "Approved/Denied by @user" and posts the final reply
  in-thread; a chained gated call in the same turn posts a new card rather
  than reusing the old one. Works the same on the default streaming
  protocol and `a2a-turn`.

## Transports

Both NATS and HTTP support the gate. The difference is live-streaming: over
NATS, a resumed turn pushes straight into an already-open panel tab; over
HTTP it doesn't — the browser sees the result on reload, not live.

## The PyPI-schema fallback

Deployed agents install `vystak` from PyPI, not the dev workspace. As of
the latest published release, PyPI's `Skill` doesn't have `needs_approval`
yet — pydantic drops it silently. The runtime falls back to reading the
raw bundled `agent.json` instead of the typed object whenever the typed
field comes back empty, and that fallback is what actually functions in
every real deployment today. `vystak plan` validation is unaffected — it
runs against the local dev `vystak`, which does have the field — so plan
correctly rejects an unknown tool name even though the *deployed*
container is on the fallback path. The typed field takes over
transparently once a release ships it.

## Try it

`examples/docker-approvals/` deploys one agent with a gated
`restart_service` tool behind the panel (Slack optional). Its README walks
through approving, denying, and confirming the park survives a closed tab
or an agent restart.

## Related

- [Durable Execution](./durable-execution) — the checkpointer and
  park/resume RPCs this feature builds on
- `docs/approvals.md` in the repo — full implementation reference
