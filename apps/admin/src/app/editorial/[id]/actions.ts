"use server";

import { redirect } from "next/navigation";

import {
  acceptBriefForDrafting,
  acceptEditorReview,
  approvePackage,
  analyzeSearchIntent,
  buildEvidencePack,
  commissionOpportunity,
  composeContentBrief,
  deselectIdea,
  evaluateOpportunity,
  generateEditorReview,
  generateIdeaCandidates,
  generateMediaImage,
  generateWriterDraft,
  reassembleEvidencePack,
  rejectBlockedWorkItem,
  rejectOpportunity,
  rejectPackage,
  requestChangesDecision,
  revokeApproval,
  requestWriterRework,
  resolveChangesRequested,
  runQaGates,
  satisfyMediaNeed,
  unsatisfyMediaNeed,
  uploadMediaAsset,
  waiveQaGate,
  resolveContradiction,
  resolveWorkItemBlock,
  selectIdea,
  submitOperatorDraft,
  type ControlResult,
  type EvidenceSelectionInput,
} from "@/lib/editorial-control-api";
import {
  EVIDENCE_ITEM_ROLES,
  RESOLVED_CONTRADICTION_STATUSES,
} from "@/lib/editorial-api";
import { isUuid } from "@/lib/research-api";

// Server actions for one editorial work item's explicit operator commands.
// Every action is one named business decision with its own required reason
// where editorial judgment is involved; the backend/domain stays
// authoritative — a stale form receives the backend's 409, never a bypass.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function errorCode(result: ControlResult<unknown>): string {
  switch (result.kind) {
    case "conflict":
      return "conflict";
    case "invalid":
      return "invalid";
    case "not_found":
      return "not-found";
    case "queue_failed":
      return "queue-failed";
    case "unreachable":
      return "unreachable";
    default:
      return "malformed";
  }
}

function detailPath(workItemId: string, query: string): string {
  return `/editorial/${workItemId}?${query}`;
}

function requireWorkItemId(formData: FormData): string {
  const workItemId = field(formData, "work_item_id");
  if (!isUuid(workItemId)) {
    redirect("/editorial?error=invalid");
  }
  return workItemId;
}

function finish(
  workItemId: string,
  result: ControlResult<unknown>,
  notice: string,
): never {
  if (result.kind !== "ok") {
    redirect(detailPath(workItemId, `error=${errorCode(result)}`));
  }
  redirect(detailPath(workItemId, `notice=${notice}`));
}

export async function evaluateOpportunityAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const result = await evaluateOpportunity(opportunityId);
  finish(workItemId, result, "evaluation-queued");
}

export async function commissionOpportunityAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await commissionOpportunity(opportunityId, reason);
  finish(workItemId, result, "commissioned");
}

export async function rejectOpportunityAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await rejectOpportunity(opportunityId, reason);
  finish(workItemId, result, "opportunity-rejected");
}

export async function generateIdeasAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const countRaw = field(formData, "candidate_count");
  const count = /^[1-5]$/.test(countRaw) ? Number(countRaw) : undefined;
  const result = await generateIdeaCandidates(opportunityId, {
    candidateCount: count,
  });
  finish(workItemId, result, "ideas-queued");
}

export async function selectIdeaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const ideaId = field(formData, "idea_id");
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await selectIdea(ideaId, reason);
  finish(workItemId, result, "idea-selected");
}

export async function deselectIdeaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const ideaId = field(formData, "idea_id");
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await deselectIdea(ideaId, reason);
  finish(workItemId, result, "idea-deselected");
}

export async function buildEvidencePackAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const ideaId = field(formData, "idea_id");
  if (!isUuid(ideaId)) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  // The OPERATOR's explicit selection: one checkbox row per eligible
  // evidence id, with the row's role and claim cluster. Nothing is
  // auto-selected.
  const selections: EvidenceSelectionInput[] = [];
  for (const [name, value] of formData.entries()) {
    if (!name.startsWith("select-") || value !== "on") {
      continue;
    }
    const evidenceId = name.slice("select-".length);
    if (!isUuid(evidenceId)) {
      continue;
    }
    const roleValue = field(formData, `role-${evidenceId}`);
    const role = (EVIDENCE_ITEM_ROLES as readonly string[]).includes(roleValue)
      ? (roleValue as (typeof EVIDENCE_ITEM_ROLES)[number])
      : undefined;
    const claimCluster = field(formData, `cluster-${evidenceId}`);
    if (role === undefined || !claimCluster) {
      redirect(detailPath(workItemId, "error=invalid"));
    }
    const displayNote = field(formData, `note-${evidenceId}`);
    selections.push({
      researchEvidenceId: evidenceId,
      role,
      claimCluster,
      displayNote: displayNote || undefined,
    });
  }
  if (selections.length === 0) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await buildEvidencePack(opportunityId, ideaId, selections);
  finish(workItemId, result, "pack-queued");
}

