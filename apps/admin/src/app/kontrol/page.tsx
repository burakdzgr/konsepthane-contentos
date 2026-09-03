import Link from "next/link";

import {
  fetchDashboardActivity,
  fetchDashboardAgents,
  fetchDashboardPublications,
  fetchDashboardSummary,
  type ActivityEntry,
  type AgentView,
  type DashboardSummary,
  type PublicationQueueRow,
} from "@/lib/dashboard-api";
import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { fetchIntakeRuns, type IntakeRunView } from "@/lib/intake-api";
import { STATE_LABELS_TR } from "@/lib/motor-plan";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { pauseIntakeAction, resumeIntakeAction } from "./actions";
import { AutoRefresh } from "./refresh";

// The control center: the whole ContentOS engine on one operational
// screen. Every number is a durable read-model projection; the only
// mutations are the audited intake pause/resume commands. Workflow
// transitions stay on their governed surfaces (Motor, detail pages).
export const dynamic = "force-dynamic";

const KONTROL_NOTICES: Record<string, string> = {
  durduruldu:
    "Alım durduruldu ve denetim kaydına geçti. Çalışan işler güvenle tamamlanır; yeni iş kuyruğa alınmaz.",
  devam: "Alım yeniden açıldı ve denetim kaydına geçti.",
};

const AGENT_NAMES: Record<string, string> = {
  research: "Araştırma Ajanı",
  opportunity: "Fırsat Puanlama",
  ideas: "Fikir Ajanı",
  evidence: "Kanıt Ajanı",
  intent: "SEO / Niyet Ajanı",
  brief: "Brief Ajanı",
  writer: "Writer Ajanı",
  editor: "Editor Ajanı",
  qa: "QA Ajanı",
  media: "Medya Ajanı",
  publisher: "Yayıncı Ajanı",
};

const AGENT_KIND_LABELS: Record<string, string> = {
  ai: "AI",
  deterministic: "Deterministik",
  transport: "Transport",
};

const AGENT_QUEUE_LINKS: Record<string, string> = {
  research: "/research",
  opportunity: "/editorial?state=idea_scoring",
  ideas: "/editorial?state=idea_scoring",
  evidence: "/editorial?state=evidence_building",
  intent: "/editorial?state=seo_research",
  brief: "/editorial?state=briefing",
  writer: "/editorial?state=drafting",
  editor: "/editorial?state=editing",
  qa: "/editorial?state=qa_review",
  media: "/editorial?state=qa_review",
  publisher: "/kontrol#yayin-kuyrugu",
};

const PUBLICATION_STATE_LABELS: Record<string, string> = {
  approved: "Hazır",
  scheduled: "Planlandı",
  publishing: "Yayınlanıyor",
  published: "Başarılı",
  blocked: "Bloke",
};

function stateCount(summary: DashboardSummary, state: string): number {
  return summary.work_item_states[state] ?? 0;
}

