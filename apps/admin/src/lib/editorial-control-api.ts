import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type FetchedResponse,
} from "@/lib/contentos-api";
import {
  BRIEF_STATUSES,
  DECISION_KINDS,
  DRAFT_ORIGINS,
  DRAFT_STATUSES,
  EVIDENCE_ITEM_ROLES,
  OPPORTUNITY_DISPOSITIONS,
  PACK_SUFFICIENCIES,
  RESOLVED_CONTRADICTION_STATUSES,
  REVIEW_VERDICTS,
  WORKFLOW_STATES,
} from "@/lib/editorial-api";
import { isUuid } from "@/lib/research-api";

// Server-only module: the mutation client for the internal editorial control
// API. Every call is one explicit business command; backend failure details
// are reduced to bounded result kinds so the internal URL and transport
// configuration never reach the browser.

export type ControlResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "conflict" }
  | { kind: "invalid" }
  | { kind: "not_found" }
  | { kind: "queue_failed" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

const EDITORIAL_TASKS = [
  "promote_research",
  "evaluate_opportunity",
  "generate_idea_candidates",
  "build_evidence_pack",
  "analyze_search_intent",
  "compose_content_brief",
  "generate_writer_draft",
  "generate_editor_review",
  "run_qa_gates",
  "generate_media_image",
  "publish_package",
] as const;

const queuedResponseSchema = z.object({
  status: z.literal("queued"),
  task: z.enum(EDITORIAL_TASKS),
  entity_id: z.string().uuid(),
});

const promotionResponseSchema = z.object({
  status: z.enum(["created", "existing"]),
  work_item_id: z.string().uuid(),
  opportunity_id: z.string().uuid(),
  duplicate_outcome: z.string(),
});

const commissionResponseSchema = z.object({
  status: z.enum(["commissioned", "already_commissioned"]),
  opportunity_id: z.string().uuid(),
  disposition: z.enum(OPPORTUNITY_DISPOSITIONS),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
  opportunity_score_id: z.string().uuid().nullable(),
});

const rejectionResponseSchema = z.object({
  status: z.enum(["rejected", "already_rejected"]),
  opportunity_id: z.string().uuid(),
  disposition: z.enum(OPPORTUNITY_DISPOSITIONS),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
});

const selectionResponseSchema = z.object({
  status: z.enum(["selected", "already_selected", "deselected"]),
  idea_id: z.string().uuid(),
  opportunity_id: z.string().uuid(),
});

const contradictionResolutionResponseSchema = z.object({
  status: z.literal("resolved"),
  contradiction_id: z.string().uuid(),
  pack_id: z.string().uuid(),
  resolution_status: z.string(),
  note: z.string(),
});

const reassembleResponseSchema = z.object({
  status: z.enum(["reassembled", "unchanged"]),
  evidence_pack_id: z.string().uuid(),
  version: z.number().int(),
  sufficiency: z.enum(PACK_SUFFICIENCIES),
  note: z.string(),
});

const workItemStateResponseSchema = z.object({
  status: z.literal("updated"),
  work_item_id: z.string().uuid(),
  current_state: z.enum(WORKFLOW_STATES),
});

const draftSubmissionResponseSchema = z.object({
  status: z.enum(["created", "reused"]),
  content_draft_id: z.string().uuid(),
  draft_version: z.number().int(),
  draft_origin: z.enum(DRAFT_ORIGINS),
  draft_status: z.enum(DRAFT_STATUSES),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
});

const acceptReviewResponseSchema = z.object({
  status: z.literal("accepted"),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
  editorial_review_id: z.string().uuid(),
  review_verdict: z.enum(REVIEW_VERDICTS),
});

const waiverResponseSchema = z.object({
  status: z.literal("waived"),
  work_item_id: z.string().uuid(),
  gate_key: z.literal("media_needs"),
  note: z.string(),
});

const publicationPackageResponseSchema = z.object({
  status: z.enum(["assembled", "already_exists"]),
  publication_package_id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  version: z.number().int(),
  package_hash: z.string(),
  content_hash: z.string(),
});

const mediaUploadResponseSchema = z.object({
  status: z.enum(["registered", "already_exists"]),
  media_asset_id: z.string().uuid(),
  content_sha256: z.string(),
  media_type: z.string(),
  byte_size: z.number().int(),
});

const mediaSatisfactionResponseSchema = z.object({
  status: z.enum(["satisfied", "unsatisfied"]),
  work_item_id: z.string().uuid(),
  need_index: z.number().int(),
  satisfaction_id: z.string().uuid(),
  media_asset_id: z.string().uuid(),
});

const decisionResponseSchema = z.object({
  status: z.literal("decided"),
  decision: z.enum(DECISION_KINDS),
  human_decision_id: z.string().uuid(),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
  reviewer_username: z.string(),
});

const briefAcceptanceResponseSchema = z.object({
  status: z.enum(["accepted", "already_accepted"]),
  brief_id: z.string().uuid(),
  brief_status: z.enum(BRIEF_STATUSES),
  work_item_id: z.string().uuid(),
  work_item_state: z.enum(WORKFLOW_STATES),
});

export type QueuedResult = z.infer<typeof queuedResponseSchema>;
export type PromotionResult = z.infer<typeof promotionResponseSchema>;
export type CommissionResult = z.infer<typeof commissionResponseSchema>;
export type RejectionResult = z.infer<typeof rejectionResponseSchema>;
export type SelectionResult = z.infer<typeof selectionResponseSchema>;
export type ContradictionResolutionResult = z.infer<
  typeof contradictionResolutionResponseSchema
>;
export type ReassembleResult = z.infer<typeof reassembleResponseSchema>;
export type WorkItemStateResult = z.infer<typeof workItemStateResponseSchema>;
export type BriefAcceptanceResult = z.infer<
  typeof briefAcceptanceResponseSchema
>;
export type DraftSubmissionResult = z.infer<
  typeof draftSubmissionResponseSchema
>;
export type AcceptReviewResult = z.infer<typeof acceptReviewResponseSchema>;
export type WaiverResult = z.infer<typeof waiverResponseSchema>;
export type DecisionResult = z.infer<typeof decisionResponseSchema>;
export type MediaUploadResult = z.infer<typeof mediaUploadResponseSchema>;
export type PublicationPackageResult = z.infer<
  typeof publicationPackageResponseSchema
>;
export type MediaSatisfactionResult = z.infer<
  typeof mediaSatisfactionResponseSchema
>;

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

function guarded<T>(
  id: string,
  run: () => Promise<ControlResult<T>>,
): Promise<ControlResult<T>> {
  if (!isUuid(id)) {
    return Promise.resolve({ kind: "not_found" });
  }
  return run();
}

export function promoteResearchDocument(
  normalizedDocumentId: string,
): Promise<ControlResult<QueuedResult>> {
  return guarded(normalizedDocumentId, () =>
    postControl(
      `/internal/editorial/research/${encodeURIComponent(normalizedDocumentId)}/promote`,
      undefined,
      queuedResponseSchema,
    ),
  );
}

export function reopenDuplicateDocument(
  normalizedDocumentId: string,
  reason: string,
  distinctAngle: string,
): Promise<ControlResult<PromotionResult>> {
  return guarded(normalizedDocumentId, () =>
    postControl(
      `/internal/editorial/research/${encodeURIComponent(normalizedDocumentId)}/reopen-duplicate`,
      { reason, distinct_angle: distinctAngle },
      promotionResponseSchema,
    ),
  );
}

export function evaluateOpportunity(
  opportunityId: string,
): Promise<ControlResult<QueuedResult>> {
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/evaluate`,
      undefined,
      queuedResponseSchema,
    ),
  );
}

// ADR 0010: `overrideGate` is the named operator's explicit decision to
// commission over a weak source-base score; the backend still refuses an
// unscored opportunity and records the override on the transition.
export function commissionOpportunity(
  opportunityId: string,
  reason: string,
  options: { overrideGate?: boolean } = {},
): Promise<ControlResult<CommissionResult>> {
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/commission`,
      options.overrideGate === true
        ? { reason, override_gate: true }
        : { reason },
      commissionResponseSchema,
    ),
  );
}