export async function resolveContradictionAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const contradictionId = field(formData, "contradiction_id");
  const statusValue = field(formData, "resolution_status");
  const status = (
    RESOLVED_CONTRADICTION_STATUSES as readonly string[]
  ).includes(statusValue)
    ? (statusValue as (typeof RESOLVED_CONTRADICTION_STATUSES)[number])
    : undefined;
  const reason = field(formData, "reason");
  if (status === undefined || !reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await resolveContradiction(contradictionId, status, reason);
  finish(workItemId, result, "contradiction-resolved");
}

export async function reassemblePackAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const packId = field(formData, "pack_id");
  const result = await reassembleEvidencePack(packId);
  finish(workItemId, result, "pack-reassembled");
}

export async function resolveBlockAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await resolveWorkItemBlock(workItemId, reason);
  finish(workItemId, result, "block-resolved");
}

export async function rejectBlockedAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await rejectBlockedWorkItem(workItemId, reason);
  finish(workItemId, result, "blocked-rejected");
}

export async function analyzeSearchIntentAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const opportunityId = field(formData, "opportunity_id");
  const ideaId = field(formData, "idea_id");
  const packId = field(formData, "evidence_pack_id");
  if (!isUuid(ideaId) || !isUuid(packId)) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  // Exact chosen signal observations only — no implicit latest lookup.
  const signalIds = formData
    .getAll("signal_id")
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter((value) => isUuid(value));
  const result = await analyzeSearchIntent(opportunityId, {
    ideaId,
    evidencePackId: packId,
    searchSignalIds: signalIds,
  });
  finish(workItemId, result, "analysis-queued");
}

export async function composeBriefAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const ideaId = field(formData, "idea_id");
  const packId = field(formData, "evidence_pack_id");
  const analysisId = field(formData, "search_intent_analysis_id");
  if (!isUuid(ideaId) || !isUuid(packId) || !isUuid(analysisId)) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const supersedeReason = field(formData, "supersede_reason");
  const result = await composeContentBrief(workItemId, {
    ideaId,
    evidencePackId: packId,
    searchIntentAnalysisId: analysisId,
    supersedeReason: supersedeReason || undefined,
  });
  finish(workItemId, result, "compose-queued");
}

export async function acceptBriefAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const briefId = field(formData, "brief_id");
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await acceptBriefForDrafting(briefId, reason);
  finish(workItemId, result, "brief-accepted");
}

export async function generateDraftAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const briefId = field(formData, "brief_id");
  const retryRaw = field(formData, "retry_number");
  const retryNumber = /^([0-9]|[1-4][0-9]|50)$/.test(retryRaw)
    ? Number(retryRaw)
    : undefined;
  const supersedeReason = field(formData, "supersede_reason");
  const result = await generateWriterDraft(briefId, {
    retryNumber,
    supersedeReason: supersedeReason || undefined,
  });
  finish(workItemId, result, "draft-queued");
}

export async function submitDraftAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const briefId = field(formData, "brief_id");
  const reason = field(formData, "reason");
  const sectionsRaw = field(formData, "sections_json");
  if (!reason || !sectionsRaw) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  // The operator pastes the bounded sections payload; only JSON shape is
  // checked here — the backend/domain enforces every content rule.
  let sections: unknown;
  try {
    sections = JSON.parse(sectionsRaw);
  } catch {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  if (!Array.isArray(sections)) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const titleProposal = field(formData, "title_proposal");
  const supersedeReason = field(formData, "supersede_reason");
  const result = await submitOperatorDraft(briefId, {
    reason,
    titleProposal: titleProposal || undefined,
    supersedeReason: supersedeReason || undefined,
    sections,
  });
  finish(workItemId, result, "draft-submitted");
}

export async function requestReworkAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const responsibleRaw = field(formData, "responsible_state");
  const responsible =
    responsibleRaw === "drafting" || responsibleRaw === "editing"
      ? responsibleRaw
      : undefined;
  const result = await requestWriterRework(workItemId, reason, responsible);
  finish(workItemId, result, "rework-requested");
}

