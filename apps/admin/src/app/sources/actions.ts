"use server";

import { redirect } from "next/navigation";

import {
  REGISTRABLE_SOURCE_KINDS,
  registerSource,
  runSourceDiscovery,
  transitionSourceLifecycle,
  type ControlResult,
} from "@/lib/research-control-api";
import {
  SOURCE_LIFECYCLE_STATES,
  TRUST_TIERS,
  isUuid,
} from "@/lib/research-api";

// Server actions only: the browser posts forms to the admin server, which
// calls the internal control API. No backend URL or raw error ever reaches
// the browser — failures become bounded notice codes in the redirect URL.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function pick<const T extends readonly string[]>(
  value: string,
  allowed: T,
): T[number] | undefined {
  return (allowed as readonly string[]).includes(value)
    ? (value as T[number])
    : undefined;
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

export async function registerSourceAction(formData: FormData): Promise<void> {
  const kind = pick(field(formData, "kind"), REGISTRABLE_SOURCE_KINDS);
  const trustTier = pick(field(formData, "trust_tier"), TRUST_TIERS);
  const slug = field(formData, "slug");
  const name = field(formData, "name");
  const baseUrl = field(formData, "base_url");
  if (!kind || !trustTier || !slug || !name || !baseUrl) {
    redirect("/sources/new?error=invalid");
  }

  const result = await registerSource({
    slug,
    name,
    kind,
    baseUrl,
    trustTier,
    locale: field(formData, "locale") || undefined,
    market: field(formData, "market") || undefined,
    termsNotes: field(formData, "terms_notes") || undefined,
  });
  if (result.kind !== "ok") {
    redirect(`/sources/new?error=${errorCode(result)}`);
  }
  redirect(
    `/sources?notice=${
      result.data.status === "existing"
        ? "source-existing"
        : "source-registered"
    }`,
  );
}

export async function transitionSourceLifecycleAction(
  formData: FormData,
): Promise<void> {
  const sourceId = field(formData, "source_id");
  const newState = pick(field(formData, "new_state"), SOURCE_LIFECYCLE_STATES);
  const reason = field(formData, "reason");
  if (!isUuid(sourceId) || !newState || !reason) {
    redirect("/sources?error=invalid");
  }

  const result = await transitionSourceLifecycle(sourceId, newState, reason);
  if (result.kind !== "ok") {
    redirect(`/sources?error=${errorCode(result)}`);
  }
  redirect("/sources?notice=lifecycle-updated");
}

export async function runSourceDiscoveryAction(
  formData: FormData,
): Promise<void> {
  const sourceId = field(formData, "source_id");
  if (!isUuid(sourceId)) {
    redirect("/sources?error=invalid");
  }

  const result = await runSourceDiscovery(sourceId);
  if (result.kind !== "ok") {
    redirect(`/sources?error=${errorCode(result)}`);
  }
  redirect("/sources?notice=discovery-queued");
}