export function rejectOpportunity(
  opportunityId: string,
  reason: string,
): Promise<ControlResult<RejectionResult>> {
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/reject`,
      { reason },
      rejectionResponseSchema,
    ),
  );
}

export function generateIdeaCandidates(
  opportunityId: string,
  options: { candidateCount?: number; retryNumber?: number } = {},
): Promise<ControlResult<QueuedResult>> {
  const body: Record<string, number> = {};
  if (options.candidateCount !== undefined) {
    body.candidate_count = options.candidateCount;
  }
  if (options.retryNumber !== undefined) {
    body.retry_number = options.retryNumber;
  }
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/generate-ideas`,
      body,
      queuedResponseSchema,
    ),
  );
}

export function selectIdea(
  ideaId: string,
  reason: string,
): Promise<ControlResult<SelectionResult>> {
  return guarded(ideaId, () =>
    postControl(
      `/internal/editorial/ideas/${encodeURIComponent(ideaId)}/select`,
      { reason },
      selectionResponseSchema,
    ),
  );
}

export function deselectIdea(
  ideaId: string,
  reason: string,
): Promise<ControlResult<SelectionResult>> {
  return guarded(ideaId, () =>
    postControl(
      `/internal/editorial/ideas/${encodeURIComponent(ideaId)}/deselect`,
      { reason },
      selectionResponseSchema,
    ),
  );
}

