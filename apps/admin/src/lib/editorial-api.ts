import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";
import { isUuid, TRUST_TIERS, DUPLICATE_OUTCOMES } from "@/lib/research-api";

// Server-only module: the Phase-3 editorial read API client. Enum lists
// mirror the backend's persisted values exactly, so an unknown value is a
// malformed response rather than silently rendered. Nothing here ever
// receives raw payloads, clean text, prompts, or model output — the backend
// read boundary excludes them, and these schemas add no such fields.

export const WORKFLOW_STATES = [
  "discovered",
  "researching",
  "normalized",
  "duplicate_check",
  "duplicate",
  "idea_scoring",
  "evidence_building",
  "seo_research",
  "briefing",
  "drafting",
  "editing",
  "qa_review",
  "awaiting_human_review",
  "approved",
  "scheduled",
  "publishing",
  "published",
  "pinterest_pending",
  "distributed",
  "measuring",
  "refresh_candidate",
  "changes_requested",
  "blocked",
  "approval_expired",
  "rejected",
  "archived",
] as const;

// The Phase-3 operator queue states an operator filters day to day.
export const QUEUE_FILTER_STATES = [
  "idea_scoring",
  "evidence_building",
  "seo_research",
  "briefing",
  "drafting",
  "editing",
  "qa_review",
  "awaiting_human_review",
  "approved",
  "scheduled",
  "publishing",
  "published",
  "changes_requested",
  "approval_expired",
  "blocked",
  "rejected",
] as const;

export const OPPORTUNITY_DISPOSITIONS = [
  "open",
  "commissioned",
  "rejected",
] as const;

export const WORKFLOW_ACTOR_ORIGINS = ["operator", "system"] as const;
export const WORK_ITEM_ORIGINS = ["research_intake", "operator"] as const;
export const RESEARCH_INPUT_ROLES = [
  "primary_signal",
  "supporting",
  "contradicting",
  "context",
  "update_signal",
] as const;
export const SCORE_BANDS = [
  "strong",
  "moderate",
  "weak",
  "ineligible",
] as const;
export const SCORE_ELIGIBILITIES = [
  "commissionable",
  "not_commissionable",
  "needs_operator_review",
] as const;
export const INSPIRATION_BANDS = ["high", "medium", "low", "unknown"] as const;
export const SEARCH_OPPORTUNITY_BANDS = [
  "strong",
  "moderate",
  "weak",
  "unknown",
] as const;
export const OPPORTUNITY_RECOMMENDATIONS = [
  "produce",
  "continue_research",
  "eliminate",
  "human_review",
] as const;
export const TREND_STATES = ["known", "unknown"] as const;
export const COMPONENT_AVAILABILITIES = [
  "known",
  "unknown",
  "not_applicable",
] as const;
export const IDEA_ORIGINS = ["operator", "model_assisted"] as const;
export const ORIGINALITY_STATUSES = [
  "passed",
  "failed",
  "not_checkable",
] as const;
export const SELECTION_ACTIONS = ["selected", "deselected"] as const;
export const PACK_SUFFICIENCIES = [
  "ready",
  "insufficient",
  "conflicted",
  "blocked",
] as const;
export const EVIDENCE_ITEM_ROLES = [
  "key_fact",
  "supporting",
  "contradicting",
  "context",
  "caution",
] as const;
export const CONTRADICTION_SEVERITIES = [
  "low",
  "material",
  "blocking",
] as const;
export const CONTRADICTION_RESOLUTION_STATUSES = [
  "unresolved",
  "resolved_cautious_wording",
  "resolved_needs_research",
  "resolved_editorial_judgment",
] as const;
export const RESOLVED_CONTRADICTION_STATUSES = [
  "resolved_cautious_wording",
  "resolved_needs_research",
  "resolved_editorial_judgment",
] as const;
export const CANNIBALIZATION_STATUSES = [
  "not_checked",
  "no_known_conflict",
  "potential_conflict",
  "known_conflict",
] as const;
export const BRIEF_STATUSES = [
  "draft",
  "accepted_for_drafting",
  "superseded",
] as const;
export const BRIEF_CLAIM_KINDS = [
  "factual",
  "source_assertion",
  "observation",
  "inference",
  "editorial_judgment",
  "instruction",
] as const;
export const GENERATION_PURPOSES = [
  "idea_candidates",
  "intent_synthesis",
  "brief_composition",
  "evidence_organization",
  "writer_draft",
  "editor_review",
] as const;
export const REVIEW_VERDICTS = ["pass", "revise"] as const;
export const REVIEW_STATUSES = ["active", "superseded"] as const;
export const FINDING_DIMENSIONS = [
  "claim_faithfulness",
  "exclusion_compliance",
  "objective_fit",
  "clarity_style",
  "uncertainty_framing",
] as const;
export const FINDING_SEVERITIES = ["blocking", "major", "minor"] as const;
export const FINDING_ORIGINS = ["model_signal", "deterministic"] as const;
export const QA_OUTCOMES = ["ready_for_human_review", "not_ready"] as const;
export const QA_REPORT_STATUSES = ["active", "superseded"] as const;
export const QA_WAIVABLE_GATES = ["media_needs"] as const;
export const MEDIA_ORIGINS = ["human_upload", "ai_generated"] as const;
export const PUBLICATION_ATTEMPT_STATUSES = [
  "succeeded",
  "transport_error",
  "rejected_by_api",
  "timeout",
] as const;
export const MEDIA_SATISFACTION_STATUSES = ["active", "superseded"] as const;
export const DECISION_KINDS = [
  "approved",
  "changes_requested",
  "rejected",
  "approval_revoked",
] as const;
export const DRAFT_ORIGINS = ["writer_engine", "operator"] as const;
export const DRAFT_STATUSES = ["active", "superseded"] as const;
export const DRAFT_ACTOR_ORIGINS = ["operator", "system"] as const;
export const DRAFT_BLOCK_KINDS = [
  "paragraph",
  "list",
  "how_to_step",
  "callout",
  "faq_item",
  "internal_link_need",
  "media_need",
] as const;
export const GENERATION_STATUSES = [
  "succeeded",
  "validation_failed",
  "provider_error",
  "timeout",
  "cancelled",
] as const;
export const SEARCH_SIGNAL_TYPES = [
  "search_volume",
  "trend",
  "serp_observation",
  "query_set",
  "manual_intent_note",
] as const;
export const EVIDENCE_TYPES = [
  "source_assertion",
  "observation",
  "statistic",
  "quote",
  "instruction",
] as const;
export const VERIFICATION_STATUSES = [
  "unverified",
  "verified",
  "disputed",
  "retracted",
] as const;

