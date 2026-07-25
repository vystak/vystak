import { redirect } from 'next/navigation';
import type { UIMessage } from 'ai';
import { auth } from '@/auth';
import { Chat } from '@/components/chat';
import { listConversations, listMessages } from '@/lib/panel';

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ projectId: string; convId: string }>;
}) {
  const { projectId, convId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');

  const [{ conversations }, { messages }] = await Promise.all([
    listConversations(email, projectId),
    listMessages(email, convId),
  ]);
  const conversation = conversations.find(c => c.id === convId);
  if (!conversation) redirect(`/p/${projectId}`);

  const initialMessages: UIMessage[] = messages.map(m => ({
    id: m.id,
    role: m.role,
    parts: [{ type: 'text', text: m.content }],
  }));

  return (
    <Chat
      conversationId={convId}
      initialMessages={initialMessages}
      agentName={conversation.agent_name}
    />
  );
}
