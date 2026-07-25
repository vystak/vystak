import type { UIMessageChunk } from 'ai';

const TEXT_ID = 'panel-text';

/**
 * Adapt the panel channel's plain SSE ({type: delta|done|error}) into the
 * AI SDK UI message stream chunks consumed by useChat. The Python side
 * stays protocol-neutral; this is the only Vercel-specific encoding.
 */
export function panelStreamToUIChunks(
  body: ReadableStream<Uint8Array>,
): ReadableStream<UIMessageChunk> {
  const decoder = new TextDecoder();
  let buffer = '';
  let textOpen = false;

  return new ReadableStream<UIMessageChunk>({
    async start(controller) {
      controller.enqueue({ type: 'start' });
      const reader = body.getReader();
      const handleLine = (line: string) => {
        if (!line.startsWith('data: ')) return;
        let payload: { type?: string; text?: string; message?: string };
        try {
          payload = JSON.parse(line.slice(6));
        } catch {
          return;
        }
        if (payload.type === 'delta') {
          if (!textOpen) {
            controller.enqueue({ type: 'text-start', id: TEXT_ID });
            textOpen = true;
          }
          controller.enqueue({
            type: 'text-delta',
            id: TEXT_ID,
            delta: payload.text ?? '',
          });
        } else if (payload.type === 'error') {
          if (textOpen) {
            controller.enqueue({ type: 'text-end', id: TEXT_ID });
            textOpen = false;
          }
          controller.enqueue({
            type: 'error',
            errorText: payload.message ?? 'stream error',
          });
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
        if (textOpen) {
          controller.enqueue({ type: 'text-end', id: TEXT_ID });
          textOpen = false;
        }
        controller.enqueue({
          type: 'error',
          errorText: err instanceof Error ? err.message : 'stream failed',
        });
      } finally {
        if (textOpen) controller.enqueue({ type: 'text-end', id: TEXT_ID });
        controller.enqueue({ type: 'finish' });
        controller.close();
      }
    },
  });
}
