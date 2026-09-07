import type { Metadata } from "next";
import type { ReactNode } from "react";

import {
  fetchBackendLiveness,
  fetchBackendReadiness,
} from "@/lib/contentos-api";
import { fetchCurrentUser, type AuthenticatedUser } from "@/lib/auth-api";
import { fetchDashboardSummary } from "@/lib/dashboard-api";
import { fetchIntakeRuns } from "@/lib/intake-api";
import { getSessionToken } from "@/lib/session";

import { HeaderChrome } from "./chrome";
import { ContentOsMark } from "./icons";
import { AppNav, type NavBadges } from "./nav";

import "./globals.css";
import "./studio.css";

export const metadata: Metadata = {
  title: "ContentOS",
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
  // is made and the shell simply omits identity, badges and stats.
  let user: AuthenticatedUser | null = null;
  let environment: string | null = null;
  let health: "ok" | "bad" | "unknown" = "unknown";
  let badges: NavBadges = {};
  if ((await getSessionToken()) !== null) {
    const [userResult, liveness, readiness, summaryResult, runsResult] =
      await Promise.all([
        fetchCurrentUser(),
        fetchBackendLiveness(),
        fetchBackendReadiness(),
        fetchDashboardSummary(),
        fetchIntakeRuns(),
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
    if (summaryResult.kind === "ok") {
      const summary = summaryResult.data;
      // "Benden Bekleyenler" = every genuine human decision: production,
      // publication approval, refresh, strategy suggestion.
      badges = {
        firsatlar:
          summary.attention.production_decisions +
          summary.attention.awaiting_human_review +
          (summary.attention.refresh_decisions ?? 0) +
          (summary.attention.strategy_suggestions ?? 0),
        onay: summary.attention.awaiting_human_review,
        yayin:
          (summary.work_item_states["scheduled"] ?? 0) +
          (summary.work_item_states["publishing"] ?? 0),
      };
    }
    if (runsResult.kind === "ok") {
      badges = {
        ...badges,
        calisma: runsResult.data.runs.filter(
          (run) => run.status === "running" || run.status === "paused",
        ).length,
      };
    }
  }
  return (
    <html lang="tr">
      <body>
        <div className="app-shell">
          <aside className="app-sidebar">
            <div className="app-identity">
              <ContentOsMark />
              <span className="app-identity-copy">
                <span className="app-brand-kicker">Konsepthane</span>
                <span className="app-name">ContentOS</span>
              </span>
            </div>
            <AppNav badges={badges} />
            <div className="sidebar-manifesto">
              <span className="manifesto-spark">✦</span>
              <p>
                Daha iyi fikirler,
                <br />
                daha güçlü içerikler.
              </p>
              <small>Konsepthane ContentOS</small>
            </div>
          </aside>
          <div className="app-body">
            <HeaderChrome
              environment={environment}
              health={health}
              user={
                user === null
                  ? null
                  : { displayName: user.display_name, roles: user.roles }
              }
            />
            <main className="app-main">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
