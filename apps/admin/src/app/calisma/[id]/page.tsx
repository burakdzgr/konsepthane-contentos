import Link from "next/link";
import { notFound } from "next/navigation";

import {
  fetchIntakeRunDetail,
  type IntakeChainView,
  type IntakeEventView,
  type IntakeRunView,
  type IntakeStageView,
} from "@/lib/intake-api";
import { fetchDashboardAgents, type AgentView } from "@/lib/dashboard-api";
import { formatUtcTimestamp } from "@/lib/format";
import { fetchIntelligenceSummary } from "@/lib/intelligence-api";
import { fetchIntegrations } from "@/lib/integrations-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import { AutoRefresh } from "../../kontrol/refresh";
import { controlIntakeRunAction } from "../actions";
import { buildLineStages, LineStageList, stageProgress } from "../stages";

// One run's live operation view: real durable stage state, the
// append-only event timeline, and the audited lifecycle controls.
export const dynamic = "force-dynamic";

const RUN_NOTICES: Record<string, string> = {
  baslatildi:
    "Çalışma başlatıldı. Motor keşif, ön eleme, sınırlı getirme ve yükseltmeyi otonom yürütür; insan kararı fırsat incelemesinde sorulur.",
  duraklatildi: "Çalışma duraklatıldı ve denetim kaydına geçti.",
  devam: "Çalışma devam ediyor.",
  durduruldu:
    "Çalışma güvenle durduruldu: yeni iş dağıtılmaz, uçuştaki zincirler tamamlanır.",
};

const RUN_STATUS_LABELS: Record<IntakeRunView["status"], string> = {
  running: "ÇALIŞIYOR",
  paused: "DURAKLATILDI",
  completed: "TAMAMLANDI",
  stopped: "DURDURULDU",
  failed: "BAŞARISIZ",
};

const RUN_STATUS_TONES: Record<IntakeRunView["status"], string> = {
  running: "run",
  paused: "warn",
  completed: "ok",
  stopped: "idle",
  failed: "bad",
};

// Event-feed badges per intake stage (the stage list itself is the shared
// Turkish line view in ../stages).
const STAGE_LABELS: Record<IntakeStageView["key"], string> = {
  discovery: "Keşif",
  prefilter: "Ön Eleme",
  fetch: "Getirme",
  normalize: "Anlama",
  duplicate: "Kopya Analizi",
  promote: "Fırsat",
};

const AGENT_NAMES: Record<string, string> = {
  research: "Araştırma ajanı",
  opportunity: "Fırsat ajanı",
  ideas: "Fikir ajanı",
  evidence: "Kanıt ajanı",
  intent: "SEO / Niyet ajanı",
  brief: "Brief ajanı",
  writer: "Yazar ajanı",
  editor: "Editör ajanı",
  qa: "Kalite ajanı",
  media: "Medya ajanı",
  publisher: "Yayın ajanı",
};

function elapsed(run: IntakeRunView): string {
  const start = new Date(run.created_at).getTime();
  const end =
    run.finished_at !== null ? new Date(run.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) {
    return "bilinmiyor";
  }
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 120) {
    return `${seconds} sn`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 120) {
    return `${minutes} dk`;
  }
  return `${Math.floor(minutes / 60)} sa`;
}

