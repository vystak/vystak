import { redirect } from 'next/navigation';
import { auth, signIn } from '@/auth';

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const session = await auth();
  if (session?.user?.email) redirect('/');
  const { error } = await searchParams;
  return (
    <main style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
      <form
        action={async () => {
          'use server';
          await signIn('google', { redirectTo: '/' });
        }}
      >
        <h1>Vystak Panel</h1>
        <p>Sign in with your invited Google account.</p>
        {error === 'AccessDenied' && (
          <p style={{ color: 'crimson' }}>
            This Google account has not been invited. Ask an administrator to
            add your email.
          </p>
        )}
        {error && error !== 'AccessDenied' && (
          <p style={{ color: 'crimson' }}>
            Sign-in failed. The control panel API may be unavailable — try
            again, or contact an administrator.
          </p>
        )}
        <button type="submit">Sign in with Google</button>
      </form>
    </main>
  );
}