export type EvidenceSelectionInput = {
  researchEvidenceId: string;
  role: (typeof EVIDENCE_ITEM_ROLES)[number];
  claimCluster: string;
  displayNote?: string;
};

export function buildEvidencePack(
  opportunityId: string,
  ideaId: string,
  selections: EvidenceSelectionInput[],
): Promise<ControlResult<QueuedResult>> {
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/evidence-packs/build`,
      {
        idea_id: ideaId,
        selections: selections.map((entry) => ({
          research_evidence_id: entry.researchEvidenceId,
          role: entry.role,
          claim_cluster: entry.claimCluster,
          display_note: entry.displayNote ?? null,
        })),
      },
      queuedResponseSchema,
    ),
  );
}

export function resolveContradiction(
  contradictionId: string,
  resolutionStatus: (typeof RESOLVED_CONTRADICTION_STATUSES)[number],
  reason: string,
): Promise<ControlResult<ContradictionResolutionResult>> {
  return guarded(contradictionId, () =>
    postControl(
      `/internal/editorial/contradictions/${encodeURIComponent(contradictionId)}/resolve`,
      { resolution_status: resolutionStatus, reason },
      contradictionResolutionResponseSchema,
    ),
  );
}

export function reassembleEvidencePack(
  packId: string,
): Promise<ControlResult<ReassembleResult>> {
  return guarded(packId, () =>
    postControl(
      `/internal/editorial/evidence-packs/${encodeURIComponent(packId)}/reassemble`,
      undefined,
      reassembleResponseSchema,
    ),
  );
}

export function resolveWorkItemBlock(
  workItemId: string,
  reason: string,
): Promise<ControlResult<WorkItemStateResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/resolve-block`,
      { reason },
      workItemStateResponseSchema,
    ),
  );
}

