import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// Intelligence-signal summary (agent B's read endpoint): per family, how
// many durable PII-free signals exist, how many occurrences and distinct
// sources back them, and when the last one was observed. A family with no
// rows simply has none — the operator reads "veri yok", never a strength.
// `runId` bounds the tallies to ONE intake run's own documents so a live
// run view never borrows another run's signals.

export const SIGNAL_FAMILIES = [
  "inspiration",
  "community_need",
  "market",
  "competition",
  "taxonomy",
  "search",
  "trend",
  "visual_trend",
  "historical_performance",
] as const;
export type SignalFamily = (typeof SIGNAL_FAMILIES)[number];

const familySummarySchema = z.object({
  family: z.enum(SIGNAL_FAMILIES),
  signal_count: z.number().int().nonnegative(),
  occurrence_total: z.number().int().nonnegative(),
  distinct_sources: z.number().int().nonnegative(),
  last_observed_at: z.string().min(1).nullable(),
});

const summarySchema = z.object({
  families: z.array(familySummarySchema),
  total_signals: z.number().int().nonnegative(),
  run_id: z.string().uuid().nullable().optional(),
  run_document_count: z.number().int().nonnegative().nullable().optional(),
});

export type FamilySummary = z.infer<typeof familySummarySchema>;
export type IntelligenceSummary = z.infer<typeof summarySchema>;

export type IntelligenceSummaryResult =
  BackendResult<IntelligenceSummary> | { kind: "not_found" };

export async function fetchIntelligenceSummary(
  runId?: string,
): Promise<IntelligenceSummaryResult> {
  const suffix =
    runId !== undefined ? `?run_id=${encodeURIComponent(runId)}` : "";
  const response = await requestBackend(
    `/internal/intelligence/summary${suffix}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, summarySchema, [200]);
}

export function familySummary(
  summary: IntelligenceSummary | null,
  family: SignalFamily,
): FamilySummary | null {
  if (summary === null) {
    return null;
  }
  return summary.families.find((entry) => entry.family === family) ?? null;
}
