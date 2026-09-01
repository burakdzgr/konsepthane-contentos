import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type FetchedResponse,
} from "@/lib/contentos-api";
import {
  DISCOVERY_LIFECYCLE_STATES,
  DISCOVERY_REJECTION_REASONS,
  SOURCE_LIFECYCLE_STATES,
  TRUST_TIERS,
  isUuid,
} from "@/lib/research-api";

// Server-only module: the mutation client for the internal research control
// API. All calls run on the server; the backend URL never reaches browser
// bundles, and backend failure details are reduced to bounded result kinds.

export const REGISTRABLE_SOURCE_KINDS = [
  "rss_feed",
  "sitemap",
  "manual",
] as const;

export type RegistrableSourceKind = (typeof REGISTRABLE_SOURCE_KINDS)[number];

export type ControlResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "conflict" }
  | { kind: "invalid" }
  | { kind: "not_found" }
  | { kind: "queue_failed" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

const registrationResponseSchema = z.object({
  status: z.enum(["registered", "existing"]),
  source_id: z.string().uuid(),
  lifecycle_state: z.enum(SOURCE_LIFECYCLE_STATES),
});

const lifecycleResponseSchema = z.object({
  status: z.literal("updated"),
  source_id: z.string().uuid(),
  lifecycle_state: z.enum(SOURCE_LIFECYCLE_STATES),
});

const itemMutationResponseSchema = z.object({
  status: z.literal("updated"),
  discovery_item_id: z.string().uuid(),
  lifecycle_state: z.enum(DISCOVERY_LIFECYCLE_STATES),
});

const triggerResponseSchema = z.object({
  status: z.literal("queued"),
  task: z.enum(["discover_source", "fetch_discovery_item"]),
  entity_id: z.string().uuid(),
});

export type SourceRegistrationResult = z.infer<
  typeof registrationResponseSchema
>;
export type SourceLifecycleResult = z.infer<typeof lifecycleResponseSchema>;
export type ItemMutationResult = z.infer<typeof itemMutationResponseSchema>;
export type TaskTriggerResult = z.infer<typeof triggerResponseSchema>;

async function postControl<T>(
  path: string,
  jsonBody: unknown,
  schema: z.ZodType<T>,
): Promise<ControlResult<T>> {
  const response = await requestBackend(path, { method: "POST", jsonBody });
  if (response === null) {
    return { kind: "unreachable" };
  }
  const failure = failureKind(response);
  if (failure !== null) {
    return failure;
  }
  const parsed = await parseBackendResponse(response, schema, [200]);
  if (parsed.kind === "ok") {
    return { kind: "ok", data: parsed.data };
  }
  return { kind: parsed.kind };
}

type ControlFailure =
  | { kind: "not_found" }
  | { kind: "conflict" }
  | { kind: "invalid" }
  | { kind: "queue_failed" };

function failureKind(response: FetchedResponse): ControlFailure | null {
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
  return null;
}

export type SourceRegistrationInput = {
  slug: string;
  name: string;
  kind: RegistrableSourceKind;
  baseUrl: string;
  trustTier: (typeof TRUST_TIERS)[number];
  locale?: string;
  market?: string;
  termsNotes?: string;
};

export async function registerSource(
  input: SourceRegistrationInput,
): Promise<ControlResult<SourceRegistrationResult>> {
  const body: Record<string, string> = {
    slug: input.slug,
    name: input.name,
    kind: input.kind,
    base_url: input.baseUrl,
    trust_tier: input.trustTier,
  };
  if (input.locale) {
    body.locale = input.locale;
  }
  if (input.market) {
    body.market = input.market;
  }
  if (input.termsNotes) {
    body.terms_notes = input.termsNotes;
  }
  return postControl(
    "/internal/research/sources",
    body,
    registrationResponseSchema,
  );
}

export async function transitionSourceLifecycle(
  sourceId: string,
  newState: (typeof SOURCE_LIFECYCLE_STATES)[number],
  reason: string,
): Promise<ControlResult<SourceLifecycleResult>> {
  if (!isUuid(sourceId)) {
    return { kind: "not_found" };
  }
  return postControl(
    `/internal/research/sources/${encodeURIComponent(sourceId)}/lifecycle`,
    { new_state: newState, reason },
    lifecycleResponseSchema,
  );
}

export async function runSourceDiscovery(
  sourceId: string,
): Promise<ControlResult<TaskTriggerResult>> {
  if (!isUuid(sourceId)) {
    return { kind: "not_found" };
  }
  return postControl(
    `/internal/research/sources/${encodeURIComponent(sourceId)}/discover`,
    undefined,
    triggerResponseSchema,
  );
}

export async function acceptDiscoveryItem(
  discoveryItemId: string,
): Promise<ControlResult<ItemMutationResult>> {
  if (!isUuid(discoveryItemId)) {
    return { kind: "not_found" };
  }
  return postControl(
    `/internal/research/discovery-items/${encodeURIComponent(discoveryItemId)}/accept`,
    undefined,
    itemMutationResponseSchema,
  );
}

export async function rejectDiscoveryItem(
  discoveryItemId: string,
  reason: (typeof DISCOVERY_REJECTION_REASONS)[number],
  note?: string,
): Promise<ControlResult<ItemMutationResult>> {
  if (!isUuid(discoveryItemId)) {
    return { kind: "not_found" };
  }
  const body: Record<string, string> = { reason };
  if (note) {
    body.note = note;
  }
  return postControl(
    `/internal/research/discovery-items/${encodeURIComponent(discoveryItemId)}/reject`,
    body,
    itemMutationResponseSchema,
  );
}

export async function requeueDiscoveryItem(
  discoveryItemId: string,
  reason: string,
): Promise<ControlResult<ItemMutationResult>> {
  if (!isUuid(discoveryItemId)) {
    return { kind: "not_found" };
  }
  return postControl(
    `/internal/research/discovery-items/${encodeURIComponent(discoveryItemId)}/requeue`,
    { reason },
    itemMutationResponseSchema,
  );
}

export async function startDiscoveryItemFetch(
  discoveryItemId: string,
): Promise<ControlResult<TaskTriggerResult>> {
  if (!isUuid(discoveryItemId)) {
    return { kind: "not_found" };
  }
  return postControl(
    `/internal/research/discovery-items/${encodeURIComponent(discoveryItemId)}/fetch`,
    undefined,
    triggerResponseSchema,
  );
}
