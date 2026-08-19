import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { panelStreamToUIChunks } from '../lib/stream';

function sseBody(...payloads: (object | string)[]): ReadableStream<Uint8Array> {
  const text = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}\n\n`)
    .join('');
  return new Blob([text]).stream() as ReadableStream<Uint8Array>;
}

// Shared cross-language fixture (Task 3 also asserts this file byte-for-byte
// on the Python side) — pins the panel SSE wire format so the two languages
// can't silently drift apart.
const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/panel-sse.txt', import.meta.url));

function fixtureBody(): ReadableStream<Uint8Array> {
  const text = readFileSync(FIXTURE_PATH, 'utf-8');
  return new Blob([text]).stream() as ReadableStream<Uint8Array>;
}

function failingBody(firstFrame: string): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(firstFrame));
      // Per the WHATWG streams spec, calling error() synchronously in the
      // same tick as enqueue() clears the queue before any read can
      // observe it — the first read() would reject with no chunk ever
      // delivered. Defer by a microtask so the reader actually gets the
      // enqueued frame on the first read and the error on the next one,
      // which is what a real mid-stream connection drop looks like.
      queueMicrotask(() => controller.error(new Error('connection reset')));
    },
  });
}

async function collect(stream: ReadableStream<unknown>): Promise<unknown[]> {
  const out: unknown[] = [];
  const reader = stream.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    out.push(value);
  }
  return out;
}

describe('panelStreamToUIChunks', () => {
  it('emits a data-reset marker on a reset frame', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody({ type: 'delta', text: 'stale' }, { type: 'reset' }, { type: 'delta', text: 'fresh' }),
      ),
    );
    expect(chunks).toContainEqual({ type: 'data-reset', data: {} });
  });

  // The marker must land *after* a text-end for whatever was open, and the
  // next delta must open a brand-new text part (not resume the pre-reset
  // one) — see the comment on `visiblePartsAfterReset` in lib/messageParts.ts
  // for why: reusing the pre-reset text id would let a post-reset delta
  // mutate a part that sits *before* the marker, which the client's
  // post-marker render filter would then never show at all.
  it('closes the open text part and opens a fresh one around the reset marker', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          { type: 'delta', text: 'stale' },
          { type: 'reset' },
          { type: 'delta', text: 'fresh' },
          { type: 'done', message_id: 'm2', response_id: 'r2', title: 'T' },
        ),
      ),
    );
    expect(chunks).toEqual([
      { type: 'start' },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'stale' },
      { type: 'text-end', id: 'panel-text' },
      { type: 'data-reset', data: {} },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'fresh' },
      { type: 'text-end', id: 'panel-text' },
      { type: 'finish' },
    ]);
  });

  it('passes through streams with no reset unchanged', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(sseBody({ type: 'delta', text: 'a' }, { type: 'delta', text: 'b' })),
    );
    expect(chunks).not.toContainEqual(expect.objectContaining({ type: 'data-reset' }));
  });

  it('maps deltas to a text part between start and finish', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          { type: 'delta', text: 'Hel' },
          { type: 'delta', text: 'lo' },
          { type: 'done', message_id: 'm1', response_id: 'r1', title: 'T' },
        ),
      ),
    );
    expect(chunks).toEqual([
      { type: 'start' },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'Hel' },
      { type: 'text-delta', id: 'panel-text', delta: 'lo' },
      { type: 'text-end', id: 'panel-text' },
      { type: 'finish' },
    ]);
  });

  it('maps error events to error chunks', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(sseBody({ type: 'error', message: 'boom' })),
    );
    expect(chunks[0]).toEqual({ type: 'start' });
    expect(chunks).toContainEqual({ type: 'error', errorText: 'boom' });
    expect(chunks[chunks.length - 1]).toEqual({ type: 'finish' });
  });

  it('done without any delta still emits valid start/finish', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody({ type: 'done', message_id: 'm1', response_id: 'r1', title: '' }),
      ),
    );
    expect(chunks).toEqual([{ type: 'start' }, { type: 'finish' }]);
  });

  it('surfaces a dropped connection as an error instead of a clean finish', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(failingBody('data: {"type":"delta","text":"par"}\n\n')),
    );
    expect(chunks[0]).toEqual({ type: 'start' });
    expect(chunks).toContainEqual({ type: 'text-delta', id: 'panel-text', delta: 'par' });
    const errorChunk = chunks.find(
      (c): c is { type: string; errorText: string } =>
        typeof c === 'object' && c !== null && (c as { type?: string }).type === 'error',
    );
    expect(errorChunk).toBeDefined();
    expect(errorChunk?.errorText).toContain('connection reset');
    expect(chunks[chunks.length - 1]).toEqual({ type: 'finish' });
    const textEndCount = chunks.filter(
      c => typeof c === 'object' && c !== null && (c as { type?: string }).type === 'text-end',
    ).length;
    expect(textEndCount).toBe(1);
  });

  it('maps the shared panel-sse fixture to the exact chunk sequence', async () => {
    const chunks = await collect(panelStreamToUIChunks(fixtureBody()));
    expect(chunks).toEqual([
      { type: 'start' },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'Let me check ' },
      { type: 'text-delta', id: 'panel-text', delta: 'the weather.' },
      { type: 'text-end', id: 'panel-text' },
      {
        type: 'tool-input-start',
        toolCallId: 'call_1',
        toolName: 'get_weather',
        dynamic: true,
      },
      {
        type: 'tool-input-available',
        toolCallId: 'call_1',
        toolName: 'get_weather',
        input: { city: 'Kyiv' },
        dynamic: true,
      },
      {
        type: 'tool-output-available',
        toolCallId: 'call_1',
        output: '{"tempC": 21, "conditions": "clear"}',
        dynamic: true,
      },
      { type: 'text-start', id: 'panel-text-2' },
      { type: 'text-delta', id: 'panel-text-2', delta: "It's 21" },
      { type: 'text-delta', id: 'panel-text-2', delta: '°C and clear.' },
      { type: 'text-end', id: 'panel-text-2' },
      { type: 'finish' },
    ]);
  });

  it('closes the open text part before a tool call and opens a fresh one when text resumes', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          { type: 'delta', text: 'A' },
          {
            type: 'tool_call',
            tool_call_id: 'c1',
            tool_name: 'foo',
            arguments: '{"x": 1}',
          },
          { type: 'tool_result', tool_call_id: 'c1', output: 'ok', is_error: false },
          { type: 'delta', text: 'B' },
          { type: 'done', message_id: 'm1', response_id: 'r1', title: 'T' },
        ),
      ),
    );
    expect(chunks).toEqual([
      { type: 'start' },
      { type: 'text-start', id: 'panel-text' },
      { type: 'text-delta', id: 'panel-text', delta: 'A' },
      { type: 'text-end', id: 'panel-text' },
      { type: 'tool-input-start', toolCallId: 'c1', toolName: 'foo', dynamic: true },
      {
        type: 'tool-input-available',
        toolCallId: 'c1',
        toolName: 'foo',
        input: { x: 1 },
        dynamic: true,
      },
      { type: 'tool-output-available', toolCallId: 'c1', output: 'ok', dynamic: true },
      { type: 'text-start', id: 'panel-text-2' },
      { type: 'text-delta', id: 'panel-text-2', delta: 'B' },
      { type: 'text-end', id: 'panel-text-2' },
      { type: 'finish' },
    ]);
    // The two text parts must have distinct ids, and no tool chunk may sit
    // between a text-start and its matching text-end.
    const textStartIds = chunks
      .filter((c): c is { type: string; id: string } => (c as { type?: string }).type === 'text-start')
      .map(c => c.id);
    expect(new Set(textStartIds).size).toBe(textStartIds.length);
    expect(textStartIds).toEqual(['panel-text', 'panel-text-2']);
  });

  it('emits tool-output-error with errorText when is_error is true', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          {
            type: 'tool_call',
            tool_call_id: 'c1',
            tool_name: 'foo',
            arguments: '{}',
          },
          { type: 'tool_result', tool_call_id: 'c1', output: 'boom', is_error: true },
          { type: 'done', message_id: 'm1', response_id: 'r1', title: 'T' },
        ),
      ),
    );
    expect(chunks).toContainEqual({
      type: 'tool-output-error',
      toolCallId: 'c1',
      errorText: 'boom',
      dynamic: true,
    });
    expect(chunks).not.toContainEqual(
      expect.objectContaining({ type: 'tool-output-available' }),
    );
  });

  it('passes non-JSON arguments through as a raw string without throwing', async () => {
    const chunks = await collect(
      panelStreamToUIChunks(
        sseBody(
          {
            type: 'tool_call',
            tool_call_id: 'c1',
            tool_name: 'foo',
            arguments: 'not valid json{',
          },
          { type: 'tool_result', tool_call_id: 'c1', output: 'ok', is_error: false },
          { type: 'done', message_id: 'm1', response_id: 'r1', title: 'T' },
        ),
      ),
    );
    expect(chunks).toContainEqual({
      type: 'tool-input-available',
      toolCallId: 'c1',
      toolName: 'foo',
      input: 'not valid json{',
      dynamic: true,
    });
  });
});
