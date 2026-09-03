"use server";

import { redirect } from "next/navigation";

import {
  acceptBriefForDrafting,
  acceptEditorReview,
  analyzeSearchIntent,
  approvePackage,
  assemblePublicationPackage,
  composeContentBrief,
  evaluateOpportunity,
  generateEditorReview,
  generateIdeaCandidates,
  generateWriterDraft,
  promoteResearchDocument,
  publishWorkItem,
  requestChangesDecision,
  resolveApprovalExpired,
  resolveChangesRequested,
  resolveWorkItemBlock,
  runQaGates,
  schedulePublication,
  selectIdea,
  waiveQaGate,
  type ControlResult,
} from "@/lib/editorial-control-api";
import {
  acceptDiscoveryItem,
  runSourceDiscovery,
  startDiscoveryItemFetch,
} from "@/lib/research-control-api";
import { isUuid } from "@/lib/research-api";

// The Motor's server actions: the SAME control-api commands the detail
// pages use, differing only in where they land afterwards — always back
// on /motor so the operator never leaves the single-page engine.

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

function motorPath(workItemId: string | null, query: string): string {
  if (workItemId === null) {
    return `/motor?${query}`;
  }
  return `/motor?item=${encodeURIComponent(workItemId)}&${query}`;
}

function finish(
  workItemId: string | null,
  result: ControlResult<unknown>,
  notice: string,
): never {
  if (result.kind !== "ok") {
    redirect(motorPath(workItemId, `error=${errorCode(result)}`));
  }
  redirect(motorPath(workItemId, `notice=${notice}`));
}

function requireWorkItemId(formData: FormData): string {
  const workItemId = field(formData, "work_item_id");
  if (!isUuid(workItemId)) {
    redirect("/motor?error=invalid");
  }
  return workItemId;
}

function requireReason(formData: FormData, workItemId: string | null): string {
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(motorPath(workItemId, "error=invalid"));
  }
  return reason;
}

// --- Giriş bölümü: kaynak, keşif, yükseltme -------------------------------

export async function motorRunDiscoveryAction(
  formData: FormData,
): Promise<void> {
  const sourceId = field(formData, "source_id");
  const result = await runSourceDiscovery(sourceId);
  finish(null, result, "kesif-kuyrukta");
}

export async function motorAcceptDiscoveryAction(
  formData: FormData,
): Promise<void> {
  const itemId = field(formData, "discovery_item_id");
  const result = await acceptDiscoveryItem(itemId);
  finish(null, result, "kesif-kabul");
}

export async function motorFetchDiscoveryAction(
  formData: FormData,
): Promise<void> {
  const itemId = field(formData, "discovery_item_id");
  const result = await startDiscoveryItemFetch(itemId);
  finish(null, result, "getirme-kuyrukta");
}

export async function motorPromoteAction(formData: FormData): Promise<void> {
  const documentId = field(formData, "normalized_document_id");
  if (!isUuid(documentId)) {
    redirect("/motor?error=invalid");
  }
  const result = await promoteResearchDocument(documentId);
  finish(null, result, "yukseltme-kuyrukta");
}

// --- Seçili işin aşama adımları -------------------------------------------

export async function motorEvaluateAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await evaluateOpportunity(field(formData, "opportunity_id"));
  finish(workItemId, result, "puanlama-kuyrukta");
}

export async function motorGenerateIdeasAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await generateIdeaCandidates(
    field(formData, "opportunity_id"),
    {},
  );
  finish(workItemId, result, "fikirler-kuyrukta");
}

export async function motorSelectIdeaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await selectIdea(field(formData, "idea_id"), reason);
  finish(workItemId, result, "fikir-secildi");
}

export async function motorAnalyzeIntentAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const ideaId = field(formData, "idea_id");
  const packId = field(formData, "evidence_pack_id");
  if (!isUuid(ideaId) || !isUuid(packId)) {
    redirect(motorPath(workItemId, "error=invalid"));
  }
  const result = await analyzeSearchIntent(field(formData, "opportunity_id"), {
    ideaId,
    evidencePackId: packId,
    searchSignalIds: [],
  });
  finish(workItemId, result, "analiz-kuyrukta");
}

export async function motorComposeBriefAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const ideaId = field(formData, "idea_id");
  const packId = field(formData, "evidence_pack_id");
  const analysisId = field(formData, "search_intent_analysis_id");
  if (!isUuid(ideaId) || !isUuid(packId) || !isUuid(analysisId)) {
    redirect(motorPath(workItemId, "error=invalid"));
  }
  const result = await composeContentBrief(workItemId, {
    ideaId,
    evidencePackId: packId,
    searchIntentAnalysisId: analysisId,
  });
  finish(workItemId, result, "brief-kuyrukta");
}

export async function motorAcceptBriefAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await acceptBriefForDrafting(
    field(formData, "brief_id"),
    reason,
  );
  finish(workItemId, result, "brief-kabul");
}

export async function motorGenerateDraftAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await generateWriterDraft(field(formData, "brief_id"), {});
  finish(workItemId, result, "taslak-kuyrukta");
}

export async function motorGenerateReviewAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await generateEditorReview(workItemId, {});
  finish(workItemId, result, "inceleme-kuyrukta");
}

export async function motorAcceptReviewAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await acceptEditorReview(workItemId, reason);
  finish(workItemId, result, "inceleme-kabul");
}

export async function motorRunQaAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await runQaGates(workItemId);
  finish(workItemId, result, "qa-kuyrukta");
}

export async function motorWaiveQaGateAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await waiveQaGate(workItemId, "media_needs", reason);
  finish(workItemId, result, "qa-kapisi-atlandi");
}

export async function motorApproveAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await approvePackage(workItemId, reason);
  finish(workItemId, result, "paket-onaylandi");
}

export async function motorRequestChangesAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const responsibleRaw = field(formData, "responsible_state");
  const responsible =
    responsibleRaw === "editing" || responsibleRaw === "qa_review"
      ? responsibleRaw
      : "drafting";
  const result = await requestChangesDecision(workItemId, reason, responsible);
  finish(workItemId, result, "degisiklik-istendi");
}

export async function motorAssemblePackageAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await assemblePublicationPackage(workItemId);
  finish(workItemId, result, "paket-birlestirildi");
}

export async function motorSchedulePublicationAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const packageId = field(formData, "publication_package_id");
  if (!packageId) {
    redirect(motorPath(workItemId, "error=invalid"));
  }
  const result = await schedulePublication(workItemId, packageId, reason);
  finish(workItemId, result, "yayin-zamanlandi");
}

export async function motorPublishNowAction(formData: FormData): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const result = await publishWorkItem(workItemId);
  finish(workItemId, result, "yayin-kuyrukta");
}

export async function motorResolveBlockAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await resolveWorkItemBlock(workItemId, reason);
  finish(workItemId, result, "blok-cozuldu");
}

export async function motorResolveChangesRequestedAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await resolveChangesRequested(workItemId, reason);
  finish(workItemId, result, "degisiklik-cozuldu");
}

export async function motorResolveApprovalExpiredAction(
  formData: FormData,
): Promise<void> {
  const workItemId = requireWorkItemId(formData);
  const reason = requireReason(formData, workItemId);
  const result = await resolveApprovalExpired(workItemId, reason);
  finish(workItemId, result, "onay-suresi-cozuldu");
}
