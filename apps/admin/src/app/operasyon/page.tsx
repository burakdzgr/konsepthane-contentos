import Link from "next/link";

import { formatUtcTimestamp } from "@/lib/format";
import { fetchIntakeRunDetail } from "@/lib/intake-api";
import { fetchIntelligenceSummary } from "@/lib/intelligence-api";
import {
  fetchIntegrations,
  type IntegrationView,
} from "@/lib/integrations-api";
import {
  AUTOPILOT_MODE_HINTS,
  AUTOPILOT_MODE_LABELS,
  AUTOPILOT_MODES,
  fetchLiveOperations,
  type FeedEntry,
  type GatewayView,
  type LineItem,
  type LiveOperations,
} from "@/lib/operations-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { trLabel } from "@/lib/tr-labels";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";
import { setAutopilotModeAction } from "./actions";
import { BrowserView } from "./browser-view";
import {
  buildLineStages,
  LineStageList,
  type LineStage,
} from "../calisma/stages";

// Canlı Operasyon (ADR 0012): one page that follows the whole line from the
// discovery click to publication — the autopilot's mode and last word per
// item, the intake runs, the AI gateway's health and running job, and one
// merged feed. Read-only except the mode switch; refreshed every 5 seconds.
export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {
  "mode-off": "Otopilot kapatıldı. Adımlar yeniden elle tetiklenecek.",
  "mode-supervised":
    "Otopilot denetimli modda: çıktılar kendiliğinden üretilir, kabuller sizde.",
  "mode-autonomous":
    "Otopilot otonom modda: nihai yayın onayı dışında her adım kendiliğinden ilerler.",
};

function shortTime(iso: string): string {
  return formatUtcTimestamp(iso).replace(/^\d{4}-\d{2}-\d{2} /, "");
}

function ModeCard({ live }: { live: LiveOperations }) {
  const current = live.autopilot.mode;
  return (
    <section className="ops-card" data-span="8" aria-labelledby="ops-mode">
      <h2 id="ops-mode">Otopilot</h2>
      <p className="muted">{AUTOPILOT_MODE_HINTS[current]}</p>
      <dl className="ops-facts">
        <div>
          <dt>Mod</dt>
          <dd>{AUTOPILOT_MODE_LABELS[current]}</dd>
        </div>
        <div>
          <dt>Sorumlu</dt>
          <dd>{live.autopilot.actor_display_name ?? "—"}</dd>
        </div>
        <div>
          <dt>Gerekçe</dt>
          <dd>{live.autopilot.reason ?? "—"}</dd>
        </div>
        <div>
          <dt>Değişti</dt>
          <dd>
            {live.autopilot.updated_at !== null
              ? formatUtcTimestamp(live.autopilot.updated_at)
              : "—"}
          </dd>
        </div>
      </dl>
      <div className="ops-mode">
        <form action={setAutopilotModeAction} className="control-form">
          <select name="mode" defaultValue={current} aria-label="Otopilot modu">
            {AUTOPILOT_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {AUTOPILOT_MODE_LABELS[mode]}
              </option>
            ))}
          </select>
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="mod değişikliği gerekçesi"
            aria-label="Otopilot mod gerekçesi"
          />
          <button type="submit">Modu uygula</button>
          <span className="muted">
            Kayıtlı bir karar: adınız ve gerekçeniz otopilotun her kabulünde
            sorumlu olarak görünür.
          </span>
        </form>
      </div>
    </section>
  );
}

