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
