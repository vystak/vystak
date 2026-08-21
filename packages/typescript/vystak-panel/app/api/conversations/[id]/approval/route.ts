import { auth } from '@/auth';
import { postApproval } from '@/lib/panel';

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return new Response('Unauthorized', { status: 401 });

  const { id } = await params;
  const body = (await req.json()) as {
    turn_id?: string;
    approved?: boolean;
    note?: string | null;
  };
  if (!body.turn_id || typeof body.approved !== 'boolean') {
    return new Response('turn_id and approved required', { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await postApproval(email, id, {
      turn_id: body.turn_id,
      approved: body.approved,
      note: body.note ?? null,
    });
  } catch {
    return new Response('panel channel unreachable', { status: 502 });
  }
  return new Response(await upstream.text(), { status: upstream.status });
}
