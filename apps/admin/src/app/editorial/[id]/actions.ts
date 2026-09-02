"use server";

import { redirect } from "next/navigation";

import {
  acceptBriefForDrafting,
  analyzeSearchIntent,
  buildEvidencePack,
  commissionOpportunity,
  composeContentBrief,
  deselectIdea,
  evaluateOpportunity,
  generateIdeaCandidates,
  reassembleEvidencePack,
  rejectBlockedWorkItem,
  rejectOpportunity,
  resolveContradiction,
  resolveWorkItemBlock,
  selectIdea,
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
