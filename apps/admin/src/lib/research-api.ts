import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// Server-only module: the research read API stays behind the same server-side
// boundary as the health client. Enum lists mirror the backend's persisted
// values exactly, so an unknown value is treated as a malformed response
// rather than silently rendered.

export const SOURCE_LIFECYCLE_STATES = [
  "active",
  "paused",
  "disabled",
  "blocked",
] as const;

export const SOURCE_KINDS = [
  "editorial_site",
  "competitor_site",
  "rss_feed",
  "sitemap",
  "manual",
  "trend_provider",
  "search_provider",
] as const;

export const TRUST_TIERS = [
  "official",
  "expert",
  "reputable",
  "general",
  "reference_only",
] as const;

// Editorial purpose (backend SourceRole / SourceCapability). Technical
// `kind` says HOW content is acquired; these say WHAT it may be used for.
export const SOURCE_ROLES = [
  "inspiration",
  "turkish_editorial",
  "community_intent",
  "competitor",
  "taxonomy",
  "trend",
  "search",
] as const;

export const SOURCE_CAPABILITIES = [
  "inspiration",
  "community_need",
  "market",
  "competition",
  "taxonomy",
  "search",
  "trend",
  "visual_trend",
] as const;

export const DISCOVERY_STRATEGIES = [
  "feed",
  "sitemap",
  "manual",
  "provider",
] as const;

export const DISCOVERY_LIFECYCLE_STATES = [
  "discovered",
  "accepted",
  "rejected",
  "fetched",
  "fetch_failed",
] as const;

export const DISCOVERY_METHODS = [
  "manual",
  "feed",
  "sitemap",
  "provider",
  "search",
] as const;

export const DISCOVERY_REJECTION_REASONS = [
  "out_of_scope",
  "duplicate_url",
  "source_not_active",
  "policy",
  "invalid_url",
  "unsupported_scheme",
] as const;

export const FETCH_OUTCOMES = [
  "success",
  "invalid_url",
  "ssrf_blocked",
  "network_error",
  "timeout",
  "too_large",
  "disallowed_mime",
  "redirect_limit_exceeded",
  "robots_disallowed",
  "robots_unavailable",
  "http_error",
] as const;

export const RETRY_CLASSIFICATIONS = [
  "not_applicable",
  "retryable",
  "terminal",
] as const;

export const ROBOTS_DECISIONS = [
  "allowed",
  "disallowed",
  "unavailable",
  "not_evaluated",
] as const;

export const NORMALIZATION_STATUSES = ["succeeded", "failed"] as const;

export const NORMALIZATION_FAILURE_CODES = [
  "unsupported_content",
  "decode_error",
  "parse_error",
  "empty_content",
  "extractor_error",
  "policy_rejected",
] as const;

export const DUPLICATE_OUTCOMES = [
  "unique",
  "related",
  "update_existing",
  "duplicate",
  "reject",
] as const;

const countSchema = z.number().int().min(0);
const timestampSchema = z.string().min(1);

const sourceListItemSchema = z.object({
  id: z.string().uuid(),
  slug: z.string().min(1),
  name: z.string().min(1),
  kind: z.enum(SOURCE_KINDS),
  primary_role: z.enum(SOURCE_ROLES),
  capabilities: z.array(z.enum(SOURCE_CAPABILITIES)),
  locale: z.string(),
  market: z.string(),
  lifecycle_state: z.enum(SOURCE_LIFECYCLE_STATES),
  trust_tier: z.enum(TRUST_TIERS),
  discovery_strategy: z.enum(DISCOVERY_STRATEGIES),
  base_url: z.string(),
  created_at: timestampSchema,
  updated_at: timestampSchema,
  total_discovery_items: countSchema,
  discovered_count: countSchema,
  accepted_count: countSchema,
  fetched_count: countSchema,
  fetch_failed_count: countSchema,
  rejected_count: countSchema,
});

function pageSchema<T extends z.ZodTypeAny>(itemSchema: T) {
  return z.object({
    items: z.array(itemSchema),
    total: countSchema,
    limit: z.number().int().min(1),
    offset: z.number().int().min(0),
  });
}