function GatewayCard({ gateway }: { gateway: GatewayView }) {
  const tone = !gateway.configured
    ? "neutral"
    : !gateway.reachable
      ? "bad"
      : gateway.status === "ok"
        ? "ok"
        : "warn";
  const headline = !gateway.configured
    ? "Yapılandırılmadı"
    : !gateway.reachable
      ? `Erişilemiyor (${gateway.error ?? "bilinmiyor"})`
      : gateway.status === "ok"
        ? "Çalışıyor"
        : `Kısıtlı (${gateway.status})`;
  return (
    <section className="ops-card" data-span="4" aria-labelledby="ops-gateway">
      <h2 id="ops-gateway">Yapay zeka köprüsü</h2>
      <p>
        <span className="badge" data-tone={tone}>
          {headline}
        </span>{" "}
        <span className="muted">
          {gateway.provider === "subcontractor"
            ? `Subcontractor gateway${gateway.base_url_host ? ` · ${gateway.base_url_host}` : ""}`
            : "OpenAI"}
        </span>
      </p>
      {gateway.reachable && (
        <dl className="ops-facts">
          <div>
            <dt>Hazır hesap</dt>
            <dd>{gateway.ready_accounts ?? "—"}</dd>
          </div>
          <div>
            <dt>Kuyrukta</dt>
            <dd>{gateway.queued ?? "—"}</dd>
          </div>
          <div>
            <dt>Çalışan</dt>
            <dd>{gateway.running ?? "—"}</dd>
          </div>
        </dl>
      )}
      <details className="detail-fold">
        <summary>Gelişmiş</summary>
        {gateway.accounts.length > 0 && (
          <ul className="plain-list">
            {gateway.accounts.map((account) => (
              <li key={account.id}>
                {account.label}{" "}
                <span
                  className="badge"
                  data-tone={
                    account.blocked_by
                      ? "bad"
                      : account.busy
                        ? "info"
                        : account.enabled
                          ? "ok"
                          : "neutral"
                  }
                >
                  {account.blocked_by
                    ? `engelli: ${account.blocked_by}`
                    : account.busy
                      ? "meşgul"
                      : account.enabled
                        ? "hazır"
                        : "kapalı"}
                </span>
              </li>
            ))}
          </ul>
        )}
        {gateway.jobs.length > 0 && (
          <ul className="plain-list">
            {gateway.jobs.map((job) => (
              <li key={job.job_id}>
                <span className="mono">{job.job_id.slice(0, 8)}</span> ·{" "}
                {job.model ?? "?"} ·{" "}
                {job.job_type === "image" ? "görsel" : "metin"} ·{" "}
                {job.phase ?? job.status}
              </li>
            ))}
          </ul>
        )}
        {gateway.configured &&
          gateway.reachable &&
          gateway.accounts.length === 0 && (
            <p className="muted">
              Yönetim anahtarı olmadan yalnızca sağlık özeti okunuyor. Hesap ve
              iş ayrıntıları için CONTENTOS_SUBCONTRACTOR_ADMIN_TOKEN
              tanımlayın.
            </p>
          )}
      </details>
    </section>
  );
}

function BrowserCard({ gateway }: { gateway: GatewayView }) {
  const available =
    gateway.configured && gateway.reachable && gateway.accounts.length > 0;
  return (
    <section className="ops-card" data-span="4" aria-labelledby="ops-browser">
      <h2 id="ops-browser">Tarayıcı</h2>
      <BrowserView available={available} />
      <p className="muted">
        Gateway&apos;in ChatGPT oturumunun canlı görüntüsü (3 sn&apos;de bir
        kare). Nstbrowser penceresi host makinede açık kalır ama önde olmak
        zorunda değildir.
      </p>
    </section>
  );
}

// Live runs carry the full Turkish stage list (intake stages from the run
// view, signal stages from the run-scoped intelligence summary, provider
// stages from the integrations board); nothing here is inferred.
const MAX_STAGED_RUNS = 3;

async function lineStagesForRuns(
  runs: LiveOperations["intake_runs"],
): Promise<Record<string, LineStage[]>> {
  const live = runs
    .filter((run) => run.status === "running" || run.status === "paused")
    .slice(0, MAX_STAGED_RUNS);
  if (live.length === 0) {
    return {};
  }
  const integrationsResult = await fetchIntegrations();
  const integrations: IntegrationView[] | null =
    integrationsResult.kind === "ok" ? integrationsResult.data.providers : null;
  const entries = await Promise.all(
    live.map(async (run) => {
      const [detail, signals] = await Promise.all([
        fetchIntakeRunDetail(run.id),
        fetchIntelligenceSummary(run.id),
      ]);
      return [
        run.id,
        buildLineStages({
          run,
          chain: detail.kind === "ok" ? detail.data.chain : null,
          stages: detail.kind === "ok" ? detail.data.stages : [],
          signals: signals.kind === "ok" ? signals.data : null,
          integrations,
        }),
      ] as const;
    }),
  );
  return Object.fromEntries(entries);
}

function IntakeCard({
  live,
  stageMap,
}: {
  live: LiveOperations;
  stageMap: Record<string, LineStage[]>;
}) {
  return (
    <section className="ops-card" data-span="4" aria-labelledby="ops-intake">
      <h2 id="ops-intake">Keşif çalışmaları</h2>
      {live.intake_runs.length === 0 && (
        <p className="muted">
          Aktif keşif çalışması yok. <Link href="/sources">Kaynaklar</Link>{" "}
          sayfasından başlatın.
        </p>
      )}
      {live.intake_runs.map((run) => (
        <div key={run.id} className="detail-card">
          <strong>
            <Link href={`/calisma/${run.id}`}>{run.source_name}</Link>
          </strong>{" "}
          <span
            className="badge"
            data-tone={run.status === "running" ? "ok" : "warn"}
          >
            {trLabel(run.status).toLocaleUpperCase("tr-TR")}
          </span>
          <dl className="ops-facts">
            <div>
              <dt>Keşfedilen</dt>
              <dd>{run.discovered_new + run.rediscovered}</dd>
            </div>
            <div>
              <dt>Uygun</dt>
              <dd>{run.prefilter_accepted}</dd>
            </div>
            <div>
              <dt>Getirilen</dt>
              <dd>
                {run.fetched} / {run.fetch_dispatched}
              </dd>
            </div>
            <div>
              <dt>Fırsat</dt>
              <dd>{run.opportunities_created}</dd>
            </div>
          </dl>
          {stageMap[run.id] !== undefined && (
            <LineStageList
              stages={stageMap[run.id] ?? []}
              label={`${run.source_name} aşamaları`}
            />
          )}
        </div>
      ))}
    </section>
  );
}