const countSchema = z.number().int().min(0);
const timestampSchema = z.string().min(1);
const jsonRecordSchema = z.record(z.string(), z.unknown());

// Opportunity Intelligence: explainable sections over ONE band vocabulary.
// A provider that is not configured / refused / rate-limited stays unknown
// with its state and last observation time — never a number.
export const INTELLIGENCE_BANDS = [
  "very_high",
  "high",
  "medium",
  "low",
  "unknown",
] as const;
export const TREND_DIRECTIONS = [
  "rising",
  "stable",
  "falling",
  "unknown",
] as const;
export const EVIDENCE_STATES = [
  "sufficient",
  "insufficient",
  "unknown",
] as const;

const intelligenceBandSchema = z.enum(INTELLIGENCE_BANDS);

const providerFreshnessSchema = z.object({
  state: z.string(),
  observed_at: timestampSchema.nullable(),
  error_class: z.string().nullable(),
  region: z.string().nullable(),
});

const intelligenceSchema = z.object({
  engine_version: z.string(),
  content_value: z.object({
    inspiration_band: intelligenceBandSchema,
    audience_fit_band: intelligenceBandSchema,
    strategy_fit_band: intelligenceBandSchema,
    market_band: intelligenceBandSchema,
    community_need_band: intelligenceBandSchema,
  }),
  search_intelligence: z.object({
    semrush_potential_band: intelligenceBandSchema,
    search_keyword: z.string().nullable(),
    search_volume: countSchema.nullable(),
    keyword_difficulty: z.number().nullable(),
    google_trends_direction: z.enum(TREND_DIRECTIONS),
    pinterest_trend_band: intelligenceBandSchema,
    competition_band: intelligenceBandSchema,
    provider_freshness: z.record(z.string(), providerFreshnessSchema),
  }),
  konsepthane_data: z.object({
    similar_content_performance_band: intelligenceBandSchema,
    cannibalization_status: z.string(),
    historical_outcome: z.string().nullable(),
  }),
  research: z.object({
    independent_sources: countSchema.nullable(),
    signal_families: countSchema.nullable(),
    evidence_state: z.enum(EVIDENCE_STATES),
  }),
  recommendation: z.enum(OPPORTUNITY_RECOMMENDATIONS),
  why: z.string(),
  factor_bands: z.array(
    z.object({
      factor: z.string(),
      band: intelligenceBandSchema,
      basis: z.string(),
    }),
  ),
});

const inspirationEvaluationSchema = z.object({
  id: z.string().uuid(),
  engine_name: z.string(),
  engine_version: z.string(),
  inspiration_band: z.enum(INSPIRATION_BANDS),
  search_opportunity: z.enum(SEARCH_OPPORTUNITY_BANDS),
  trend_state: z.enum(TREND_STATES),
  recommendation: z.enum(OPPORTUNITY_RECOMMENDATIONS),
  rationale: z.string(),
  missing_signals: z.array(z.string()),
  strategy_context: jsonRecordSchema,
  evaluated_at: timestampSchema,
  intelligence: intelligenceSchema,
});

