# Human-in-the-Loop Tool Approvals — Design

**Date:** 2026-08-20
**Status:** Approved for planning
**Builds on:** `2026-07-27-durable-checkpointed-execution-design.md` (merged as PR #7) — the park/`interrupt()`/`resumeDetached` seam was built explicitly as this feature's foundation.

## 1. Goal

A skill can mark tools as requiring human approval. When the agent decides to call a gated tool, the run parks *before* the tool executes — durably, at zero compute — and a human approves or denies from the panel or Slack. Approval executes the tool with the original arguments and the turn continues from its exact execution point; denial resolves the call to a standardized denied result and the agent continues and adapts. Parked approvals wait indefinitely and survive agent restarts and browser closes.

## 2. Decisions (fixed by this design)

| Question | Decision |
|---|---|
| Approval surfaces (v1) | Panel **and** Slack |
| Granularity | Per-tool list on `Skill`: `needs_approval: [tool, ...]` |
| Deny semantics | Tool resolves to `"Denied by <decided_by>: <note>"`; turn continues (not an error, no `response.failed`) |
| Timeout | Park indefinitely; the panel's 15-minute turn deadline pauses while parked |
| Transports | Both HTTP and NATS |
| Authorization | Anyone in the conversation (panel project member / Slack channel participant); approver identity recorded |
| First decision wins | A second concurrent decision gets a clear "already resolved" error |

**Non-goals (v1):** MCP tool gating (MCP tools attach via `McpServer`, not skills — follow-up), per-approver authorization lists, argument-conditional gates, auto-deny TTLs, Discord surface.

## 3. Schema

`vystak.schema.Skill` gains:

```yaml
skills:
  - name: ops
    tools: [restart_service, read_logs]
    needs_approval: [restart_service]
```

- `needs_approval: list[str] = []`.
- Load-time validation (schema loader + `multi_loader`, surfacing at `vystak plan`): every name must be in the same skill's `tools`; unknown names are a load error.
- The field reaches the container via the existing bundled `agent.json` round-trip (`_vystak/runtime/config.py` loads the whole `Agent` object) — no new env plumbing.
- Hash impact: the field changes deploy identity (prompt/tool behavior), so it contributes to `AgentHashTree` like other skill fields.

## 4. Agent-side gate (template runtime)

**Choke point:** `app_factory.build_agent_app` assembles `user_tools + workspace_tools + subagent_tools + skill_tools + schedule_tools` and passes them to `build_graph` — at two call sites (initial build, and the lifespan MCP-rebuild). Both call sites apply the same wrapping step.

**Wrapper.** For each tool whose name appears in any skill's `needs_approval`, wrap it in a `StructuredTool` preserving name / description / args schema. The coroutine:

```python
decision = interrupt({
    "kind": "tool_approval",
    "tool": tool_name,
    "args": kwargs,          # the exact arguments the model chose
    "skill": skill_name,
})
if decision.get("approved"):
    return await original(**kwargs)
return f"Denied by {decision.get('decided_by', 'unknown')}: {decision.get('note') or 'no reason given'}"
```

- `interrupt()` parks the run on the durable checkpointer; the existing park detection marks the journal row `parked`. Nothing executes until resume.
- The resume value (any JSON) is the decision object: `{"approved": bool, "decided_by": str, "note": str | null}`.
- Each gated call parks individually; sequential gated calls produce sequential approval requests.
- Restart while parked: already handled — re-drive leaves `parked` turns alone; the checkpoint holds the pending interrupt.

## 5. Surfacing the pending approval

Today the interrupt payload is read nowhere. Additions:

1. **`GET /v1/_vystak/checkpoint`** gains `"interrupts": [<payload>, ...]` from `snapshot.tasks[*].interrupts` — the transport-agnostic source of truth.
2. **NATS detached path:** when the shared SSE consumer detects a park, it fetches the payload and publishes a **non-terminal, seq'd** event into the turn's JetStream subject:
   `{"type": "vystak.approval.requested", "payload": {...}}` — live consumers learn why the turn parked without polling.
3. **`responses/turnStatus`** additionally returns the pending payload when status is `parked` (covers re-attach after the stream event was consumed).
4. **A2A executor** (`a2a_native/executor.py`): after its run ends, it checks graph state; if interrupted, instead of an empty reply it returns a structured **approval-pending reply** carrying the payload and the thread id. This is what the Slack path consumes.

## 6. Resume paths

**Panel (NATS).**
- New sender `PanelNatsClient.resume_detached(agent_name, turn_id, resume)` → the bridge's existing `responses/resumeDetached`.
- `_handle_resume_detached` gains the status guard (from the todo backlog): only `parked` rows may be resumed; anything else → JSON-RPC error ("already resolved" to a losing concurrent approver).
- The resumed stream continues into the same JetStream subject with **no rewind** (nothing was lost on a park) — the panel's live view continues seamlessly.
- `run_turn_persister`'s 15-minute deadline **pauses while status is `parked`** (the deadline clock excludes parked time; it resumes on decision), implementing park-indefinitely without unbounding genuinely-stuck running turns.

**Panel (HTTP transport).** The panel's HTTP path streams `/v1/responses` directly; on a park the stream ends with no terminal event. The channel then consults `GET /v1/_vystak/checkpoint` for the `interrupts` payload (persisting the same approval-requested part), and a decision POSTs the agent's `/v1/_vystak/resume` and consumes the continued SSE — the same primitives as the Slack-HTTP path below.

**Slack (both transports).** The Slack runner, on receiving an approval-pending A2A reply, posts a Block Kit message with Approve / Deny buttons (Socket Mode delivers `block_actions` over the socket; no public HTTP endpoint needed). On click:
- **HTTP transport:** the channel client POSTs the agent's existing `POST /v1/_vystak/resume {thread_id, resume}` and consumes the SSE stream to the final text.
- **NATS transport:** new small bridge RPC `responses/resumeThread {thread_id, resume}` — needed because A2A turns have no detached-journal row for `resumeDetached` to key on. The bridge drives the local resume endpoint, consumes the stream, and replies with the final text (mirroring how a normal A2A reply is produced).

The runner then posts the agent's final reply in-thread and edits the button message to "Approved by @user" / "Denied by @user". Approver identity: Slack user id/display name → `decided_by`.

## 7. Panel UI + persistence

- The `vystak.approval.requested` event translates to a `PanelStreamEvent` and browser frame, and `TurnAccumulator` gains the previously-undefined shape for an unresolved call — a persisted part:
  `{"type": "tool", "state": "approval-requested", "tool_call_id", "tool_name", "input"}`.
  (This replaces the current behavior of silently dropping a `tool_call` that never got a result.)
- The vendored AI Elements tool component already ships "Awaiting Approval" / "Denied" badge states — they get wired. The card renders Approve / Deny buttons and an optional note field.
- Click → new Next.js API route → panel channel endpoint `POST /api/turns/{turn_id}/approval {"approved": bool, "note": str | null}`; `decided_by` = the signed-in user's email; the channel calls the resume path for its transport.
- After the decision, the live stream continues and the part transitions to its completed state (or a Denied badge, rendered from the standardized denied tool result).
- A reload while parked re-renders the pending card from the persisted part plus `turnStatus` — approvals survive agent restarts *and* browser closes.

## 8. Failure handling

- **Concurrent decisions:** first wins (bridge/parked guard); the loser gets "already resolved", surfaced as a toast (panel) / ephemeral message (Slack).
- **Agent restart while parked:** turn stays parked; the card persists; the re-drive sweep skips parked rows (already true).
- **Deny is not an error:** it's a normal tool result; no synthetic `response.failed`, the turn completes normally.
- **Plan-time:** `needs_approval` naming a tool absent from the skill's `tools` fails the load/`vystak plan`.
- **Unreachable agent at decision time:** the resume call fails visibly at the surface (toast / Slack ephemeral); the turn remains parked and the decision can be retried.

## 9. Testing

- **Unit:** wrapper approve / deny / args passthrough / decision shape; schema + multi_loader validation; checkpoint-endpoint `interrupts` payload; bridge `approval.requested` event + parked-only resume guard; `resumeThread` RPC; accumulator approval part shape; Slack approval-pending reply handling and block-action dispatch; panel channel approval endpoint.
- **Template integration:** extend the existing real-`interrupt()` test into a real gated tool driven end-to-end via `resumeDetached` — one approve path (tool executes once), one deny path (denied result string, turn completes).
- **Release cells:** a live panel approvals cell (`release_live_chat`: gated tool, approve mid-turn, assert the tool ran exactly once and the decision is persisted on the part) and a Slack cell gated behind `release_slack` tokens.
- **Example:** `examples/docker-approvals` — one harmless tool, one gated destructive-looking tool, README walkthrough for both panel and Slack surfaces.

## 10. Follow-ups this design absorbs or creates

- Absorbs: the `_handle_resume_detached` parked-status guard (todo backlog).
- Creates: MCP tool gating (v2); per-approver authorization (v2); the panel SSE proxy's idle-as-terminal inconsistency becomes more visible with long parks and should be fixed alongside (it already has a backlog entry).
