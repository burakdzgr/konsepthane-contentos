"use server";

import { redirect } from "next/navigation";

import { controlIntakeRun, startIntakeRun } from "@/lib/intake-api";
import { isUuid } from "@/lib/research-api";

// Run-lifecycle commands only: starting publishes exactly one step job;
// pause/resume/stop are audited controls. No editorial state is touched.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function errorCode(kind: string): string {
  switch (kind) {
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

export async function startIntakeRunAction(formData: FormData): Promise<void> {
  const sourceId = field(formData, "source_id");
  const backTo = field(formData, "back_to") || "/sources";
  if (!isUuid(sourceId)) {
    redirect(`${backTo}?error=invalid`);
  }
  const result = await startIntakeRun(sourceId);
  if (result.kind !== "ok") {
    redirect(`${backTo}?error=${errorCode(result.kind)}`);
  }
  // The acceptance rule: the running operation opens IMMEDIATELY.
  redirect(`/calisma/${result.data.run_id}?notice=baslatildi`);
}

export async function controlIntakeRunAction(
  formData: FormData,
): Promise<void> {
  const runId = field(formData, "run_id");
  const action = field(formData, "action");
  const reason = field(formData, "reason");
  if (
    !isUuid(runId) ||
    !reason ||
    (action !== "pause" && action !== "resume" && action !== "stop")
  ) {
    redirect("/calisma?error=invalid");
  }
  const result = await controlIntakeRun(runId, action, reason);
  if (result.kind !== "ok") {
    redirect(`/calisma/${runId}?error=${errorCode(result.kind)}`);
  }
  const notice =
    action === "pause"
      ? "duraklatildi"
      : action === "resume"
        ? "devam"
        : "durduruldu";
  redirect(`/calisma/${runId}?notice=${notice}`);
}
