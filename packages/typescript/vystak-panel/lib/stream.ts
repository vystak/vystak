import type { UIMessageChunk } from 'ai';

const TEXT_ID_BASE = 'panel-text';

/**
 * Adapt the panel channel's plain SSE ({type: delta|done|error|tool_call|
 * tool_result}) into the AI SDK UI message stream chunks consumed by
 * useChat. The Python side stays protocol-neutral; this is the only
 * Vercel-specific encoding.
 */
export function panelStreamToUIChunks(
  body: ReadableStream<Uint8Array>,
): ReadableStream<UIMessageChunk> {
  const decoder = new TextDecoder();
  let buffer = '';
  let textOpen = false;
  // Text arrives in runs, interrupted by tool calls. Each run needs its own
  // part id — the AI SDK keys parts by id, so reusing one across runs would
  // make the second run a no-op update to the first instead of a new part.
  // The first run keeps the original constant id for backward compatibility
  // with single-text-run callers/tests; later runs get a numbered suffix.
  let textRunCount = 0;
  let textId = TEXT_ID_BASE;
  // Replayed tool_call/tool_result frames after a rewind carry their
  // ORIGINAL toolCallId (the Python persister's own accumulator, untouched
  // by this adapter). Verified against installed ai@5.0.220: a dynamic
  // tool's 'tool-input-available' goes through `updateDynamicToolPart`,
  // which finds the *existing* part with that toolCallId anywhere in the
  // message (this adapter never emits 'step-start', so the search spans
  // the whole parts array) and updates it in place — including the stale
  // copy sitting BEFORE the 'data-reset' marker. `visiblePartsAfterReset`
  // then hides that (updated-but-still-pre-marker) part forever instead of
  // showing a fresh post-marker tool block. Prefixing the outgoing id by a
  // reset generation counter forces the replayed tool part to be treated
  // as new (no existing part has that prefixed id), so it gets pushed
  // fresh — after the marker. Rendering-only: persistence keys off the
  // Python side's own unprefixed ids, never this adapter's output.
  let resetGeneration = 0;
  const outgoingToolCallId = (id: string) =>
    resetGeneration === 0 ? id : `g${resetGeneration}:${id}`;

  return new ReadableStream<UIMessageChunk>({
    async start(controller) {
      controller.enqueue({ type: 'start' });
      const reader = body.getReader();

      const closeTextIfOpen = () => {
        if (!textOpen) return;
        controller.enqueue({ type: 'text-end', id: textId });
        textOpen = false;
      };

      const handleLine = (line: string) => {
        if (!line.startsWith('data: ')) return;
        let payload: {
          type?: string;
          text?: string;
          message?: string;
          tool_call_id?: string;
          tool_name?: string;
          arguments?: string;
          output?: string;
          is_error?: boolean;
        };
        try {
          payload = JSON.parse(line.slice(6));
        } catch {
          return;
        }
        if (payload.type === 'delta') {
          if (!textOpen) {
            textRunCount += 1;
            textId = textRunCount === 1 ? TEXT_ID_BASE : `${TEXT_ID_BASE}-${textRunCount}`;
            controller.enqueue({ type: 'text-start', id: textId });
            textOpen = true;
          }
          controller.enqueue({
            type: 'text-delta',
            id: textId,
            delta: payload.text ?? '',
          });
        } else if (payload.type === 'error') {
          closeTextIfOpen();
          controller.enqueue({
            type: 'error',
            errorText: payload.message ?? 'stream error',
          });
        } else if (payload.type === 'tool_call') {
          // A tool part must not open inside an unclosed text part.
          closeTextIfOpen();
          const toolCallId = outgoingToolCallId(payload.tool_call_id ?? '');
          const toolName = payload.tool_name ?? '';
          const rawArguments = payload.arguments ?? '';
          let input: unknown = rawArguments;
          try {
            input = JSON.parse(rawArguments);
          } catch {
            // The agent serializes arguments defensively; a non-JSON
            // payload must not kill the stream — fall back to the raw
            // string.
            input = rawArguments;
          }
          controller.enqueue({
            type: 'tool-input-start',
            toolCallId,
            toolName,
            dynamic: true,
          });
          controller.enqueue({
            type: 'tool-input-available',
            toolCallId,
            toolName,
            input,
            dynamic: true,
          });
        } else if (payload.type === 'tool_result') {
          closeTextIfOpen();
          const toolCallId = outgoingToolCallId(payload.tool_call_id ?? '');
          if (payload.is_error) {
            controller.enqueue({
              type: 'tool-output-error',
              toolCallId,
              errorText: payload.output ?? '',
              dynamic: true,
            });
          } else {
            controller.enqueue({
              type: 'tool-output-available',
              toolCallId,
              output: payload.output ?? '',
              dynamic: true,
            });
          }
        } else if (payload.type === 'reset') {
          // A resumed turn rewinds and re-emits its retained prefix from
          // scratch. The AI SDK's UIMessageChunk protocol has no chunk that
          // clears an in-progress assistant message's parts — 'start' only
          // touches id/metadata, and 'text-start' always appends a new part
          // rather than replacing one (verified against the installed
          // ai@5.0.220 processUIMessageStream). So instead of trying to
          // erase state we can't reach, drop a marker data part into the
          // stream: the client (components/chat.tsx) renders only the parts
          // that come after the last 'data-reset' marker in a message.
          //
          // Close (and discard) any text part that was open when the reset
          // arrived *before* emitting the marker, and reset this adapter's
          // own run bookkeeping. Without this, a post-reset delta would
          // resume writing into the still-open pre-reset text part (the AI
          // SDK keys deltas by id via activeTextParts) — mutating content
          // that sits *before* the marker in the parts array, which the
          // client's post-marker filter would then never render at all.
          closeTextIfOpen();
          textRunCount = 0;
          textId = TEXT_ID_BASE;
          resetGeneration += 1;
          controller.enqueue({ type: 'data-reset', data: {} });
        }
        // 'done' carries persistence ids the UI refetches via the API.
      };
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) handleLine(line.trim());
        }
        if (buffer.trim()) handleLine(buffer.trim());
      } catch (err) {
        // A transport-level failure (dropped connection, dead channel) never
        // produces an SSE line, so without this the finally below would emit
        // a clean finish and the user would see truncated text as complete.
        closeTextIfOpen();
        controller.enqueue({
          type: 'error',
          errorText: err instanceof Error ? err.message : 'stream failed',
        });
      } finally {
        closeTextIfOpen();
        controller.enqueue({ type: 'finish' });
        controller.close();
      }
    },
  });
}
