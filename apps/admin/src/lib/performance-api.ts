import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// Performance loop (Measure -> Learn -> Improve). Every number here is a
// durable backend observation or classification; absent provider data is
// null / "unknown" / "insufficient_data" and is rendered as such — never as
// a zero. The only mutations are named, reasoned decisions and the manual
// "sync now" trigger.

export const PERFORMANCE_WINDOWS = [7, 28, 90] as const;
export type PerformanceWindow = (typeof PERFORMANCE_WINDOWS)[number];

export const ASSESSMENT_STATUSES = [
  "insufficient_data",
  "rising",
  "stable",
  "declining",
  "volatile",
  "unknown",
] as const;
export type AssessmentStatus = (typeof ASSESSMENT_STATUSES)[number];

export const PERFORMANCE_PROVIDERS = [
  "google_search_console",
  "google_analytics",
  "semrush",
  "google_trends",
  "pinterest_trends",
] as const;
export type PerformanceProvider = (typeof PERFORMANCE_PROVIDERS)[number];

export const REFRESH_STATUSES = [
  "proposed",
  "approved",
  "dismissed",
  "superseded",
] as const;
export const SUGGESTION_KINDS = [
  "cluster_focus",
  "keyword_add",
  "audience_focus",
  "theme_focus",
] as const;
export const SUGGESTION_STATUSES = ["proposed", "accepted", "ignored"] as const;

const timestampSchema = z.string().min(1);
const jsonRecordSchema = z.record(z.string(), z.unknown());

const assessmentSchema = z.object({
  id: z.string().uuid(),
  window_days: z.number().int(),
  status: z.enum(ASSESSMENT_STATUSES),
  assessed_at: timestampSchema,
  engine_name: z.string(),
  engine_version: z.string(),
  basis: jsonRecordSchema,
});

const contentRowSchema = z.object({
  published_content_id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  title_working_label: z.string(),
  current_state: z.string(),
  canonical_url: z.string().nullable(),
  canonical_url_missing: z.boolean(),
  remote_publication_ref: z.string(),
  published_at: timestampSchema,
  age_days: z.number().int(),
  topic_cluster_id: z.string().uuid().nullable(),
  cluster_name: z.string().nullable(),
  audience_id: z.string().uuid().nullable(),
  audience_name: z.string().nullable(),
  theme_key: z.string().nullable(),
  content_format: z.string().nullable(),
  assessment: assessmentSchema.nullable(),
  impressions: z.number().int().nullable(),
  clicks: z.number().int().nullable(),
  position: z.number().nullable(),
  ctr: z.number().nullable(),
  impressions_pct: z.number().nullable(),
  clicks_pct: z.number().nullable(),
  has_open_refresh: z.boolean(),
});

const clusterSchema = z.object({
  cluster_id: z.string().uuid().nullable(),
  cluster_name: z.string(),
  published: z.number().int(),
  rising: z.number().int(),
  stable: z.number().int(),
  declining: z.number().int(),
  volatile: z.number().int(),
  new: z.number().int(),
  insufficient: z.number().int(),
  unknown: z.number().int(),
  sufficient: z.boolean(),
});

const totalsSchema = z.object({
  published: z.number().int(),
  rising: z.number().int(),
  stable: z.number().int(),
  declining: z.number().int(),
  volatile: z.number().int(),
  new: z.number().int(),
  insufficient: z.number().int(),
  unknown: z.number().int(),
});

const freshnessSchema = z.object({
  provider: z.enum(PERFORMANCE_PROVIDERS),
  last_observed_at: timestampSchema.nullable(),
  state: z.string().nullable(),
});

const overviewSchema = z.object({
  generated_at: timestampSchema,
  window_days: z.number().int(),
  totals: totalsSchema,
  rising: z.array(contentRowSchema),
  declining: z.array(contentRowSchema),
  stable: z.array(contentRowSchema),
  volatile: z.array(contentRowSchema),
  new: z.array(contentRowSchema),
  insufficient: z.array(contentRowSchema),
  clusters: z.array(clusterSchema),
  freshness: z.array(freshnessSchema),
  pending_refresh_decisions: z.number().int(),
  pending_strategy_suggestions: z.number().int(),
  schedule_enabled: z.boolean(),
});

