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

import { logoutAction } from "./login/actions";
import { AppNav, type NavBadges } from "./nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "ContentOS",
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
  // is made and the shell simply omits identity, badges and stats.
  let user: AuthenticatedUser | null = null;
  let environment: string | null = null;
  let health: "ok" | "bad" | "unknown" = "unknown";
  let badges: NavBadges = {};
  let aiUsed: number | null = null;
  let aiBudget: number | null = null;
  let queueDepth: number | null = null;
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
      badges = {
        firsatlar: summary.attention.production_decisions,
        onay: summary.attention.awaiting_human_review,
        yayin:
          (summary.work_item_states["scheduled"] ?? 0) +
          (summary.work_item_states["publishing"] ?? 0),
      };
      aiUsed = summary.ai.attempts_today;
      aiBudget = summary.ai.daily_budget;
      queueDepth = summary.queue.depth;
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
  const budgetPercent =
    aiBudget !== null && aiBudget > 0 && aiUsed !== null
      ? Math.min(100, Math.round((aiUsed / aiBudget) * 100))
      : null;
  return (
    <html lang="tr">
      <body>
        <div className="app-shell">
          <aside className="app-sidebar">
            <div className="app-identity">
              <span className="app-name">ContentOS</span>
              <span className="app-role">Content Operations Engine</span>
            </div>
            <AppNav badges={badges} />
            <div className="sidebar-stats">
              {budgetPercent !== null && (
                <div>
                  <span className="sidebar-stat-label">
                    <span>AI Bütçe (günlük deneme)</span>
                    <span>
                      {aiUsed}/{aiBudget}
                    </span>
                  </span>
                  <span className="sidebar-stat-bar">
                    <span style={{ width: `${budgetPercent}%` }} />
                  </span>
                </div>
              )}
              {queueDepth !== null && (
                <span className="sidebar-stat-label">
                  <span>Kuyruk derinliği</span>
                  <span>{queueDepth}</span>
                </span>
              )}
            </div>
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
