import { describe, expect, it } from 'vitest';
import { panelStreamToUIChunks } from '../lib/stream';

function sseBody(...payloads: (object | string)[]): ReadableStream<Uint8Array> {
  const text = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}\n\n`)
    .join('');
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
});
