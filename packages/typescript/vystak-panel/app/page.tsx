import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { getBootstrap } from '@/lib/panel';

export default async function Home() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');
  if (!bootstrap.default_project_id) redirect('/signin?error=AccessDenied');
  redirect(`/p/${bootstrap.default_project_id}`);
}
