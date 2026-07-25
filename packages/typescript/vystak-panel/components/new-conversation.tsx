import { createConversationAction } from '@/app/actions';

export function NewConversation({
  projectId,
  agents,
}: {
  projectId: string;
  agents: string[];
}) {
  const action = createConversationAction.bind(null, projectId);
  return (
    <form action={action} style={{ display: 'flex', gap: 8 }}>
      <select name="agent" required defaultValue="">
        <option value="" disabled>
          Choose an agent…
        </option>
        {agents.map(a => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>
      <button type="submit">New conversation</button>
    </form>
  );
}