function wordTone(item: LineItem): string {
  if (item.state === "blocked") {
    return "bad";
  }
  if (item.autopilot === null) {
    return "neutral";
  }
  switch (item.autopilot.kind) {
    case "action":
      return "ok";
    case "waiting":
      return "warn";
    case "error":
      return "bad";
    default:
      return "neutral";
  }
}

function wordText(item: LineItem): string {
  if (item.state === "blocked") {
    return item.blocked_reason ?? "engellendi";
  }
  if (item.autopilot === null) {
    return "otopilot henüz bakmadı";
  }
  const { kind, action, reason } = item.autopilot;
  if (kind === "action") {
    return `${action}: ${reason ?? ""}`.trim();
  }
  if (kind === "waiting") {
    return `bekliyor — ${reason ?? action}`;
  }
  if (kind === "error") {
    return `hata — ${action}`;
  }
  return reason ?? action ?? kind;
}

function LineCard({ items }: { items: LineItem[] }) {
  return (
    <section className="ops-card" data-span="8" aria-labelledby="ops-line">
      <h2 id="ops-line">Editoryal hat</h2>
      {items.length === 0 && <p className="muted">Hatta iş öğesi yok.</p>}
      {items.length > 0 && (
        <div className="table-scroll">
          <table className="ops-line">
            <thead>
              <tr>
                <th scope="col">İş öğesi</th>
                <th scope="col">Aşama</th>
                <th scope="col">Otopilotun son sözü</th>
                <th scope="col">Ne zaman</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.work_item_id}>
                  <td>
                    <Link href={`/editorial/${item.work_item_id}`}>
                      {item.title}
                    </Link>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={item.state === "blocked" ? "bad" : "info"}
                    >
                      {trLabel(item.state)}
                    </span>
                  </td>
                  <td>
                    <span className="badge" data-tone={wordTone(item)}>
                      {wordText(item)}
                    </span>
                  </td>
                  <td>
                    {item.autopilot !== null
                      ? shortTime(item.autopilot.at)
                      : shortTime(item.entered_at)}
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

function FeedCard({ feed }: { feed: FeedEntry[] }) {
  return (
    <section className="ops-card" data-span="12" aria-labelledby="ops-feed">
      <h2 id="ops-feed">Akış</h2>
      {feed.length === 0 && <p className="muted">Henüz olay yok.</p>}
      <ul className="ops-feed">
        {feed.map((entry, index) => (
          <li key={`${entry.at}-${index}`} data-tone={entry.tone}>
            <time dateTime={entry.at}>{shortTime(entry.at)}</time>
            <span>
              {entry.title !== null && entry.work_item_id !== null && (
                <>
                  <Link href={`/editorial/${entry.work_item_id}`}>
                    {entry.title}
                  </Link>
                  {" · "}
                </>
              )}
              {entry.summary}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default async function LiveOperationsPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchLiveOperations();
  const stageMap =
    result.kind === "ok"
      ? await lineStagesForRuns(result.data.intake_runs)
      : {};
  return (
    <section className="panel panel-wide" aria-labelledby="ops-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Keşiften yayına</p>
          <h1 id="ops-title">Canlı Operasyon</h1>
          <p className="muted">
            Keşif, fırsat, fikir, kanıt, brief, taslak, editör, kalite ve yayın
            tek ekranda. Otopilot neyi ilerletti, neyi neden bekliyor, yapay
            zeka köprüsü ne durumda.
          </p>
        </div>
        <AutoRefresh generatedAt={new Date().toISOString()} intervalMs={5000} />
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      {result.kind !== "ok" && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      {result.kind === "ok" && (
        <div className="ops-grid">
          <ModeCard live={result.data} />
          <GatewayCard gateway={result.data.gateway} />
          <LineCard items={result.data.items} />
          <IntakeCard live={result.data} stageMap={stageMap} />
          <BrowserCard gateway={result.data.gateway} />
          <FeedCard feed={result.data.feed} />
        </div>
      )}
    </section>
  );
}
