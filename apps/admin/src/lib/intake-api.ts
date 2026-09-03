import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// Intake runs: the durable "what happened after I pressed start" record.
// Reads are bounded projections; the controls are audited run-lifecycle
// commands that never touch editorial workflow state.

export const RUN_STATUSES = [
  "running",
  "paused",
  "completed",
  "stopped",
  "failed",
] as const;

const timestampSchema = z.string().min(1);

const runSchema = z.object({
  id: z.string().uuid(),
  source_id: z.string().uuid(),
  source_slug: z.string(),
  source_name: z.string(),
  status: z.enum(RUN_STATUSES),
  discovered_new: z.number().int(),
  rediscovered: z.number().int(),
  prefilter_accepted: z.number().int(),
  prefilter_rejected: z.number().int(),
  fetch_dispatched: z.number().int(),
  fetched: z.number().int(),
  fetch_failed: z.number().int(),
  promotions_dispatched: z.number().int(),
  opportunities_created: z.number().int(),
  remaining_accepted: z.number().int(),
  remaining_discovered: z.number().int(),
  policy: z.record(z.string(), z.unknown()),
  failure_note: z.string().nullable(),
  created_at: timestampSchema,
  discovery_completed_at: timestampSchema.nullable(),
  prefilter_completed_at: timestampSchema.nullable(),
  finished_at: timestampSchema.nullable(),
  updated_at: timestampSchema,
  last_event_at: timestampSchema.nullable(),
});

const stageSchema = z.object({
  key: z.enum([
    "discovery",
    "prefilter",
    "fetch",
    "normalize",
    "duplicate",
    "promote",
  ]),
  state: z.enum(["done", "active", "pending"]),
  counts: z.record(z.string(), z.number().int()),
});

const eventSchema = z.object({
  id: z.number().int(),
  stage: z.string(),
  kind: z.string(),
  detail: z.record(z.string(), z.unknown()),
  occurred_at: timestampSchema,
});

const runsPageSchema = z.object({
  generated_at: timestampSchema,
  runs: z.array(runSchema),
});

const chainSchema = z.object({
  normalized_succeeded: z.number().int(),
  normalized_failed: z.number().int(),
  duplicates_evaluated: z.number().int(),
  last_processed_title: z.string().nullable(),
  last_processed_url: z.string().nullable(),
});

const runDetailSchema = z.object({
  generated_at: timestampSchema,
  run: runSchema,
  chain: chainSchema,
  stages: z.array(stageSchema),
  events: z.array(eventSchema),
});

const runStartedSchema = z.object({
  status: z.literal("started"),
  run_id: z.string().uuid(),
});

const runControlSchema = z.object({
  status: z.literal("updated"),
  run_id: z.string().uuid(),
  run_status: z.enum(RUN_STATUSES),
});

export type IntakeRunView = z.infer<typeof runSchema>;
export type IntakeStageView = z.infer<typeof stageSchema>;
export type IntakeChainView = z.infer<typeof chainSchema>;
export type IntakeEventView = z.infer<typeof eventSchema>;
export type IntakeRunsPage = z.infer<typeof runsPageSchema>;
export type IntakeRunDetail = z.infer<typeof runDetailSchema>;

export async function fetchIntakeRuns(
  sourceId?: string,
): Promise<BackendResult<IntakeRunsPage>> {
  const suffix =
    sourceId !== undefined ? `?source_id=${encodeURIComponent(sourceId)}` : "";
  const response = await requestBackend(`/internal/intake/runs${suffix}`);
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, runsPageSchema, [200]);
}

export type IntakeRunDetailResult =
  BackendResult<IntakeRunDetail> | { kind: "not_found" };

export async function fetchIntakeRunDetail(
  runId: string,
): Promise<IntakeRunDetailResult> {
  const response = await requestBackend(
    `/internal/intake/runs/${encodeURIComponent(runId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, runDetailSchema, [200]);
}

export type IntakeControlResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "invalid" }
  | { kind: "conflict" }
  | { kind: "not_found" }
  | { kind: "queue_failed" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

async function postIntake<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<IntakeControlResult<T>> {
  const response = await requestBackend(path, {
    method: "POST",
    jsonBody: body,
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  if (response.status === 409) {
    return { kind: "conflict" };
  }
  if (response.status === 422) {
    return { kind: "invalid" };
  }
  if (response.status === 503) {
    return { kind: "queue_failed" };
  }
  const parsed = await parseBackendResponse(response, schema, [200]);
  if (parsed.kind === "ok") {
    return { kind: "ok", data: parsed.data };
  }
  return { kind: parsed.kind === "unreachable" ? "unreachable" : "malformed" };
}

export async function startIntakeRun(
  sourceId: string,
): Promise<IntakeControlResult<z.infer<typeof runStartedSchema>>> {
  return postIntake(
    `/internal/intake/sources/${encodeURIComponent(sourceId)}/runs`,
    {},
    runStartedSchema,
  );
}

export async function controlIntakeRun(
  runId: string,
  action: "pause" | "resume" | "stop",
  reason: string,
): Promise<IntakeControlResult<z.infer<typeof runControlSchema>>> {
  return postIntake(
    `/internal/intake/runs/${encodeURIComponent(runId)}/${action}`,
    { reason },
    runControlSchema,
  );
}
