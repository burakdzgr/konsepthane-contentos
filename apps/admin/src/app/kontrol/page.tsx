import type { ReactNode } from "react";
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
import { formatUtcTimestamp } from "@/lib/format";
import {
  fetchIntakeRunDetail,
  fetchIntakeRuns,
  type IntakeEventView,
  type IntakeRunDetail,
  type IntakeRunView,
  type IntakeStageView,
} from "@/lib/intake-api";
import { STATE_LABELS_TR } from "@/lib/motor-plan";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { controlIntakeRunAction } from "../calisma/actions";
import { AppIcon } from "../icons";
import { ControlNotice } from "../notices";
import { pauseIntakeAction, resumeIntakeAction } from "./actions";
import { AutoRefresh } from "./refresh";

export const dynamic = "force-dynamic";

const KONTROL_NOTICES: Record<string, string> = {
  durduruldu:
    "Alım durduruldu. Çalışan işler güvenle tamamlanır; yeni iş kuyruğa alınmaz.",
  devam: "Alım yeniden açıldı ve denetim kaydına geçti.",
};

const AGENT_NAMES: Record<string, string> = {
  research: "Research Agent",
  opportunity: "Opportunity Agent",
  ideas: "Idea Agent",
  evidence: "Evidence Agent",
  intent: "SEO / Niyet Agent",
  brief: "Brief Agent",
  writer: "Writer Agent",
  editor: "Editor Agent",
  qa: "QA Agent",
  media: "Media Agent",
  publisher: "Publisher Agent",
};

const EVENT_LABELS: Record<string, string> = {
  run_started: "Çalışma başlatıldı",
  run_paused: "Çalışma duraklatıldı",
  run_resumed: "Çalışma devam ettirildi",
  run_stopped: "Çalışma güvenle durduruldu",
  run_completed: "Çalışma tamamlandı",
  run_failed: "Çalışma başarısız oldu",
  discovery_started: "Kaynak keşfi başladı",
  discovery_completed: "Kaynak keşfi tamamlandı",
  discovery_retrying: "Keşif yeniden deneniyor",
  prefilter_progress: "Ön eleme devam ediyor",
  prefilter_completed: "Ön eleme tamamlandı",
  fetch_batch_dispatched: "Fetch partisi kuyruğa aktarıldı",
  fetch_item_dispatched: "Sayfa fetch kuyruğuna aktarıldı",
  fetch_progress: "Sayfalar indiriliyor",
  fetch_budget_exhausted: "Günlük fetch bütçesi doldu",
  fetch_cap_reached: "Fetch sınırına ulaşıldı",
  fetch_completed: "Fetch aşaması tamamlandı",
  promotion_dispatched: "İçerik fırsata yükseltiliyor",
  promotion_cap_reached: "Fırsat sınırına ulaşıldı",
  operational_pause: "Operasyonel durdurma devrede",
  step_error: "Aşama hatası oluştu",
};

const STAGE_EVENT_LABELS: Record<string, string> = {
  discovery: "KEŞİF",
  prefilter: "ÖN ELEME",
  fetch: "FETCH",
  normalize: "NORMALİZE",
  duplicate: "ANALİZ",
  promote: "FIRSAT",
};

function stateCount(summary: DashboardSummary, state: string): number {
  return summary.work_item_states[state] ?? 0;
}

function shortTime(iso: string): string {
  const stamp = new Date(iso);
  return Number.isNaN(stamp.getTime())
    ? iso
    : stamp.toISOString().slice(11, 19);
}

