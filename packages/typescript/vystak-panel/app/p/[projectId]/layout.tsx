import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { AppSidebar } from '@/components/app-sidebar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getBootstrap, listConversations, listProjects } from '@/lib/panel';

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
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');
  const [{ projects }, { conversations }] = await Promise.all([
    listProjects(email),
    listConversations(email, projectId),
  ]);
  return (
    <SidebarProvider>
      <AppSidebar
        projects={projects}
        conversations={conversations}
        activeProjectId={projectId}
        user={bootstrap.user}
        agents={bootstrap.agents}
      />
      <SidebarInset>{children}</SidebarInset>
    </SidebarProvider>
  );
}