function waitingSince(iso: string): string {
  const entered = new Date(iso).getTime();
  if (Number.isNaN(entered)) {
    return "bilinmiyor";
  }
  const minutes = Math.max(0, Math.floor((Date.now() - entered) / 60_000));
  if (minutes < 60) {
    return `${minutes} dk`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours} sa`;
  }
  return `${Math.floor(hours / 24)} gün`;
}

function Unavailable({ children }: { children: React.ReactNode }) {
  return (
    <p className="empty-note" role="status">
      {children}
    </p>
  );
}

function AttentionPanel({ summary }: { summary: DashboardSummary }) {
  const attention = summary.attention;
  const items: { label: string; count: number; href: string }[] = [
    {
      label: "içerik üretim kararı bekliyor",
      count: attention.production_decisions,
      href: "/firsatlar",
    },
    {
      label: "nihai yayın onayı bekliyor",
      count: attention.awaiting_human_review,
      href: "/editorial?state=awaiting_human_review",
    },
    {
      label: "süresi dolan onay kararı bekliyor",
      count: attention.approval_expired,
      href: "/editorial?state=approval_expired",
    },
    {
      label: "değişiklik talebi yönlendirme bekliyor",
      count: attention.changes_requested,
      href: "/editorial?state=changes_requested",
    },
  ].filter((item) => item.count > 0);
  return (
    <section
      className="panel-block attention-panel"
      aria-label="Benden bekleyenler"
    >
      <h2>Benden Bekleyenler</h2>
      {items.length === 0 ? (
        <p className="empty-note">
          Sizi bekleyen karar yok — motor otonom işleri yürütüyor.
        </p>
      ) : (
        <ul className="alert-list">
          {items.map((item) => (
            <li key={item.label}>
              <Link href={item.href} className="alert-row" data-tone="warn">
                <span>{item.label}</span>
                <span className="alert-count">{item.count}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ActiveRunsPanel({ runs }: { runs: IntakeRunView[] | null }) {
  const live = (runs ?? []).filter(
    (run) => run.status === "running" || run.status === "paused",
  );
  return (
    <section className="panel-block" aria-label="Aktif çalışmalar">
      <h2>Aktif Çalışmalar</h2>
      {runs === null && (
        <p className="empty-note" role="status">
          Çalışma durumu okunamıyor.
        </p>
      )}
      {runs !== null && live.length === 0 && (
        <p className="empty-note">
          Aktif çalışma yok. <Link href="/sources">Kaynaklar</Link> sayfasından
          keşif başlatın; geçmiş <Link href="/calisma">Çalışmalar</Link>da.
        </p>
      )}
      {live.length > 0 && (
        <div className="run-card-grid">
          {live.map((run) => (
            <Link key={run.id} href={`/calisma/${run.id}`} className="run-card">
              <span className="run-card-title">{run.source_name}</span>
              <span
                className="badge"
                data-tone={run.status === "running" ? "run" : "warn"}
              >
                {run.status === "running" ? "ÇALIŞIYOR" : "DURAKLATILDI"}
              </span>
              <span className="run-card-facts">
                {run.discovered_new + run.rediscovered} keşif ·{" "}
                {run.prefilter_accepted} uygun · {run.fetched}/
                {run.fetch_dispatched} getirildi · {run.opportunities_created}{" "}
                fırsat
              </span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

// --- KPI strip ---------------------------------------------------------------

function KpiStrip({ summary }: { summary: DashboardSummary }) {
  const cards: { label: string; value: number; href: string; tone?: string }[] =
    [
      {
        label: "Getirilen Doküman",
        value: summary.research.discovery_states["fetched"] ?? 0,
        href: "/research",
      },
      {
        label: "Aktif Fırsat",
        value: stateCount(summary, "idea_scoring"),
        href: "/editorial?state=idea_scoring",
      },
      {
        label: "Brief Aşaması",
        value:
          stateCount(summary, "seo_research") + stateCount(summary, "briefing"),
        href: "/editorial?state=briefing",
      },
      {
        label: "Drafting",
        value: stateCount(summary, "drafting"),
        href: "/editorial?state=drafting",
      },
      {
        label: "QA Bekleyen",
        value: stateCount(summary, "qa_review"),
        href: "/editorial?state=qa_review",
      },
      {
        label: "İnsan Onayı",
        value: stateCount(summary, "awaiting_human_review"),
        href: "/editorial?state=awaiting_human_review",
        tone:
          stateCount(summary, "awaiting_human_review") > 0 ? "warn" : undefined,
      },
      {
        label: "Bugün Yayınlanan",
        value: summary.published_today,
        href: "/editorial?state=published",
        tone: "ok",
      },
      {
        label: "Bloke İçerik",
        value: stateCount(summary, "blocked"),
        href: "/editorial?state=blocked",
        tone: stateCount(summary, "blocked") > 0 ? "bad" : undefined,
      },
    ];
  return (
    <div className="kpi-strip">
      {cards.map((card) => (
        <Link
          key={card.label}
          href={card.href}
          className="kpi-card"
          data-tone={card.tone}
        >
          <span className="kpi-value">{card.value}</span>
          <span className="kpi-label">{card.label}</span>
        </Link>
      ))}
    </div>
  );
}

// --- pipeline strip ----------------------------------------------------------

function PipelineStrip({ summary }: { summary: DashboardSummary }) {
  const discovery = summary.research.discovery_states;
  const stages: {
    key: string;
    label: string;
    value: number;
    href: string;
    note?: string;
    tone?: string;
  }[] = [
    {
      key: "research",
      label: "Research",
      value:
        (discovery["discovered"] ?? 0) +
        (discovery["accepted"] ?? 0) +
        (discovery["fetched"] ?? 0),
      href: "/research",
      note:
        (discovery["fetch_failed"] ?? 0) > 0
          ? `${discovery["fetch_failed"]} getirme hatası`
          : undefined,
      tone: (discovery["fetch_failed"] ?? 0) > 0 ? "warn" : undefined,
    },
    {
      key: "opportunity",
      label: "Opportunity",
      value: stateCount(summary, "idea_scoring"),
      href: "/editorial?state=idea_scoring",
    },
    {
      key: "evidence",
      label: "Evidence",
      value: stateCount(summary, "evidence_building"),
      href: "/editorial?state=evidence_building",
    },
    {
      key: "brief",
      label: "Brief",
      value:
        stateCount(summary, "seo_research") + stateCount(summary, "briefing"),
      href: "/editorial?state=briefing",
    },
    {
      key: "writer",
      label: "Writer",
      value: stateCount(summary, "drafting"),
      href: "/editorial?state=drafting",
    },
    {
      key: "editor",
      label: "Editor",
      value: stateCount(summary, "editing"),
      href: "/editorial?state=editing",
    },
    {
      key: "qa",
      label: "QA",
      value: stateCount(summary, "qa_review"),
      href: "/editorial?state=qa_review",
    },
    {
      key: "review",
      label: "Human Review",
      value: stateCount(summary, "awaiting_human_review"),
      href: "/editorial?state=awaiting_human_review",
      tone:
        stateCount(summary, "awaiting_human_review") > 0 ? "warn" : undefined,
      note:
        stateCount(summary, "awaiting_human_review") > 0
          ? "ONAY BEKLİYOR"
          : undefined,
    },
    {
      key: "package",
      label: "Package",
      value: stateCount(summary, "approved"),
      href: "/editorial?state=approved",
    },
    {
      key: "schedule",
      label: "Schedule",
      value: stateCount(summary, "scheduled"),
      href: "/editorial?state=scheduled",
    },
    {
      key: "publish",
      label: "Publish",
      value:
        stateCount(summary, "publishing") + stateCount(summary, "published"),
      href: "/kontrol#yayin-kuyrugu",
      note: `bugün ${summary.published_today}`,
      tone: "ok",
    },
  ];
  return (
    <section className="panel-block" aria-label="Üretim hattı">
      <h2>Üretim Hattı</h2>
      <ol className="pipeline-strip">
        {stages.map((stage) => (
          <li key={stage.key}>
            <Link
              href={stage.href}
              className="pipeline-stage"
              data-tone={stage.tone}
            >
              <span className="pipeline-label">{stage.label}</span>
              <span className="pipeline-value">{stage.value}</span>
              {stage.note !== undefined && (
                <span className="pipeline-note">{stage.note}</span>
              )}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- live workflow table -----------------------------------------------------

function LiveWorkTable({ rows }: { rows: WorkQueueRow[] | null }) {
  return (
    <section className="panel-block" aria-label="Canlı iş akışı">
      <h2>Canlı İş Akışı</h2>
      {rows === null && (
        <Unavailable>İş kuyruğu şu anda okunamıyor.</Unavailable>
      )}
      {rows !== null && rows.length === 0 && (
        <Unavailable>Aktif iş öğesi yok.</Unavailable>
      )}
      {rows !== null && rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>İçerik</th>
                <th>Aşama</th>
                <th>Son Güncelleme</th>
                <th>Bekleme</th>
                <th>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.work_item_id}>
                  <td>
                    <span className="cell-primary">
                      {row.title_working_label}
                    </span>
                    {row.blocked_reason !== null && (
                      <span className="cell-secondary">
                        Engel: {row.blocked_reason}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className="badge" data-state={row.current_state}>
                      {STATE_LABELS_TR[row.current_state]}
                    </span>
                  </td>
                  <td>{formatUtcTimestamp(row.current_state_entered_at)}</td>
                  <td>{waitingSince(row.current_state_entered_at)}</td>
                  <td>
                    <Link href={`/editorial/${row.work_item_id}`}>İncele</Link>{" "}
                    ·{" "}
                    <Link href={`/motor?item=${row.work_item_id}`}>Motor</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// --- alerts panel ------------------------------------------------------------

function AlertsPanel({ summary }: { summary: DashboardSummary }) {
  const publishFailures = Object.entries(summary.publishing.attempts_today)
    .filter(([status]) => status !== "succeeded")
    .reduce((total, [, count]) => total + count, 0);
  const budget = summary.ai.daily_budget;
  const remaining = summary.ai.remaining_budget;
  const budgetLow =
    budget !== null &&
    remaining !== null &&
    remaining <= Math.ceil(budget / 10);
  const alerts: { label: string; count: number; href: string; tone: string }[] =
    [
      {
        label: "Bloke içerik",
        count: stateCount(summary, "blocked"),
        href: "/editorial?state=blocked",
        tone: "bad",
      },
      {
        label: "İnsan onayı bekleyen",
        count: stateCount(summary, "awaiting_human_review"),
        href: "/editorial?state=awaiting_human_review",
        tone: "warn",
      },
      {
        label: "Süresi dolan onay",
        count: stateCount(summary, "approval_expired"),
        href: "/editorial?state=approval_expired",
        tone: "warn",
      },
      {
        label: "Değişiklik istendi",
        count: stateCount(summary, "changes_requested"),
        href: "/editorial?state=changes_requested",
        tone: "warn",
      },
      {
        label: "Bugünkü yayın hatası",
        count: publishFailures,
        href: "/kontrol#yayin-kuyrugu",
        tone: "bad",
      },
      {
        label: "Bugünkü AI hatası",
        count: summary.ai.failures_today,
        href: "/kontrol#agentlar",
        tone: "warn",
      },
      {
        label: "Getirme hatası",
        count: summary.research.discovery_states["fetch_failed"] ?? 0,
        href: "/research?fetch=failed",
        tone: "warn",
      },
    ];
  const active = alerts.filter((alert) => alert.count > 0);
  const pausedScopes = summary.pauses.filter((pause) => pause.is_paused);
  return (
    <section className="panel-block" aria-label="Onay, risk ve uyarılar">
      <h2>Onay / Risk / Uyarılar</h2>
      {pausedScopes.length > 0 && (
        <ul className="alert-list">
          {pausedScopes.map((pause) => (
            <li key={pause.scope}>
              <Link
                href="/kontrol#motor-kontrolu"
                className="alert-row"
                data-tone="bad"
              >
                <span>
                  Alım durduruldu: {pause.scope}
                  {pause.reason !== null && ` — ${pause.reason}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {budgetLow && budget !== null && (
        <p className="alert-row" data-tone="warn" role="status">
          AI bütçesi azaldı: bugün {summary.ai.attempts_today}/{budget} deneme
          kullanıldı.
        </p>
      )}
      {active.length === 0 && pausedScopes.length === 0 && !budgetLow && (
        <Unavailable>Aktif uyarı yok.</Unavailable>
      )}
      <ul className="alert-list">
        {active.map((alert) => (
          <li key={alert.label}>
            <Link
              href={alert.href}
              className="alert-row"
              data-tone={alert.tone}
            >
              <span>{alert.label}</span>
              <span className="alert-count">{alert.count}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --- agent control center ----------------------------------------------------

function agentStatus(
  agent: AgentView,
  enginePaused: boolean,
): { label: string; tone: string } {
  if (enginePaused) {
    return { label: "MOTOR DURDU", tone: "bad" };
  }
  if (agent.is_paused) {
    return { label: "DURAKLATILDI", tone: "warn" };
  }
  if (
    agent.last_attempt !== null &&
    agent.last_attempt.status !== "succeeded"
  ) {
    return { label: "HATA", tone: "bad" };
  }
  if (agent.attempts_today > 0) {
    return { label: "AKTİF", tone: "ok" };
  }
  return { label: "BOŞTA", tone: "idle" };
}

function AgentCard({
  agent,
  enginePaused,
}: {
  agent: AgentView;
  enginePaused: boolean;
}) {
  const status = agentStatus(agent, enginePaused);
  const successRate =
    agent.attempts_today > 0
      ? Math.round(
          ((agent.attempts_today - agent.failures_today) /
            agent.attempts_today) *
            100,
        )
      : null;
  return (
    <article className="agent-card" data-agent={agent.key}>
      <header className="agent-card-header">
        <h3>{AGENT_NAMES[agent.key] ?? agent.key}</h3>
        <span className="badge" data-tone={status.tone}>
          {status.label}
        </span>
      </header>
      <dl className="agent-facts">
        <div>
          <dt>Tür</dt>
          <dd>{AGENT_KIND_LABELS[agent.kind]}</dd>
        </div>
        {agent.kind === "ai" && (
          <>
            <div>
              <dt>Bugün deneme</dt>
              <dd>
                {agent.attempts_today}
                {agent.failures_today > 0 && ` (${agent.failures_today} hata)`}
              </dd>
            </div>
            {successRate !== null && (
              <div>
                <dt>Başarı</dt>
                <dd>%{successRate}</dd>
              </div>
            )}
            <div>
              <dt>Model</dt>
              <dd>
                {agent.last_attempt !== null
                  ? `${agent.last_attempt.provider}/${agent.last_attempt.model_name}`
                  : "henüz çalışmadı"}
              </dd>
            </div>
          </>
        )}
        {Object.entries(agent.metrics).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        {agent.last_attempt !== null &&
          agent.last_attempt.error_class !== null && (
            <div>
              <dt>Son hata</dt>
              <dd className="mono">{agent.last_attempt.error_class}</dd>
            </div>
          )}
      </dl>
      {agent.is_paused && agent.pause_reason !== null && (
        <p className="muted">Durdurma gerekçesi: {agent.pause_reason}</p>
      )}
      <details className="agent-drawer">
        <summary>Detay &amp; kontroller</summary>
        <div className="agent-drawer-body">
          {agent.recent_attempts.length > 0 ? (
            <ul className="agent-activity">
              {agent.recent_attempts.map((attempt) => (
                <li key={attempt.id}>
                  <span className="mono">
                    {formatUtcTimestamp(attempt.created_at)}
                  </span>{" "}
                  {attempt.purpose} ·{" "}
                  <span
                    className="badge"
                    data-tone={attempt.status === "succeeded" ? "ok" : "bad"}
                  >
                    {attempt.status}
                  </span>
                  {attempt.error_class !== null && (
                    <span className="mono"> {attempt.error_class}</span>
                  )}
                  {attempt.retry_number > 0 && (
                    <span className="muted">
                      {" "}
                      (deneme {attempt.retry_number})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-note">
              {agent.kind === "ai"
                ? "Kayıtlı AI denemesi yok."
                : "Bu ajan deterministik çalışır; denemeleri AI kaydı üretmez."}
            </p>
          )}
          <div className="agent-controls">
            {agent.is_paused ? (
              <form action={resumeIntakeAction} className="control-form">
                <input type="hidden" name="scope" value={agent.key} />
                <input
                  type="text"
                  name="reason"
                  required
                  placeholder="devam gerekçesi"
                  aria-label={`${AGENT_NAMES[agent.key]} devam gerekçesi`}
                />
                <button type="submit">Alımı aç</button>
              </form>
            ) : (
              <form action={pauseIntakeAction} className="control-form">
                <input type="hidden" name="scope" value={agent.key} />
                <input
                  type="text"
                  name="reason"
                  required
                  placeholder="durdurma gerekçesi"
                  aria-label={`${AGENT_NAMES[agent.key]} durdurma gerekçesi`}
                />
                <button type="submit">Yeni işi durdur</button>
              </form>
            )}
            <p>
              <Link href={AGENT_QUEUE_LINKS[agent.key] ?? "/editorial"}>
                Kuyruğu aç →
              </Link>
            </p>
          </div>
        </div>
      </details>
    </article>
  );
}

function TopOpportunities({ rows }: { rows: WorkQueueRow[] | null }) {
  return (
    <section className="panel-block" aria-label="Son fırsatlar">
      <h2>Son Fırsatlar</h2>
      {rows === null && (
        <p className="empty-note" role="status">
          Fırsatlar okunamıyor.
        </p>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="empty-note">Skorlanmış açık fırsat yok.</p>
      )}
      {rows !== null && rows.length > 0 && (
        <ul className="alert-list">
          {rows.map((row) => (
            <li key={row.work_item_id}>
              <Link
                href={`/editorial/${row.work_item_id}`}
                className="alert-row"
              >
                <span className="motor-item-title">
                  {row.title_working_label}
                </span>
                <span className="alert-count">
                  {row.score_overall_value !== null
                    ? row.score_overall_value.toFixed(2)
                    : "—"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        <Link href="/firsatlar">Tüm fırsatları gör →</Link>
      </p>
    </section>
  );
}

// --- engine control ----------------------------------------------------------

function EngineControl({
  enginePaused,
  engineReason,
}: {
  enginePaused: boolean;
  engineReason: string | null;
}) {
  return (
    <section
      className="panel-block engine-control"
      id="motor-kontrolu"
      aria-label="Motor kontrolü"
      data-tone={enginePaused ? "bad" : "ok"}
    >
      <h2>Motor Kontrolü</h2>
      <p className="muted">
        Durdurma yalnızca YENİ iş alımını keser: çalışan atomik işler güvenle
        tamamlanır, kuyruk ve iş akışı durumu bozulmaz. Her komut gerekçesiyle
        denetim kaydına geçer.
      </p>
      {enginePaused ? (
        <>
          <p className="alert-row" data-tone="bad" role="status">
            Motor durduruldu{engineReason !== null && `: ${engineReason}`}
          </p>
          <form action={resumeIntakeAction} className="control-form">
            <input type="hidden" name="scope" value="engine" />
            <input
              type="text"
              name="reason"
              required
              placeholder="devam gerekçesi"
              aria-label="Motoru başlatma gerekçesi"
            />
            <button type="submit">▶ Motoru Başlat</button>
          </form>
        </>
      ) : (
        <form action={pauseIntakeAction} className="control-form">
          <input type="hidden" name="scope" value="engine" />
          <input
            type="text"
            name="reason"
            required
            placeholder="durdurma gerekçesi (zorunlu)"
            aria-label="Acil durdurma gerekçesi"
          />
          <button type="submit" className="danger">
            🛑 Acil Durdurma (yeni iş alımını kes)
          </button>
        </form>
      )}
    </section>
  );
}

// --- publication queue -------------------------------------------------------

function PublicationQueue({ rows }: { rows: PublicationQueueRow[] | null }) {
  return (
    <section
      className="panel-block"
      id="yayin-kuyrugu"
      aria-label="Yayın kuyruğu"
    >
      <h2>Yayın Kuyruğu</h2>
      {rows === null && <Unavailable>Yayın kuyruğu okunamıyor.</Unavailable>}
      {rows !== null && rows.length === 0 && (
        <Unavailable>Henüz yayın paketi yok.</Unavailable>
      )}
      {rows !== null && rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>İçerik</th>
                <th>Paket</th>
                <th>Durum</th>
                <th>Deneme</th>
                <th>Son Deneme</th>
                <th>Ref</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.package_id}>
                  <td>
                    <Link href={`/editorial/${row.work_item_id}`}>
                      {row.title_working_label}
                    </Link>
                  </td>
                  <td>
                    v{row.version} · {row.section_count} bölüm ·{" "}
                    {row.manifest_needs} medya
                  </td>
                  <td>
                    <span className="badge" data-state={row.work_item_state}>
                      {PUBLICATION_STATE_LABELS[row.work_item_state] ??
                        STATE_LABELS_TR[row.work_item_state]}
                    </span>
                  </td>
                  <td>
                    {row.attempts_total === 0
                      ? "—"
                      : `${row.attempts_total} deneme`}
                    {row.last_attempt_status !== null && (
                      <span
                        className="badge"
                        data-tone={
                          row.last_attempt_status === "succeeded" ? "ok" : "bad"
                        }
                      >
                        {row.last_attempt_status}
                      </span>
                    )}
                    {row.last_attempt_error_class !== null && (
                      <span className="mono">
                        {" "}
                        {row.last_attempt_error_class}
                      </span>
                    )}
                  </td>
                  <td>
                    {row.last_attempt_at !== null
                      ? formatUtcTimestamp(row.last_attempt_at)
                      : "—"}
                  </td>
                  <td className="mono">{row.remote_publication_ref ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// --- AI / worker / media -----------------------------------------------------

function AiWorkerPanel({ summary }: { summary: DashboardSummary }) {
  const budget = summary.ai.daily_budget;
  const used = summary.ai.attempts_today;
  return (
    <section className="panel-block" aria-label="AI ve worker durumu">
      <h2>AI / Worker Durumu</h2>
      <dl className="status-list">
        <div className="status-row">
          <dt>Kuyruk derinliği</dt>
          <dd>
            {summary.queue.depth !== null ? summary.queue.depth : "ölçülemedi"}
          </dd>
        </div>
        <div className="status-row">
          <dt>Bugünkü AI denemesi</dt>
          <dd>
            {used}
            {summary.ai.failures_today > 0 &&
              ` (${summary.ai.failures_today} hata)`}
          </dd>
        </div>
        <div className="status-row">
          <dt>Günlük AI bütçesi</dt>
          <dd>
            {budget === null ? (
              "kapalı (sınırsız)"
            ) : (
              <>
                {used}/{budget}
                <progress value={Math.min(used, budget)} max={budget} />
              </>
            )}
          </dd>
        </div>
        <div className="status-row">
          <dt>Son yayın denemesi</dt>
          <dd>
            {summary.publishing.last_attempt_status === null
              ? "henüz yok"
              : `${summary.publishing.last_attempt_status}${
                  summary.publishing.last_attempt_error_class !== null
                    ? ` (${summary.publishing.last_attempt_error_class})`
                    : ""
                } · ${
                  summary.publishing.last_attempt_at !== null
                    ? formatUtcTimestamp(summary.publishing.last_attempt_at)
                    : ""
                }`}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function MediaPanel({ summary }: { summary: DashboardSummary }) {
  return (
    <section className="panel-block" aria-label="Medya durumu">
      <h2>Medya Durumu</h2>
      <dl className="status-list">
        <div className="status-row">
          <dt>Toplam varlık</dt>
          <dd>{summary.media.assets_total}</dd>
        </div>
        <div className="status-row">
          <dt>Bugün eklenen</dt>
          <dd>{summary.media.assets_today}</dd>
        </div>
        <div className="status-row">
          <dt>Aktif ihtiyaç bağlaması</dt>
          <dd>{summary.media.active_satisfactions}</dd>
        </div>
      </dl>
      <p className="muted">
        Medya bağlama işlemleri iş öğesi detayında yapılır.
      </p>
    </section>
  );
}

// --- activity ---------------------------------------------------------------

function activityText(entry: ActivityEntry): string {
  if (entry.kind === "workflow") {
    const to =
      entry.to_state !== null
        ? ((STATE_LABELS_TR as Record<string, string>)[entry.to_state] ??
          entry.to_state)
        : "?";
    return `${entry.title ?? "İş öğesi"} → ${to}`;
  }
  if (entry.kind === "publication") {
    return `Yayın denemesi: ${entry.title ?? ""} · ${entry.status ?? "?"}${
      entry.error_class !== null ? ` (${entry.error_class})` : ""
    }`;
  }
  return `Alım ${entry.action === "paused" ? "durduruldu" : "açıldı"}: ${
    entry.scope ?? "?"
  } — ${entry.reason ?? ""}`;
}

function ActivityFeed({ entries }: { entries: ActivityEntry[] | null }) {
  return (
    <section className="panel-block" aria-label="Gerçek zamanlı olaylar">
      <h2>Gerçek Zamanlı Olaylar</h2>
      {entries === null && <Unavailable>Olay akışı okunamıyor.</Unavailable>}
      {entries !== null && entries.length === 0 && (
        <Unavailable>Kayıtlı olay yok.</Unavailable>
      )}
      {entries !== null && entries.length > 0 && (
        <ul className="activity-feed">
          {entries.map((entry, index) => (
            <li key={`${entry.kind}-${index}`} data-kind={entry.kind}>
              <span className="mono">
                {formatUtcTimestamp(entry.occurred_at)}
              </span>{" "}
              {entry.work_item_id !== null ? (
                <Link href={`/editorial/${entry.work_item_id}`}>
                  {activityText(entry)}
                </Link>
              ) : (
                activityText(entry)
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// --- page --------------------------------------------------------------------

export default async function KontrolPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const [
    summaryResult,
    agentsResult,
    activityResult,
    publicationsResult,
    queueResult,
    runsResult,
  ] = await Promise.all([
    fetchDashboardSummary(),
    fetchDashboardAgents(),
    fetchDashboardActivity(30),
    fetchDashboardPublications(),
    fetchWorkQueue({ limit: 12 }),
    fetchIntakeRuns(),
  ]);
  const opportunitiesResult = await fetchWorkQueue({
    workflowState: "idea_scoring",
    opportunityDisposition: "open",
    limit: 20,
  });
  const topOpportunities =
    opportunitiesResult.kind === "ok"
      ? opportunitiesResult.data.items
          .filter((row) => row.score_overall_value !== null)
          .sort(
            (a, b) =>
              (b.score_overall_value ?? 0) - (a.score_overall_value ?? 0),
          )
          .slice(0, 5)
      : null;
  const intakeRuns = runsResult.kind === "ok" ? runsResult.data.runs : null;

  const summary = summaryResult.kind === "ok" ? summaryResult.data : null;
  const agents = agentsResult.kind === "ok" ? agentsResult.data : null;
  const activity = activityResult.kind === "ok" ? activityResult.data : null;
  const publications =
    publicationsResult.kind === "ok" ? publicationsResult.data : null;
  const queueRows = queueResult.kind === "ok" ? queueResult.data.items : null;

  return (
    <section
      className="panel panel-wide kontrol"
      aria-labelledby="kontrol-title"
    >
      <div className="kontrol-header">
        <div>
          <h1 id="kontrol-title">ContentOS Motoru</h1>
          <p className="muted">İçerik Üretim Kontrol Merkezi</p>
        </div>
        <AutoRefresh
          generatedAt={summary?.generated_at ?? new Date().toISOString()}
        />
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={KONTROL_NOTICES}
      />
      {summary === null ? (
        <Unavailable>
          Backend API&apos;ye şu anda erişilemiyor; kontrol merkezi verisi yok.
        </Unavailable>
      ) : (
        <>
          <AttentionPanel summary={summary} />
          <ActiveRunsPanel runs={intakeRuns} />
          <KpiStrip summary={summary} />
          <PipelineStrip summary={summary} />
          <div className="kontrol-columns">
            <LiveWorkTable rows={queueRows} />
            <AlertsPanel summary={summary} />
          </div>
          <section
            className="panel-block"
            id="agentlar"
            aria-label="Agent kontrol merkezi"
          >
            <h2>Agent Kontrol Merkezi</h2>
            {agents === null ? (
              <Unavailable>Agent durumu okunamıyor.</Unavailable>
            ) : (
              <>
                {agents.engine_paused && (
                  <p className="alert-row" data-tone="bad" role="status">
                    Motor durduruldu — hiçbir ajan yeni iş almaz.
                  </p>
                )}
                <div className="agent-grid">
                  {agents.agents.map((agent) => (
                    <AgentCard
                      key={agent.key}
                      agent={agent}
                      enginePaused={agents.engine_paused}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
          <EngineControl
            enginePaused={agents?.engine_paused ?? false}
            engineReason={agents?.engine_pause_reason ?? null}
          />
          <div className="kontrol-columns">
            <PublicationQueue rows={publications?.rows ?? null} />
            <div>
              <TopOpportunities rows={topOpportunities} />
              <AiWorkerPanel summary={summary} />
              <MediaPanel summary={summary} />
            </div>
          </div>
          <ActivityFeed entries={activity?.entries ?? null} />
        </>
      )}
    </section>
  );
}
