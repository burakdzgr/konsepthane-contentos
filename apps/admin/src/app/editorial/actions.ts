"use server";

import { redirect } from "next/navigation";

import {
  promoteResearchDocument,
  reopenDuplicateDocument,
  type ControlResult,
} from "@/lib/editorial-control-api";
import { isUuid } from "@/lib/research-api";

// Queue-level research-intake commands: explicit promotion of a normalized
// research document, and the operator duplicate override with a mandatory
// distinct angle. The DUPLICATE decision itself is never touched.

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

export async function promoteResearchAction(formData: FormData): Promise<void> {
  const documentId = field(formData, "normalized_document_id");
  if (!isUuid(documentId)) {
    redirect("/editorial?error=invalid");
  }
  const result = await promoteResearchDocument(documentId);
  if (result.kind !== "ok") {
    redirect(`/editorial?error=${errorCode(result)}`);
  }
  redirect("/editorial?notice=promotion-queued");
}

export async function reopenDuplicateAction(formData: FormData): Promise<void> {
  const documentId = field(formData, "normalized_document_id");
  const reason = field(formData, "reason");
  const distinctAngle = field(formData, "distinct_angle");
  if (!isUuid(documentId) || !reason || !distinctAngle) {
    redirect("/editorial?error=invalid");
  }
  const result = await reopenDuplicateDocument(
    documentId,
    reason,
    distinctAngle,
  );
  if (result.kind !== "ok") {
    redirect(`/editorial?error=${errorCode(result)}`);
  }
  redirect(`/editorial/${result.data.work_item_id}?notice=duplicate-reopened`);
}
