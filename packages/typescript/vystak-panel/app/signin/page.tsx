import { redirect } from 'next/navigation';
import { AuthError } from 'next-auth';
import { auth, passwordAuthEnabled, signIn } from '@/auth';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { AlertCircleIcon } from 'lucide-react';

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M21.35 11.1H12v2.9h5.35c-.25 1.4-1.02 2.58-2.17 3.38v2.8h3.5c2.05-1.9 3.22-4.7 3.22-8.03 0-.66-.06-1.3-.15-1.05Z"
      />
      <path
        fill="currentColor"
        d="M12 22c2.7 0 4.97-.9 6.63-2.42l-3.5-2.8c-.9.6-2.05.96-3.13.96-2.4 0-4.44-1.62-5.17-3.8H3.2v2.88C4.85 19.98 8.2 22 12 22Z"
        opacity=".8"
      />
      <path
        fill="currentColor"
        d="M6.83 13.94A5.9 5.9 0 0 1 6.5 12c0-.67.12-1.33.33-1.94V7.18H3.2A9.98 9.98 0 0 0 2 12c0 1.62.39 3.15 1.2 4.82l3.63-2.88Z"
        opacity=".6"
      />
      <path
        fill="currentColor"
        d="M12 6.25c1.47 0 2.79.5 3.83 1.5l2.87-2.87C16.96 3.3 14.7 2.3 12 2.3 8.2 2.3 4.85 4.32 3.2 7.18l3.63 2.88C7.56 7.88 9.6 6.25 12 6.25Z"
        opacity=".9"
      />
    </svg>
  );
}

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const session = await auth();
  if (session?.user?.email && !error) redirect('/');
  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-lg font-bold text-primary-foreground">
            V
          </div>
          <CardTitle className="text-xl">Vystak Panel</CardTitle>
          <CardDescription>
            Sign in with your invited Google account.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error === 'AccessDenied' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Not invited</AlertTitle>
              <AlertDescription>
                This Google account has not been invited. Ask an administrator
                to add your email.
              </AlertDescription>
            </Alert>
          )}
          {error === 'PanelUnavailable' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Panel unreachable</AlertTitle>
              <AlertDescription>
                Could not reach the control panel API. Try again, or contact an
                administrator.
              </AlertDescription>
            </Alert>
          )}
          {passwordAuthEnabled() && error === 'CredentialsSignin' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Sign-in failed</AlertTitle>
              <AlertDescription>Invalid email or password.</AlertDescription>
            </Alert>
          )}
          {error &&
            !['AccessDenied', 'PanelUnavailable',
              ...(passwordAuthEnabled() ? ['CredentialsSignin'] : []),
            ].includes(error) && (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertTitle>Sign-in failed</AlertTitle>
                <AlertDescription>
                  Contact an administrator if this persists.
                </AlertDescription>
              </Alert>
            )}
          {passwordAuthEnabled() && (
            <>
              <form
                action={async formData => {
                  'use server';
                  try {
                    await signIn('credentials', {
                      email: formData.get('email'),
                      password: formData.get('password'),
                      redirectTo: '/',
                    });
                  } catch (error) {
                    // signIn throws NEXT_REDIRECT on success — let it propagate.
                    if (error instanceof AuthError) {
                      redirect('/signin?error=CredentialsSignin');
                    }
                    throw error;
                  }
                }}
                className="flex flex-col gap-3"
              >
                <Input
                  name="email"
                  type="email"
                  placeholder="you@example.com"
                  required
                />
                <Input
                  name="password"
                  type="password"
                  placeholder="Password"
                  autoComplete="current-password"
                  required
                />
                <Button type="submit" className="w-full">
                  Sign in
                </Button>
              </form>
              <div className="flex items-center gap-3">
                <Separator className="flex-1" />
                <span className="text-xs text-muted-foreground">or</span>
                <Separator className="flex-1" />
              </div>
            </>
          )}
          <form
            action={async () => {
              'use server';
              await signIn('google', { redirectTo: '/' });
            }}
          >
            <Button type="submit" variant="outline" className="w-full">
              <GoogleIcon /> Continue with Google
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