const sourceListPageSchema = pageSchema(sourceListItemSchema);

const pipelineListItemSchema = z.object({
  id: z.string().uuid(),
  source_id: z.string().uuid(),
  source_slug: z.string().min(1),
  source_name: z.string().min(1),
  canonical_url: z.string().min(1),
  discovery_method: z.enum(DISCOVERY_METHODS),
  lifecycle_state: z.enum(DISCOVERY_LIFECYCLE_STATES),
  rejection_reason: z.enum(DISCOVERY_REJECTION_REASONS).nullable(),
  discovered_at: timestampSchema,
  last_seen_at: timestampSchema,
  external_published_at: timestampSchema.nullable(),
  fetch_snapshot_id: z.string().uuid().nullable(),
  fetch_outcome: z.enum(FETCH_OUTCOMES).nullable(),
  fetched_at: timestampSchema.nullable(),
  status_code: z.number().int().nullable(),
  retry_classification: z.enum(RETRY_CLASSIFICATIONS).nullable(),
  normalized_document_id: z.string().uuid().nullable(),
  normalization_status: z.enum(NORMALIZATION_STATUSES).nullable(),
  normalization_failure_code: z.enum(NORMALIZATION_FAILURE_CODES).nullable(),
  normalized_at: timestampSchema.nullable(),
  duplicate_decision_id: z.string().uuid().nullable(),
  duplicate_outcome: z.enum(DUPLICATE_OUTCOMES).nullable(),
  duplicate_evaluated_at: timestampSchema.nullable(),
  evidence_count: countSchema,
  latest_evidence_at: timestampSchema.nullable(),
});

const pipelineListPageSchema = pageSchema(pipelineListItemSchema);

const pipelineDetailSchema = z.object({
  source: z.object({
    id: z.string().uuid(),
    slug: z.string().min(1),
    name: z.string().min(1),
    kind: z.enum(SOURCE_KINDS),
    primary_role: z.enum(SOURCE_ROLES),
    capabilities: z.array(z.enum(SOURCE_CAPABILITIES)),
    locale: z.string(),
    market: z.string(),
    lifecycle_state: z.enum(SOURCE_LIFECYCLE_STATES),
    trust_tier: z.enum(TRUST_TIERS),
    discovery_strategy: z.enum(DISCOVERY_STRATEGIES),
    base_url: z.string(),
  }),
  discovery_item: z.object({
    id: z.string().uuid(),
    source_id: z.string().uuid(),
    discovered_url: z.string(),
    canonical_url: z.string(),
    discovery_method: z.enum(DISCOVERY_METHODS),
    lifecycle_state: z.enum(DISCOVERY_LIFECYCLE_STATES),
    rejection_reason: z.enum(DISCOVERY_REJECTION_REASONS).nullable(),
    rejection_note: z.string().nullable(),
    title_hint: z.string().nullable(),
    locale: z.string(),
    external_published_at: timestampSchema.nullable(),
    discovered_at: timestampSchema,
    last_seen_at: timestampSchema,
    created_at: timestampSchema,
    updated_at: timestampSchema,
  }),
  fetch_attempts: z.array(
    z.object({
      id: z.string().uuid(),
      fetch_outcome: z.enum(FETCH_OUTCOMES),
      retry_classification: z.enum(RETRY_CLASSIFICATIONS),
      robots_decision: z.enum(ROBOTS_DECISIONS),
      status_code: z.number().int().nullable(),
      content_type: z.string().nullable(),
      body_size_bytes: z.number().int().nullable(),
      duration_ms: z.number(),
      failure_detail: z.string().nullable(),
      fetched_at: timestampSchema,
    }),
  ),
  total_fetch_attempts: countSchema,
  fetch_attempts_truncated: z.boolean(),
  normalization_attempts: z.array(
    z.object({
      id: z.string().uuid(),
      fetch_snapshot_id: z.string().uuid(),
      normalization_status: z.enum(NORMALIZATION_STATUSES),
      extractor_name: z.string().min(1),
      extractor_version: z.string().min(1),
      parser_version: z.string().nullable(),
      failure_code: z.enum(NORMALIZATION_FAILURE_CODES).nullable(),
      failure_detail: z.string().nullable(),
      title: z.string().nullable(),
      author_name: z.string().nullable(),
      external_published_at: timestampSchema.nullable(),
      normalized_at: timestampSchema,
    }),
  ),
  total_normalization_attempts: countSchema,
  normalization_attempts_truncated: z.boolean(),
  duplicate_decisions: z.array(
    z.object({
      id: z.string().uuid(),
      normalized_document_id: z.string().uuid(),
      engine_name: z.string().min(1),
      engine_version: z.string().min(1),
      decision: z.enum(DUPLICATE_OUTCOMES),
      rationale_codes: z.array(z.string()),
      match_count: countSchema,
      evaluated_at: timestampSchema,
    }),
  ),
  total_duplicate_decisions: countSchema,
  duplicate_decisions_truncated: z.boolean(),
  evidence: z.object({
    total: countSchema,
    by_verification_status: z.record(z.string(), countSchema),
    by_evidence_type: z.record(z.string(), countSchema),
    latest_extracted_at: timestampSchema.nullable(),
  }),
});

