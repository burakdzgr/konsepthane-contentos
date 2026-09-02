// Shared fixtures for the editorial admin tests. Shapes mirror the backend
// read models exactly; tests override fields per scenario.

import type {
  AiAttemptView,
  BriefView,
  ContradictionView,
  DraftDetail,
  DraftListPage,
  DraftSummaryView,
  ReviewDetail,
  ReviewListPage,
  ReviewSummaryView,
  EligibleEvidenceItem,
  EligibleEvidencePage,
  IdeaView,
  IntentAnalysisView,
  PackView,
  ScoreView,
  WorkItemDetail,
  WorkQueuePage,
  WorkQueueRow,
} from "@/lib/editorial-api";

type SelectionEvent = WorkItemDetail["selection_events"][number];
type ResearchInput = WorkItemDetail["research_inputs"][number];
type WorkflowEvent = WorkItemDetail["workflow_events"][number];

export const WORK_ITEM_ID = "a1111111-2222-4333-8444-555555555555";
export const OPPORTUNITY_ID = "b1111111-2222-4333-8444-555555555555";
export const SCORE_ID = "c1111111-2222-4333-8444-555555555555";
export const IDEA_ID = "d1111111-2222-4333-8444-555555555555";
export const SECOND_IDEA_ID = "d2111111-2222-4333-8444-555555555555";
export const PACK_ID = "e1111111-2222-4333-8444-555555555555";
export const CONTRADICTION_ID = "e2111111-2222-4333-8444-555555555555";
export const ANALYSIS_ID = "f1111111-2222-4333-8444-555555555555";
export const BRIEF_ID = "a2111111-2222-4333-8444-555555555555";
export const EVIDENCE_ID = "a3111111-2222-4333-8444-555555555555";
export const SIGNAL_ID = "a4111111-2222-4333-8444-555555555555";
export const ATTEMPT_ID = "a5111111-2222-4333-8444-555555555555";
export const DOCUMENT_ID = "a6111111-2222-4333-8444-555555555555";
export const DECISION_ID = "a7111111-2222-4333-8444-555555555555";
export const SOURCE_ID = "a8111111-2222-4333-8444-555555555555";
export const DRAFT_ID = "a9111111-2222-4333-8444-555555555555";
export const CLAIM_ID = "aa111111-2222-4333-8444-555555555555";
export const REVIEW_ID = "ad111111-2222-4333-8444-555555555555";

const AT = "2026-09-01T12:00:00+00:00";

export function queueRow(overrides: Partial<WorkQueueRow> = {}): WorkQueueRow {
  return {
    work_item_id: WORK_ITEM_ID,
    title_working_label: "Evde doğum günü partisi rehberi",
    locale: "tr-TR",
    market: "TR",
    origin: "research_intake",
    current_state: "briefing",
    current_state_entered_at: AT,
    blocked_reason: null,
    rejected_reason: null,
    opportunity_id: OPPORTUNITY_ID,
    disposition: "commissioned",
    topic_summary: "Evde doğum günü partisi planlama",
    score_id: SCORE_ID,
    score_band: "strong",
    score_eligibility: "commissionable",
    score_overall_value: 0.82,
    score_missing_signals: ["search_demand"],
    score_risk_flags: [],
    score_evaluated_at: AT,
    score_engine_name: "opportunity-score",
    score_engine_version: "1",
    selected_idea_id: IDEA_ID,
    selected_idea_title: "Balon temalı plan",
    selected_idea_originality: "passed",
    latest_pack_id: PACK_ID,
    latest_pack_version: 1,
    latest_pack_sufficiency: "ready",
    latest_analysis_id: ANALYSIS_ID,
    latest_analysis_version: 1,
    latest_brief_id: BRIEF_ID,
    latest_brief_version: 1,
    latest_brief_status: "draft",
    ...overrides,
  };
}

export function queuePage(
  items: WorkQueueRow[],
  total = items.length,
): WorkQueuePage {
  return { items, total, limit: 50, offset: 0 };
}

