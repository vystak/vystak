import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { NewConversationDialog } from '@/components/new-conversation-dialog';
import { PageHeader } from '@/components/page-header';
import { ProjectSettings } from '@/components/project-settings';
import { Button } from '@/components/ui/button';
import { getBootstrap, listMembers, listProjects } from '@/lib/panel';
import { MessagesSquareIcon, PlusIcon } from 'lucide-react';

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
  const [{ projects }, { members }] = await Promise.all([
    listProjects(email),
    listMembers(email, projectId),
  ]);
  const project = projects.find(p => p.id === projectId);
  return (
    <div className="flex h-svh flex-col">
      <PageHeader>
        <h1 className="truncate text-sm font-medium">
          {project?.name ?? 'Project'}
        </h1>
        <div className="ml-auto">
          <ProjectSettings projectId={projectId} members={members} />
        </div>
      </PageHeader>
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <MessagesSquareIcon className="size-6" />
          </div>
          <h2 className="text-lg font-semibold">Start a conversation</h2>
          <p className="text-sm text-muted-foreground">
            Pick one of your deployed agents and start chatting. Conversations
            appear in the sidebar.
          </p>
          <NewConversationDialog
            projectId={projectId}
            agents={bootstrap.agents}
            trigger={
              <Button>
                <PlusIcon /> New conversation
              </Button>
            }
          />
        </div>
      </div>
    </div>
  );
}