export type SourceListItem = z.infer<typeof sourceListItemSchema>;
export type SourceListPage = z.infer<typeof sourceListPageSchema>;
export type PipelineListItem = z.infer<typeof pipelineListItemSchema>;
export type PipelineListPage = z.infer<typeof pipelineListPageSchema>;
export type PipelineDetail = z.infer<typeof pipelineDetailSchema>;

export type SourceFilters = {
  lifecycleState?: (typeof SOURCE_LIFECYCLE_STATES)[number];
  kind?: (typeof SOURCE_KINDS)[number];
  discoveryStrategy?: (typeof DISCOVERY_STRATEGIES)[number];
  search?: string;
  limit?: number;
  offset?: number;
};

export type PipelineFilters = {
  sourceId?: string;
  lifecycleState?: (typeof DISCOVERY_LIFECYCLE_STATES)[number];
  discoveryMethod?: (typeof DISCOVERY_METHODS)[number];
  fetchOutcome?: (typeof FETCH_OUTCOMES)[number];
  normalizationStatus?: (typeof NORMALIZATION_STATUSES)[number];
  duplicateOutcome?: (typeof DUPLICATE_OUTCOMES)[number];
  hasEvidence?: boolean;
  urlContains?: string;
  limit?: number;
  offset?: number;
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

function buildQuery(
  params: Record<string, string | number | boolean | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

export async function fetchResearchSources(
  filters: SourceFilters = {},
): Promise<BackendResult<SourceListPage>> {
  const path = `/internal/research/sources${buildQuery({
    lifecycle_state: filters.lifecycleState,
    kind: filters.kind,
    discovery_strategy: filters.discoveryStrategy,
    search: filters.search,
    limit: filters.limit,
    offset: filters.offset,
  })}`;
  const response = await requestBackend(path);
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, sourceListPageSchema, [200]);
}

export async function fetchPipelineItems(
  filters: PipelineFilters = {},
): Promise<BackendResult<PipelineListPage>> {
  const path = `/internal/research/discovery-items${buildQuery({
    source_id: filters.sourceId,
    lifecycle_state: filters.lifecycleState,
    discovery_method: filters.discoveryMethod,
    fetch_outcome: filters.fetchOutcome,
    normalization_status: filters.normalizationStatus,
    duplicate_outcome: filters.duplicateOutcome,
    has_evidence: filters.hasEvidence,
    url_contains: filters.urlContains,
    limit: filters.limit,
    offset: filters.offset,
  })}`;
  const response = await requestBackend(path);
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, pipelineListPageSchema, [200]);
}

export type PipelineDetailResult =
  BackendResult<PipelineDetail> | { kind: "not_found" };

export async function fetchPipelineDetail(
  discoveryItemId: string,
): Promise<PipelineDetailResult> {
  if (!isUuid(discoveryItemId)) {
    // Never send junk path segments to the backend; treat them as missing.
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/research/discovery-items/${encodeURIComponent(discoveryItemId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, pipelineDetailSchema, [200]);
}
