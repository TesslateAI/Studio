import type { AuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

export const authOptions: AuthOptions = {
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const expectedUser = process.env.DASHBOARD_USER;
        const expectedPass = process.env.DASHBOARD_PASSWORD;

        if (!expectedUser || !expectedPass) {
          console.error("[auth] DASHBOARD_USER or DASHBOARD_PASSWORD not set");
          return null;
        }

        if (
          credentials?.username === expectedUser &&
          credentials?.password === expectedPass
        ) {
          return { id: "1", name: expectedUser, email: `${expectedUser}@firm.local` };
        }

        return null;
      },
    }),
  ],
  session: {
    strategy: "jwt",
    maxAge: 8 * 60 * 60, // 8 hours
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.sub = user.id;
      return token;
    },
    async session({ session, token }) {
      if (token.sub) session.user = { ...session.user, name: token.name ?? undefined };
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
};
