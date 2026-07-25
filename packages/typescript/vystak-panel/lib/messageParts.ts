import type { UIMessage } from 'ai';
import type { MessagePart } from './types';

// Element type of UIMessage['parts'] (default generics — no client-side
// `tools` map is declared, so tool parts always arrive/replay as
// 'dynamic-tool', never 'tool-<name>').
type UIPart = UIMessage['parts'][number];

export type ToolPartState = 'input-streaming' | 'input-available' | 'output-available' | 'output-error';

/**
 * Human label for a dynamic-tool part's state. Exhaustive over the four
 * states the AI SDK defines; a state affordance for the chat UI.
 */
export function toolStateLabel(state: ToolPartState): string {
  switch (state) {
    case 'input-streaming':
    case 'input-available':
      return 'running…';
    case 'output-available':
      return 'done';
    case 'output-error':
      return 'failed';
  }
}

/**
 * Defensive stringify for a tool part's `input`/`output`, both typed
 * `unknown` by the AI SDK. Never throws: a running tool has no `output`
 * yet (undefined), and inputs/outputs that resist JSON.stringify (e.g. a
 * BigInt or circular reference) fall back to String(value) rather than
 * crashing the render.
 */
export function stringifyToolValue(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * Mirrors lib/stream.ts's live-path handling of a tool call's arguments:
 * JSON.parse into a structured value, falling back to the raw string on
 * parse failure. Persisted `ToolMessagePart.input` is always a raw string
 * (Python never parses it), so history replay must apply this same
 * transform to render identically to the live stream after a reload.
 */
export function parseToolInput(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/**
 * Map persisted message `parts` (vystak_channel_panel's ordered
 * text/tool segments) into AI SDK UIMessage parts for history replay.
 * Tool parts always replay as already-finished ('output-available' or
 * 'output-error') — a persisted row only exists once the turn completed.
 */
export function mapPersistedParts(parts: MessagePart[]): UIPart[] {
  return parts.map((part): UIPart => {
    if (part.type === 'text') {
      return { type: 'text', text: part.text };
    }
    const input = parseToolInput(part.input);
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
