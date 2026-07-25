import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';
import Google from 'next-auth/providers/google';
import { evaluateSignIn } from '@/lib/auth-policy';
import { getBootstrap, setupAdmin, verifyPassword } from '@/lib/panel';

export const passwordAuthEnabled = () =>
  process.env.PANEL_PASSWORD_AUTH === '1';

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google,
    ...(passwordAuthEnabled()
      ? [
          Credentials({
            credentials: { email: {}, password: {} },
            async authorize(credentials) {
              const email = String(credentials?.email ?? '')
                .trim()
                .toLowerCase();
              const password = String(credentials?.password ?? '');
              if (!email || !password) return null;
              // A channel outage surfaces as a failed login rather than a
              // crash; the Google path keeps its distinct PanelUnavailable
              // handling in the signIn callback below.
              let result;
              try {
                result = await verifyPassword(email, password);
              } catch {
                return null;
              }
              if (!result.ok || !result.user) return null;
              return {
                email: result.user.email,
                name: result.user.name,
                image: result.user.image,
              };
            },
          }),
        ]
      : []),
  ],
  session: { strategy: 'jwt' },
  pages: { signIn: '/signin', error: '/signin' },
  callbacks: {
    async signIn({ user }) {
      const email = user.email?.toLowerCase();
      if (!email) return false;
      let decision;
      try {
        // evaluateSignIn is inside the try too: a 200 response carrying a
        // null/malformed body would otherwise throw here and get rewrapped
        // as AccessDenied — the same wrong "not invited" screen.
        decision = evaluateSignIn(await getBootstrap(email));
      } catch {
        // The channel is unreachable or erroring. Letting this throw would be
        // rewrapped as AccessDenied and render "not invited", which is both
        // wrong and alarming — redirect with a distinguishable code instead.
        return '/signin?error=PanelUnavailable';
      }
      if (decision === 'setup') {
        try {
          await setupAdmin({
            email,
            name: user.name ?? '',
            image: user.image ?? '',
          });
        } catch {
          return '/signin?error=PanelUnavailable';
        }
        return true;
      }
      return decision === 'allow';
    },
    async jwt({ token }) {
      if (token.email) token.email = token.email.toLowerCase();
      return token;
    },
  },
});
