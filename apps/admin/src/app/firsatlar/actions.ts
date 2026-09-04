"use server";

import { redirect } from "next/navigation";

import {
  commissionOpportunity,
  rejectOpportunity,
  type ControlResult,
} from "@/lib/editorial-control-api";
import { isUuid } from "@/lib/research-api";
import { buildPageQuery } from "@/lib/search-params";
import { MAX_BULK_ITEMS, parseInboxFilters } from "./filters";

// Bulk operator decisions on the reviewed-opportunity inbox. Each item is
// still ONE named backend command with the shared written reason — there is
// no bulk endpoint and no bypass: a card the domain gate refuses comes back
// as a 409 and is counted truthfully as "çelişen", never silently dropped.
// The bounded batch is the page's own listing (max 50 rows).

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function uuidList(formData: FormData, name: string): string[] {
  const seen = new Set<string>();
  for (const entry of formData.getAll(name)) {
    if (typeof entry === "string" && isUuid(entry)) {
      seen.add(entry);
    }
  }
  return [...seen].slice(0, MAX_BULK_ITEMS);
}

function finish(
  formData: FormData,
  extra: Record<string, string | number | undefined>,
): never {
  const filters = parseInboxFilters({
    durum: field(formData, "durum"),
    oneri: field(formData, "oneri"),
  });
  redirect(`/firsatlar${buildPageQuery({ ...filters, ...extra })}`);
}

// The chosen scope decides the batch: the ticked cards, or every card the
// current filter listed (ids the page itself rendered as hidden inputs).
function targets(formData: FormData): string[] {
  return field(formData, "kapsam") === "listelenen"
    ? uuidList(formData, "listelenen")
    : uuidList(formData, "secili");
}

async function runBatch(
  ids: string[],
  command: (opportunityId: string) => Promise<ControlResult<unknown>>,
): Promise<{ basarili: number; celisen: number; hatali: number }> {
  const outcome = { basarili: 0, celisen: 0, hatali: 0 };
  // Sequential on purpose: each call takes the work item's row lock on the
  // backend, and a bounded batch must never stampede the API.
  for (const id of ids) {
    const result = await command(id);
    if (result.kind === "ok") {
      outcome.basarili += 1;
    } else if (result.kind === "conflict") {
      outcome.celisen += 1;
    } else {
      outcome.hatali += 1;
    }
  }
  return outcome;
}

export async function bulkRejectAction(formData: FormData): Promise<void> {
  const reason = field(formData, "reason");
  const ids = targets(formData);
  if (!reason || ids.length === 0) {
    finish(formData, { error: "invalid" });
  }
  const outcome = await runBatch(ids, (id) => rejectOpportunity(id, reason));
  finish(formData, { toplu: "ret", ...outcome, atlanan: 0 });
}

export async function bulkCommissionAction(formData: FormData): Promise<void> {
  const reason = field(formData, "reason");
  const ids = targets(formData);
  if (!reason || ids.length === 0) {
    finish(formData, { error: "invalid" });
  }
  // Only cards the read model marked commission_eligible are sent; the rest
  // are reported as skipped instead of producing a wall of 409s. The
  // backend gate still decides — a stale card still comes back "çelişen".
  // With the explicit ADR 0010 override ticked, cards the read model marked
  // commission_override_possible are sent too, flagged as overrides.
  const eligible = new Set(uuidList(formData, "onaylanabilir"));
  const overrideGate = field(formData, "override_gate") === "true";
  const overridable = overrideGate
    ? new Set(uuidList(formData, "asilabilir"))
    : new Set<string>();
  const sendable = ids.filter((id) => eligible.has(id) || overridable.has(id));
  const outcome = await runBatch(sendable, (id) =>
    commissionOpportunity(id, reason, {
      overrideGate: !eligible.has(id) && overridable.has(id),
    }),
  );
  finish(formData, {
    toplu: "onay",
    ...outcome,
    atlanan: ids.length - sendable.length,
  });
}