export function scoreView(overrides: Partial<ScoreView> = {}): ScoreView {
  return {
    id: SCORE_ID,
    engine_name: "opportunity-score",
    engine_version: "1",
    overall_band: "strong",
    overall_value: 0.82,
    eligibility: "commissionable",
    missing_signals: ["search_demand"],
    risk_flags: ["single_source_risk"],
    weights_snapshot: { recency: 0.15 },
    threshold_snapshot: { strong: 0.75 },
    input_snapshot: { documents: 2 },
    evaluated_at: AT,
    created_at: AT,
    effective: true,
    components: [
      {
        component: "recency",
        availability: "known",
        value: 1,
        confidence: null,
        provider: null,
        observed_at: AT,
        provenance_ref: { basis: "fetched_at" },
      },
      {
        component: "search_demand",
        availability: "unknown",
        value: null,
        confidence: null,
        provider: null,
        observed_at: null,
        provenance_ref: {
          reason: "no durable deterministic signal source exists",
        },
      },
    ],
    ...overrides,
  };
}

export function ideaView(overrides: Partial<IdeaView> = {}): IdeaView {
  return {
    id: IDEA_ID,
    logical_idea_id: IDEA_ID,
    version: 1,
    working_title: "Balon temalı plan",
    angle: "Bütçe dostu üç saatlik hazırlık akışı.",
    audience: "Küçük çocuklu ebeveynler",
    value_proposition: "Tek listeyle eksiksiz hazırlık.",
    content_type: "planning_guide",
    locale: "tr-TR",
    market: "TR",
    rationale: "Kaynaklar genel; uygulanabilir plan veriyoruz.",
    exclusions: ["marka önerme"],
    planning_dimensions: { schema_version: 1, dimensions: { theme: "balon" } },
    originality_status: "passed",
    originality_detail: {},
    originality_policy_snapshot: {},
    origin: "model_assisted",
    generation_attempt_id: ATTEMPT_ID,
    created_at: AT,
    effective_selected: true,
    ...overrides,
  };
}

export function contradictionView(
  overrides: Partial<ContradictionView> = {},
): ContradictionView {
  return {
    id: CONTRADICTION_ID,
    pack_id: PACK_ID,
    claim_key: "sure-tahmini",
    evidence_side_a: [EVIDENCE_ID],
    evidence_side_b: ["b3111111-2222-4333-8444-555555555555"],
    nature: "Kaynaklar hazırlık süresinde uyuşmuyor.",
    severity: "material",
    resolution_status: "unresolved",
    handling_recommendation: null,
    resolution_reason: null,
    resolved_by: null,
    resolved_at: null,
    ...overrides,
  };
}

export function packView(overrides: Partial<PackView> = {}): PackView {
  return {
    id: PACK_ID,
    version: 1,
    idea_id: IDEA_ID,
    organization_attempt_id: null,
    assembler_name: "evidence-pack-assembler",
    assembler_version: "1",
    sufficiency: "ready",
    sufficiency_detail: { missing: [], unresolved_blocking_contradictions: [] },
    source_diversity: { distinct_sources: 2 },
    staleness_notes: [],
    locale_limitations: {},
    licensing_cautions: [],
    policy_snapshot: { min_evidence_items: 3 },
    assembly_input_hash: "hash",
    created_at: AT,
    items: [
      {
        id: "e3111111-2222-4333-8444-555555555555",
        research_evidence_id: EVIDENCE_ID,
        role: "key_fact",
        claim_cluster: "detaylar",
        display_note: null,
        evidence_type: "observation",
        verification_status: "unverified",
        statement: "Kaynak, konsept detaylarını belirtiyor.",
        normalized_document_id: DOCUMENT_ID,
        source_id: SOURCE_ID,
        source_slug: "ana-kaynak",
        trust_tier: "general",
        extracted_at: AT,
      },
    ],
    contradictions: [contradictionView()],
    ...overrides,
  };
}

