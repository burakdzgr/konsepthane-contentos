import {
  ACCESS_REQUIRED_LABEL,
  NOT_CONFIGURED_LABEL,
  freshnessLabel,
  relativeAge,
} from "@/lib/freshness";
import type {
  IntakeChainView,
  IntakeRunView,
  IntakeStageView,
} from "@/lib/intake-api";
import {
  familySummary,
  type IntelligenceSummary,
  type SignalFamily,
} from "@/lib/intelligence-api";
import type { IntegrationView } from "@/lib/integrations-api";

// The operator's view of ONE run through the whole line, in the order the
// system works: source → URLs → prefilter → fetch → understand → ideas →
// grouping → community / market / strategy signals → Semrush / Google
// Trends / Pinterest Trends → Konsepthane's own history → opportunity.
//
// Every state is derived from durable data: intake stages from the run
// view, signal stages from the run-scoped intelligence summary, provider
// stages from the integrations board. A stage with nothing behind it says
// "veri yok" / "bekleniyor" — progress is never faked.

export type StageState = "done" | "active" | "pending" | "unavailable";

export type LineStage = {
  key: string;
  label: string;
  state: StageState;
  detail: string;
};

export type LineStageInput = {
  run: IntakeRunView;
  chain: IntakeChainView | null;
  stages: IntakeStageView[];
  // null: the summary could not be read (never treated as "no signals").
  signals: IntelligenceSummary | null;
  // null: the integrations board could not be read.
  integrations: IntegrationView[] | null;
  now?: Date;
};

const WAITING = "bekleniyor";
const NO_DATA = "veri yok";

function count(value: number | undefined): number {
  return value ?? 0;
}

function intakeStage(
  stages: IntakeStageView[],
  key: IntakeStageView["key"],
): IntakeStageView | null {
  return stages.find((stage) => stage.key === key) ?? null;
}

function intakeState(stage: IntakeStageView | null): StageState {
  return stage?.state ?? "pending";
}

function signalStage(
  key: string,
  label: string,
  family: SignalFamily,
  input: LineStageInput,
  live: boolean,
  now: Date,
): LineStage {
  if (input.signals === null) {
    return {
      key,
      label,
      state: "unavailable",
      detail: "sinyal özeti okunamadı",
    };
  }
  const entry = familySummary(input.signals, family);
  if (entry !== null && entry.signal_count > 0) {
    const age =
      entry.last_observed_at !== null
        ? ` · ${relativeAge(entry.last_observed_at, now)}`
        : "";
    return {
      key,
      label,
      state: "done",
      detail: `${entry.signal_count} sinyal · ${entry.distinct_sources} kaynak${age}`,
    };
  }
  return {
    key,
    label,
    state: live ? "pending" : "unavailable",
    detail: live ? WAITING : NO_DATA,
  };
}

function providerStage(
  key: string,
  label: string,
  provider: IntegrationView["name"],
  family: SignalFamily | null,
  input: LineStageInput,
  now: Date,
): LineStage {
  if (input.integrations === null) {
    return {
      key,
      label,
      state: "unavailable",
      detail: "sağlayıcı durumu okunamadı",
    };
  }
  const item = input.integrations.find((entry) => entry.name === provider);
  if (item === undefined) {
    return { key, label, state: "unavailable", detail: NOT_CONFIGURED_LABEL };
  }
  if (item.state === "not_configured") {
    return { key, label, state: "unavailable", detail: NOT_CONFIGURED_LABEL };
  }
  if (item.state === "access_required") {
    return {
      key,
      label,
      state: "unavailable",
      detail: "API erişimi bekleniyor",
    };
  }
  const stored =
    family !== null && input.signals !== null
      ? familySummary(input.signals, family)
      : null;
  const storedNote =
    stored !== null && stored.signal_count > 0
      ? `${stored.signal_count} kayıtlı gözlem · `
      : "";
  const freshness = freshnessLabel({
    provider,
    state: item.state,
    observedAt: item.freshness,
    now,
    cacheHours: item.cache_hours,
  });
  if (item.state === "healthy") {
    return {
      key,
      label,
      state: item.freshness === null ? "pending" : "done",
      detail: `${storedNote}${item.freshness === null ? `bağlı · ${WAITING}` : freshness}`,
    };
  }
  return {
    key,
    label,
    state: item.state === "rate_limited" ? "pending" : "unavailable",
    detail: `${storedNote}${freshness}`,
  };
}

