import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { Sidebar } from '@/components/sidebar';
import { getBootstrap, listProjects } from '@/lib/panel';

export default async function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin');
  const { projects } = await listProjects(email);
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar
        projects={projects}
        activeProjectId={projectId}
        user={bootstrap.user}
      />
      <main style={{ flex: 1, padding: 16 }}>{children}</main>
    </div>
  );
}
