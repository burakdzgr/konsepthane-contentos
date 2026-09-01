"use server";

import { redirect } from "next/navigation";

import {
  acceptDiscoveryItem,
  rejectDiscoveryItem,
  requeueDiscoveryItem,
  startDiscoveryItemFetch,
  type ControlResult,
} from "@/lib/research-control-api";
import { DISCOVERY_REJECTION_REASONS, isUuid } from "@/lib/research-api";

// Server actions for one DiscoveryItem's operator decisions. Accept and
// fetch stay two separate actions on purpose: the Phase 2 admission boundary
// is an explicit operator decision, and execution is a second one.

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

function detailPath(itemId: string, query: string): string {
  return `/research/${itemId}?${query}`;
}

function requireItemId(formData: FormData): string {
  const itemId = field(formData, "discovery_item_id");
  if (!isUuid(itemId)) {
    redirect("/research?error=invalid");
  }
  return itemId;
}

export async function acceptDiscoveryItemAction(
  formData: FormData,
): Promise<void> {
  const itemId = requireItemId(formData);
  const result = await acceptDiscoveryItem(itemId);
  if (result.kind !== "ok") {
    redirect(detailPath(itemId, `error=${errorCode(result)}`));
  }
  redirect(detailPath(itemId, "notice=accepted"));
}

export async function rejectDiscoveryItemAction(
  formData: FormData,
): Promise<void> {
  const itemId = requireItemId(formData);
  const reasonValue = field(formData, "reason");
  const reason = (DISCOVERY_REJECTION_REASONS as readonly string[]).includes(
    reasonValue,
  )
    ? (reasonValue as (typeof DISCOVERY_REJECTION_REASONS)[number])
    : undefined;
  if (!reason) {
    redirect(detailPath(itemId, "error=invalid"));
  }

  const result = await rejectDiscoveryItem(
    itemId,
    reason,
    field(formData, "note") || undefined,
  );
  if (result.kind !== "ok") {
    redirect(detailPath(itemId, `error=${errorCode(result)}`));
  }
  redirect(detailPath(itemId, "notice=rejected"));
}

export async function requeueDiscoveryItemAction(
  formData: FormData,
): Promise<void> {
  const itemId = requireItemId(formData);
  const reason = field(formData, "reason");
  if (!reason) {
    redirect(detailPath(itemId, "error=invalid"));
  }

  const result = await requeueDiscoveryItem(itemId, reason);
  if (result.kind !== "ok") {
    redirect(detailPath(itemId, `error=${errorCode(result)}`));
  }
  redirect(detailPath(itemId, "notice=requeued"));
}

export async function startDiscoveryItemFetchAction(
  formData: FormData,
): Promise<void> {
  const itemId = requireItemId(formData);
  const result = await startDiscoveryItemFetch(itemId);
  if (result.kind !== "ok") {
    redirect(detailPath(itemId, `error=${errorCode(result)}`));
  }
  redirect(detailPath(itemId, "notice=fetch-queued"));
}
