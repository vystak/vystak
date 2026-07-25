import Link from 'next/link';
import { createProjectAction } from '@/app/actions';
import type { PanelUser, Project } from '@/lib/types';

export function Sidebar({
  projects,
  activeProjectId,
  user,
}: {
  projects: Project[];
  activeProjectId: string;
  user: PanelUser;
}) {
  return (
    <nav style={{ width: 240, borderRight: '1px solid #ccc', padding: 12 }}>
      <h2 style={{ fontSize: 16 }}>Projects</h2>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {projects.map(p => (
          <li key={p.id} style={{ margin: '4px 0' }}>
            <Link
              href={`/p/${p.id}`}
              style={{ fontWeight: p.id === activeProjectId ? 700 : 400 }}
            >
              {p.name}
            </Link>
          </li>
        ))}
      </ul>
      <form action={createProjectAction}>
        <input name="name" placeholder="New project" required />
        <button type="submit">Add</button>
      </form>
      {user.role === 'admin' && (
        <p>
          <Link href="/admin/users">Manage users</Link>
        </p>
      )}
    </nav>
  );
}
