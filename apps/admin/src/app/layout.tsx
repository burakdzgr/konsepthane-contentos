import type { Metadata } from "next";
import type { ReactNode } from "react";

import { fetchCurrentUser, type AuthenticatedUser } from "@/lib/auth-api";
import { getSessionToken } from "@/lib/session";

import { logoutAction } from "./login/actions";
import { AppNav } from "./nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "ContentOS Admin",
  description: "Konsepthane ContentOS için özel dahili kontrol paneli.",
  robots: {
    index: false,
    follow: false,
  },
};

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  // Best effort: on /login, an expired session, or outside a request scope
  // (build-time prerender) there is no session cookie, so no backend call
  // is made and the header simply omits the identity.
  let user: AuthenticatedUser | null = null;
  if ((await getSessionToken()) !== null) {
    const userResult = await fetchCurrentUser();
    user = userResult.kind === "ok" ? userResult.data : null;
  }
  return (
    <html lang="tr">
      <body>
        <header className="app-header">
          <div className="app-identity">
            <span className="app-name">ContentOS</span>
            <span className="app-role">Dahili Kontrol Paneli</span>
          </div>
          <AppNav />
          {user !== null && (
            <span className="app-user">
              {user.display_name} ({user.roles.join(", ")})
            </span>
          )}
          <form action={logoutAction}>
            <button type="submit">Çıkış yap</button>
          </form>
        </header>
        <main className="app-main">{children}</main>
      </body>
    </html>
  );
}
