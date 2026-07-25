import { redirect } from 'next/navigation';
import type { UIMessage } from 'ai';
import { auth } from '@/auth';
import { Chat } from '@/components/chat';
import { mapPersistedParts } from '@/lib/messageParts';
import { getBootstrap, listConversations, listMessages } from '@/lib/panel';

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

  const [{ conversations }, { messages }] = await Promise.all([
    listConversations(email, projectId),
    listMessages(email, convId),
  ]);
  const conversation = conversations.find(c => c.id === convId);
  if (!conversation) redirect(`/p/${projectId}`);

  const initialMessages: UIMessage[] = messages.map(m => ({
    id: m.id,
    role: m.role,
    // parts is null for rows written before the schema-2 migration (and any
    // row where the channel didn't populate it) — fall back to synthesizing
    // a single text part from content, exactly as before parts existed.
    // The store never persists an empty array (routes_messages.py writes
    // `msg_parts or None`), but guard length too rather than trust that
    // invariant across the wire — an empty-but-truthy array must not
    // render a blank message where `content` still has text.
    parts:
      Array.isArray(m.parts) && m.parts.length > 0
        ? mapPersistedParts(m.parts)
        : [{ type: 'text', text: m.content }],
  }));

  return (
    <Chat
      conversationId={convId}
      initialMessages={initialMessages}
      agentName={conversation.agent_name}
    />
  );
}
