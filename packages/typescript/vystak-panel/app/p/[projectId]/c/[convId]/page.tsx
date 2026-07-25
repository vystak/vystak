import { redirect } from 'next/navigation';
import type { UIMessage } from 'ai';
import { auth } from '@/auth';
import { Chat } from '@/components/chat';
import { ConversationTitle } from '@/components/conversation-title';
import { PageHeader } from '@/components/page-header';
import { ProjectSettings } from '@/components/project-settings';
import { Badge } from '@/components/ui/badge';
import { safeParseJson } from '@/lib/format';
import {
  getBootstrap,
  listConversations,
  listMembers,
  listMessages,
} from '@/lib/panel';
import type { MessagePart } from '@/lib/types';

type UIPart = UIMessage['parts'][number];

function toUIParts(parts: MessagePart[] | null | undefined, content: string): UIPart[] {
  if (!parts?.length) return [{ type: 'text', text: content }];
  return parts.map<UIPart>(p => {
    if (p.type === 'text') return { type: 'text', text: p.text };
    if (p.is_error) {
      return {
        type: 'dynamic-tool',
        toolCallId: p.tool_call_id,
        toolName: p.tool_name,
        state: 'output-error',
        input: safeParseJson(p.input),
        errorText: p.output,
      };
    }
    return {
      type: 'dynamic-tool',
      toolCallId: p.tool_call_id,
      toolName: p.tool_name,
      state: 'output-available',
      input: safeParseJson(p.input),
      output: p.output,
    };
  });
}

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ projectId: string; convId: string }>;
}) {
  const { projectId, convId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');

  const [{ conversations }, { messages }, { members }] = await Promise.all([
    listConversations(email, projectId),
    listMessages(email, convId),
    listMembers(email, projectId),
  ]);
  const conversation = conversations.find(c => c.id === convId);
  if (!conversation) redirect(`/p/${projectId}`);

  const initialMessages: UIMessage[] = messages.map(m => ({
    id: m.id,
    role: m.role,
    parts: toUIParts(m.parts, m.content),
  }));

  return (
    <div className="flex h-svh flex-col">
      <PageHeader>
        <ConversationTitle
          projectId={projectId}
          convId={convId}
          title={conversation.title}
        />
        <Badge variant="secondary">{conversation.agent_name}</Badge>
        <div className="ml-auto">
          <ProjectSettings projectId={projectId} members={members} />
        </div>
      </PageHeader>
      <Chat
        conversationId={convId}
        initialMessages={initialMessages}
        agentName={conversation.agent_name}
      />
    </div>
  );
}