export function analysisView(
  overrides: Partial<IntentAnalysisView> = {},
): IntentAnalysisView {
  return {
    id: ANALYSIS_ID,
    version: 1,
    idea_id: IDEA_ID,
    primary_intent: "Ev partisi planlama rehberi arayışı",
    secondary_intents: ["fikir arayışı"],
    target_audience: "Küçük çocuklu ebeveynler",
    query_concepts: ["evde doğum günü partisi"],
    page_purpose: "Uygulanabilir planlama rehberi sunmak",
    likely_format: "planlama rehberi",
    known_signal_refs: [{ signal_id: SIGNAL_ID }],
    known_signals: [
      {
        id: SIGNAL_ID,
        signal_type: "manual_intent_note",
        provider: "operator",
        subject: "evde doğum günü partisi",
        observed_at: AT,
        as_of: null,
        recorded_at: AT,
      },
    ],
    missing_signals: ["search_volume", "trend"],
    cannibalization_status: "not_checked",
    cannibalization_basis: {},
    related_references: [],
    locale: "tr-TR",
    market: "TR",
    engine_name: "search-intent-analyzer",
    engine_version: "1",
    synthesis_attempt_id: ATTEMPT_ID,
    created_at: AT,
    ...overrides,
  };
}

export function briefView(overrides: Partial<BriefView> = {}): BriefView {
  return {
    id: BRIEF_ID,
    version: 1,
    idea_id: IDEA_ID,
    evidence_pack_id: PACK_ID,
    search_intent_analysis_id: ANALYSIS_ID,
    locale: "tr-TR",
    market: "TR",
    target_audience: "Küçük çocuklu ebeveynler",
    intent_summary: "Okur evde parti planlamak istiyor.",
    original_angle: "Bütçe dostu üç saatlik akış.",
    title_guidance: { direction: "pratik plan" },
    content_objective: "Okura eksiksiz bir plan kazandırmak.",
    required_sections: [{ key: "giris" }, { key: "plan" }],
    optional_sections: [],
    practical_requirements: {},
    exclusions: ["marka önerme"],
    uncertainty_notes: ["Eksik arama sinyalleri: search_volume, trend"],
    internal_link_needs: [],
    media_needs: [],
    faq_questions: [],
    acceptance_criteria: [{ key: "claims-mapped" }],
    structure_guard_result: { outcome: "passed" },
    structure_policy_snapshot: {},
    status: "draft",
    composition_attempt_id: ATTEMPT_ID,
    engine_name: "brief-composer",
    engine_version: "1",
    content_hash: "hash",
    created_at: AT,
    claims: [
      {
        id: "b4111111-2222-4333-8444-555555555555",
        claim_key: "konsept-detaylari",
        claim_text: "Kaynaklar konsept detaylarını belirtir.",
        claim_kind: "factual",
        handling: null,
        evidence_ids: [EVIDENCE_ID],
      },
    ],
    status_events: [],
    ...overrides,
  };
}

export function attemptView(
  overrides: Partial<AiAttemptView> = {},
): AiAttemptView {
  return {
    id: ATTEMPT_ID,
    purpose: "idea_candidates",
    provider: "fake",
    model_name: "deterministic-structured-test-model",
    model_version: "1",
    schema_name: "idea-candidates",
    schema_version: "1",
    template_name: "idea-candidates",
    template_version: "1",
    input_hash: "hash",
    input_refs: { opportunity_id: OPPORTUNITY_ID },
    status: "succeeded",
    error_class: null,
    retry_number: 0,
    usage: { input_tokens: 100 },
    created_at: AT,
    ...overrides,
  };
}