const seriesPointSchema = z.object({
  period_start: z.string(),
  period_end: z.string(),
  observed_at: timestampSchema,
  metrics: jsonRecordSchema,
});

const refreshSchema = z.object({
  id: z.string().uuid(),
  published_content_id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  title_working_label: z.string(),
  current_state: z.string(),
  status: z.enum(REFRESH_STATUSES),
  trigger_assessment_id: z.string().uuid(),
  window_days: z.number().int().nullable(),
  diagnosis: jsonRecordSchema,
  recommendation: z.string(),
  proposed_at: timestampSchema,
  decided_at: timestampSchema.nullable(),
  decided_by_display_name: z.string().nullable(),
  decision_reason: z.string().nullable(),
});

const suggestionSchema = z.object({
  id: z.string().uuid(),
  kind: z.enum(SUGGESTION_KINDS),
  title: z.string(),
  rationale: z.string(),
  basis: jsonRecordSchema,
  status: z.enum(SUGGESTION_STATUSES),
  proposed_at: timestampSchema,
  decided_at: timestampSchema.nullable(),
  decided_by_display_name: z.string().nullable(),
  decision_reason: z.string().nullable(),
});

const detailSchema = z.object({
  content: contentRowSchema,
  assessments: z.array(assessmentSchema),
  search_console_daily: z.array(seriesPointSchema),
  search_console_summary: z.array(seriesPointSchema),
  top_queries: z.array(jsonRecordSchema),
  analytics: z.array(seriesPointSchema),
  google_trends: z.array(seriesPointSchema),
  pinterest_trends: z.array(seriesPointSchema),
  semrush: z.array(seriesPointSchema),
  refresh: refreshSchema.nullable(),
  refresh_history: z.array(refreshSchema),
  historical_signal: jsonRecordSchema,
});

const syncSchema = z.object({
  status: z.literal("queued"),
  backfilled_published: z.number().int(),
  tasks: z.array(z.string()),
});

export type AssessmentView = z.infer<typeof assessmentSchema>;
export type PublishedContentRow = z.infer<typeof contentRowSchema>;
export type ClusterOverview = z.infer<typeof clusterSchema>;
export type ProviderFreshness = z.infer<typeof freshnessSchema>;
export type PerformanceOverview = z.infer<typeof overviewSchema>;
export type SeriesPoint = z.infer<typeof seriesPointSchema>;
export type RefreshOpportunity = z.infer<typeof refreshSchema>;
export type StrategySuggestion = z.infer<typeof suggestionSchema>;
export type ContentPerformanceDetail = z.infer<typeof detailSchema>;
export type PerformanceSyncResponse = z.infer<typeof syncSchema>;

export function boundedWindow(
  raw: string | null | undefined,
): PerformanceWindow {
  const parsed = Number(raw);
  return (PERFORMANCE_WINDOWS as readonly number[]).includes(parsed)
    ? (parsed as PerformanceWindow)
    : 28;
}

export async function fetchPerformanceOverview(
  window: PerformanceWindow,
): Promise<BackendResult<PerformanceOverview>> {
  const response = await requestBackend(
    `/internal/performance/overview?window=${window}`,
  );
  if (response === null) return { kind: "unreachable" };
  return parseBackendResponse(response, overviewSchema, [200]);
}

export type DetailResult =
  BackendResult<ContentPerformanceDetail> | { kind: "not_found" };

export async function fetchContentPerformance(
  workItemId: string,
): Promise<DetailResult> {
  const response = await requestBackend(
    `/internal/performance/contents/${encodeURIComponent(workItemId)}`,
  );
  if (response === null) return { kind: "unreachable" };
  if (response.status === 404) return { kind: "not_found" };
  return parseBackendResponse(response, detailSchema, [200]);
}

