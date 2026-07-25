import Link from 'next/link';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { Members } from '@/components/members';
import { getBootstrap, listConversations, listMembers } from '@/lib/panel';

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');
  const [{ conversations }, { members }] = await Promise.all([
    listConversations(email, projectId),
    listMembers(email, projectId),
  ]);
  return (
    <div>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {conversations.map(c => (
          <li key={c.id} style={{ margin: '8px 0' }}>
            <Link href={`/p/${projectId}/c/${c.id}`}>
              {c.title || '(untitled)'}{' '}
              <small>· {c.agent_name}</small>
            </Link>
          </li>
        ))}
      </ul>
      <Members projectId={projectId} members={members} />
    </div>
  );
}
