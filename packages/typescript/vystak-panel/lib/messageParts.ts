import type { UIMessage } from 'ai';
import { safeParseJson } from './format';
import type { MessagePart } from './types';

// Element type of UIMessage['parts'] (default generics — no client-side
// `tools` map is declared, so tool parts always arrive/replay as
// 'dynamic-tool', never 'tool-<name>').
type UIPart = UIMessage['parts'][number];

/**
 * Map persisted message `parts` (vystak_channel_panel's ordered
 * text/tool segments) into AI SDK UIMessage parts for history replay.
 * Tool parts always replay as already-finished ('output-available' or
 * 'output-error') — a persisted row only exists once the turn completed.
 *
 * Falls back to a single text part built from `content` when `parts` is
 * null/empty (messages persisted before the parts column existed).
 *
 * `input` is JSON.parse'd with a raw-string fallback via `safeParseJson`,
 * mirroring lib/stream.ts's live-path handling of a tool call's arguments:
 * persisted `ToolMessagePart.input` is always a raw string (Python never
 * parses it), so history replay must apply this same transform to render
 * identically to the live stream after a reload. `output` has no such gap
 * — both the live path and this persisted shape leave it as the raw string.
 */
export function mapPersistedParts(
  parts: MessagePart[] | null | undefined,
  content: string,
): UIPart[] {
  if (!parts?.length) return [{ type: 'text', text: content }];
  return parts.map((part): UIPart => {
    if (part.type === 'text') {
      return { type: 'text', text: part.text };
    }
    const input = safeParseJson(part.input);
    if (part.state === 'approval-requested') {
      // Parked HITL tool call awaiting a decision — no output yet. 'ai'@5
      // doesn't declare this state (it's a v6 addition the vendored
      // tool.tsx already anticipates via `@ts-expect-error`), so this cast
      // follows that same local-augmentation convention rather than
      // upgrading the package.
      return {
        type: 'dynamic-tool',
        toolCallId: part.tool_call_id,
        toolName: part.tool_name,
        // @ts-expect-error state only available in AI SDK v6
        state: 'approval-requested',
        input,
      };
    }
    // A 'resolved' part (the decision has been made — see
    // routes_approvals.py's _resolve_pending_part) intentionally falls
    // through to the same finished-part shape as any other completed tool
    // call below: it renders as a normal/neutral tool block (no live
    // buttons) rather than a distinct visual state. Its `output` is
    // typically empty (the real result lives in a later message's own
    // tool_call/tool_result pair — see task-9's resume path), which
    // ToolOutput already renders as nothing, so this reads as a quiet
    // "completed" block instead of a duplicate of that later part.
    if (part.is_error) {
      return {
        type: 'dynamic-tool',
        toolCallId: part.tool_call_id,
        toolName: part.tool_name,
        state: 'output-error',
        input,
        errorText: part.output,
      };
    }
    return {
      type: 'dynamic-tool',
      toolCallId: part.tool_call_id,
      toolName: part.tool_name,
      state: 'output-available',
      input,
      output: part.output,
    };
  });
}

/**
 * Render-time filter for a rewound turn's 'data-reset' marker
 * (emitted by lib/stream.ts on a Task 11 `{"type": "reset"}` SSE frame).
 *
 * The AI SDK's UIMessageChunk protocol has no operation that removes parts
 * already committed to a streaming message — `useChat`'s internal reducer
 * (`processUIMessageStream` in the `ai` package) always *appends* on
 * 'text-start', and on a resumed stream it seeds that message from a
 * `structuredClone` of the pre-disconnect message, parts included
 * (`@ai-sdk/react`'s `ChatState.snapshot`). Splicing the public `messages`
 * array from a `useChat({ onData })` callback doesn't survive either: every
 * subsequent chunk's `write()` re-stamps `this.state.messages[i]` from that
 * same internal, un-spliced streaming object
 * (`AbstractChat`'s `replaceMessage(idx, response.state.message)`), so any
 * onData-time edit to the public array is overwritten by the very next
 * delta. Verified by reading the installed `ai@5.0.220` /
 * `@ai-sdk/react@2.0.222` sources — see task-12-report.md.
 *
 * So instead of trying to erase state we can't reach, the marker is left in
 * place and the *renderer* only shows what comes after the last one: since
 * the marker is a non-transient data part, the SDK's own reducer pushes it
 * into `message.parts` unconditionally (no `dataPartSchemas` registration
 * needed — the wire schema accepts any unregistered `data-*` type), and it
 * keeps that position through every later `write()` for the rest of the
 * stream. Parts before the last marker are stale pre-rewind content and are
 * simply never rendered; nothing needs to be mutated or removed.
 */
/**
 * Live-path approval bookkeeping: maps each still-unresolved 'data-approval'
 * marker's toolCallId to its turnId (see lib/stream.ts's 'approval' branch
 * — it enqueues a marker alongside a pending dynamic-tool part whose
 * toolCallId is `approval:<tool>`, distinct from the real tool_call's own
 * id once the turn resumes).
 *
 * A marker resolves the same way the Python persister already resolves it
 * server-side for the live-NATS path (`turn_stream.py`'s `feed`, lines
 * ~120-130: a `tool_call` for the same tool_name supersedes the pending
 * `approval-requested` part) — by TOOL NAME, not toolCallId, since the
 * resumed call gets its own agent-minted id. A marker whose pending part's
 * toolName has a LATER completed ('output-available' | 'output-error')
 * dynamic-tool part anywhere in `parts` is dropped from the result.
 *
 * Without this, a resumed HTTP-path turn (which persists the resume as a
 * separate message rather than rewriting this one — see task-9's
 * `_resolve_pending_part`) would leave a NATS-live client showing
 * Approve/Deny controls forever on a call that already has a real answer
 * sitting right next to it.
 */
export function pendingApprovalTurns(parts: UIPart[]): Map<string, string> {
  const markers = new Map<string, string>();
  const toolNameByCallId = new Map<string, string>();
  const resolvedToolNames = new Set<string>();
  for (const part of parts) {
    if (part.type === 'data-approval') {
      const data = part.data as { toolCallId: string; turnId: string };
      markers.set(data.toolCallId, data.turnId);
    } else if (part.type === 'dynamic-tool') {
      const state = part.state as string;
      toolNameByCallId.set(part.toolCallId, part.toolName);
      if (state === 'output-available' || state === 'output-error') {
        resolvedToolNames.add(part.toolName);
      }
    }
  }
  const pending = new Map<string, string>();
  for (const [toolCallId, turnId] of markers) {
    const toolName = toolNameByCallId.get(toolCallId);
    if (toolName && resolvedToolNames.has(toolName)) continue;
    pending.set(toolCallId, turnId);
  }
  return pending;
}

export function visiblePartsAfterReset(parts: UIPart[]): UIPart[] {
  let lastResetIndex = -1;
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].type === 'data-reset') lastResetIndex = i;
  }
  return lastResetIndex === -1 ? parts : parts.slice(lastResetIndex + 1);
}