export function buildLineStages(input: LineStageInput): LineStage[] {
  const now = input.now ?? new Date();
  const { run, chain, stages } = input;
  const live = run.status === "running" || run.status === "paused";
  const discovery = intakeStage(stages, "discovery");
  const prefilter = intakeStage(stages, "prefilter");
  const fetch = intakeStage(stages, "fetch");
  const normalize = intakeStage(stages, "normalize");
  const duplicate = intakeStage(stages, "duplicate");
  const promote = intakeStage(stages, "promote");
  const discovered = run.discovered_new + run.rediscovered;
  const fetchFailed = run.fetch_failed;
  const normalizedFailed = chain?.normalized_failed ?? 0;

  const sourceScan: LineStage = {
    key: "source",
    label: "Kaynak taranıyor",
    state:
      run.discovery_completed_at !== null
        ? "done"
        : intakeState(discovery) === "active"
          ? "active"
          : "pending",
    detail:
      run.discovery_completed_at !== null
        ? "site haritası / besleme okundu"
        : intakeState(discovery) === "active"
          ? "site haritası / besleme okunuyor"
          : WAITING,
  };
  const urls: LineStage = {
    key: "urls",
    label: "URL'ler keşfediliyor",
    state: intakeState(discovery),
    detail:
      discovered > 0
        ? `${discovered} URL · ${run.discovered_new} yeni, ${run.rediscovered} bilinen`
        : WAITING,
  };
  const prefilterStage: LineStage = {
    key: "prefilter",
    label: "Ön eleme",
    state: intakeState(prefilter),
    detail:
      run.prefilter_accepted + run.prefilter_rejected > 0
        ? `${run.prefilter_accepted} uygun · ${run.prefilter_rejected} elendi`
        : WAITING,
  };
  const fetchStage: LineStage = {
    key: "fetch",
    label: "İçerikler getiriliyor",
    state: intakeState(fetch),
    detail:
      run.fetch_dispatched > 0
        ? `${run.fetched} / ${run.fetch_dispatched} sayfa${fetchFailed > 0 ? ` · ${fetchFailed} hata` : ""}`
        : WAITING,
  };
  const normalized =
    chain?.normalized_succeeded ?? count(normalize?.counts["succeeded"]);
  const understand: LineStage = {
    key: "understand",
    label: "İçerik anlaşılıyor",
    state: intakeState(normalize),
    detail:
      normalized + normalizedFailed > 0
        ? `${normalized} içerik${normalizedFailed > 0 ? ` · ${normalizedFailed} hata` : ""}`
        : WAITING,
  };
  const ideas: LineStage = {
    key: "ideas",
    label: "Fikirler çıkarılıyor",
    state:
      run.promotions_dispatched > 0
        ? intakeState(promote) === "pending"
          ? "active"
          : intakeState(promote)
        : "pending",
    detail:
      run.promotions_dispatched > 0
        ? `${run.promotions_dispatched} içerikten fikir çıkarılıyor`
        : WAITING,
  };
  const evaluated =
    chain?.duplicates_evaluated ?? count(duplicate?.counts["evaluated"]);
  const grouping: LineStage = {
    key: "grouping",
    label: "Benzer fikirler gruplanıyor",
    state: intakeState(duplicate),
    detail: evaluated > 0 ? `${evaluated} içerik karşılaştırıldı` : WAITING,
  };
  const opportunity: LineStage = {
    key: "opportunity",
    label: "Fırsat",
    state: intakeState(promote),
    detail:
      run.opportunities_created > 0
        ? `${run.opportunities_created} fırsat oluştu`
        : WAITING,
  };

  const searchConsole =
    input.integrations?.find(
      (entry) => entry.name === "google_search_console",
    ) ?? null;
  const history = familySummary(input.signals, "historical_performance");
  const historyStage: LineStage =
    history !== null && history.signal_count > 0
      ? {
          key: "history",
          label: "Konsepthane geçmiş verisi",
          state: "done",
          detail: `${history.signal_count} geçmiş sinyal${history.last_observed_at !== null ? ` · ${relativeAge(history.last_observed_at, now)}` : ""}`,
        }
      : input.integrations === null
        ? {
            key: "history",
            label: "Konsepthane geçmiş verisi",
            state: "unavailable",
            detail: "sağlayıcı durumu okunamadı",
          }
        : searchConsole === null || searchConsole.state === "not_configured"
          ? {
              key: "history",
              label: "Konsepthane geçmiş verisi",
              state: "unavailable",
              detail: `Search Console · ${NOT_CONFIGURED_LABEL}`,
            }
          : searchConsole.state === "access_required"
            ? {
                key: "history",
                label: "Konsepthane geçmiş verisi",
                state: "unavailable",
                detail: `Search Console · ${ACCESS_REQUIRED_LABEL}`,
              }
            : {
                key: "history",
                label: "Konsepthane geçmiş verisi",
                state: searchConsole.freshness === null ? "pending" : "done",
                detail: `Search Console · ${freshnessLabel({
                  provider: "google_search_console",
                  state: searchConsole.state,
                  observedAt: searchConsole.freshness,
                  now,
                  cacheHours: searchConsole.cache_hours,
                  mode: "date",
                })}`,
              };

  return [
    sourceScan,
    urls,
    prefilterStage,
    fetchStage,
    understand,
    ideas,
    grouping,
    signalStage(
      "community",
      "Topluluk sinyali",
      "community_need",
      input,
      live,
      now,
    ),
    signalStage("market", "Pazar sinyali", "competition", input, live, now),
    signalStage("strategy", "Strateji eşleşmesi", "market", input, live, now),
    providerStage("semrush", "Semrush", "semrush", "search", input, now),
    providerStage(
      "google-trends",
      "Google Trends",
      "google_trends",
      "trend",
      input,
      now,
    ),
    providerStage(
      "pinterest",
      "Pinterest Trends",
      "pinterest_trends",
      "visual_trend",
      input,
      now,
    ),
    historyStage,
    opportunity,
  ];
}

const STATE_LABELS: Record<StageState, string> = {
  done: "tamamlandı",
  active: "sürüyor",
  pending: "bekliyor",
  unavailable: "veri yok",
};

export function LineStageList({
  stages,
  label = "Hat aşamaları",
}: {
  stages: LineStage[];
  label?: string;
}) {
  return (
    <ol className="stage-list" aria-label={label}>
      {stages.map((stage, index) => (
        <li key={stage.key} data-state={stage.state}>
          <span className="stage-node" aria-hidden="true">
            {stage.state === "done" ? "✓" : index + 1}
          </span>
          <span className="stage-copy">
            <span className="stage-label">{stage.label}</span>
            <small className="stage-detail">{stage.detail}</small>
          </span>
          <span className="stage-state">{STATE_LABELS[stage.state]}</span>
        </li>
      ))}
    </ol>
  );
}

export function stageProgress(stages: LineStage[]): number {
  const done = stages.filter((stage) => stage.state === "done").length;
  const active = stages.some((stage) => stage.state === "active") ? 0.5 : 0;
  return Math.round(((done + active) / Math.max(stages.length, 1)) * 100);
}