const workQueueRowSchema = z.object({
  work_item_id: z.string().uuid(),
  title_working_label: z.string(),
  locale: z.string(),
  market: z.string(),
  origin: z.enum(WORK_ITEM_ORIGINS),
  current_state: z.enum(WORKFLOW_STATES),
  current_state_entered_at: timestampSchema,
  blocked_reason: z.string().nullable(),
  rejected_reason: z.string().nullable(),
  opportunity_id: z.string().uuid().nullable(),
  disposition: z.enum(OPPORTUNITY_DISPOSITIONS).nullable(),
  topic_summary: z.string().nullable(),
  score_id: z.string().uuid().nullable(),
  score_band: z.enum(SCORE_BANDS).nullable(),
  score_eligibility: z.enum(SCORE_ELIGIBILITIES).nullable(),
  score_overall_value: z.number().nullable(),
  score_missing_signals: z.array(z.string()),
  score_risk_flags: z.array(z.string()),
  score_evaluated_at: timestampSchema.nullable(),
  score_engine_name: z.string().nullable(),
  score_engine_version: z.string().nullable(),
  // The backend's own commissioning gate evaluated over the effective
  // score; the ONLY thing that may show a commissioning affordance.
  commission_eligible: z.boolean(),
  // ADR 0010: scored but refused; a named operator may still commission
  // with override_gate + reason. Never true for an unscored card.
  commission_override_possible: z.boolean(),
  inspiration_evaluation_id: z.string().uuid().nullable(),
  inspiration_band: z.enum(INSPIRATION_BANDS).nullable(),
  search_opportunity: z.enum(SEARCH_OPPORTUNITY_BANDS).nullable(),
  trend_state: z.enum(TREND_STATES).nullable(),
  recommendation: z.enum(OPPORTUNITY_RECOMMENDATIONS).nullable(),
  inspiration_rationale: z.string().nullable(),
  strategy_context: jsonRecordSchema,
  inspiration_signal_count: countSchema,
  inspiration_concept_count: countSchema,
  intelligence: intelligenceSchema.nullable(),
  selected_idea_id: z.string().uuid().nullable(),
  selected_idea_title: z.string().nullable(),
  selected_idea_originality: z.enum(ORIGINALITY_STATUSES).nullable(),
  latest_pack_id: z.string().uuid().nullable(),
  latest_pack_version: z.number().int().nullable(),
  latest_pack_sufficiency: z.enum(PACK_SUFFICIENCIES).nullable(),
  latest_analysis_id: z.string().uuid().nullable(),
  latest_analysis_version: z.number().int().nullable(),
  latest_brief_id: z.string().uuid().nullable(),
  latest_brief_version: z.number().int().nullable(),
  latest_brief_status: z.enum(BRIEF_STATUSES).nullable(),
});

const workQueuePageSchema = z.object({
  items: z.array(workQueueRowSchema),
  total: countSchema,
  limit: z.number().int().min(1),
  offset: z.number().int().min(0),
});

const workflowEventSchema = z.object({
  id: z.number().int(),
  from_state: z.enum(WORKFLOW_STATES).nullable(),
  to_state: z.enum(WORKFLOW_STATES),
  actor_origin: z.enum(WORKFLOW_ACTOR_ORIGINS),
  reason: z.string(),
  artifact_refs: jsonRecordSchema,
  request_id: z.string().nullable(),
  // Phase 5: the named authenticated human; null renders as UNKNOWN.
  actor_user_id: z.string().uuid().nullable(),
  actor_display_name: z.string().nullable(),
  occurred_at: timestampSchema,
});

const scoreComponentSchema = z.object({
  component: z.string(),
  availability: z.enum(COMPONENT_AVAILABILITIES),
  value: z.number().nullable(),
  confidence: z.number().nullable(),
  provider: z.string().nullable(),
  observed_at: timestampSchema.nullable(),
  provenance_ref: jsonRecordSchema,
});

const scoreSchema = z.object({
  id: z.string().uuid(),
  engine_name: z.string(),
  engine_version: z.string(),
  overall_band: z.enum(SCORE_BANDS),
  overall_value: z.number().nullable(),
  eligibility: z.enum(SCORE_ELIGIBILITIES),
  missing_signals: z.array(z.string()),
  risk_flags: z.array(z.string()),
  weights_snapshot: jsonRecordSchema,
  threshold_snapshot: jsonRecordSchema,
  input_snapshot: jsonRecordSchema,
  evaluated_at: timestampSchema,
  created_at: timestampSchema,
  effective: z.boolean(),
  components: z.array(scoreComponentSchema),
});

const ideaSchema = z.object({
  id: z.string().uuid(),
  logical_idea_id: z.string().uuid(),
  version: z.number().int(),
  working_title: z.string(),
  angle: z.string(),
  audience: z.string(),
  value_proposition: z.string(),
  content_type: z.string(),
  locale: z.string(),
  market: z.string(),
  rationale: z.string(),
  exclusions: z.array(z.string()),
  planning_dimensions: jsonRecordSchema,
  originality_status: z.enum(ORIGINALITY_STATUSES),
  originality_detail: jsonRecordSchema,
  originality_policy_snapshot: jsonRecordSchema,
  origin: z.enum(IDEA_ORIGINS),
  generation_attempt_id: z.string().uuid().nullable(),
  created_at: timestampSchema,
  effective_selected: z.boolean(),
});

const selectionEventSchema = z.object({
  id: z.number().int(),
  idea_id: z.string().uuid(),
  action: z.enum(SELECTION_ACTIONS),
  actor_origin: z.string(),
  reason: z.string(),
  request_id: z.string().nullable(),
  occurred_at: timestampSchema,
});

const packItemSchema = z.object({
  id: z.string().uuid(),
  research_evidence_id: z.string().uuid(),
  role: z.enum(EVIDENCE_ITEM_ROLES),
  claim_cluster: z.string(),
  display_note: z.string().nullable(),
  evidence_type: z.enum(EVIDENCE_TYPES).nullable(),
  verification_status: z.enum(VERIFICATION_STATUSES).nullable(),
  statement: z.string().nullable(),
  normalized_document_id: z.string().uuid().nullable(),
  source_id: z.string().uuid().nullable(),
  source_slug: z.string().nullable(),
  trust_tier: z.enum(TRUST_TIERS).nullable(),
  extracted_at: timestampSchema.nullable(),
});

