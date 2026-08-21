# Human-in-the-loop tool approvals

A tool a skill declares as gated pauses the agent turn — durably, indefinitely
— until a human clicks Approve or Deny in the panel or Slack. Deny is not an
error: the turn continues, with the tool call short-circuited to a denial
string the model can reason about.

**v1 scope: skill tools only, Docker, panel + Slack, both transports.** MCP
tools are not gateable (they attach to an agent via `McpServer`, not a
skill's `tools` list — there's no hook point). There's no approver allowlist,
no argument-conditional gating, no auto-deny timeout, and no Discord support.
Verified on Docker; there is no Azure release coverage or example for this
feature (the gate itself lives in the framework template's tool wrapper,
which isn't provider-specific, but nothing here has been exercised against
`vystak-provider-azure`).

## Declaring a gate

```python
Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    needs_approval=["restart_service"],
)
```

`needs_approval` is a subset of the skill's own `tools`. Every entry must
name a tool that's actually in that list — validated at schema load time
(`vystak.schema.skill.validate_needs_approval`, wired into both
`skill_resolver.resolve_folder_skills` and `multi_loader`) and therefore at
`vystak plan`/`vystak apply`. Naming an unknown tool fails fast, before
anything deploys:

```
skill 'ops': needs_approval names tools not in its tools list: not_a_real_tool
```

`needs_approval` is part of the `Skill` object, which is hashed wholesale
like every other skill field (`vystak.hash.tree._hash_list` calls
`hash_model` on each skill). Adding or changing it changes the skill's hash,
which changes the agent's deploy hash — `vystak plan` shows a diff and
`vystak apply` redeploys the agent. (Known, separate gap: editing only a
`tools/<name>.py` function's *source* is invisible to `vystak plan` — the
hash doesn't cover tool implementation bodies. This predates approvals and
isn't specific to it.)

## The gate mechanism

The runtime (`_vystak/runtime/approvals.py`) wraps every tool named in
`needs_approval` before the LangGraph react-agent is built. A wrapped call
raises LangGraph's `interrupt()` **before** the underlying function runs:

```python
interrupt({
    "kind": "tool_approval",
    "tool": original.name,
    "args": kwargs,
    "skill": skill_name,
})
```

`interrupt()` doesn't fail and doesn't complete the turn — it parks it. The
graph state is checkpointed at that point (the same checkpointer — SQLite
by default, Postgres when the agent declares Postgres sessions — that
backs [durable execution](durable-execution.md)), so the pending decision
survives an agent container restart, not just a browser tab close.

Resuming passes a decision object through as the `interrupt()` return value:

```python
{"approved": bool, "decided_by": str, "note": str | None}
```

- **Approved** → the original tool actually runs, and the turn continues
  with its real result.
- **Denied** → the tool call is short-circuited to a string the model sees
  as the tool's output:

  ```
  Denied by {decided_by}: {note or "no reason given"}
  ```

  This is not an error path. The agent keeps going — typically explaining
  to the user that it couldn't proceed and why, referencing the denial text
  verbatim if it chooses to.

If a resumed run calls another gated tool later in the same turn, it parks
again — a fresh `interrupt()`, a fresh pending decision, same mechanism.

## Park is durable and indefinite

A parked turn has no deadline of its own. The panel's turn persister
(`vystak-channel-panel/turn_worker.py`) tracks an overall 15-minute wall
deadline per turn (`DEFAULT_TURN_DEADLINE_S = 900.0`), but **time spent
parked is excluded from that budget** — a park can legitimately outlast the
15 minutes, e.g. someone approves it the next morning. A confirmed park
(one where a `turnStatus` poll has actually reported `parked` at least once)
keeps that exclusion even if a later status poll flakes or the agent is
briefly unreachable; only *unconfirmed* time is bound by the deadline.

Because the pause is a checkpoint, not in-memory state:

- Closing the browser tab and reopening the panel later shows the same
  Awaiting Approval card, unresolved.
- Restarting the agent container while a turn is parked doesn't lose the
  pending decision.
- Restarting a channel container (Slack) doesn't lose it either — the
  Slack approve/deny buttons carry the agent route and thread id in their
  own payload, not in channel process memory, so a fresh channel process
  can still resolve them.

## First decision wins

If two people click Approve/Deny on the same pending approval, only the
first one to land takes effect.

- **NATS transport**: the bridge's `responses/resumeDetached` handler
  (`_vystak/runtime/nats_bridge.py`) checks the journal row's status and
  replies with a JSON-RPC error (`"turn is not parked"`) if it isn't
  `parked` — a second resume for an already-resolved turn always hits this
  check. The panel's `resume_detached` call surfaces that as a
  `RuntimeError`, which the route turns into `409`.
- **HTTP transport**: the panel claims an in-flight guard
  (`rt.turn_tasks[turn_id]`) synchronously, with no `await` between the
  membership check and the claim, so two concurrent POSTs for the same turn
  can't both win the race; the loser also gets `409`.
- A POST for a `turn_id` that isn't the conversation's current active turn
  (e.g. already resolved and moved on) gets `422`.

The loser's surface reflects this: in the panel, the losing request's
`fetch` returns non-200 and `ApprovalActions` renders the response body as
an inline error under the Approve/Deny controls. In Slack, the losing
click gets an ephemeral message: *"Could not apply decision (already
resolved or unavailable): ..."*.

