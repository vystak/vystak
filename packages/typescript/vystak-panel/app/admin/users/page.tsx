import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { addUserAction, setUserStatusAction } from '@/app/actions';
import { getBootstrap, listUsers } from '@/lib/panel';

export default async function UsersPage() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  const me = bootstrap.user;
  if (me?.role !== 'admin') redirect('/');
  const { users } = await listUsers(email);

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Users</h1>
      <form action={addUserAction} style={{ display: 'flex', gap: 8 }}>
        <input name="email" type="email" placeholder="person@example.com" required />
        <select name="role" defaultValue="member">
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button type="submit">Invite</button>
      </form>
      <table style={{ marginTop: 16, width: '100%' }}>
        <tbody>
          {users.map(u => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.role}</td>
              <td>{u.status}</td>
              <td>
                {/* No self-deactivation: the channel only refuses removing
                    the LAST admin, so with a second admin present one stray
                    click would end your own session. */}
                {u.id === me.id ? (
                  <span style={{ opacity: 0.6 }}>you</span>
                ) : (
                  <form
                    action={setUserStatusAction.bind(
                      null,
                      u.id,
                      u.status === 'active' ? 'deactivated' : 'active',
                    )}
                  >
                    <button type="submit">
                      {u.status === 'active' ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </form>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
