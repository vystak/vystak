import { addMemberAction, removeMemberAction } from '@/app/actions';
import type { PanelUser } from '@/lib/types';

export function Members({
  projectId,
  members,
}: {
  projectId: string;
  members: PanelUser[];
}) {
  const add = addMemberAction.bind(null, projectId);
  return (
    <section style={{ marginTop: 24 }}>
      <h3 style={{ fontSize: 14 }}>Shared with</h3>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {members.map(m => (
          <li key={m.id}>
            {m.email}{' '}
            <form
              action={removeMemberAction.bind(null, projectId, m.id)}
              style={{ display: 'inline' }}
            >
              <button type="submit">Remove</button>
            </form>
          </li>
        ))}
      </ul>
      <form action={add} style={{ display: 'flex', gap: 8 }}>
        <input name="email" type="email" placeholder="Share by email" required />
        <button type="submit">Share</button>
      </form>
    </section>
  );
}
