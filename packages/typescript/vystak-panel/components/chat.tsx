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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { AlertCircleIcon } from 'lucide-react';

export function Chat({
  conversationId,
  initialMessages,
  agentName,
}: {
  conversationId: string;
  initialMessages: UIMessage[];
  agentName: string;
}) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, error, clearError, stop } = useChat({
    id: conversationId,
    messages: initialMessages,
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
          {messages.map(message => (
            <Message from={message.role} key={message.id}>
              <MessageContent>
                {message.parts.map((part, i) => {
                  if (part.type === 'text') {
                    return (
                      <MessageResponse key={`${message.id}-${i}`}>
                        {part.text}
                      </MessageResponse>
                    );
                  }
                  if (part.type === 'dynamic-tool') {
                    return (
                      <Tool
                        key={part.toolCallId}
                        defaultOpen={part.state === 'output-error'}
                      >
                        <ToolHeader
                          type={`tool-${part.toolName}`}
                          state={part.state}
                        />
                        <ToolContent>
                          <ToolInput input={part.input} />
                          <ToolOutput
                            output={
                              part.state === 'output-available'
                                ? part.output
                                : undefined
                            }
                            errorText={
                              part.state === 'output-error'
                                ? part.errorText
                                : undefined
                            }
                          />
                        </ToolContent>
                      </Tool>
                    );
                  }
                  return null;
                })}
              </MessageContent>
            </Message>
          ))}
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