## Surfaces

**v1 decision surfaces are panel and Slack only.** A gated agent driven
from any other surface — the chat channel (`vystak-channel-chat`'s
OpenAI-compatible endpoint), Discord, a heartbeat-triggered invocation, the
`vystak-chat` terminal REPL, or a subagent orchestrator calling a gated peer
— has no decision path on that surface. The turn still parks correctly
(the gate mechanism doesn't care who or what drove the turn), but nothing on
those surfaces can approve or deny it: the caller just sees the turn go
`input-required`/never complete, and the pending decision waits until
someone opens the panel (or the Slack thread, if that channel is also
configured) and resolves it there. An orchestrator whose subagent call hits
a gated peer gets a friendly waiting message instead of the raw approval
marker (`"The sub-agent is waiting for human approval of tool '<tool>' and
cannot proceed. A human must approve it in the panel or Slack."`) rather
than a way to decide it itself — subagent orchestration is a caller of a
gated turn, never a decision surface for one.

### Panel

`vystak-panel`'s `ApprovalActions` component (`components/approval-actions.tsx`)
renders inside the message transcript for a tool part whose state is
`approval-requested`: the tool name and args (from the persisted part),
an optional free-text note field, and Approve/Deny buttons. `POST
/api/conversations/{id}/approval` takes `{turn_id, approved, note}`;
`decided_by` is **not** sent by the client — the server fills it in from
the authenticated panel user's email.

Once resolved, the persisted part flips from `approval-requested` to
`resolved` (`_resolve_pending_part` in `routes_approvals.py`), so a page
reload after the decision renders the historical record, not a live control
for an already-made decision.

### Slack

Gated calls post a Block Kit message: the tool name, its JSON-formatted
args, and Approve/Deny buttons (`vystak_approve` / `vystak_deny` action
IDs). The button's `value` carries `{thread_id, tool, agent}` so a resume
still works even after a channel container restart wiped any in-process
route cache. Clicking a button:

- Edits the original message in place to `"Approved by @user"` or
  `"Denied by @user"` (`chat_update`, blocks cleared).
- If the resumed run parks again on another gated tool, posts a **new**
  approval message in the same thread rather than reusing the old one —
  sequential gated calls chain independent cards.
- Otherwise posts the agent's final reply in-thread.

This works identically whether the agent runs the default streaming
protocol or `a2a-turn` — the approval gate lives below both, in the tool
layer.

## Transports

Both NATS and HTTP support the gate. The difference is what happens to an
**already-open panel tab** when a park resolves:

- **NATS**: the bridge streams the resumed turn's events live back to any
  attached SSE connection — the transcript updates in the open tab with no
  reload.
- **HTTP**: the resumed turn does not push to an already-open tab. The
  panel's HTTP resume path runs the resume server-side and persists the
  result, but the browser only sees it on the next page load/reconnect.
  `examples/docker-approvals`'s live walkthrough (panel, no-reload
  continuation) specifically depends on NATS for that reason.

