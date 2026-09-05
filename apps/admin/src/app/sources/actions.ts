"use server";

import { redirect } from "next/navigation";

import {
  REGISTRABLE_SOURCE_KINDS,
  registerSource,
  runSourceDiscovery,
  transitionSourceLifecycle,
  updateSourcePurpose,
  type ControlResult,
} from "@/lib/research-control-api";
import {
  SOURCE_CAPABILITIES,
  SOURCE_LIFECYCLE_STATES,
  SOURCE_ROLES,
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

// Multi-select checkboxes: keep only known values, deduplicated, in order.
function pickMany<const T extends readonly string[]>(
  formData: FormData,
  name: string,
  allowed: T,
): T[number][] {
  const seen = new Set<string>();
  const picked: T[number][] = [];
  for (const raw of formData.getAll(name)) {
    if (typeof raw !== "string") {
      continue;
    }
    const value = raw.trim();
    if ((allowed as readonly string[]).includes(value) && !seen.has(value)) {
      seen.add(value);
      picked.push(value as T[number]);
    }
  }
  return picked;
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
  // Purpose is optional for older forms; a present but unknown role is a
  // form error, never silently downgraded to the default.
  const rawRole = field(formData, "primary_role");
  const primaryRole = rawRole ? pick(rawRole, SOURCE_ROLES) : undefined;
  if (rawRole && !primaryRole) {
    redirect("/sources/new?error=invalid");
  }
  const capabilities = pickMany(formData, "capabilities", SOURCE_CAPABILITIES);

  const result = await registerSource({
    slug,
    name,
    kind,
    baseUrl,
    trustTier,
    locale: field(formData, "locale") || undefined,
    market: field(formData, "market") || undefined,
    termsNotes: field(formData, "terms_notes") || undefined,
    primaryRole,
    capabilities: capabilities.length > 0 ? capabilities : undefined,
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

export async function updateSourcePurposeAction(
  formData: FormData,
): Promise<void> {
  const sourceId = field(formData, "source_id");
  const primaryRole = pick(field(formData, "primary_role"), SOURCE_ROLES);
  if (!isUuid(sourceId) || !primaryRole) {
    redirect("/sources?error=invalid");
  }
  const capabilities = pickMany(formData, "capabilities", SOURCE_CAPABILITIES);

  const result = await updateSourcePurpose(
    sourceId,
    primaryRole,
    capabilities.length > 0 ? capabilities : undefined,
  );
  if (result.kind !== "ok") {
    redirect(`/sources?error=${errorCode(result)}`);
  }
  redirect("/sources?notice=purpose-updated");
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
