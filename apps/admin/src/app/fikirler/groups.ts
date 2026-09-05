import type { WorkQueueRow } from "@/lib/editorial-api";

// Idea grouping for the Fikirler page (kept outside the page module: Next.js
// pages may only export page fields).
export const IDEA_GROUPS = [
  "guclu",
  "incelenmeli",
  "arastirma",
  "elenen",
] as const;
export type IdeaGroup = (typeof IDEA_GROUPS)[number];

export const IDEA_GROUP_LABELS: Record<IdeaGroup, string> = {
  guclu: "Güçlü fikirler",
  incelenmeli: "İncelenmeli",
  arastirma: "Araştırma sürüyor",
  elenen: "Elenenler",
};

export const IDEA_GROUP_HINTS: Record<IdeaGroup, string> = {
  guclu:
    "Sistem üretim öneriyor ya da ilham değeri yüksek. Neden güçlü olduğu her kartta yazar.",
  incelenmeli:
    "Sinyaller dengeli değil; editoryal göz gerekiyor. Karar Benden Bekleyenler'de sorulur.",
  arastirma:
    "Değerlendirme sürüyor ya da mevcut fikirler henüz yeterince güçlü değil; sistem araştırmaya devam ediyor.",
  elenen:
    "İlham ve temel uygunluk birlikte zayıf. Kayıt silinmez; gerekçesi kartta kalır.",
};

// Which group a row belongs to, from the backend's own verdicts: the
// recommendation first, then the inspiration band. Never a UI guess.
export function ideaGroupOf(row: WorkQueueRow): IdeaGroup {
  if (row.inspiration_evaluation_id === null) {
    // Not evaluated yet: nothing is "strong" before the engine has spoken.
    return "arastirma";
  }
  if (row.recommendation === "eliminate") {
    return "elenen";
  }
  const band =
    row.intelligence?.content_value.inspiration_band ?? row.inspiration_band;
  if (
    row.recommendation === "produce" ||
    band === "high" ||
    band === "very_high"
  ) {
    return "guclu";
  }
  if (row.recommendation === "continue_research") {
    return "arastirma";
  }
  return "incelenmeli";
}
