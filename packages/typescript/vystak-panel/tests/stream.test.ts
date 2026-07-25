import { describe, expect, it } from 'vitest';
import { panelStreamToUIChunks } from '../lib/stream';

function sseBody(...payloads: (object | string)[]): ReadableStream<Uint8Array> {
  const text = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}\n\n`)
    .join('');
  return new Blob([text]).stream() as ReadableStream<Uint8Array>;
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
});