export async function runQaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await runQaGates(workItemId);
  finish(workItemId, result, "qa-queued");
}

export async function waiveQaGateAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason || field(formData, "gate_key") !== "media_needs") {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await waiveQaGate(workItemId, "media_needs", reason);
  finish(workItemId, result, "qa-gate-waived");
}

export async function resolveChangesRequestedAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await resolveChangesRequested(workItemId, reason);
  finish(workItemId, result, "changes-request-resolved");
}

export async function generateEditorReviewAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const retryRaw = field(formData, "retry_number");
  const retryNumber = /^([0-9]|[1-4][0-9]|50)$/.test(retryRaw)
    ? Number(retryRaw)
    : undefined;
  const supersedeReason = field(formData, "supersede_reason");
  const result = await generateEditorReview(workItemId, {
    retryNumber,
    supersedeReason: supersedeReason || undefined,
  });
  finish(workItemId, result, "review-queued");
}

export async function acceptReviewAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await acceptEditorReview(workItemId, reason);
  finish(workItemId, result, "review-accepted");
}

function boundedResponsible(
  formData: FormData,
): "drafting" | "editing" | "qa_review" {
  const raw = field(formData, "responsible_state");
  return raw === "editing" || raw === "qa_review" ? raw : "drafting";
}

export async function approvePackageAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await approvePackage(workItemId, reason);
  finish(workItemId, result, "package-approved");
}

export async function requestChangesDecisionAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await requestChangesDecision(
    workItemId,
    reason,
    boundedResponsible(formData),
  );
  finish(workItemId, result, "decision-changes-requested");
}

export async function rejectPackageAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await rejectPackage(workItemId, reason);
  finish(workItemId, result, "package-rejected");
}

export async function revokeApprovalAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await revokeApproval(
    workItemId,
    reason,
    boundedResponsible(formData),
  );
  finish(workItemId, result, "approval-revoked");
}

function boundedNeedIndex(formData: FormData): number | null {
  const raw = field(formData, "need_index");
  if (!/^\d{1,3}$/.test(raw)) {
    return null;
  }
  return Number.parseInt(raw, 10);
}

export async function uploadAndBindMediaAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const needIndex = boundedNeedIndex(formData);
  const file = formData.get("file");
  const altText = field(formData, "alt_text");
  const licenseNote = field(formData, "license_note");
  const reason = field(formData, "reason");
  if (
    needIndex === null ||
    !(file instanceof File) ||
    file.size === 0 ||
    !altText ||
    !licenseNote ||
    !reason
  ) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const backendForm = new FormData();
  backendForm.set("file", file);
  backendForm.set("alt_text", altText);
  backendForm.set("license_note", licenseNote);
  const title = field(formData, "title");
  if (title) {
    backendForm.set("title", title);
  }
  const attribution = field(formData, "source_attribution");
  if (attribution) {
    backendForm.set("source_attribution", attribution);
  }
  const uploaded = await uploadMediaAsset(backendForm);
  if (uploaded.kind !== "ok") {
    finish(workItemId, uploaded, "media-bound");
    return;
  }
  const bound = await satisfyMediaNeed(
    workItemId,
    needIndex,
    uploaded.data.media_asset_id,
    reason,
  );
  finish(workItemId, bound, "media-bound");
}

export async function bindMediaAssetAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const needIndex = boundedNeedIndex(formData);
  const mediaAssetId = field(formData, "media_asset_id");
  const reason = field(formData, "reason");
  if (needIndex === null || !mediaAssetId || !reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await satisfyMediaNeed(
    workItemId,
    needIndex,
    mediaAssetId,
    reason,
  );
  finish(workItemId, result, "media-bound");
}

export async function unbindMediaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const needIndex = boundedNeedIndex(formData);
  const reason = field(formData, "reason");
  if (needIndex === null || !reason) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await unsatisfyMediaNeed(workItemId, needIndex, reason);
  finish(workItemId, result, "media-unbound");
}

export async function generateMediaImageAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const needIndex = boundedNeedIndex(formData);
  if (needIndex === null) {
    redirect(detailPath(workItemId, "error=invalid"));
  }
  const result = await generateMediaImage(workItemId, needIndex);
  finish(workItemId, result, "media-image-queued");
}
