'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';
import type { UIMessage } from 'ai';
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation';
import { Loader } from '@/components/ai-elements/loader';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from '@/components/ai-elements/prompt-input';
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from '@/components/ai-elements/tool';
import { ApprovalActions } from '@/components/approval-actions';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { AlertCircleIcon } from 'lucide-react';
import { pendingApprovalTurns, visiblePartsAfterReset } from '@/lib/messageParts';

export function Chat({
  conversationId,
  initialMessages,
  agentName,
  activeTurnId,
}: {
  conversationId: string;
  initialMessages: UIMessage[];
  agentName: string;
  // The conversation's currently-parked turn, if any (Conversation.
  // active_turn_id). Only used as the turn_id source for an approval
  // decided on a *reloaded* pending part, where no live 'data-approval'
  // stream marker exists to carry it — see the dynamic-tool branch below.
  activeTurnId?: string | null;
}) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, error, clearError, stop, resumeStream } = useChat({
    id: conversationId,
    messages: initialMessages,
    resume: true,
    transport: new DefaultChatTransport({
      api: '/api/chat',
      prepareSendMessagesRequest({ messages }) {
        const last = messages[messages.length - 1];
        const text = last.parts
          .filter(p => p.type === 'text')
          .map(p => p.text)
          .join('');
        return { body: { conversationId, text } };
      },
    }),
  });

  const busy = status === 'submitted' || status === 'streaming';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto w-full max-w-3xl">
          {messages.map(message => {
            const visibleParts = visiblePartsAfterReset(message.parts);
            // Live path: still-unresolved 'data-approval' markers'
            // toolCallId->turnId (see lib/messageParts.ts's
            // pendingApprovalTurns — already accounts for a later
            // same-tool-name completion resolving the marker).
            const pendingTurnByToolCallId = pendingApprovalTurns(visibleParts);
            return (
              <Message from={message.role} key={message.id}>
                <MessageContent>
                  {visibleParts.map((part, i) => {
                    if (part.type === 'text') {
                      return (
                        <MessageResponse key={`${message.id}-${i}`}>
                          {part.text}
                        </MessageResponse>
                      );
                    }
                    if (part.type === 'dynamic-tool') {
                      const state = part.state as string;
                      // Unresolved approval: either the persisted-history
                      // path (part.state === 'approval-requested', from
                      // mapPersistedParts) or the live path (an unresolved
                      // 'data-approval' marker names this toolCallId).
                      const isPersistedApproval = state === 'approval-requested';
                      const liveTurnId = pendingTurnByToolCallId.get(part.toolCallId);
                      const isLiveApproval = liveTurnId !== undefined;
                      const isPendingApproval = isPersistedApproval || isLiveApproval;
                      const turnId = isLiveApproval ? (liveTurnId ?? null) : (activeTurnId ?? null);
                      // @ts-expect-error state only available in AI SDK v6
                      const headerState: typeof part.state = isPendingApproval
                        ? 'approval-requested'
                        : part.state;
                      return (
                        <Tool key={part.toolCallId} defaultOpen={state === 'output-error'}>
                          <ToolHeader type={`tool-${part.toolName}`} state={headerState} />
                          <ToolContent>
                            <ToolInput input={part.input} />
                            <ToolOutput
                              output={state === 'output-available' ? part.output : undefined}
                              errorText={state === 'output-error' ? part.errorText : undefined}
                            />
                            {isPendingApproval && (
                              <ApprovalActions
                                conversationId={conversationId}
                                turnId={turnId}
                                // Reopen the same reconnect endpoint
                                // `resume: true` already used on mount
                                // (GET /api/chat/[id]/stream, proxying the
                                // NATS turn subject) so the resumed
                                // content streams straight into this
                                // message without a reload. On an HTTP-only
                                // deployment (no NATS transport) the
                                // channel has nothing live to proxy and
                                // this is a no-op 204 — the resumed reply
                                // only becomes visible on the next reload.
                                onDecided={() => resumeStream()}
                              />
                            )}
                          </ToolContent>
                        </Tool>
                      );
                    }
                    return null;
                  })}
                </MessageContent>
              </Message>
            );
          })}
          {status === 'submitted' && <Loader />}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      {error && (
        <Alert
          variant="destructive"
          className="mx-auto mb-2 w-full max-w-3xl shrink-0"
        >
          <AlertCircleIcon />
          <AlertTitle>Agent error</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{error.message}</span>
            <Button variant="outline" size="sm" onClick={() => clearError()}>
              Dismiss
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div className="mx-auto w-full max-w-3xl shrink-0 p-4 pt-0">
        <PromptInput
          onSubmit={message => {
            if (busy) {
              stop();
              return;
            }
            const text = (message.text ?? '').trim();
            if (!text) return;
            sendMessage({ text });
            setInput('');
          }}
        >
          <PromptInputTextarea
            value={input}
            placeholder={`Message ${agentName}…`}
            onChange={e => {
              if (error) clearError();
              setInput(e.target.value);
            }}
          />
          <PromptInputSubmit status={status} disabled={!busy && !input.trim()} />
        </PromptInput>
      </div>
    </div>
  );
}