function describeEvent(event: IntakeEventView): string {
  const d = event.detail as Record<string, unknown>;
  const n = (key: string): number => Number(d[key] ?? 0);
  switch (event.kind) {
    case "run_started":
      return "Çalışma başlatıldı";
    case "run_paused":
      return `Çalışma duraklatıldı — ${String(d.reason ?? "")}`;
    case "run_resumed":
      return "Çalışma devam etti";
    case "run_stopped":
      return `Çalışma durduruldu — ${String(d.reason ?? "")}`;
    case "run_completed":
      return `Çalışma tamamlandı: ${n("fetched")} getirildi, ${n(
        "opportunities_created",
      )} fırsat oluştu, ${n("remaining_accepted_candidates")} aday sonraki çalışmaya kaldı`;
    case "run_failed":
      return `Çalışma başarısız (${String(d.error_type ?? "bilinmiyor")})`;
    case "discovery_started":
      return "Keşif başladı (sitemap/feed indiriliyor)";
    case "discovery_completed":
      return `Keşif tamamlandı: ${n("entries_seen")} kayıt görüldü, ${n(
        "admitted_new",
      )} yeni URL, ${n("rediscovered")} zaten biliniyordu`;
    case "discovery_retrying":
      return "Keşif yeniden denenecek";
    case "prefilter_progress":
      return `Ön eleme ilerliyor: toplam ${n("total_accepted")} uygun, ${n(
        "total_rejected",
      )} makine reddi`;
    case "prefilter_completed":
      return `Ön eleme tamamlandı: ${n("total_accepted")} uygun aday, ${n(
        "total_rejected",
      )} reddedildi (gerekçeleri kayıtlı)`;
    case "fetch_batch_dispatched":
      return `${n("count")} sayfalık getirme partisi kuyruğa verildi (toplam ${n(
        "dispatched_total",
      )})`;
    case "fetch_item_dispatched":
      return d.redispatch === true
        ? "Takılan getirme yeniden kuyruğa verildi"
        : "Sayfa getirme kuyruğa verildi";
    case "fetch_progress":
      return `Getirme ilerliyor: ${n("fetched")} tamam, ${n(
        "fetch_failed",
      )} hata, ${n("in_flight")} uçuşta`;
    case "fetch_budget_exhausted":
      return `Günlük getirme bütçesi doldu (${n("daily_budget")}/gün)`;
    case "fetch_cap_reached":
      return `Çalışma başına getirme sınırına ulaşıldı (${n("cap")})`;
    case "fetch_completed":
      return `Getirme bitti: ${n("fetched")} sayfa, ${n("fetch_failed")} hata`;
    case "promotion_dispatched":
      return "Uygun doküman fırsata yükseltiliyor (skorlama otomatik zincirlenir)";
    case "promotion_cap_reached":
      return `Çalışma başına yükseltme sınırına ulaşıldı (${n("cap")})`;
    case "operational_pause":
      return `Operasyonel durdurma devrede (${String(d.scope ?? "")}) — çalışma bekletildi`;
    case "step_error":
      return `Adım hatası (${String(d.error_type ?? "bilinmiyor")}); yeniden denenecek`;
    default:
      return event.kind;
  }
}

function ControlForm({
  run,
  action,
  label,
  placeholder,
  danger = false,
}: {
  run: IntakeRunView;
  action: "pause" | "resume" | "stop";
  label: string;
  placeholder: string;
  danger?: boolean;
}) {
  return (
    <details className="run-control-menu" data-danger={danger || undefined}>
      <summary role="button" tabIndex={0}>
        {label}
      </summary>
      <form action={controlIntakeRunAction} className="control-form">
        <input type="hidden" name="run_id" value={run.id} />
        <input type="hidden" name="action" value={action} />
        <input
          type="text"
          name="reason"
          required
          placeholder={placeholder}
          aria-label={`${label} gerekçesi`}
        />
        <button type="submit" className={danger ? "danger" : undefined}>
          Onayla
        </button>
      </form>
    </details>
  );
}

