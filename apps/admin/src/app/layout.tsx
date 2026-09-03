import type { Metadata } from "next";
import type { ReactNode } from "react";

import {
  fetchBackendLiveness,
  fetchBackendReadiness,
} from "@/lib/contentos-api";
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

const ENVIRONMENT_LABELS: Record<string, string> = {
  local: "Local",
  test: "Test",
  production: "Production",
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
  let environment: string | null = null;
  let health: "ok" | "bad" | "unknown" = "unknown";
  if ((await getSessionToken()) !== null) {
    const [userResult, liveness, readiness] = await Promise.all([
      fetchCurrentUser(),
      fetchBackendLiveness(),
      fetchBackendReadiness(),
    ]);
    user = userResult.kind === "ok" ? userResult.data : null;
    environment =
      liveness.kind === "ok" ? (liveness.data.environment ?? null) : null;
    health =
      readiness.kind === "ok"
        ? readiness.data.status === "ready"
          ? "ok"
          : "bad"
        : "unknown";
  }
  return (
    <html lang="tr">
      <body>
        <div className="app-shell">
          <aside className="app-sidebar">
            <div className="app-identity">
              <span className="app-name">ContentOS</span>
              <span className="app-role">Motoru</span>
            </div>
            <AppNav />
            <div className="sidebar-health" data-tone={health}>
              <span className="sidebar-health-title">Sistem Sağlığı</span>
              <span className="sidebar-health-state">
                {health === "ok" && "● Tüm sistemler çevrimiçi"}
                {health === "bad" && "● Altyapı hazır değil"}
                {health === "unknown" && "● Durum bilinmiyor"}
              </span>
            </div>
          </aside>
          <div className="app-body">
            <header className="app-header">
              <div className="app-header-title">
                <span className="app-name">ContentOS Motoru</span>
                <span
                  className="badge env-badge"
                  data-env={environment ?? "unknown"}
                >
                  {environment !== null
                    ? (ENVIRONMENT_LABELS[environment] ?? environment)
                    : "Ortam bilinmiyor"}
                </span>
              </div>
              <div className="app-header-controls">
                {user !== null && (
                  <span className="app-user">
                    {user.display_name} ({user.roles.join(", ")})
                  </span>
                )}
                <form action={logoutAction}>
                  <button type="submit">Çıkış yap</button>
                </form>
              </div>
            </header>
            <main className="app-main">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
