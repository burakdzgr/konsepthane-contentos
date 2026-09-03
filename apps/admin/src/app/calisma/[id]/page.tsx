import Link from "next/link";
import { notFound } from "next/navigation";

import {
  fetchIntakeRunDetail,
  type IntakeEventView,
  type IntakeRunView,
  type IntakeStageView,
} from "@/lib/intake-api";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import { AutoRefresh } from "../../kontrol/refresh";
import { controlIntakeRunAction } from "../actions";

// One run's live operation view: real durable stage state, the
// append-only event timeline, and the audited lifecycle controls.
export const dynamic = "force-dynamic";

const RUN_NOTICES: Record<string, string> = {
  baslatildi:
    "Çalışma başlatıldı. Motor keşif, ön filtre, sınırlı getirme ve yükseltmeyi otonom yürütür; insan kararı fırsat incelemesinde sorulur.",
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

const STAGE_LABELS: Record<IntakeStageView["key"], string> = {
  discovery: "Keşif",
  prefilter: "Ön Filtre",
  fetch: "Getir & Normalleştir",
  promote: "Fırsat Yükseltme",
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
      return `Ön filtre ilerliyor: toplam ${n("total_accepted")} uygun, ${n(
        "total_rejected",
      )} makine reddi`;
    case "prefilter_completed":
      return `Ön filtre tamamlandı: ${n("total_accepted")} uygun aday, ${n(
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

function StageTimeline({ stages }: { stages: IntakeStageView[] }) {
  return (
    <ol className="run-stages" aria-label="Aşama ilerlemesi">
      {stages.map((stage) => (
        <li key={stage.key} className="run-stage" data-state={stage.state}>
          <span className="run-stage-mark">
            {stage.state === "done"
              ? "✓"
              : stage.state === "active"
                ? "●"
                : "○"}
          </span>
          <span className="run-stage-label">{STAGE_LABELS[stage.key]}</span>
          <span className="run-stage-counts">
            {Object.entries(stage.counts)
              .map(([key, value]) => `${value} ${countLabel(key)}`)
              .join(" · ")}
          </span>
        </li>
      ))}
    </ol>
  );
}

function countLabel(key: string): string {
  const labels: Record<string, string> = {
    new: "yeni",
    rediscovered: "bilinen",
    accepted: "uygun",
    rejected: "reddedildi",
    remaining: "sırada",
    dispatched: "dağıtıldı",
    fetched: "getirildi",
    failed: "hata",
    waiting_candidates: "bekleyen aday",
    opportunities: "fırsat",
  };
  return labels[key] ?? key;
}

function ControlForm({
  run,
  action,
  label,
  placeholder,
}: {
  run: IntakeRunView;
  action: "pause" | "resume" | "stop";
  label: string;
  placeholder: string;
}) {
  return (
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
      <button type="submit">{label}</button>
    </form>
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
  const result = await fetchIntakeRunDetail(id);
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
  const { run, stages, events } = result.data;
  const live = run.status === "running" || run.status === "paused";
  const errorEvents = events.filter(
    (event) =>
      event.kind === "step_error" ||
      event.kind === "run_failed" ||
      event.kind === "operational_pause",
  );
  return (
    <section className="panel panel-wide" aria-labelledby="run-title">
      <div className="kontrol-header">
        <div>
          <p className="muted run-breadcrumb">
            <Link href="/calisma">← Çalışmalar</Link>
          </p>
          <h1 id="run-title">{run.source_name}</h1>
          <p className="muted">
            Araştırma Çalışması ·{" "}
            <span className="badge" data-tone={RUN_STATUS_TONES[run.status]}>
              {RUN_STATUS_LABELS[run.status]}
            </span>{" "}
            · Başladı: {formatUtcTimestamp(run.created_at)} · Geçen süre:{" "}
            {elapsed(run)}
          </p>
        </div>
        {live && (
          <AutoRefresh
            generatedAt={result.data.generated_at}
            intervalMs={5000}
          />
        )}
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={RUN_NOTICES}
      />

      <div className="kontrol-columns">
        <div>
          <section className="panel-block" aria-label="Aşama ilerlemesi">
            <h2>Aşamalar</h2>
            <StageTimeline stages={stages} />
          </section>

          <section className="panel-block" aria-label="Canlı olaylar">
            <h2>Canlı Olaylar</h2>
            {events.length === 0 ? (
              <p className="empty-note">Henüz olay yok.</p>
            ) : (
              <ul className="activity-feed run-feed">
                {events.map((event) => (
                  <li key={event.id} data-kind={event.kind}>
                    <span className="mono">
                      {formatUtcTimestamp(event.occurred_at)}
                    </span>{" "}
                    <span className="badge run-stage-badge">
                      {STAGE_LABELS[event.stage as IntakeStageView["key"]] ??
                        "Çalışma"}
                    </span>{" "}
                    {describeEvent(event)}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div>
          <section className="panel-block" aria-label="Sonuçlar">
            <h2>Sonuçlar</h2>
            <dl className="status-list">
              <div className="status-row">
                <dt>Keşfedilen (yeni)</dt>
                <dd>{run.discovered_new}</dd>
              </div>
              <div className="status-row">
                <dt>Ön filtre: uygun</dt>
                <dd>{run.prefilter_accepted}</dd>
              </div>
              <div className="status-row">
                <dt>Ön filtre: makine reddi</dt>
                <dd>{run.prefilter_rejected}</dd>
              </div>
              <div className="status-row">
                <dt>Getirilen</dt>
                <dd>
                  {run.fetched}/{run.fetch_dispatched}
                  {run.fetch_failed > 0 && ` (${run.fetch_failed} hata)`}
                </dd>
              </div>
              <div className="status-row">
                <dt>Fırsata yükseltilen</dt>
                <dd>
                  {run.opportunities_created}/{run.promotions_dispatched}
                </dd>
              </div>
              <div className="status-row">
                <dt>Sıradaki aday</dt>
                <dd>{run.remaining_accepted}</dd>
              </div>
            </dl>
            {run.opportunities_created > 0 && (
              <p>
                <Link href="/firsatlar">İncelenecek fırsatlara git →</Link>
              </p>
            )}
            <p className="muted">
              Reddedilenler gerekçeleriyle{" "}
              <Link href="/research">Araştırma (gelişmiş)</Link> altında.
            </p>
          </section>

          <section className="panel-block" aria-label="Çalışma kontrolleri">
            <h2>Kontroller</h2>
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
                />
              </>
            )}
            {!live && (
              <p className="muted">
                Çalışma kapandı. Kalan adaylar için kaynaktan yeni bir çalışma
                başlatın.
              </p>
            )}
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
        </div>
      </div>
    </section>
  );
}
