'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';
import type { UIMessage } from 'ai';

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
  const { messages, sendMessage, status, error } = useChat({
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

  return (
    <div style={{ maxWidth: 720 }}>
      <p>
        <small>Talking to {agentName}</small>
      </p>
      {messages.map(message => (
        <div key={message.id} style={{ margin: '12px 0' }}>
          <strong>{message.role === 'user' ? 'You' : agentName}: </strong>
          {message.parts.map((part, i) =>
            part.type === 'text' ? (
              <span key={i} style={{ whiteSpace: 'pre-wrap' }}>
                {part.text}
              </span>
            ) : null,
          )}
        </div>
      ))}
      {error && (
        <p style={{ color: 'crimson' }}>Agent error: {error.message}</p>
      )}
      <form
        onSubmit={e => {
          e.preventDefault();
          if (!input.trim() || status !== 'ready') return;
          sendMessage({ text: input });
          setInput('');
        }}
      >
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Message the agent…"
          style={{ width: '80%' }}
        />
        <button type="submit" disabled={status !== 'ready'}>
          Send
        </button>
      </form>
    </div>
  );
}
