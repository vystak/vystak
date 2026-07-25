import Link from 'next/link';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { NewConversation } from '@/components/new-conversation';
import { getBootstrap, listConversations } from '@/lib/panel';

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
  const { conversations } = await listConversations(email, projectId);
  return (
    <div>
      <NewConversation projectId={projectId} agents={bootstrap.agents} />
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
    </div>
  );
}
