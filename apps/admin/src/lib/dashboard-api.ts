import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";
import { WORKFLOW_STATES } from "@/lib/editorial-api";

// Bounded read models for the control center plus the audited intake
// pause/resume commands. Every value is durable backend state; the only
// mutation is the pause control, which gates NEW dispatch server-side.

export const PAUSE_SCOPES = [
  "engine",
  "research",
  "opportunity",
  "ideas",
  "evidence",
  "intent",
  "brief",
  "writer",
  "editor",
  "qa",
  "media",
  "publisher",
] as const;

export type PauseScope = (typeof PAUSE_SCOPES)[number];

export const AGENT_KEYS = [
  "research",
  "opportunity",
  "ideas",
  "evidence",
  "intent",
  "brief",
  "writer",
  "editor",
  "qa",
  "media",
  "publisher",
] as const;

export type AgentKey = (typeof AGENT_KEYS)[number];

const timestampSchema = z.string().min(1);

const pauseStateSchema = z.object({
  scope: z.enum(PAUSE_SCOPES),
  is_paused: z.boolean(),
  reason: z.string().nullable(),
  updated_at: timestampSchema.nullable(),
});

const summarySchema = z.object({
  generated_at: timestampSchema,
  work_item_states: z.record(z.string(), z.number().int()),
  published_today: z.number().int(),
  active_intake_runs: z.number().int(),
  attention: z.object({
    production_decisions: z.number().int(),
    awaiting_human_review: z.number().int(),
    approval_expired: z.number().int(),
    changes_requested: z.number().int(),
    // Performance loop (agent E); absent on older backends -> not shown.
    refresh_decisions: z.number().int().optional(),
    strategy_suggestions: z.number().int().optional(),
  }),
  research: z.object({
    active_sources: z.number().int(),
    discovery_states: z.record(z.string(), z.number().int()),
  }),
  ai: z.object({
    attempts_today: z.number().int(),
    failures_today: z.number().int(),
    daily_budget: z.number().int().nullable(),
    remaining_budget: z.number().int().nullable(),
    provider: z.string(),
    text_provider_configured: z.boolean(),
    image_provider_configured: z.boolean(),
  }),
  publishing: z.object({
    packages_total: z.number().int(),
    attempts_today: z.record(z.string(), z.number().int()),
    last_attempt_status: z.string().nullable(),
    last_attempt_error_class: z.string().nullable(),
    last_attempt_at: timestampSchema.nullable(),
  }),
  media: z.object({
    assets_total: z.number().int(),
    assets_today: z.number().int(),
    active_satisfactions: z.number().int(),
  }),
  queue: z.object({ depth: z.number().int().nullable() }),
  pauses: z.array(pauseStateSchema),
});

const attemptSchema = z.object({
  id: z.string().uuid(),
  purpose: z.string(),
  status: z.string(),
  error_class: z.string().nullable(),
  provider: z.string(),
  model_name: z.string(),
  retry_number: z.number().int(),
  created_at: timestampSchema,
});

const agentSchema = z.object({
  key: z.enum(AGENT_KEYS),
  kind: z.enum(["ai", "deterministic", "transport"]),
  purposes: z.array(z.string()),
  is_paused: z.boolean(),
  pause_reason: z.string().nullable(),
  attempts_today: z.number().int(),
  failures_today: z.number().int(),
  last_attempt: attemptSchema.nullable(),
  recent_attempts: z.array(attemptSchema),
  metrics: z.record(z.string(), z.number().int()),
});

const agentsPageSchema = z.object({
  generated_at: timestampSchema,
  engine_paused: z.boolean(),
  engine_pause_reason: z.string().nullable(),
  agents: z.array(agentSchema),
});

const activityEntrySchema = z.object({
  kind: z.enum(["workflow", "publication", "pause"]),
  occurred_at: timestampSchema,
  work_item_id: z.string().uuid().nullable(),
  title: z.string().nullable(),
  from_state: z.string().nullable(),
  to_state: z.string().nullable(),
  actor_origin: z.string().nullable(),
  status: z.string().nullable(),
  error_class: z.string().nullable(),
  scope: z.string().nullable(),
  action: z.string().nullable(),
  reason: z.string().nullable(),
});

