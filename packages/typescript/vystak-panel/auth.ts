import NextAuth from 'next-auth';
import Google from 'next-auth/providers/google';
import { evaluateSignIn } from '@/lib/auth-policy';
import { getBootstrap, setupAdmin } from '@/lib/panel';

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
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