const contradictionSchema = z.object({
  id: z.string().uuid(),
  pack_id: z.string().uuid(),
  claim_key: z.string(),
  evidence_side_a: z.array(z.string()),
  evidence_side_b: z.array(z.string()),
  nature: z.string(),
  severity: z.enum(CONTRADICTION_SEVERITIES),
  resolution_status: z.enum(CONTRADICTION_RESOLUTION_STATUSES),
  handling_recommendation: z.string().nullable(),
  resolution_reason: z.string().nullable(),
  resolved_by: z.string().nullable(),
  resolved_at: timestampSchema.nullable(),
});

const packSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int(),
  idea_id: z.string().uuid().nullable(),
  organization_attempt_id: z.string().uuid().nullable(),
  assembler_name: z.string(),
  assembler_version: z.string(),
  sufficiency: z.enum(PACK_SUFFICIENCIES),
  sufficiency_detail: jsonRecordSchema,
  source_diversity: jsonRecordSchema,
  staleness_notes: z.array(jsonRecordSchema),
  locale_limitations: jsonRecordSchema,
  licensing_cautions: z.array(jsonRecordSchema),
  policy_snapshot: jsonRecordSchema,
  assembly_input_hash: z.string(),
  created_at: timestampSchema,
  items: z.array(packItemSchema),
  contradictions: z.array(contradictionSchema),
});

const knownSignalSchema = z.object({
  id: z.string().uuid(),
  signal_type: z.enum(SEARCH_SIGNAL_TYPES),
  provider: z.string(),
  subject: z.string(),
  observed_at: timestampSchema,
  as_of: timestampSchema.nullable(),
  recorded_at: timestampSchema,
});

const intentAnalysisSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int(),
  idea_id: z.string().uuid(),
  primary_intent: z.string(),
  secondary_intents: z.array(z.string()),
  target_audience: z.string(),
  query_concepts: z.array(z.string()),
  page_purpose: z.string(),
  likely_format: z.string(),
  known_signal_refs: z.array(jsonRecordSchema),
  known_signals: z.array(knownSignalSchema),
  missing_signals: z.array(z.string()),
  cannibalization_status: z.enum(CANNIBALIZATION_STATUSES),
  cannibalization_basis: jsonRecordSchema,
  related_references: z.array(jsonRecordSchema),
  locale: z.string(),
  market: z.string(),
  engine_name: z.string(),
  engine_version: z.string(),
  synthesis_attempt_id: z.string().uuid().nullable(),
  created_at: timestampSchema,
});

const briefClaimSchema = z.object({
  id: z.string().uuid(),
  claim_key: z.string(),
  claim_text: z.string(),
  claim_kind: z.enum(BRIEF_CLAIM_KINDS),
  handling: z.string().nullable(),
  evidence_ids: z.array(z.string().uuid()),
});

const briefStatusEventSchema = z.object({
  id: z.number().int(),
  from_status: z.enum(BRIEF_STATUSES),
  to_status: z.enum(BRIEF_STATUSES),
  actor_origin: z.string(),
  reason: z.string(),
  request_id: z.string().nullable(),
  replacement_brief_id: z.string().uuid().nullable(),
  occurred_at: timestampSchema,
});

const briefSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int(),
  idea_id: z.string().uuid(),
  evidence_pack_id: z.string().uuid(),
  search_intent_analysis_id: z.string().uuid(),
  locale: z.string(),
  market: z.string(),
  target_audience: z.string(),
  intent_summary: z.string(),
  original_angle: z.string(),
  title_guidance: jsonRecordSchema,
  content_objective: z.string(),
  required_sections: z.array(jsonRecordSchema),
  optional_sections: z.array(jsonRecordSchema),
  practical_requirements: jsonRecordSchema,
  exclusions: z.array(z.string()),
  uncertainty_notes: z.array(z.string()),
  internal_link_needs: z.array(jsonRecordSchema),
  media_needs: z.array(jsonRecordSchema),
  faq_questions: z.array(z.string()),
  acceptance_criteria: z.array(jsonRecordSchema),
  structure_guard_result: jsonRecordSchema,
  structure_policy_snapshot: jsonRecordSchema,
  status: z.enum(BRIEF_STATUSES),
  composition_attempt_id: z.string().uuid().nullable(),
  engine_name: z.string(),
  engine_version: z.string(),
  content_hash: z.string(),
  created_at: timestampSchema,
  claims: z.array(briefClaimSchema),
  status_events: z.array(briefStatusEventSchema),
});

const aiAttemptSchema = z.object({
  id: z.string().uuid(),
  purpose: z.enum(GENERATION_PURPOSES),
  provider: z.string(),
  model_name: z.string(),
  model_version: z.string().nullable(),
  schema_name: z.string(),
  schema_version: z.string(),
  template_name: z.string(),
  template_version: z.string(),
  input_hash: z.string(),
  input_refs: jsonRecordSchema,
  status: z.enum(GENERATION_STATUSES),
  error_class: z.string().nullable(),
  retry_number: z.number().int(),
  usage: jsonRecordSchema,
  created_at: timestampSchema,
});

