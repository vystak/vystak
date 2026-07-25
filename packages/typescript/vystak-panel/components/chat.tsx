'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';
import type { UIMessage } from 'ai';
import { stringifyToolValue, toolStateLabel } from '@/lib/messageParts';

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
  const { messages, sendMessage, status, error, clearError } = useChat({
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
          {message.parts.map((part, i) => {
            if (part.type === 'text') {
              return (
                <span key={i} style={{ whiteSpace: 'pre-wrap' }}>
                  {part.text}
                </span>
              );
            }
            if (part.type === 'dynamic-tool') {
              let resultLine: string;
              if (part.state === 'output-error') {
                resultLine = `Error: ${stringifyToolValue(part.errorText)}`;
              } else if (part.state === 'output-available') {
                resultLine = `Result: ${stringifyToolValue(part.output)}`;
              } else {
                resultLine = 'Result: (pending)';
              }
              return (
                <div
                  key={i}
                  style={{
                    margin: '4px 0',
                    padding: '4px 8px',
                    border: '1px solid #ccc',
                    fontSize: 13,
                  }}
                >
                  <span>
                    tool: <strong>{part.toolName}</strong> — {toolStateLabel(part.state)}
                  </span>
                  <details>
                    <summary>Details</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', margin: '4px 0' }}>
                      Arguments: {stringifyToolValue(part.input)}
                    </pre>
                    <pre style={{ whiteSpace: 'pre-wrap', margin: '4px 0' }}>{resultLine}</pre>
                  </details>
                </div>
              );
            }
            return null;
          })}
        </div>
      ))}
      {status === 'submitted' && (
        <p>
          <em>thinking…</em>
        </p>
      )}
      {error && (
        <p style={{ color: 'crimson' }}>
          Agent error: {error.message}{' '}
          <button type="button" onClick={() => clearError()}>
            Dismiss
          </button>
        </p>
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
          onChange={e => {
            if (error) clearError();
            setInput(e.target.value);
          }}
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