export function workItemDetail(
  overrides: Partial<WorkItemDetail> = {},
): WorkItemDetail {
  return {
    work_item: {
      id: WORK_ITEM_ID,
      locale: "tr-TR",
      market: "TR",
      origin: "research_intake",
      current_state: "briefing",
      current_state_entered_at: AT,
      title_working_label: "Evde doğum günü partisi rehberi",
      blocked_reason: null,
      blocked_resume_state: null,
      rejected_reason: null,
      created_at: AT,
      updated_at: AT,
    },
    workflow_events: [
      {
        id: 4,
        from_state: "seo_research",
        to_state: "briefing",
        actor_origin: "system",
        reason: "search intent analysis ready",
        artifact_refs: { search_intent_analysis_id: ANALYSIS_ID },
        request_id: null,
        occurred_at: AT,
      },
      {
        id: 2,
        from_state: "idea_scoring",
        to_state: "evidence_building",
        actor_origin: "operator",
        reason: "operatör komisyonu",
        artifact_refs: { opportunity_id: OPPORTUNITY_ID },
        request_id: null,
        occurred_at: AT,
      },
    ],
    total_workflow_events: 2,
    workflow_events_truncated: false,
    opportunity: {
      id: OPPORTUNITY_ID,
      disposition: "commissioned",
      disposition_reason: "operatör komisyonu",
      disposition_by: "operator",
      disposition_at: AT,
      topic_summary: "Evde doğum günü partisi planlama",
      update_of_reference: null,
      promotion_root_document_id: DOCUMENT_ID,
      created_at: AT,
      updated_at: AT,
    },
    research_inputs: [
      {
        id: "b5111111-2222-4333-8444-555555555555",
        normalized_document_id: DOCUMENT_ID,
        duplicate_decision_id: DECISION_ID,
        duplicate_outcome: "unique",
        role: "primary_signal",
        added_by: "system",
        note: null,
        added_at: AT,
        document_title: "Doğum günü partisi fikirleri",
        external_published_at: null,
        fetched_at: AT,
        source_id: SOURCE_ID,
        source_slug: "ana-kaynak",
        source_name: "Ana Kaynak",
        trust_tier: "general",
      },
    ],
    scores: [scoreView()],
    total_scores: 1,
    scores_truncated: false,
    ideas: [ideaView()],
    total_ideas: 1,
    ideas_truncated: false,
    selection_events: [
      {
        id: 1,
        idea_id: IDEA_ID,
        action: "selected",
        actor_origin: "operator",
        reason: "tek aday",
        request_id: null,
        occurred_at: AT,
      },
    ],
    total_selection_events: 1,
    selection_events_truncated: false,
    effective_selected_idea_id: IDEA_ID,
    evidence_packs: [packView()],
    total_evidence_packs: 1,
    evidence_packs_truncated: false,
    intent_analyses: [analysisView()],
    total_intent_analyses: 1,
    intent_analyses_truncated: false,
    briefs: [briefView()],
    total_briefs: 1,
    briefs_truncated: false,
    ai_attempts: [attemptView()],
    ...overrides,
  };
}

export function eligiblePage(
  items: EligibleEvidenceItem[] = [],
  total = items.length,
): EligibleEvidencePage {
  return { items, total, limit: 100, offset: 0 };
}

export function eligibleEvidenceItem(
  overrides: Partial<EligibleEvidenceItem> = {},
): EligibleEvidenceItem {
  return {
    id: EVIDENCE_ID,
    evidence_type: "observation",
    verification_status: "unverified",
    statement: "Kaynak, konsept detaylarını belirtiyor.",
    extraction_method: "machine",
    confidence: null,
    licensing_notes: null,
    normalized_document_id: DOCUMENT_ID,
    source_id: SOURCE_ID,
    source_slug: "ana-kaynak",
    source_name: "Ana Kaynak",
    trust_tier: "general",
    fetched_at: AT,
    extracted_at: AT,
    ...overrides,
  };
}

export function draftSummary(
  overrides: Partial<DraftSummaryView> = {},
): DraftSummaryView {
  return {
    id: DRAFT_ID,
    work_item_id: WORK_ITEM_ID,
    content_brief_id: BRIEF_ID,
    version: 1,
    origin: "writer_engine",
    status: "active",
    engine_name: "writer",
    engine_version: "1",
    title_proposal: "Evde balon temali dogum gunu plani",
    generation_attempt_id: ATTEMPT_ID,
    manual_input_hash: null,
    superseded_by_draft_id: null,
    body_schema_version: "writer-draft-body/1",
    uncertainty_coverage_status: "evaluated",
    originality_outcome: "passed",
    content_hash: "c".repeat(64),
    created_at: AT,
    ...overrides,
  };
}