const workItemDetailSchema = z.object({
  work_item: z.object({
    id: z.string().uuid(),
    locale: z.string(),
    market: z.string(),
    origin: z.enum(WORK_ITEM_ORIGINS),
    current_state: z.enum(WORKFLOW_STATES),
    current_state_entered_at: timestampSchema,
    title_working_label: z.string(),
    blocked_reason: z.string().nullable(),
    blocked_resume_state: z.enum(WORKFLOW_STATES).nullable(),
    rejected_reason: z.string().nullable(),
    created_at: timestampSchema,
    updated_at: timestampSchema,
  }),
  workflow_events: z.array(workflowEventSchema),
  total_workflow_events: countSchema,
  workflow_events_truncated: z.boolean(),
  opportunity: z
    .object({
      id: z.string().uuid(),
      disposition: z.enum(OPPORTUNITY_DISPOSITIONS),
      commission_eligible: z.boolean(),
      commission_override_possible: z.boolean(),
      disposition_reason: z.string().nullable(),
      disposition_by: z.string().nullable(),
      disposition_at: timestampSchema.nullable(),
      topic_summary: z.string(),
      update_of_reference: z.string().nullable(),
      promotion_root_document_id: z.string().uuid(),
      created_at: timestampSchema,
      updated_at: timestampSchema,
    })
    .nullable(),
  research_inputs: z.array(
    z.object({
      id: z.string().uuid(),
      normalized_document_id: z.string().uuid(),
      duplicate_decision_id: z.string().uuid(),
      duplicate_outcome: z.enum(DUPLICATE_OUTCOMES).nullable(),
      role: z.enum(RESEARCH_INPUT_ROLES),
      added_by: z.string(),
      note: z.string().nullable(),
      added_at: timestampSchema,
      document_title: z.string().nullable(),
      external_published_at: timestampSchema.nullable(),
      fetched_at: timestampSchema.nullable(),
      source_id: z.string().uuid().nullable(),
      source_slug: z.string().nullable(),
      source_name: z.string().nullable(),
      trust_tier: z.enum(TRUST_TIERS).nullable(),
    }),
  ),
  scores: z.array(scoreSchema),
  total_scores: countSchema,
  scores_truncated: z.boolean(),
  ideas: z.array(ideaSchema),
  total_ideas: countSchema,
  ideas_truncated: z.boolean(),
  selection_events: z.array(selectionEventSchema),
  total_selection_events: countSchema,
  selection_events_truncated: z.boolean(),
  effective_selected_idea_id: z.string().uuid().nullable(),
  evidence_packs: z.array(packSchema),
  total_evidence_packs: countSchema,
  evidence_packs_truncated: z.boolean(),
  intent_analyses: z.array(intentAnalysisSchema),
  total_intent_analyses: countSchema,
  intent_analyses_truncated: z.boolean(),
  briefs: z.array(briefSchema),
  total_briefs: countSchema,
  briefs_truncated: z.boolean(),
  ai_attempts: z.array(aiAttemptSchema),
  inspiration: inspirationEvaluationSchema.nullable(),
});

const draftSummarySchema = z.object({
  id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  content_brief_id: z.string().uuid(),
  version: z.number().int(),
  origin: z.enum(DRAFT_ORIGINS),
  status: z.enum(DRAFT_STATUSES),
  engine_name: z.string(),
  engine_version: z.string(),
  title_proposal: z.string().nullable(),
  generation_attempt_id: z.string().uuid().nullable(),
  manual_input_hash: z.string().nullable(),
  superseded_by_draft_id: z.string().uuid().nullable(),
  body_schema_version: z.string(),
  // null means the durable record carries no verdict: rendered UNKNOWN.
  uncertainty_coverage_status: z.string().nullable(),
  originality_outcome: z.string().nullable(),
  content_hash: z.string(),
  created_at: timestampSchema,
});

const draftListPageSchema = z.object({
  work_item_id: z.string().uuid(),
  drafts: z.array(draftSummarySchema),
  total: countSchema,
  truncated: z.boolean(),
});

const draftBlockSchema = z.object({
  block_id: z.string(),
  kind: z.enum(DRAFT_BLOCK_KINDS),
  text: z.string(),
  claim_refs: z.array(z.string().uuid()),
  uncertainty_refs: z.array(z.string()),
  link_need_ref: z.number().int().optional(),
  media_need_ref: z.number().int().optional(),
});

const draftBodySchema = z.object({
  sections: z.array(
    z.object({
      key: z.string(),
      heading: z.string(),
      blocks: z.array(draftBlockSchema),
    }),
  ),
});

const draftClaimUsageSchema = z.object({
  id: z.string().uuid(),
  brief_claim_id: z.string().uuid(),
  claim_key: z.string(),
  claim_kind: z.enum(BRIEF_CLAIM_KINDS),
  claim_text: z.string(),
  handling: z.string().nullable(),
  section_key: z.string(),
  block_id: z.string(),
  research_evidence_ids: z.array(z.string().uuid()),
});

const draftStatusEventSchema = z.object({
  id: z.number().int(),
  from_status: z.enum(DRAFT_STATUSES),
  to_status: z.enum(DRAFT_STATUSES),
  actor_origin: z.enum(DRAFT_ACTOR_ORIGINS),
  reason: z.string(),
  request_id: z.string().nullable(),
  replacement_draft_id: z.string().uuid().nullable(),
  occurred_at: timestampSchema,
});

const draftDetailSchema = z.object({
  draft: draftSummarySchema,
  body: draftBodySchema,
  uncertainty_coverage: jsonRecordSchema,
  validation_policy_snapshot: jsonRecordSchema,
  originality_policy_snapshot: jsonRecordSchema,
  originality_result: jsonRecordSchema,
  claim_usages: z.array(draftClaimUsageSchema),
  status_events: z.array(draftStatusEventSchema),
  generation_attempts: z.array(aiAttemptSchema),
  generation_attempts_truncated: z.boolean(),
});