export async function fetchRefreshOpportunities(
  status: (typeof REFRESH_STATUSES)[number] | null = "proposed",
): Promise<BackendResult<RefreshOpportunity[]>> {
  const query = status === null ? "" : `?status=${status}`;
  const response = await requestBackend(
    `/internal/performance/refresh-opportunities${query}`,
  );
  if (response === null) return { kind: "unreachable" };
  return parseBackendResponse(response, z.array(refreshSchema), [200]);
}

export async function fetchStrategySuggestions(
  status: (typeof SUGGESTION_STATUSES)[number] | null = "proposed",
): Promise<BackendResult<StrategySuggestion[]>> {
  const query = status === null ? "" : `?status=${status}`;
  const response = await requestBackend(
    `/internal/performance/strategy-suggestions${query}`,
  );
  if (response === null) return { kind: "unreachable" };
  return parseBackendResponse(response, z.array(suggestionSchema), [200]);
}

export type DecisionResult =
  | { kind: "ok" }
  | { kind: "unreachable" }
  | { kind: "not_found" }
  | { kind: "conflict" }
  | { kind: "invalid" }
  | { kind: "malformed" };

async function decide(path: string, reason: string): Promise<DecisionResult> {
  const response = await requestBackend(path, {
    method: "POST",
    jsonBody: { reason },
  });
  if (response === null) return { kind: "unreachable" };
  if (response.status === 200) return { kind: "ok" };
  if (response.status === 404) return { kind: "not_found" };
  if (response.status === 409) return { kind: "conflict" };
  if (response.status === 422) return { kind: "invalid" };
  return { kind: "malformed" };
}

export function decideRefresh(
  refreshId: string,
  action: "approve" | "dismiss",
  reason: string,
): Promise<DecisionResult> {
  return decide(
    `/internal/performance/refresh-opportunities/${encodeURIComponent(refreshId)}/${action}`,
    reason,
  );
}

export function decideSuggestion(
  suggestionId: string,
  action: "accept" | "ignore",
  reason: string,
): Promise<DecisionResult> {
  return decide(
    `/internal/performance/strategy-suggestions/${encodeURIComponent(suggestionId)}/${action}`,
    reason,
  );
}

export type SyncResult =
  | { kind: "ok"; data: PerformanceSyncResponse }
  | { kind: "unreachable" }
  | { kind: "queue_failed" }
  | { kind: "malformed" };

export async function triggerPerformanceSync(): Promise<SyncResult> {
  const response = await requestBackend("/internal/performance/sync", {
    method: "POST",
  });
  if (response === null) return { kind: "unreachable" };
  if (response.status === 503) return { kind: "queue_failed" };
  const parsed = await parseBackendResponse(response, syncSchema, [200]);
  return parsed.kind === "ok" ? { kind: "ok", data: parsed.data } : parsed;
}

// --- display helpers (pure; shared by the list and the detail page) ------

export function numberOrUnknown(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Bilinmiyor";
  }
  return new Intl.NumberFormat("tr-TR").format(value);
}

export function positionOrUnknown(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Bilinmiyor";
  }
  return value.toFixed(1);
}

export function pctOrUnknown(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Bilinmiyor";
  }
  const rounded = Math.round(value * 100);
  return `${rounded > 0 ? "+" : ""}%${rounded}`;
}

export function ratioOrUnknown(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Bilinmiyor";
  }
  return `%${(value * 100).toFixed(1)}`;
}

export function metricNumber(
  metrics: Record<string, unknown>,
  key: string,
): number | null {
  const raw = metrics[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

export function assessmentTone(
  status: AssessmentStatus | null | undefined,
): "ok" | "warn" | "bad" | "info" {
  switch (status) {
    case "rising":
      return "ok";
    case "declining":
      return "bad";
    case "volatile":
      return "warn";
    default:
      return "info";
  }
}