## The PyPI-schema fallback: read this before assuming `needs_approval` works in your deployment

Deployed agent containers install `vystak` from PyPI (unpinned, in
`_vystak/requirements.txt`), not the workspace/dev checkout. As of the
latest published release (`vystak==0.3.0`), PyPI's `vystak.schema.skill.Skill`
has **no** `needs_approval` field — pydantic's default `extra="ignore"`
silently drops it when the typed `Agent` object is reconstructed inside the
container.

`load_approval_map()` in `_vystak/runtime/approvals.py` handles this with a
fallback: it first checks the typed `Skill.needs_approval` field, and if
every skill comes back empty, it re-reads the raw bundled `agent.json` (the
project's own compiled agent definition, shipped into the image regardless
of what the installed `vystak` package understands) and pulls
`needs_approval` out of that JSON directly. **This fallback is the only
branch that functions in a real deployment today** — verified live by
`packages/python/vystak-provider-docker/tests/release/test_approvals.py`'s
`release_live_chat` cells, which run against a real container built exactly
this way.

The typed field only takes over once a `vystak` release ships it to PyPI —
at that point both branches agree and the fallback simply never triggers
(since the typed path won't come back empty). Nothing needs to change in
the runtime code for that cutover; it's automatic.

**`vystak plan` validation is different**: `validate_needs_approval` runs
inside the CLI's own process, against the local workspace/dev `vystak`
package (which does have the field) — so unknown-tool validation at plan
time works today, independent of what's published to PyPI. Don't confuse
"plan validates it" with "the deployed container's typed object has it" —
they're two different `vystak` installs.

## Try it

`examples/docker-approvals/` deploys one agent with a gated
`restart_service` tool behind the panel channel (Slack optional, commented
out in `vystak.py`). Its README walks through: approving a gated call live,
denying one and reading the denial text in the transcript, and confirming
durability by closing the tab (or restarting the agent container) mid-park
and finding the same pending card on return.

Release coverage: `packages/python/vystak-provider-docker/tests/release/test_approvals.py` —
two `release_live_chat` cells (approve, deny) against a real deployed
container, plus a `release_slack` smoke cell.

## Security and trust boundary

The agent's `POST /v1/_vystak/resume` and `GET /v1/_vystak/checkpoint`
endpoints are **unauthenticated within the deployment network** — same
posture as the durable-execution machinery they're part of (see
[`docs/durable-execution.md`](durable-execution.md)). Any process that can
reach the agent container's port can call `resume` with an arbitrary
decision (approving or denying on someone else's behalf) and can read
`checkpoint` to see a pending tool call's full arguments, including
whatever sensitive values were about to be passed to a gated tool.

This means the approval guarantee — "a human must decide before this tool
runs" — is only as strong as the network isolation around the agent
container. It does not, on its own, protect against another workload on
the same Docker network or a compromised sibling container. What actually
authenticates a decision is the *surface*: the panel authenticates its
users (session/password auth) and stamps `decided_by` from that identity
server-side; Slack authenticates via its own bot/app tokens and OAuth
scopes. Neither the panel nor Slack sends its authentication through to
the agent's `_vystak` routes — those routes trust whatever calls them.

A shared-secret (or similar) hardening of the `_vystak` routes is a
planned follow-up, not implemented here — don't build against an assumed
token today.

## Related

- [`docs/durable-execution.md`](durable-execution.md) — the checkpointer and
  park/resume RPCs (`turnStatus`, `resumeDetached`) this feature builds on.
- [`examples/docker-approvals/`](../examples/docker-approvals/) — the
  runnable walkthrough, including the Slack path.
