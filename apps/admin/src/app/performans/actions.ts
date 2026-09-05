"use server";

import { redirect } from "next/navigation";

import {
  decideRefresh,
  decideSuggestion,
  triggerPerformanceSync,
  type DecisionResult,
} from "@/lib/performance-api";

// The ONLY mutations on the performance pages: named, reasoned decisions
// on refresh opportunities and strategy suggestions, plus the manual
// "sync now" trigger. Approving a refresh never publishes anything — the
// backend only moves the item onto the governed rework route.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

// Decisions are also offered on the human inbox (/firsatlar); the
// redirect target stays an allow-list, never a free URL.
function returnTarget(formData: FormData): string {
  const raw = field(formData, "return_to");
  if (raw === "/firsatlar") {
    return raw;
  }
  return raw.startsWith("/performans") && !raw.includes("?")
    ? raw
    : "/performans";
}

function errorCode(result: DecisionResult): string {
  switch (result.kind) {
    case "conflict":
      return "conflict";
    case "not_found":
      return "not-found";
    case "invalid":
      return "invalid";
    case "unreachable":
      return "unreachable";
    default:
      return "malformed";
  }
}

export async function decideRefreshAction(formData: FormData): Promise<void> {
  const refreshId = field(formData, "refresh_id");
  const action = field(formData, "action");
  const reason = field(formData, "reason");
  const back = returnTarget(formData);
  if (!refreshId || !reason || (action !== "approve" && action !== "dismiss")) {
    redirect(`${back}?error=invalid#guncelleme`);
  }
  const result = await decideRefresh(refreshId, action, reason);
  if (result.kind !== "ok") {
    redirect(`${back}?error=${errorCode(result)}#guncelleme`);
  }
  redirect(
    `${back}?notice=${action === "approve" ? "refresh-approved" : "refresh-dismissed"}#guncelleme`,
  );
}

export async function decideSuggestionAction(
  formData: FormData,
): Promise<void> {
  const suggestionId = field(formData, "suggestion_id");
  const action = field(formData, "action");
  const reason = field(formData, "reason");
  const back = returnTarget(formData);
  if (
    !suggestionId ||
    !reason ||
    (action !== "accept" && action !== "ignore")
  ) {
    redirect(`${back}?error=invalid#strateji`);
  }
  const result = await decideSuggestion(suggestionId, action, reason);
  if (result.kind !== "ok") {
    redirect(`${back}?error=${errorCode(result)}#strateji`);
  }
  redirect(
    `${back}?notice=${action === "accept" ? "suggestion-accepted" : "suggestion-ignored"}#strateji`,
  );
}

export async function syncPerformanceAction(formData: FormData): Promise<void> {
  const back = returnTarget(formData);
  const result = await triggerPerformanceSync();
  if (result.kind !== "ok") {
    const code =
      result.kind === "queue_failed"
        ? "queue-failed"
        : result.kind === "unreachable"
          ? "unreachable"
          : "malformed";
    redirect(`${back}?error=${code}`);
  }
  redirect(`${back}?notice=sync-queued`);
}