function AgentRail({ agents }: { agents: AgentView[] | null }) {
  if (agents === null) {
    return <p className="empty-note">Agent durumu okunamıyor.</p>;
  }
  return (
    <ul className="agent-mini-list">
      {agents.map((agent) => {
        const status = agent.is_paused
          ? { label: "DURAKLATILDI", tone: "warn" }
          : agent.last_attempt !== null &&
              agent.last_attempt.status !== "succeeded"
            ? { label: "HATA", tone: "bad" }
            : agent.attempts_today > 0
              ? { label: "AKTİF", tone: "ok" }
              : { label: "BOŞTA", tone: "idle" };
        return (
          <li key={agent.key}>
            <span className="agent-mini-identity">
              <span className="agent-status-dot" data-tone={status.tone} />
              <span className="agent-mini-copy">
                <strong>{AGENT_NAMES[agent.key] ?? agent.key}</strong>
                <small>
                  {agent.attempts_today > 0
                    ? `${agent.attempts_today} deneme · ${agent.failures_today} hata`
                    : "Beklemede"}
                </small>
              </span>
            </span>
            <span className="badge" data-tone={status.tone}>
              {status.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function RunStats({
  run,
  chain,
}: {
  run: IntakeRunView;
  chain: IntakeChainView;
}) {
  const stats: { label: string; value: string }[] = [
    {
      label: "Keşfedilen URL",
      value: String(run.discovered_new + run.rediscovered),
    },
    { label: "Ön elemeden geçen", value: String(run.prefilter_accepted) },
    { label: "Makine reddi", value: String(run.prefilter_rejected) },
    {
      label: "Getirilen sayfa",
      value: `${run.fetched}/${run.fetch_dispatched}`,
    },
    { label: "Getirme hatası", value: String(run.fetch_failed) },
    { label: "Anlaşılan içerik", value: String(chain.normalized_succeeded) },
    { label: "Anlama hatası", value: String(chain.normalized_failed) },
    { label: "Kopya analizi", value: String(chain.duplicates_evaluated) },
    { label: "Fırsat oluşturulan", value: String(run.opportunities_created) },
    { label: "Sıradaki aday", value: String(run.remaining_accepted) },
  ];
  return (
    <div className="stat-grid">
      {stats.map((stat) => (
        <div key={stat.label} className="stat-card">
          <span className="stat-label">{stat.label}</span>
          <span className="stat-value">{stat.value}</span>
        </div>
      ))}
    </div>
  );
}

export default async function RunDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<RawSearchParams>;
}) {
  const { id } = await params;
  const query = searchParams === undefined ? {} : await searchParams;
  const [result, agentsResult, signalsResult, integrationsResult] =
    await Promise.all([
      fetchIntakeRunDetail(id),
      fetchDashboardAgents(),
      fetchIntelligenceSummary(id),
      fetchIntegrations(),
    ]);
  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind !== "ok") {
    return (
      <section className="panel panel-wide" aria-labelledby="run-title">
        <h1 id="run-title">Çalışma</h1>
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      </section>
    );
  }
  const { run, chain, stages, events } = result.data;
  const agents = agentsResult.kind === "ok" ? agentsResult.data.agents : null;
  const lineStages = buildLineStages({
    run,
    chain,
    stages,
    signals: signalsResult.kind === "ok" ? signalsResult.data : null,
    integrations:
      integrationsResult.kind === "ok"
        ? integrationsResult.data.providers
        : null,
  });
  const progress = stageProgress(lineStages);
  const live = run.status === "running" || run.status === "paused";
  const errorEvents = events.filter(
    (event) =>
      event.kind === "step_error" ||
      event.kind === "run_failed" ||
      event.kind === "operational_pause",
  );
  return (
    <section className="run-console panel-wide" aria-labelledby="run-title">
      <div className="kontrol-header run-console-header">
        <div>
          <p className="muted run-breadcrumb">
            <Link href="/calisma">← Çalışmalar</Link>
          </p>
          <h1 id="run-title">{run.source_name} — Araştırma Çalışması</h1>
          <p className="muted">
            <span className="badge" data-tone={RUN_STATUS_TONES[run.status]}>
              {RUN_STATUS_LABELS[run.status]}
            </span>{" "}
            · Başladı: {formatUtcTimestamp(run.created_at)} · Geçen süre:{" "}
            {elapsed(run)}
          </p>
        </div>
        <div className="run-header-controls">
          {run.status === "running" && (
            <>
              <ControlForm
                run={run}
                action="pause"
                label="Duraklat"
                placeholder="duraklatma gerekçesi"
              />
              <ControlForm
                run={run}
                action="stop"
                label="Güvenli durdur"
                placeholder="durdurma gerekçesi"
                danger
              />
            </>
          )}
          {run.status === "paused" && (
            <>
              <ControlForm
                run={run}
                action="resume"
                label="Devam ettir"
                placeholder="devam gerekçesi"
              />
              <ControlForm
                run={run}
                action="stop"
                label="Güvenli durdur"
                placeholder="durdurma gerekçesi"
                danger
              />
            </>
          )}
          {live && (
            <AutoRefresh
              generatedAt={result.data.generated_at}
              intervalMs={5000}
            />
          )}
        </div>
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={RUN_NOTICES}
      />

      <section className="run-progress-panel" aria-label="Çalışma ilerlemesi">
        <div className="panel-block-heading">
          <h2>Hat aşamaları</h2>
          <span className="muted">%{progress} tamamlandı</span>
        </div>
        <LineStageList stages={lineStages} label="Çalışma aşamaları" />
        <div className="run-overall-progress" aria-hidden="true">
          <span style={{ width: `${progress}%` }} />
        </div>
      </section>

      <div className="run-console-grid">
        <section className="panel-block" aria-label="Canlı aktivite akışı">
          <div className="panel-block-heading">
            <h2>Canlı Aktivite Akışı</h2>
            {live && <span className="live-indicator">● Canlı</span>}
          </div>
          {events.length === 0 ? (
            <p className="empty-note">Henüz olay yok.</p>
          ) : (
            <ul className="activity-feed run-feed">
              {events.map((event) => (
                <li key={event.id} data-kind={event.kind}>
                  <span className="mono activity-time">
                    {formatUtcTimestamp(event.occurred_at)}
                  </span>
                  <span className="badge run-stage-badge">
                    {STAGE_LABELS[event.stage as IntakeStageView["key"]] ??
                      "Çalışma"}
                  </span>
                  <span className="activity-copy">{describeEvent(event)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="run-metrics-column">
          <section className="panel-block" aria-label="Çalışma istatistikleri">
            <h2>Çalışma İstatistikleri</h2>
            <RunStats run={run} chain={chain} />
            {run.opportunities_created > 0 && (
              <p>
                <Link href="/firsatlar">İncelenecek fırsatlara git →</Link>
              </p>
            )}
          </section>

          {chain.last_processed_title !== null && (
            <section className="panel-block" aria-label="Son işlenen içerik">
              <h2>Son İşlenen İçerik</h2>
              <div className="last-processed">
                <p className="cell-primary">{chain.last_processed_title}</p>
                {chain.last_processed_url !== null && (
                  <p className="muted mono">{chain.last_processed_url}</p>
                )}
              </div>
            </section>
          )}
        </div>

        <aside className="run-side-rail">
          <section className="panel-block" aria-label="Agentlar">
            <h2>Agentlar</h2>
            <AgentRail agents={agents} />
            <p className="muted">
              <Link href="/kontrol#agentlar">Detaylı görünüm →</Link>
            </p>
          </section>

          <section className="panel-block" aria-label="Motor kontrolü">
            <h2>Motor Kontrolü</h2>
            <div className="run-quick-actions">
              <Link href="/sources" data-tone="ok">
                Yeni Keşif Başlat
              </Link>
              <Link href="/motor" data-tone="run">
                Tüm Motor Kontrolleri
              </Link>
              <Link href="/kontrol#motor-kontrolu" data-tone="bad">
                Alımı Durdurma Ayarları
              </Link>
            </div>
          </section>

          {(errorEvents.length > 0 || run.failure_note !== null) && (
            <section className="panel-block" aria-label="Hatalar ve uyarılar">
              <h2>Hatalar / Uyarılar</h2>
              {run.failure_note !== null && (
                <p className="alert-row" data-tone="bad">
                  {run.failure_note}
                </p>
              )}
              <ul className="plain-list">
                {errorEvents.slice(0, 5).map((event) => (
                  <li key={event.id}>
                    <span className="mono">
                      {formatUtcTimestamp(event.occurred_at)}
                    </span>{" "}
                    {describeEvent(event)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!live && (
            <section className="panel-block" aria-label="Çalışma kapandı">
              <p className="muted">
                Çalışma kapandı. Kalan adaylar için kaynaktan yeni bir çalışma
                başlatın. Reddedilenler gerekçeleriyle{" "}
                <Link href="/research">Araştırma (gelişmiş)</Link> altında.
              </p>
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
