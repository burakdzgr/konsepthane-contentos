import type { WorkQueueRow } from "@/lib/editorial-api";
import { pickEnum, type RawSearchParams } from "@/lib/search-params";

// Inbox groups for the reviewed-opportunity queue. Values are Turkish URL
// tokens (the operator sees them in the address bar); they map onto the
// read model's own facts — `commission_eligible` is the backend's
// commissioning gate, never a UI guess.
//
// The DEFAULT view is "karar": only opportunities the operator can actually
// commission. A weak / not-commissionable source base is not a decision to
// make, it is a card to eliminate — it lives under "elenecek" with bulk
// reject, never in the decision inbox.

export const MAX_BULK_ITEMS = 50;
export const BULK_SCOPES = ["secili", "listelenen"] as const;

export const INBOX_GROUPS = ["karar", "orta", "elenecek", "hepsi"] as const;
export const DEFAULT_GROUP: InboxGroup = "karar";
export const RECOMMENDATION_FILTERS = [
  "uret",
  "insan-incelemesi",
  "ele",
] as const;

export type InboxGroup = (typeof INBOX_GROUPS)[number];
export type RecommendationFilter = (typeof RECOMMENDATION_FILTERS)[number];

export const INBOX_GROUP_LABELS: Record<InboxGroup, string> = {
  karar: "Karar bekleyen",
  orta: "Orta kaynak tabanı",
  elenecek: "Elenecekler",
  hepsi: "Tümü",
};

export const INBOX_GROUP_HINTS: Record<InboxGroup, string> = {
  karar:
    "Kaynak tabanı görevlendirilebilir; üretim onayı verilebilir. Yalnızca bu grup sizden karar bekler.",
  orta: "Kaynak tabanı orta; görevlendirilemez. Yeni araştırma girdisi ve yeniden değerlendirme gerekir ya da reddedin.",
  elenecek:
    "Kaynak tabanı zayıf (tek kaynak, eski yazı, az kanıt) ya da skor yok; görevlendirilemez. Buradan toplu reddedebilirsiniz.",
  hepsi: "Skoru ne olursa olsun tüm açık fırsatlar.",
};

export const RECOMMENDATION_FILTER_LABELS: Record<
  RecommendationFilter,
  string
> = {
  uret: "İçerik üret",
  "insan-incelemesi": "İnsan incelemesi",
  ele: "Ele",
};

const RECOMMENDATION_BY_FILTER: Record<RecommendationFilter, string> = {
  uret: "produce",
  "insan-incelemesi": "human_review",
  ele: "eliminate",
};

export type InboxFilters = {
  durum: InboxGroup;
  oneri: RecommendationFilter | undefined;
};

export function parseInboxFilters(query: RawSearchParams): InboxFilters {
  return {
    durum: pickEnum(query.durum, INBOX_GROUPS) ?? DEFAULT_GROUP,
    oneri: pickEnum(query.oneri, RECOMMENDATION_FILTERS),
  };
}

// Which group a row belongs to, from the backend's own facts.
export function inboxGroupOf(row: WorkQueueRow): Exclude<InboxGroup, "hepsi"> {
  if (row.commission_eligible) {
    return "karar";
  }
  if (row.score_eligibility === "needs_operator_review") {
    return "orta";
  }
  return "elenecek";
}

export function matchesInboxFilters(
  row: WorkQueueRow,
  filters: InboxFilters,
): boolean {
  if (filters.durum !== "hepsi" && inboxGroupOf(row) !== filters.durum) {
    return false;
  }
  if (
    filters.oneri !== undefined &&
    row.recommendation !== RECOMMENDATION_BY_FILTER[filters.oneri]
  ) {
    return false;
  }
  return true;
}