export function draftListPage(
  drafts: DraftSummaryView[] = [draftSummary()],
): DraftListPage {
  return {
    work_item_id: WORK_ITEM_ID,
    drafts,
    total: drafts.length,
    truncated: false,
  };
}

export function draftDetail(overrides: Partial<DraftDetail> = {}): DraftDetail {
  return {
    draft: draftSummary(),
    body: {
      sections: [
        {
          key: "giris",
          heading: "Neden evde parti?",
          blocks: [
            {
              block_id: "giris-1",
              kind: "paragraph",
              text: "Evde parti hem samimi hem butce dostudur.",
              claim_refs: [CLAIM_ID],
              uncertainty_refs: ["note-0"],
            },
          ],
        },
      ],
    },
    uncertainty_coverage: { status: "evaluated" },
    validation_policy_snapshot: { version: "writer-validation/1" },
    originality_policy_snapshot: { version: "writer-originality/1" },
    originality_result: { outcome: "passed" },
    claim_usages: [
      {
        id: "ab111111-2222-4333-8444-555555555555",
        brief_claim_id: CLAIM_ID,
        claim_key: "konsept-detaylari",
        claim_kind: "factual",
        claim_text: "Kaynak konsept detaylarini belirtiyor.",
        handling: "dogrudan kullan",
        section_key: "giris",
        block_id: "giris-1",
        research_evidence_ids: [EVIDENCE_ID],
      },
    ],
    status_events: [],
    generation_attempts: [
      attemptView({
        purpose: "writer_draft",
        schema_name: "writer-draft",
        template_name: "writer-draft",
      }),
    ],
    generation_attempts_truncated: false,
    ...overrides,
  };
}

export function reviewSummary(
  overrides: Partial<ReviewSummaryView> = {},
): ReviewSummaryView {
  return {
    id: REVIEW_ID,
    work_item_id: WORK_ITEM_ID,
    content_draft_id: DRAFT_ID,
    content_brief_id: BRIEF_ID,
    version: 1,
    verdict: "pass",
    status: "active",
    engine_name: "editor",
    engine_version: "1",
    generation_attempt_id: ATTEMPT_ID,
    superseded_by_review_id: null,
    finding_counts: { blocking: 0, major: 0, minor: 1 },
    writer_envelope_recomputed: true,
    content_hash: "d".repeat(64),
    created_at: AT,
    ...overrides,
  };
}

export function reviewListPage(
  reviews: ReviewSummaryView[] = [reviewSummary()],
): ReviewListPage {
  return {
    work_item_id: WORK_ITEM_ID,
    reviews,
    total: reviews.length,
    truncated: false,
  };
}

export function reviewDetail(
  overrides: Partial<ReviewDetail> = {},
): ReviewDetail {
  return {
    review: reviewSummary(),
    integrity_gate_result: {
      version: "editor-integrity/1",
      writer_envelope_recomputed: true,
      writer_envelope: {
        structure_contract: "ok",
        claim_ref_integrity: "ok",
        handling_coverage: "ok",
      },
    },
    verdict_policy_snapshot: { version: "editor-verdict/1" },
    review_scope: { content_draft_id: DRAFT_ID },
    findings: [
      {
        id: "ae111111-2222-4333-8444-555555555555",
        finding_key: "ton-notu",
        dimension: "clarity_style",
        severity: "minor",
        origin: "model_signal",
        block_id: "giris-1",
        brief_claim_id: CLAIM_ID,
        claim_key: "konsept-detaylari",
        claim_kind: "factual",
        description: "Giris tonu sadelesebilir.",
        recommendation: "Cumleleri kisalt.",
      },
    ],
    status_events: [],
    generation_attempts: [
      attemptView({
        purpose: "editor_review",
        schema_name: "editor-review",
        template_name: "editor-review",
      }),
    ],
    generation_attempts_truncated: false,
    ...overrides,
  };
}