const reviewSummarySchema = z.object({
  id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  content_draft_id: z.string().uuid(),
  content_brief_id: z.string().uuid(),
  version: z.number().int(),
  verdict: z.enum(REVIEW_VERDICTS),
  status: z.enum(REVIEW_STATUSES),
  engine_name: z.string(),
  engine_version: z.string(),
  generation_attempt_id: z.string().uuid().nullable(),
  superseded_by_review_id: z.string().uuid().nullable(),
  finding_counts: z.record(z.string(), z.number().int()),
  // null means the record carries no envelope: rendered UNKNOWN.
  writer_envelope_recomputed: z.boolean().nullable(),
  content_hash: z.string(),
  created_at: timestampSchema,
});

const reviewListPageSchema = z.object({
  work_item_id: z.string().uuid(),
  reviews: z.array(reviewSummarySchema),
  total: countSchema,
  truncated: z.boolean(),
});

const reviewFindingSchema = z.object({
  id: z.string().uuid(),
  finding_key: z.string(),
  dimension: z.enum(FINDING_DIMENSIONS),
  severity: z.enum(FINDING_SEVERITIES),
  origin: z.enum(FINDING_ORIGINS),
  block_id: z.string().nullable(),
  brief_claim_id: z.string().uuid().nullable(),
  claim_key: z.string().nullable(),
  claim_kind: z.string().nullable(),
  description: z.string(),
  recommendation: z.string().nullable(),
});

const reviewStatusEventSchema = z.object({
  id: z.number().int(),
  from_status: z.enum(REVIEW_STATUSES),
  to_status: z.enum(REVIEW_STATUSES),
  actor_origin: z.enum(DRAFT_ACTOR_ORIGINS),
  reason: z.string(),
  request_id: z.string().nullable(),
  replacement_review_id: z.string().uuid().nullable(),
  occurred_at: timestampSchema,
});

const reviewDetailSchema = z.object({
  review: reviewSummarySchema,
  integrity_gate_result: jsonRecordSchema,
  verdict_policy_snapshot: jsonRecordSchema,
  review_scope: jsonRecordSchema,
  findings: z.array(reviewFindingSchema),
  status_events: z.array(reviewStatusEventSchema),
  generation_attempts: z.array(aiAttemptSchema),
  generation_attempts_truncated: z.boolean(),
});

const qaReportSummarySchema = z.object({
  id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  content_draft_id: z.string().uuid(),
  editorial_review_id: z.string().uuid(),
  content_brief_id: z.string().uuid(),
  version: z.number().int(),
  outcome: z.enum(QA_OUTCOMES),
  status: z.enum(QA_REPORT_STATUSES),
  gate_summary: z.record(z.string(), z.string()),
  engine_name: z.string(),
  engine_version: z.string(),
  superseded_by_report_id: z.string().uuid().nullable(),
  content_hash: z.string(),
  created_at: timestampSchema,
});

const qaWaiverSchema = z.object({
  id: z.string().uuid(),
  gate_key: z.enum(QA_WAIVABLE_GATES),
  reason: z.string(),
  request_id: z.string().nullable(),
  created_at: timestampSchema,
});

const qaReportListPageSchema = z.object({
  work_item_id: z.string().uuid(),
  reports: z.array(qaReportSummarySchema),
  waivers: z.array(qaWaiverSchema),
  total: countSchema,
  truncated: z.boolean(),
});

const qaReportStatusEventSchema = z.object({
  id: z.number().int(),
  from_status: z.enum(QA_REPORT_STATUSES),
  to_status: z.enum(QA_REPORT_STATUSES),
  actor_origin: z.enum(DRAFT_ACTOR_ORIGINS),
  reason: z.string(),
  request_id: z.string().nullable(),
  replacement_report_id: z.string().uuid().nullable(),
  occurred_at: timestampSchema,
});

const qaReportDetailSchema = z.object({
  report: qaReportSummarySchema,
  gate_results: jsonRecordSchema,
  gate_policy_snapshot: jsonRecordSchema,
  waivers: z.array(qaWaiverSchema),
  status_events: z.array(qaReportStatusEventSchema),
});

const publicationAttemptSchema = z.object({
  id: z.string().uuid(),
  attempt_number: z.number().int(),
  status: z.enum(PUBLICATION_ATTEMPT_STATUSES),
  error_class: z.string().nullable(),
  remote_publication_ref: z.string().nullable(),
  transport_name: z.string(),
  created_at: timestampSchema,
});

const publicationPackageSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int(),
  human_decision_id: z.string().uuid(),
  content_draft_id: z.string().uuid(),
  content_brief_id: z.string().uuid(),
  qa_report_id: z.string().uuid(),
  content_hash: z.string(),
  package_hash: z.string(),
  payload_schema_version: z.string(),
  title_proposal: z.string().nullable(),
  locale: z.string(),
  market: z.string(),
  section_count: z.number().int(),
  manifest_needs: z.number().int(),
  waived_unmet_indexes: z.array(z.number().int()),
  assembled_by: z.object({
    id: z.string().uuid(),
    username: z.string(),
    display_name: z.string(),
  }),
  created_at: timestampSchema,
  attempts: z.array(publicationAttemptSchema),
  total_attempts: z.number().int(),
  attempts_truncated: z.boolean(),
});