function elapsed(run: IntakeRunView): string {
  const start = new Date(run.created_at).getTime();
  const end =
    run.finished_at === null ? Date.now() : new Date(run.finished_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function Unavailable({ children }: { children: ReactNode }) {
  return (
    <p className="empty-note" role="status">
      {children}
    </p>
  );
}

function RunControl({
  run,
  action,
  label,
  icon,
  danger = false,
}: {
  run: IntakeRunView;
  action: "pause" | "resume" | "stop";
  label: string;
  icon: string;
  danger?: boolean;
}) {
  return (
    <details className="console-run-control" data-danger={danger || undefined}>
      <summary role="button" tabIndex={0}>
        <span aria-hidden="true">{icon}</span> {label}
      </summary>
      <form action={controlIntakeRunAction} className="control-form">
        <input type="hidden" name="run_id" value={run.id} />
        <input type="hidden" name="action" value={action} />
        <input
          type="text"
          name="reason"
          required
          placeholder="gerekçe (zorunlu)"
          aria-label={`${label} gerekçesi`}
        />
        <button type="submit">Onayla</button>
      </form>
    </details>
  );
}

function ConsoleHeader({ run }: { run: IntakeRunView | null }) {
  const live = run?.status === "running" || run?.status === "paused";
  return (
    <div className="console-titlebar">
      <div className="console-title-copy">
        <div className="console-title-line">
          <h1 id="kontrol-title">
            {run === null
              ? "ContentOS Motoru"
              : `${run.source_name} — Research Run #${run.id.slice(0, 4)}`}
          </h1>
          {run !== null && (
            <span
              className="badge"
              data-tone={
                run.status === "running"
                  ? "ok"
                  : run.status === "paused"
                    ? "warn"
                    : "idle"
              }
            >
              {run.status === "running"
                ? "ÇALIŞIYOR"
                : run.status === "paused"
                  ? "DURAKLATILDI"
                  : run.status.toLocaleUpperCase("tr-TR")}
            </span>
          )}
          {live && run !== null && (
            <span className="console-elapsed">
              <AppIcon name="history" size={14} /> {elapsed(run)}
            </span>
          )}
        </div>
        <p>
          {run === null ? (
            "İçerik Üretim Kontrol Merkezi"
          ) : (
            <>
              Başlangıç: {formatUtcTimestamp(run.created_at)} · Kaynak:{" "}
              <Link href={`/sources?source=${run.source_id}`}>
                {run.source_slug}
              </Link>
            </>
          )}
        </p>
      </div>
      <div className="console-title-actions">
        {run?.status === "running" && (
          <>
            <RunControl
              run={run}
              action="stop"
              label="Durdur"
              icon="■"
              danger
            />
            <RunControl run={run} action="pause" label="Duraklat" icon="Ⅱ" />
          </>
        )}
        {run?.status === "paused" && (
          <RunControl run={run} action="resume" label="Devam Et" icon="▶" />
        )}
        <Link href="/motor" className="console-settings-link">
          <AppIcon name="settings" size={15} /> Ayarlar
        </Link>
      </div>
    </div>
  );
}

type ConsoleStage = {
  key: string;
  label: string;
  count: string;
  note: string;
  state: "done" | "active" | "pending";
};

function formatCount(value: number): string {
  return value.toLocaleString("tr-TR");
}

function stageFromDetail(
  detail: IntakeRunDetail | null,
  key: IntakeStageView["key"],
): IntakeStageView | null {
  return detail?.stages.find((stage) => stage.key === key) ?? null;
}

function PipelineStrip({
  summary,
  detail,
}: {
  summary: DashboardSummary;
  detail: IntakeRunDetail | null;
}) {
  const run = detail?.run ?? null;
  const laterEditorial = [
    "drafting",
    "editing",
    "qa_review",
    "awaiting_human_review",
    "approved",
    "scheduled",
    "publishing",
  ].reduce((total, state) => total + stateCount(summary, state), 0);
  const stages: ConsoleStage[] = [
    {
      key: "discovery",
      label: "Keşif",
      count: formatCount(
        run === null
          ? (summary.research.discovery_states.discovered ?? 0)
          : run.discovered_new + run.rediscovered,
      ),
      note: "keşfedildi",
      state: stageFromDetail(detail, "discovery")?.state ?? "done",
    },
    {
      key: "prefilter",
      label: "Ön Eleme",
      count: formatCount(
        run?.prefilter_accepted ??
          summary.research.discovery_states.accepted ??
          0,
      ),
      note: "uygun",
      state: stageFromDetail(detail, "prefilter")?.state ?? "done",
    },
    {
      key: "fetch",
      label: "Fetch",
      count:
        run === null
          ? formatCount(summary.research.discovery_states.fetched ?? 0)
          : `${formatCount(run.fetched)} / ${formatCount(run.fetch_dispatched)}`,
      note: "alınıyor",
      state: stageFromDetail(detail, "fetch")?.state ?? "active",
    },
    {
      key: "normalize",
      label: "Normalize",
      count: formatCount(detail?.chain.normalized_succeeded ?? 0),
      note: "tamamlandı",
      state: stageFromDetail(detail, "normalize")?.state ?? "pending",
    },
    {
      key: "analysis",
      label: "Analiz",
      count: formatCount(detail?.chain.duplicates_evaluated ?? 0),
      note: "inceleniyor",
      state: stageFromDetail(detail, "duplicate")?.state ?? "pending",
    },
    {
      key: "opportunity",
      label: "Fırsat",
      count: formatCount(
        run?.opportunities_created ?? stateCount(summary, "idea_scoring"),
      ),
      note: "oluşturuldu",
      state: stageFromDetail(detail, "promote")?.state ?? "pending",
    },
    {
      key: "evidence",
      label: "Kanıt",
      count: formatCount(stateCount(summary, "evidence_building")),
      note: "bekliyor",
      state:
        stateCount(summary, "evidence_building") > 0 ? "active" : "pending",
    },
    {
      key: "intent",
      label: "SEO / Niyet",
      count: formatCount(
        stateCount(summary, "seo_research") + stateCount(summary, "briefing"),
      ),
      note: "bekliyor",
      state:
        stateCount(summary, "seo_research") + stateCount(summary, "briefing") >
        0
          ? "active"
          : "pending",
    },
    {
      key: "editorial",
      label: "Editoryal",
      count: formatCount(laterEditorial),
      note: "bekliyor",
      state: laterEditorial > 0 ? "active" : "pending",
    },
  ];
  const done = stages.filter((stage) => stage.state === "done").length;
  const hasActive = stages.some((stage) => stage.state === "active");
  const progress = Math.round(
    ((done + (hasActive ? 0.45 : 0)) / stages.length) * 100,
  );
  return (
    <section className="console-progress" aria-label="İçerik üretim aşamaları">
      <ol className="console-pipeline">
        {stages.map((stage, index) => (
          <li key={stage.key} data-state={stage.state}>
            <span className="console-stage-node">
              {stage.state === "done" ? "✓" : index + 1}
            </span>
            <span className="console-stage-label">{stage.label}</span>
            <strong>{stage.count}</strong>
            <small>{stage.note}</small>
          </li>
        ))}
      </ol>
      <div className="console-progress-total">
        <span>Genel ilerleme</span>
        <span className="console-progress-track">
          <span style={{ width: `${progress}%` }} />
        </span>
        <strong>%{progress}</strong>
      </div>
    </section>
  );
}

function runEventText(event: IntakeEventView): string {
  const detail = event.detail as Record<string, unknown>;
  const count = (key: string) => Number(detail[key] ?? 0);
  if (event.kind === "discovery_completed")
    return `${count("entries_seen")} URL keşfedildi`;
  if (event.kind === "prefilter_progress")
    return `${count("total_accepted")} URL uygun bulundu`;
  if (event.kind === "fetch_progress")
    return `${count("fetched")} sayfa indirildi, ${count("in_flight")} işlem sürüyor`;
  if (event.kind === "promotion_dispatched")
    return "Uygun doküman fırsata yükseltiliyor";
  return EVENT_LABELS[event.kind] ?? event.kind.replaceAll("_", " ");
}

function activityText(entry: ActivityEntry): string {
  if (entry.kind === "workflow") {
    const to =
      entry.to_state === null
        ? "?"
        : ((STATE_LABELS_TR as Record<string, string>)[entry.to_state] ??
          entry.to_state);
    return `${entry.title ?? "İş öğesi"} → ${to}`;
  }
  if (entry.kind === "publication")
    return `Yayın denemesi: ${entry.title ?? ""} · ${entry.status ?? "?"}`;
  return `Alım ${entry.action === "paused" ? "durduruldu" : "açıldı"}: ${entry.scope ?? "motor"}`;
}

function ActivityFeed({
  runEntries,
  dashboardEntries,
}: {
  runEntries: IntakeEventView[] | null;
  dashboardEntries: ActivityEntry[] | null;
}) {
  const hasRunEvents = runEntries !== null && runEntries.length > 0;
  const total = hasRunEvents
    ? runEntries.length
    : (dashboardEntries?.length ?? 0);
  return (
    <section
      className="console-card console-activity"
      aria-label="Canlı aktivite akışı"
    >
      <div className="console-card-heading">
        <h2>Canlı Aktivite Akışı</h2>
        <span className="live-indicator">● Canlı</span>
      </div>
      {total === 0 && <Unavailable>Henüz kayıtlı olay yok.</Unavailable>}
      {hasRunEvents && (
        <ul className="console-feed">
          {runEntries.slice(0, 12).map((event) => (
            <li key={event.id}>
              <time>{shortTime(event.occurred_at)}</time>
              <span className="console-event-icon">
                <AppIcon name="activity" size={13} />
              </span>
              <span className="console-event-copy">
                <strong>{runEventText(event)}</strong>
                <small>{STAGE_EVENT_LABELS[event.stage] ?? "SİSTEM"}</small>
              </span>
              <span className="console-event-badge">
                {STAGE_EVENT_LABELS[event.stage] ?? "SİSTEM"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {!hasRunEvents && dashboardEntries !== null && (
        <ul className="console-feed">
          {dashboardEntries.slice(0, 12).map((entry, index) => (
            <li key={`${entry.kind}-${index}`}>
              <time>{shortTime(entry.occurred_at)}</time>
              <span className="console-event-icon">
                <AppIcon name="activity" size={13} />
              </span>
              <span className="console-event-copy">
                {entry.work_item_id === null ? (
                  <strong>{activityText(entry)}</strong>
                ) : (
                  <Link href={`/editorial/${entry.work_item_id}`}>
                    {activityText(entry)}
                  </Link>
                )}
                <small>{entry.kind.toLocaleUpperCase("tr-TR")}</small>
              </span>
              <span className="console-event-badge">{entry.kind}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function KpiStrip({
  summary,
  detail,
}: {
  summary: DashboardSummary;
  detail: IntakeRunDetail | null;
}) {
  const run = detail?.run ?? null;
  const cards: { label: string; value: string; tone?: string; note: string }[] =
    [
      {
        label: "Keşfedilen URL",
        value: formatCount(
          run === null
            ? (summary.research.discovery_states.discovered ?? 0)
            : run.discovered_new + run.rediscovered,
        ),
        note: `${summary.research.active_sources} aktif kaynak`,
        tone: "ok",
      },
      {
        label: "Ön Elemeden Geçen",
        value: formatCount(
          run?.prefilter_accepted ??
            summary.research.discovery_states.accepted ??
            0,
        ),
        note: "uygun aday",
        tone: "ok",
      },
      {
        label: "Fetch Kuyruğu",
        value: formatCount(
          run === null
            ? (summary.queue.depth ?? 0)
            : Math.max(
                0,
                run.fetch_dispatched - run.fetched - run.fetch_failed,
              ),
        ),
        note: summary.queue.depth === null ? "anlık ölçüm yok" : "bekleyen",
      },
      {
        label: "Fetch Edilen",
        value: formatCount(
          run?.fetched ?? summary.research.discovery_states.fetched ?? 0,
        ),
        note: `${run?.fetch_failed ?? summary.research.discovery_states.fetch_failed ?? 0} hata`,
        tone: "ok",
      },
      {
        label: "Normalize Edilen",
        value: formatCount(detail?.chain.normalized_succeeded ?? 0),
        note: `${detail?.chain.normalized_failed ?? 0} hata`,
        tone: "ok",
      },
      {
        label: "Analiz Edilen",
        value: String(detail?.chain.duplicates_evaluated ?? 0),
        note: "kopya analizi",
      },
      {
        label: "Uygun Bulunan",
        value: String(
          run?.opportunities_created ?? stateCount(summary, "idea_scoring"),
        ),
        note: "açık fırsat",
        tone: "ok",
      },
      {
        label: "Reddedilen",
        value: String(
          run?.prefilter_rejected ??
            summary.research.discovery_states.rejected ??
            0,
        ),
        note: "makine reddi",
        tone: "bad",
      },
      {
        label: "Fırsat Oluşturulan",
        value: String(
          run?.opportunities_created ?? stateCount(summary, "idea_scoring"),
        ),
        note: "üretim kararı",
        tone: "ok",
      },
      {
        label: "Hata Sayısı",
        value: String(
          (run?.fetch_failed ??
            summary.research.discovery_states.fetch_failed ??
            0) +
            (detail?.chain.normalized_failed ?? 0) +
            summary.ai.failures_today,
        ),
        note: "güncel toplam",
        tone: "bad",
      },
      {
        label: "AI Denemeleri",
        value: String(summary.ai.attempts_today),
        note: "bugün",
      },
      {
        label: "Bugün Yayınlanan",
        value: String(summary.published_today),
        note: `${summary.publishing.packages_total} paket`,
        tone: "ok",
      },
    ];
  return (
    <section
      className="console-card console-stats"
      aria-label="Çalışma istatistikleri"
    >
      <h2>Çalışma İstatistikleri</h2>
      <div className="console-stat-grid">
        {cards.map((card) => (
          <div key={card.label} className="console-stat" data-tone={card.tone}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.note}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function CurrentContent({
  detail,
  row,
}: {
  detail: IntakeRunDetail | null;
  row: WorkQueueRow | null;
}) {
  const title =
    detail?.chain.last_processed_title ?? row?.title_working_label ?? null;
  const url = detail?.chain.last_processed_url ?? null;
  return (
    <section
      className="console-card console-current"
      aria-label="Güncel işlenen içerik"
    >
      <h2>Güncel İşlenen İçerik</h2>
      {title === null ? (
        <Unavailable>İşlenmekte olan içerik yok.</Unavailable>
      ) : (
        <div className="console-current-body">
          <span className="console-current-thumb">
            <AppIcon name="content" size={28} />
          </span>
          <span className="console-current-copy">
            {row === null ? (
              <strong>{title}</strong>
            ) : (
              <Link href={`/editorial/${row.work_item_id}`}>{title}</Link>
            )}
            {url !== null && <small>{url}</small>}
            {row !== null && (
              <dl>
                <div>
                  <dt>Aşama</dt>
                  <dd>{STATE_LABELS_TR[row.current_state]}</dd>
                </div>
                <div>
                  <dt>Skor</dt>
                  <dd>{row.score_overall_value?.toFixed(2) ?? "—"}</dd>
                </div>
              </dl>
            )}
          </span>
          {row !== null && (
            <Link
              className="console-current-action"
              href={`/editorial/${row.work_item_id}`}
            >
              İncele
            </Link>
          )}
        </div>
      )}
    </section>
  );
}

function agentStatus(
  agent: AgentView,
  enginePaused: boolean,
): { label: string; tone: string } {
  if (enginePaused) return { label: "PAUSED", tone: "bad" };
  if (agent.is_paused) return { label: "PAUSED", tone: "warn" };
  if (agent.last_attempt !== null && agent.last_attempt.status !== "succeeded")
    return { label: "ERROR", tone: "bad" };
  if (agent.attempts_today > 0) return { label: "RUNNING", tone: "ok" };
  return { label: "IDLE", tone: "idle" };
}

function AgentRail({
  agents,
  enginePaused,
}: {
  agents: AgentView[] | null;
  enginePaused: boolean;
}) {
  return (
    <section
      className="console-card console-agents"
      id="agentlar"
      aria-label="Agentlar"
    >
      <div className="console-card-heading">
        <h2>Agentlar</h2>
        <Link href="/motor">Detaylı görünüm</Link>
      </div>
      {agents === null && <Unavailable>Agent durumu okunamıyor.</Unavailable>}
      {agents !== null && (
        <ul className="console-agent-list">
          {agents.map((agent) => {
            const status = agentStatus(agent, enginePaused);
            const success =
              agent.attempts_today === 0
                ? null
                : Math.round(
                    ((agent.attempts_today - agent.failures_today) /
                      agent.attempts_today) *
                      100,
                  );
            return (
              <li key={agent.key}>
                <span className="agent-status-dot" data-tone={status.tone} />
                <span className="console-agent-copy">
                  <strong>{AGENT_NAMES[agent.key] ?? agent.key}</strong>
                  <small>
                    {agent.attempts_today > 0
                      ? `${agent.attempts_today} deneme · ${agent.failures_today} hata${success === null ? "" : ` · %${success}`}`
                      : "Beklemede"}
                  </small>
                  {agent.last_attempt !== null && (
                    <span className="sr-only">
                      {agent.last_attempt.provider}/
                      {agent.last_attempt.model_name}
                    </span>
                  )}
                </span>
                <span className="console-agent-state" data-tone={status.tone}>
                  {status.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function EngineControl({
  enginePaused,
  engineReason,
}: {
  enginePaused: boolean;
  engineReason: string | null;
}) {
  return (
    <section
      className="console-card console-engine"
      id="motor-kontrolu"
      aria-label="Motor kontrolü"
    >
      <h2>Motor Kontrolü</h2>
      <div className="console-engine-actions">
        <Link href="/sources" data-tone="ok">
          <AppIcon name="plus" size={13} /> Yeni Keşif Başlat
        </Link>
        <Link href="/motor" data-tone="run">
          <AppIcon name="agents" size={13} /> Tüm Agentları Yönet
        </Link>
        {enginePaused ? (
          <form action={resumeIntakeAction} className="console-engine-form">
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
        ) : (
          <details className="console-engine-stop">
            <summary>● Yeni İş Alımını Durdur</summary>
            <form action={pauseIntakeAction} className="console-engine-form">
              <input type="hidden" name="scope" value="engine" />
              <input
                type="text"
                name="reason"
                required
                placeholder="durdurma gerekçesi"
                aria-label="Acil durdurma gerekçesi"
              />
              <button type="submit" className="danger">
                Acil Durdurma
              </button>
            </form>
          </details>
        )}
      </div>
      {enginePaused && (
        <p className="console-engine-reason" role="status">
          Motor durduruldu{engineReason === null ? "" : `: ${engineReason}`}
        </p>
      )}
      <p className="sr-only">
        Durdurma yalnızca YENİ iş alımını keser; çalışan atomik işler güvenle
        tamamlanır.
      </p>
    </section>
  );
}

function AttentionPanel({ summary }: { summary: DashboardSummary }) {
  const items = [
    {
      label: "İçerik Üretim Kararı",
      note: "Fırsat için editoryal karar bekleniyor",
      count: summary.attention.production_decisions,
      href: "/firsatlar",
    },
    {
      label: "Nihai Yayın Onayı",
      note: "Taslak yayın için onay bekliyor",
      count: summary.attention.awaiting_human_review,
      href: "/editorial?state=awaiting_human_review",
    },
    {
      label: "Bloke içerik",
      note: "Çözüm ve yönlendirme bekleniyor",
      count: stateCount(summary, "blocked"),
      href: "/editorial?state=blocked",
    },
  ];
  return (
    <section
      className="console-card console-bottom-card"
      aria-label="Benden bekleyenler"
    >
      <h2>Benden Bekleyenler</h2>
      <ul className="console-decision-list">
        {items.map((item) => (
          <li key={item.label}>
            <Link href={item.href} aria-label={`${item.label} ${item.count}`}>
              <span className="console-count-orb">{item.count}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.note}</small>
              </span>
              <span aria-hidden="true">›</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TopOpportunities({ rows }: { rows: WorkQueueRow[] | null }) {
  return (
    <section
      className="console-card console-bottom-card"
      aria-label="Son fırsatlar"
    >
      <h2>Son Fırsatlar</h2>
      {rows === null && <Unavailable>Fırsatlar okunamıyor.</Unavailable>}
      {rows !== null && rows.length === 0 && (
        <Unavailable>Açık fırsat yok.</Unavailable>
      )}
      {rows !== null && rows.length > 0 && (
        <ul className="console-compact-list">
          {rows.slice(0, 3).map((row) => (
            <li key={row.work_item_id}>
              <Link href={`/editorial/${row.work_item_id}`}>
                <span>
                  <strong>{row.title_working_label}</strong>
                  <small>{row.topic_summary ?? "İçerik fırsatı"}</small>
                </span>
                <span>{row.score_overall_value?.toFixed(2) ?? "—"}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link className="console-card-link" href="/firsatlar">
        Tüm fırsatları gör →
      </Link>
    </section>
  );
}

function PublicationQueue({ rows }: { rows: PublicationQueueRow[] | null }) {
  return (
    <section
      className="console-card console-bottom-card"
      id="yayin-kuyrugu"
      aria-label="Yayın kuyruğu"
    >
      <h2>Yayın Kuyruğu</h2>
      {rows === null && <Unavailable>Yayın kuyruğu okunamıyor.</Unavailable>}
      {rows !== null && rows.length === 0 && (
        <Unavailable>Henüz yayın paketi yok.</Unavailable>
      )}
      {rows !== null && rows.length > 0 && (
        <ul className="console-compact-list">
          {rows.slice(0, 3).map((row) => (
            <li key={row.package_id}>
              <Link href={`/editorial/${row.work_item_id}`}>
                <span>
                  <strong>{row.title_working_label}</strong>
                  <small>{formatUtcTimestamp(row.created_at)}</small>
                </span>
                <span className="badge" data-state={row.work_item_state}>
                  {STATE_LABELS_TR[row.work_item_state]}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link className="console-card-link" href="/editorial?state=scheduled">
        Tüm kuyruğu gör →
      </Link>
    </section>
  );
}

function SystemHealth({ summary }: { summary: DashboardSummary }) {
  const budget = summary.ai.daily_budget;
  const items = [
    ["Backend API", "Sağlıklı"],
    ["Aktif kaynak", String(summary.research.active_sources)],
    [
      "İş kuyruğu",
      summary.queue.depth === null ? "ölçülemedi" : String(summary.queue.depth),
    ],
    ["AI servisleri", `${summary.ai.attempts_today} deneme`],
    ["Yayın paketleri", String(summary.publishing.packages_total)],
  ];
  return (
    <section
      className="console-card console-bottom-card"
      aria-label="Sistem sağlığı"
    >
      <h2>Sistem Sağlığı</h2>
      <dl className="console-health-list">
        {items.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {budget !== null && (
        <div className="console-budget">
          <span>AI bütçesi</span>
          <progress
            value={Math.min(summary.ai.attempts_today, budget)}
            max={budget}
          />
          <strong>
            {summary.ai.attempts_today}/{budget}
          </strong>
        </div>
      )}
    </section>
  );
}

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
    opportunitiesResult,
  ] = await Promise.all([
    fetchDashboardSummary(),
    fetchDashboardAgents(),
    fetchDashboardActivity(30),
    fetchDashboardPublications(),
    fetchWorkQueue({ limit: 12 }),
    fetchIntakeRuns(),
    fetchWorkQueue({
      workflowState: "idea_scoring",
      opportunityDisposition: "open",
      limit: 20,
    }),
  ]);
  const summary = summaryResult.kind === "ok" ? summaryResult.data : null;
  const agents = agentsResult.kind === "ok" ? agentsResult.data : null;
  const activity =
    activityResult.kind === "ok" ? activityResult.data.entries : null;
  const publications =
    publicationsResult.kind === "ok" ? publicationsResult.data.rows : null;
  const queueRows = queueResult.kind === "ok" ? queueResult.data.items : null;
  const runs = runsResult.kind === "ok" ? runsResult.data.runs : [];
  const focusRun =
    runs.find((run) => run.status === "running" || run.status === "paused") ??
    runs[0] ??
    null;
  const detailResult =
    focusRun === null ? null : await fetchIntakeRunDetail(focusRun.id);
  const detail = detailResult?.kind === "ok" ? detailResult.data : null;
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

  return (
    <section
      className="control-console panel-wide"
      aria-labelledby="kontrol-title"
    >
      <ConsoleHeader run={focusRun} />
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={KONTROL_NOTICES}
      />
      {summary === null ? (
        <section className="console-card">
          <Unavailable>
            Backend API&apos;ye şu anda erişilemiyor; kontrol merkezi verisi
            yok.
          </Unavailable>
        </section>
      ) : (
        <>
          <PipelineStrip summary={summary} detail={detail} />
          <div className="console-main-grid">
            <ActivityFeed
              runEntries={detail?.events ?? null}
              dashboardEntries={activity}
            />
            <div className="console-center-column">
              <KpiStrip summary={summary} detail={detail} />
              <CurrentContent detail={detail} row={queueRows?.[0] ?? null} />
            </div>
            <aside className="console-side-column">
              <AgentRail
                agents={agents?.agents ?? null}
                enginePaused={agents?.engine_paused ?? false}
              />
              <EngineControl
                enginePaused={agents?.engine_paused ?? false}
                engineReason={agents?.engine_pause_reason ?? null}
              />
            </aside>
          </div>
          <div className="console-bottom-grid">
            <AttentionPanel summary={summary} />
            <TopOpportunities rows={topOpportunities} />
            <PublicationQueue rows={publications} />
            <SystemHealth summary={summary} />
          </div>
          <footer className="console-live-footer">
            <AutoRefresh generatedAt={summary.generated_at} />
            <span>● Canlı güncelleme açık</span>
          </footer>
        </>
      )}
    </section>
  );
}
