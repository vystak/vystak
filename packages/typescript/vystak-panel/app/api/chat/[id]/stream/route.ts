import { createUIMessageStreamResponse } from 'ai';
import { auth } from '@/auth';
import { resumeConversationStream } from '@/lib/panel';
import { panelStreamToUIChunks } from '@/lib/stream';

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });

  const { id } = await params;
  let upstream: Response;
  try {
    upstream = await resumeConversationStream(email, id);
  } catch {
    // Panel unreachable — nothing to resume is the safe answer here; the
    // page still renders persisted history.
    return new Response(null, { status: 204 });
  }
  if (upstream.status === 204 || !upstream.ok || !upstream.body) {
    return new Response(null, { status: 204 });
  }
  return createUIMessageStreamResponse({
    stream: panelStreamToUIChunks(upstream.body),
  });
}
