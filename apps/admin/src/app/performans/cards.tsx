import Link from "next/link";
import type { ReactNode } from "react";

import { freshnessLabel } from "@/lib/freshness";
import {
  assessmentTone,
  numberOrUnknown,
  pctOrUnknown,
  positionOrUnknown,
  type ProviderFreshness,
  type PublishedContentRow,
  type RefreshOpportunity,
  type StrategySuggestion,
} from "@/lib/performance-api";
import { trLabel } from "@/lib/tr-labels";
import { decideRefreshAction, decideSuggestionAction } from "./actions";

// Shared building blocks of the performance pages. Every value shown is a
// durable backend fact; absent data reads "Bilinmiyor" / "Yetersiz veri".

export const PROVIDER_SHORT: Record<ProviderFreshness["provider"], string> = {
  google_search_console: "Search Console",
  google_analytics: "GA4",
  semrush: "Semrush",
  google_trends: "Google Trends",
  pinterest_trends: "Pinterest",
};

// "son veri 2026-09-03", "Yapılandırılmadı", "API erişimi gerekli",
// "... · eski veri" — the shared freshness vocabulary in date mode.
export function freshnessText(
  row: ProviderFreshness,
  now = new Date(),
): string {
  return freshnessLabel({
    provider: row.provider,
    state: row.state,
    observedAt: row.last_observed_at,
    now,
    mode: "date",
  });
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="empty-note" role="status">
      {children}
    </p>
  );
}

export function ContentList({
  rows,
  empty,
}: {
  rows: PublishedContentRow[];
  empty: string;
}) {
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  return (
    <ul className="strategy-list performance-list">
      {rows.map((row) => (
        <li key={row.published_content_id}>
          <Link href={`/performans/${row.work_item_id}`}>
            <strong>{row.title_working_label}</strong>
          </Link>
          <span
            className="badge"
            data-tone={assessmentTone(row.assessment?.status)}
          >
            {trLabel(row.assessment?.status)}
          </span>
          <span>{row.cluster_name ?? "Küme atanmadı"}</span>
          <span>
            Gösterim {numberOrUnknown(row.impressions)} · Tıklama{" "}
            {numberOrUnknown(row.clicks)} · Pozisyon{" "}
            {positionOrUnknown(row.position)} · Değişim{" "}
            {pctOrUnknown(row.impressions_pct)}
          </span>
          <span>{row.age_days} gündür yayında</span>
          {row.canonical_url_missing && (
            <span className="muted">Yayın adresi bilinmiyor</span>
          )}
          {row.has_open_refresh && (
            <span className="badge" data-tone="warn">
              Güncelleme kararı bekliyor
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function DecisionForm({
  action,
  hidden,
  approveLabel,
  approveValue,
  skipLabel,
  skipValue,
  reasonLabel,
  returnTo,
}: {
  action: (formData: FormData) => Promise<void>;
  hidden: Record<string, string>;
  approveLabel: string;
  approveValue: string;
  skipLabel: string;
  skipValue: string;
  reasonLabel: string;
  returnTo: string;
}) {
  return (
    <form action={action} className="control-form">
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <input type="hidden" name="return_to" value={returnTo} />
      <input
        type="text"
        name="reason"
        required
        placeholder="gerekçe (zorunlu)"
        aria-label={reasonLabel}
      />
      <button type="submit" name="action" value={approveValue}>
        {approveLabel}
      </button>
      <button
        type="submit"
        name="action"
        value={skipValue}
        className="secondary"
      >
        {skipLabel}
      </button>
    </form>
  );
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function RefreshCard({
  row,
  returnTo = "/performans",
}: {
  row: RefreshOpportunity;
  returnTo?: string;
}) {
  const movement = row.diagnosis.position_movement as
    { previous?: unknown; current?: unknown } | undefined;
  const changes = row.diagnosis.query_changes as
    { available?: boolean; lost_queries?: string[] } | undefined;
  const newSignals = Array.isArray(row.diagnosis.new_signals)
    ? row.diagnosis.new_signals.length
    : 0;
  return (
    <article className="detail-card" aria-label={row.title_working_label}>
      <h3>
        <Link href={`/performans/${row.work_item_id}`}>
          {row.title_working_label}
        </Link>
      </h3>
      <p>
        <span className="badge" data-tone="warn">
          {trLabel(row.status)}
        </span>{" "}
        {row.window_days !== null ? `${row.window_days} günlük pencere · ` : ""}
        Pozisyon {positionOrUnknown(asNumber(movement?.previous))} →{" "}
        {positionOrUnknown(asNumber(movement?.current))} · Gösterim{" "}
        {pctOrUnknown(asNumber(row.diagnosis.impressions_pct))} · Yeni sinyal{" "}
        {newSignals}
      </p>
      {changes?.available === true &&
        (changes.lost_queries?.length ?? 0) > 0 && (
          <p>Kaybedilen sorgular: {changes.lost_queries?.join(", ")}</p>
        )}
      <p>{row.recommendation}</p>
      {row.status === "proposed" ? (
        <DecisionForm
          action={decideRefreshAction}
          hidden={{ refresh_id: row.id }}
          approveLabel="Güncellemeyi Onayla"
          approveValue="approve"
          skipLabel="Şimdilik Geç"
          skipValue="dismiss"
          reasonLabel={`${row.title_working_label} güncelleme gerekçesi`}
          returnTo={returnTo}
        />
      ) : (
        <p className="muted">
          {trLabel(row.status)}
          {row.decided_by_display_name
            ? ` · ${row.decided_by_display_name}`
            : ""}
          {row.decision_reason ? ` · ${row.decision_reason}` : ""}
        </p>
      )}
    </article>
  );
}

export function SuggestionCard({
  row,
  returnTo = "/performans",
}: {
  row: StrategySuggestion;
  returnTo?: string;
}) {
  return (
    <article className="detail-card" aria-label={row.title}>
      <h3>{row.title}</h3>
      <p>
        <span className="badge" data-tone="info">
          {trLabel(row.kind)}
        </span>{" "}
        {row.rationale}
      </p>
      {row.status === "proposed" ? (
        <DecisionForm
          action={decideSuggestionAction}
          hidden={{ suggestion_id: row.id }}
          approveLabel="Stratejiye Ekle"
          approveValue="accept"
          skipLabel="Yoksay"
          skipValue="ignore"
          reasonLabel={`${row.title} karar gerekçesi`}
          returnTo={returnTo}
        />
      ) : (
        <p className="muted">
          {trLabel(row.status)}
          {row.decided_by_display_name
            ? ` · ${row.decided_by_display_name}`
            : ""}
        </p>
      )}
    </article>
  );
}
