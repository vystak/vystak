import { createUIMessageStreamResponse } from 'ai';
import { auth } from '@/auth';
import { streamConversationMessage } from '@/lib/panel';
import { panelStreamToUIChunks } from '@/lib/stream';

export async function POST(req: Request) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });

  const { conversationId, text } = (await req.json()) as {
    conversationId?: string;
    text?: string;
  };
  if (!conversationId || !text?.trim()) {
    return new Response('conversationId and text required', { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await streamConversationMessage(email, conversationId, text);
  } catch {
    return new Response('panel channel unreachable', { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response(`panel channel error: ${upstream.status}`, {
      status: 502,
    });
  }
  return createUIMessageStreamResponse({
    stream: panelStreamToUIChunks(upstream.body),
  });
}