export function rejectBlockedWorkItem(
  workItemId: string,
  reason: string,
): Promise<ControlResult<WorkItemStateResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/reject-blocked`,
      { reason },
      workItemStateResponseSchema,
    ),
  );
}

export function analyzeSearchIntent(
  opportunityId: string,
  input: {
    ideaId: string;
    evidencePackId: string;
    searchSignalIds?: string[];
    retryNumber?: number;
  },
): Promise<ControlResult<QueuedResult>> {
  const body: Record<string, unknown> = {
    idea_id: input.ideaId,
    evidence_pack_id: input.evidencePackId,
  };
  if (input.searchSignalIds !== undefined) {
    body.search_signal_ids = input.searchSignalIds;
  }
  if (input.retryNumber !== undefined) {
    body.retry_number = input.retryNumber;
  }
  return guarded(opportunityId, () =>
    postControl(
      `/internal/editorial/opportunities/${encodeURIComponent(opportunityId)}/analyze-search-intent`,
      body,
      queuedResponseSchema,
    ),
  );
}

export function composeContentBrief(
  workItemId: string,
  input: {
    ideaId: string;
    evidencePackId: string;
    searchIntentAnalysisId: string;
    retryNumber?: number;
    supersedeReason?: string;
  },
): Promise<ControlResult<QueuedResult>> {
  const body: Record<string, unknown> = {
    idea_id: input.ideaId,
    evidence_pack_id: input.evidencePackId,
    search_intent_analysis_id: input.searchIntentAnalysisId,
  };
  if (input.retryNumber !== undefined) {
    body.retry_number = input.retryNumber;
  }
  if (input.supersedeReason !== undefined && input.supersedeReason !== "") {
    body.supersede_reason = input.supersedeReason;
  }
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/compose-brief`,
      body,
      queuedResponseSchema,
    ),
  );
}

export function acceptBriefForDrafting(
  briefId: string,
  reason: string,
): Promise<ControlResult<BriefAcceptanceResult>> {
  return guarded(briefId, () =>
    postControl(
      `/internal/editorial/briefs/${encodeURIComponent(briefId)}/accept`,
      { reason },
      briefAcceptanceResponseSchema,
    ),
  );
}

export function generateWriterDraft(
  briefId: string,
  options: { retryNumber?: number; supersedeReason?: string } = {},
): Promise<ControlResult<QueuedResult>> {
  const body: Record<string, unknown> = {};
  if (options.retryNumber !== undefined) {
    body.retry_number = options.retryNumber;
  }
  if (options.supersedeReason !== undefined && options.supersedeReason !== "") {
    body.supersede_reason = options.supersedeReason;
  }
  return guarded(briefId, () =>
    postControl(
      `/internal/editorial/briefs/${encodeURIComponent(briefId)}/generate-draft`,
      body,
      queuedResponseSchema,
    ),
  );
}

export function submitOperatorDraft(
  briefId: string,
  input: {
    reason: string;
    titleProposal?: string;
    supersedeReason?: string;
    // The bounded writer-draft-body/1 sections payload; the backend/domain
    // is the authority on its structure and every content rule.
    sections: unknown;
  },
): Promise<ControlResult<DraftSubmissionResult>> {
  const body: Record<string, unknown> = {
    reason: input.reason,
    sections: input.sections,
  };
  if (input.titleProposal !== undefined && input.titleProposal !== "") {
    body.title_proposal = input.titleProposal;
  }
  if (input.supersedeReason !== undefined && input.supersedeReason !== "") {
    body.supersede_reason = input.supersedeReason;
  }
  return guarded(briefId, () =>
    postControl(
      `/internal/editorial/briefs/${encodeURIComponent(briefId)}/submit-draft`,
      body,
      draftSubmissionResponseSchema,
    ),
  );
}

export function generateEditorReview(
  workItemId: string,
  options: { retryNumber?: number; supersedeReason?: string } = {},
): Promise<ControlResult<QueuedResult>> {
  const body: Record<string, unknown> = {};
  if (options.retryNumber !== undefined) {
    body.retry_number = options.retryNumber;
  }
  if (options.supersedeReason !== undefined && options.supersedeReason !== "") {
    body.supersede_reason = options.supersedeReason;
  }
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/generate-editor-review`,
      body,
      queuedResponseSchema,
    ),
  );
}

export function acceptEditorReview(
  workItemId: string,
  reason: string,
): Promise<ControlResult<AcceptReviewResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/accept-review`,
      { reason },
      acceptReviewResponseSchema,
    ),
  );
}

export function requestWriterRework(
  workItemId: string,
  reason: string,
  responsibleState?: "drafting" | "editing",
): Promise<ControlResult<WorkItemStateResult>> {
  const body: Record<string, unknown> = { reason };
  if (responsibleState !== undefined) {
    body.responsible_state = responsibleState;
  }
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/request-rework`,
      body,
      workItemStateResponseSchema,
    ),
  );
}

export function runQaGates(
  workItemId: string,
): Promise<ControlResult<QueuedResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/run-qa`,
      undefined,
      queuedResponseSchema,
    ),
  );
}

