import Link from 'next/link';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { addUserAction, setUserStatusAction } from '@/app/actions';
import { ConfirmAction } from '@/components/confirm-action';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getBootstrap, listUsers } from '@/lib/panel';
import { ArrowLeftIcon } from 'lucide-react';

export default async function UsersPage() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  const me = bootstrap.user;
  if (me?.role !== 'admin') redirect('/');
  const { users } = await listUsers(email);

  return (
    <main className="mx-auto w-full max-w-3xl p-6">
      <div className="mb-6 flex items-center gap-2">
        <Button variant="ghost" size="icon" asChild aria-label="Back to panel">
          <Link href="/">
            <ArrowLeftIcon />
          </Link>
        </Button>
        <h1 className="text-lg font-semibold">Users</h1>
      </div>
      <form action={addUserAction} className="mb-6 flex gap-2">
        <Input
          name="email"
          type="email"
          placeholder="person@example.com"
          required
        />
        <Select name="role" defaultValue="member">
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="member">member</SelectItem>
            <SelectItem value="admin">admin</SelectItem>
          </SelectContent>
        </Select>
        <Button type="submit">Invite</Button>
      </form>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-32 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map(u => (
            <TableRow key={u.id}>
              <TableCell className="font-medium">{u.email}</TableCell>
              <TableCell>
                <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                  {u.role}
                </Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant={u.status === 'active' ? 'outline' : 'destructive'}
                >
                  {u.status}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                {/* No self-deactivation: the channel only refuses removing
                    the LAST admin, so with a second admin present one stray
                    click would end your own session. */}
                {u.id === me.id ? (
                  <span className="text-sm text-muted-foreground">you</span>
                ) : u.status === 'active' ? (
                  <ConfirmAction
                    action={setUserStatusAction.bind(null, u.id, 'deactivated')}
                    title="Deactivate user?"
                    description={`${u.email} will immediately lose access to the panel.`}
                    confirmLabel="Deactivate"
                    trigger={
                      <Button variant="outline" size="sm">
                        Deactivate
                      </Button>
                    }
                  />
                ) : (
                  <form action={setUserStatusAction.bind(null, u.id, 'active')}>
                    <Button variant="outline" size="sm" type="submit">
                      Reactivate
                    </Button>
                  </form>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </main>
  );
}
