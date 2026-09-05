import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";
import { intakeRunSchema } from "@/lib/intake-api";
import { WORKFLOW_STATES } from "@/lib/editorial-api";

// Live operations (ADR 0012): one read for the whole line, plus the
// autopilot mode command. The gateway admin token never reaches here —
// the backend reads the gateway server-side and returns a bounded view.

export const AUTOPILOT_MODES = ["off", "supervised", "autonomous"] as const;
export type AutopilotMode = (typeof AUTOPILOT_MODES)[number];

export const AUTOPILOT_MODE_LABELS: Record<AutopilotMode, string> = {
  off: "Kapalı",
  supervised: "Denetimli",
  autonomous: "Otonom",
};

export const AUTOPILOT_MODE_HINTS: Record<AutopilotMode, string> = {
  off: "Her adım elle tetiklenir.",
  supervised:
    "Makine her çıktıyı kendiliğinden üretir; fikir seçimi, brief ve editör kabulü, görsel bağlama, nihai onay ve yayın sende kalır.",
  autonomous:
    "Kabuller de otopilotta: en iyi fikir seçilir, brief ve geçen değerlendirme kabul edilir, düzelt kararı sınırlı yeniden çalışmaya gider, onaydan sonra paket-zamanlama-yayın kendiliğinden. Nihai onay yine sende (ADR 0004).",
};

const autopilotEventKindSchema = z.enum([
  "mode_changed",
  "action",
  "waiting",
  "skipped",
  "error",
]);

const autopilotWordSchema = z.object({
  kind: autopilotEventKindSchema,
  action: z.string().nullable(),
  reason: z.string().nullable(),
  at: z.string(),
});

const lineItemSchema = z.object({
  work_item_id: z.string().uuid(),
  title: z.string(),
  state: z.enum(WORKFLOW_STATES),
  entered_at: z.string(),
  blocked_reason: z.string().nullable(),
  autopilot: autopilotWordSchema.nullable(),
});

const feedEntrySchema = z.object({
  at: z.string(),
  source: z.enum(["autopilot", "workflow", "ai"]),
  work_item_id: z.string().uuid().nullable(),
  title: z.string().nullable(),
  summary: z.string(),
  tone: z.enum(["ok", "warn", "bad", "info"]),
});

const gatewayAccountSchema = z.object({
  id: z.string(),
  provider: z.string(),
  label: z.string(),
  enabled: z.boolean(),
  blocked_by: z.string().nullable(),
  busy: z.boolean(),
});

const gatewayJobSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  phase: z.string().nullable(),
  model: z.string().nullable(),
  job_type: z.string().nullable(),
  started_at: z.string().nullable(),
});

const gatewaySchema = z.object({
  configured: z.boolean(),
  reachable: z.boolean(),
  status: z.string().nullable(),
  provider: z.string(),
  base_url_host: z.string().nullable(),
  accounts: z.array(gatewayAccountSchema),
  queued: z.number().int().nullable(),
  running: z.number().int().nullable(),
  ready_accounts: z.number().int().nullable(),
  jobs: z.array(gatewayJobSchema),
  error: z.string().nullable(),
});

const autopilotViewSchema = z.object({
  mode: z.enum(AUTOPILOT_MODES),
  actor_display_name: z.string().nullable(),
  reason: z.string().nullable(),
  updated_at: z.string().nullable(),
});

const liveOperationsSchema = z.object({
  generated_at: z.string(),
  autopilot: autopilotViewSchema,
  intake_runs: z.array(intakeRunSchema),
  items: z.array(lineItemSchema),
  feed: z.array(feedEntrySchema),
  gateway: gatewaySchema,
});

const autopilotStateSchema = z.object({
  mode: z.enum(AUTOPILOT_MODES),
  actor_user_id: z.string().uuid().nullable(),
  actor_display_name: z.string().nullable(),
  reason: z.string().nullable(),
  updated_at: z.string().nullable(),
  events: z.array(
    z.object({
      id: z.string().uuid(),
      work_item_id: z.string().uuid().nullable(),
      kind: autopilotEventKindSchema,
      action: z.string().nullable(),
      mode: z.enum(AUTOPILOT_MODES),
      detail: z.record(z.string(), z.unknown()),
      created_at: z.string(),
    }),
  ),
});

export type LiveOperations = z.infer<typeof liveOperationsSchema>;
export type LineItem = z.infer<typeof lineItemSchema>;
export type FeedEntry = z.infer<typeof feedEntrySchema>;
export type GatewayView = z.infer<typeof gatewaySchema>;
export type AutopilotState = z.infer<typeof autopilotStateSchema>;

export async function fetchLiveOperations(): Promise<
  BackendResult<LiveOperations>
> {
  const response = await requestBackend("/internal/operations/live");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, liveOperationsSchema, [200]);
}

export type ModeCommandResult =
  | { kind: "ok"; data: AutopilotState }
  | { kind: "invalid" }
  | { kind: "queue_failed" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

// A NAMED decision: the backend records the operator as accountable for
// every acceptance the autopilot makes while the mode is on.
export async function setAutopilotMode(
  mode: AutopilotMode,
  reason: string,
): Promise<ModeCommandResult> {
  const response = await requestBackend("/internal/autopilot/mode", {
    method: "PUT",
    jsonBody: { mode, reason },
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 422) {
    return { kind: "invalid" };
  }
  if (response.status === 503) {
    return { kind: "queue_failed" };
  }
  const parsed = await parseBackendResponse(
    response,
    autopilotStateSchema,
    [200],
  );
  if (parsed.kind !== "ok") {
    return parsed;
  }
  return { kind: "ok", data: parsed.data };
}