const publicationPageSchema = z.object({
  work_item_id: z.string().uuid(),
  packages: z.array(publicationPackageSchema),
  total_packages: z.number().int(),
  packages_truncated: z.boolean(),
  latest_package_approval_current: z.boolean().nullable(),
});

const mediaActorSchema = z.object({
  id: z.string().uuid(),
  username: z.string(),
  display_name: z.string(),
});

const mediaAssetSchema = z.object({
  id: z.string().uuid(),
  origin: z.enum(MEDIA_ORIGINS),
  content_sha256: z.string(),
  byte_size: z.number().int(),
  media_type: z.string(),
  width: z.number().int().nullable(),
  height: z.number().int().nullable(),
  title: z.string().nullable(),
  alt_text: z.string(),
  license_note: z.string(),
  source_attribution: z.string().nullable(),
  generation_attempt_id: z.string().uuid().nullable(),
  created_by: mediaActorSchema,
  created_at: timestampSchema,
});

const mediaSatisfactionSchema = z.object({
  id: z.string().uuid(),
  need_index: z.number().int(),
  status: z.enum(MEDIA_SATISFACTION_STATUSES),
  asset: mediaAssetSchema,
  satisfied_by: mediaActorSchema,
  reason: z.string(),
  superseded_by_satisfaction_id: z.string().uuid().nullable(),
  created_at: timestampSchema,
});

const needCoverageSchema = z.object({
  need_index: z.number().int(),
  role: z.string(),
  purpose: z.string(),
  constraints: z.string().nullable(),
  // null means honestly UNSATISFIED.
  satisfaction: mediaSatisfactionSchema.nullable(),
});

const mediaCoveragePageSchema = z.object({
  work_item_id: z.string().uuid(),
  content_brief_id: z.string().uuid().nullable(),
  needs: z.array(needCoverageSchema),
  satisfied_needs: z.number().int(),
  total_needs: z.number().int(),
  history: z.array(mediaSatisfactionSchema),
  total_history: z.number().int(),
  history_truncated: z.boolean(),
});

const decisionSchema = z.object({
  id: z.string().uuid(),
  decision: z.enum(DECISION_KINDS),
  reviewer: z.object({
    id: z.string().uuid(),
    username: z.string(),
    display_name: z.string(),
  }),
  reason: z.string(),
  qa_report_id: z.string().uuid(),
  content_draft_id: z.string().uuid(),
  editorial_review_id: z.string().uuid(),
  content_hash: z.string(),
  revokes_decision_id: z.string().uuid().nullable(),
  request_id: z.string().nullable(),
  created_at: timestampSchema,
});

const approvalStatusSchema = z.object({
  approved: z.boolean(),
  current: z.boolean(),
  decision_id: z.string().uuid().nullable(),
  approved_content_hash: z.string().nullable(),
  active_content_hash: z.string().nullable(),
});

const decisionListPageSchema = z.object({
  work_item_id: z.string().uuid(),
  decisions: z.array(decisionSchema),
  total: z.number().int(),
  truncated: z.boolean(),
  approval_status: approvalStatusSchema,
});

const eligibleEvidenceSchema = z.object({
  items: z.array(
    z.object({
      id: z.string().uuid(),
      evidence_type: z.enum(EVIDENCE_TYPES),
      verification_status: z.enum(VERIFICATION_STATUSES),
      statement: z.string(),
      extraction_method: z.string(),
      confidence: z.number().nullable(),
      licensing_notes: z.string().nullable(),
      normalized_document_id: z.string().uuid(),
      source_id: z.string().uuid(),
      source_slug: z.string().nullable(),
      source_name: z.string().nullable(),
      trust_tier: z.enum(TRUST_TIERS).nullable(),
      fetched_at: timestampSchema,
      extracted_at: timestampSchema,
    }),
  ),
  total: countSchema,
  limit: z.number().int().min(1),
  offset: z.number().int().min(0),
});

export type WorkQueueRow = z.infer<typeof workQueueRowSchema>;
export type IntelligenceView = z.infer<typeof intelligenceSchema>;
export type ProviderFreshnessView = z.infer<typeof providerFreshnessSchema>;
export type InspirationEvaluationView = z.infer<
  typeof inspirationEvaluationSchema
>;
export type WorkQueuePage = z.infer<typeof workQueuePageSchema>;
export type WorkItemDetail = z.infer<typeof workItemDetailSchema>;
export type ScoreView = z.infer<typeof scoreSchema>;
export type IdeaView = z.infer<typeof ideaSchema>;
export type PackView = z.infer<typeof packSchema>;
export type ContradictionView = z.infer<typeof contradictionSchema>;
export type IntentAnalysisView = z.infer<typeof intentAnalysisSchema>;
export type BriefView = z.infer<typeof briefSchema>;
export type AiAttemptView = z.infer<typeof aiAttemptSchema>;
export type EligibleEvidencePage = z.infer<typeof eligibleEvidenceSchema>;
export type EligibleEvidenceItem = EligibleEvidencePage["items"][number];
export type DraftSummaryView = z.infer<typeof draftSummarySchema>;
export type DraftListPage = z.infer<typeof draftListPageSchema>;
export type DraftDetail = z.infer<typeof draftDetailSchema>;
export type DraftClaimUsageView = z.infer<typeof draftClaimUsageSchema>;
export type ReviewSummaryView = z.infer<typeof reviewSummarySchema>;
export type ReviewListPage = z.infer<typeof reviewListPageSchema>;
export type ReviewDetail = z.infer<typeof reviewDetailSchema>;
export type ReviewFindingView = z.infer<typeof reviewFindingSchema>;
export type QaReportSummaryView = z.infer<typeof qaReportSummarySchema>;
export type QaReportListPage = z.infer<typeof qaReportListPageSchema>;
export type QaReportDetail = z.infer<typeof qaReportDetailSchema>;
export type QaWaiverView = z.infer<typeof qaWaiverSchema>;
export type PublicationAttemptView = z.infer<typeof publicationAttemptSchema>;
export type PublicationPackageView = z.infer<typeof publicationPackageSchema>;
export type PublicationPage = z.infer<typeof publicationPageSchema>;
export type MediaAssetView = z.infer<typeof mediaAssetSchema>;
export type MediaSatisfactionView = z.infer<typeof mediaSatisfactionSchema>;
export type NeedCoverageView = z.infer<typeof needCoverageSchema>;
export type MediaCoveragePage = z.infer<typeof mediaCoveragePageSchema>;
export type DecisionView = z.infer<typeof decisionSchema>;
export type ApprovalStatusView = z.infer<typeof approvalStatusSchema>;
export type DecisionListPage = z.infer<typeof decisionListPageSchema>;

