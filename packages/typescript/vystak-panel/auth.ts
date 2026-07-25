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
      const bootstrap = await getBootstrap(email);
      const decision = evaluateSignIn(bootstrap);
      if (decision === 'setup') {
        await setupAdmin({
          email,
          name: user.name ?? '',
          image: user.image ?? '',
        });
        return true;
      }
      return decision === 'allow';
    },
  },
});