const activityPageSchema = z.object({
  generated_at: timestampSchema,
  entries: z.array(activityEntrySchema),
});

const publicationRowSchema = z.object({
  package_id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  title_working_label: z.string(),
  work_item_state: z.enum(WORKFLOW_STATES),
  version: z.number().int(),
  section_count: z.number().int(),
  manifest_needs: z.number().int(),
  created_at: timestampSchema,
  attempts_total: z.number().int(),
  last_attempt_status: z.string().nullable(),
  last_attempt_error_class: z.string().nullable(),
  last_attempt_at: timestampSchema.nullable(),
  remote_publication_ref: z.string().nullable(),
});

const publicationsPageSchema = z.object({
  generated_at: timestampSchema,
  rows: z.array(publicationRowSchema),
});

const pauseEventSchema = z.object({
  scope: z.enum(PAUSE_SCOPES),
  action: z.string(),
  reason: z.string(),
  actor_display_name: z.string().nullable(),
  occurred_at: timestampSchema,
});

const controlsPageSchema = z.object({
  generated_at: timestampSchema,
  pauses: z.array(pauseStateSchema),
  recent_events: z.array(pauseEventSchema),
});

const pauseCommandResponseSchema = z.object({
  status: z.enum(["applied", "unchanged"]),
  scope: z.enum(PAUSE_SCOPES),
  is_paused: z.boolean(),
});

export type PauseStateView = z.infer<typeof pauseStateSchema>;
export type DashboardSummary = z.infer<typeof summarySchema>;
export type AgentView = z.infer<typeof agentSchema>;
export type AgentsPage = z.infer<typeof agentsPageSchema>;
export type ActivityEntry = z.infer<typeof activityEntrySchema>;
export type ActivityPage = z.infer<typeof activityPageSchema>;
export type PublicationQueueRow = z.infer<typeof publicationRowSchema>;
export type PublicationsPage = z.infer<typeof publicationsPageSchema>;
export type ControlsPage = z.infer<typeof controlsPageSchema>;
export type PauseCommandResponse = z.infer<typeof pauseCommandResponseSchema>;

export async function fetchDashboardSummary(): Promise<
  BackendResult<DashboardSummary>
> {
  const response = await requestBackend("/internal/dashboard/summary");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, summarySchema, [200]);
}

export async function fetchDashboardAgents(): Promise<
  BackendResult<AgentsPage>
> {
  const response = await requestBackend("/internal/dashboard/agents");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, agentsPageSchema, [200]);
}

export async function fetchDashboardActivity(
  limit = 30,
): Promise<BackendResult<ActivityPage>> {
  const response = await requestBackend(
    `/internal/dashboard/activity?limit=${encodeURIComponent(String(limit))}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, activityPageSchema, [200]);
}

export async function fetchDashboardPublications(): Promise<
  BackendResult<PublicationsPage>
> {
  const response = await requestBackend("/internal/dashboard/publications");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, publicationsPageSchema, [200]);
}

export async function fetchDashboardControls(): Promise<
  BackendResult<ControlsPage>
> {
  const response = await requestBackend("/internal/dashboard/controls");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, controlsPageSchema, [200]);
}

export type ControlResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "invalid" }
  | { kind: "conflict" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

export async function sendPauseCommand(
  command: "pause" | "resume",
  scope: PauseScope,
  reason: string,
): Promise<ControlResult<PauseCommandResponse>> {
  const response = await requestBackend(
    `/internal/dashboard/controls/${command}`,
    { method: "POST", jsonBody: { scope, reason } },
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 409) {
    return { kind: "conflict" };
  }
  if (response.status === 422) {
    return { kind: "invalid" };
  }
  const parsed = await parseBackendResponse(
    response,
    pauseCommandResponseSchema,
    [200],
  );
  if (parsed.kind === "ok") {
    return { kind: "ok", data: parsed.data };
  }
  return { kind: parsed.kind === "unreachable" ? "unreachable" : "malformed" };
}