export function waiveQaGate(
  workItemId: string,
  gateKey: "media_needs",
  reason: string,
): Promise<ControlResult<WaiverResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/waive-qa-gate`,
      { gate_key: gateKey, reason },
      waiverResponseSchema,
    ),
  );
}

export function resolveChangesRequested(
  workItemId: string,
  reason: string,
): Promise<ControlResult<WorkItemStateResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/resolve-changes-requested`,
      { reason },
      workItemStateResponseSchema,
    ),
  );
}

export function approvePackage(
  workItemId: string,
  reason: string,
): Promise<ControlResult<DecisionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/approve`,
      { reason },
      decisionResponseSchema,
    ),
  );
}

export function requestChangesDecision(
  workItemId: string,
  reason: string,
  responsibleState: "drafting" | "editing" | "qa_review",
): Promise<ControlResult<DecisionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/request-changes`,
      { reason, responsible_state: responsibleState },
      decisionResponseSchema,
    ),
  );
}

export function rejectPackage(
  workItemId: string,
  reason: string,
): Promise<ControlResult<DecisionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/reject-package`,
      { reason },
      decisionResponseSchema,
    ),
  );
}

export function revokeApproval(
  workItemId: string,
  reason: string,
  responsibleState: "drafting" | "editing" | "qa_review",
): Promise<ControlResult<DecisionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/revoke-approval`,
      { reason, responsible_state: responsibleState },
      decisionResponseSchema,
    ),
  );
}

export async function uploadMediaAsset(
  form: FormData,
): Promise<ControlResult<MediaUploadResult>> {
  const response = await requestBackend("/internal/editorial/media-assets", {
    method: "POST",
    formBody: form,
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  const failure = failureKind(response);
  if (failure !== null) {
    return failure;
  }
  const parsed = await parseBackendResponse(
    response,
    mediaUploadResponseSchema,
    [200],
  );
  return parsed.kind === "ok" ? { kind: "ok", data: parsed.data } : parsed;
}

export function satisfyMediaNeed(
  workItemId: string,
  needIndex: number,
  mediaAssetId: string,
  reason: string,
): Promise<ControlResult<MediaSatisfactionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/media-needs/${needIndex}/satisfy`,
      { media_asset_id: mediaAssetId, reason },
      mediaSatisfactionResponseSchema,
    ),
  );
}

export function unsatisfyMediaNeed(
  workItemId: string,
  needIndex: number,
  reason: string,
): Promise<ControlResult<MediaSatisfactionResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/media-needs/${needIndex}/unsatisfy`,
      { reason },
      mediaSatisfactionResponseSchema,
    ),
  );
}

export function generateMediaImage(
  workItemId: string,
  needIndex: number,
): Promise<ControlResult<QueuedResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/media-needs/${needIndex}/generate-image`,
      undefined,
      queuedResponseSchema,
    ),
  );
}

export function assemblePublicationPackage(
  workItemId: string,
): Promise<ControlResult<PublicationPackageResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/assemble-publication-package`,
      undefined,
      publicationPackageResponseSchema,
    ),
  );
}

export function schedulePublication(
  workItemId: string,
  publicationPackageId: string,
  reason: string,
): Promise<ControlResult<WorkItemStateResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/schedule-publication`,
      { publication_package_id: publicationPackageId, reason },
      workItemStateResponseSchema,
    ),
  );
}

export function publishWorkItem(
  workItemId: string,
): Promise<ControlResult<QueuedResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/publish`,
      undefined,
      queuedResponseSchema,
    ),
  );
}

export function resolveApprovalExpired(
  workItemId: string,
  reason: string,
): Promise<ControlResult<WorkItemStateResult>> {
  return guarded(workItemId, () =>
    postControl(
      `/internal/editorial/work-items/${encodeURIComponent(workItemId)}/resolve-approval-expired`,
      { reason },
      workItemStateResponseSchema,
    ),
  );
}