export type WorkQueueFilters = {
  workflowState?: (typeof WORKFLOW_STATES)[number];
  opportunityDisposition?: (typeof OPPORTUNITY_DISPOSITIONS)[number];
  search?: string;
  limit?: number;
  offset?: number;
};

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

export async function fetchWorkQueue(
  filters: WorkQueueFilters = {},
): Promise<BackendResult<WorkQueuePage>> {
  const path = `/internal/editorial/work-items${buildQuery({
    workflow_state: filters.workflowState,
    opportunity_disposition: filters.opportunityDisposition,
    search: filters.search,
    limit: filters.limit,
    offset: filters.offset,
  })}`;
  const response = await requestBackend(path);
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, workQueuePageSchema, [200]);
}

export type WorkItemDetailResult =
  BackendResult<WorkItemDetail> | { kind: "not_found" };

export async function fetchWorkItemDetail(
  workItemId: string,
): Promise<WorkItemDetailResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, workItemDetailSchema, [200]);
}

export type DraftListResult =
  BackendResult<DraftListPage> | { kind: "not_found" };

export async function fetchWorkItemDrafts(
  workItemId: string,
): Promise<DraftListResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/drafts`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, draftListPageSchema, [200]);
}

export type DraftDetailResult =
  BackendResult<DraftDetail> | { kind: "not_found" };

export async function fetchDraftDetail(
  draftId: string,
): Promise<DraftDetailResult> {
  if (!isUuid(draftId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/drafts/${encodeURIComponent(draftId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, draftDetailSchema, [200]);
}

export type ReviewListResult =
  BackendResult<ReviewListPage> | { kind: "not_found" };

export async function fetchWorkItemReviews(
  workItemId: string,
): Promise<ReviewListResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/reviews`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, reviewListPageSchema, [200]);
}

export type ReviewDetailResult =
  BackendResult<ReviewDetail> | { kind: "not_found" };

export async function fetchReviewDetail(
  reviewId: string,
): Promise<ReviewDetailResult> {
  if (!isUuid(reviewId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/reviews/${encodeURIComponent(reviewId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, reviewDetailSchema, [200]);
}

export type QaReportListResult =
  BackendResult<QaReportListPage> | { kind: "not_found" };

export async function fetchWorkItemQaReports(
  workItemId: string,
): Promise<QaReportListResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/qa-reports`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, qaReportListPageSchema, [200]);
}

export type QaReportDetailResult =
  BackendResult<QaReportDetail> | { kind: "not_found" };

export async function fetchQaReportDetail(
  reportId: string,
): Promise<QaReportDetailResult> {
  if (!isUuid(reportId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/qa-reports/${encodeURIComponent(reportId)}`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, qaReportDetailSchema, [200]);
}

export type DecisionListResult =
  BackendResult<DecisionListPage> | { kind: "not_found" };

export async function fetchWorkItemDecisions(
  workItemId: string,
): Promise<DecisionListResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/decisions`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, decisionListPageSchema, [200]);
}

export type PublicationResult =
  BackendResult<PublicationPage> | { kind: "not_found" };

export async function fetchWorkItemPublication(
  workItemId: string,
): Promise<PublicationResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/publication`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, publicationPageSchema, [200]);
}

export type MediaCoverageResult =
  BackendResult<MediaCoveragePage> | { kind: "not_found" };

export async function fetchWorkItemMedia(
  workItemId: string,
): Promise<MediaCoverageResult> {
  if (!isUuid(workItemId)) {
    return { kind: "not_found" };
  }
  const response = await requestBackend(
    `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/media`,
  );
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, mediaCoveragePageSchema, [200]);
}

export type EligibleEvidenceResult =
  BackendResult<EligibleEvidencePage> | { kind: "not_found" };

export async function fetchEligibleEvidence(
  opportunityId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<EligibleEvidenceResult> {
  if (!isUuid(opportunityId)) {
    return { kind: "not_found" };
  }
  const path =
    `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}` +
    `/eligible-evidence${buildQuery({
      limit: options.limit,
      offset: options.offset,
    })}`;
  const response = await requestBackend(path);
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not_found" };
  }
  return parseBackendResponse(response, eligibleEvidenceSchema, [200]);
}
