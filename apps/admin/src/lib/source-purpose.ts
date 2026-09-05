import { SOURCE_CAPABILITIES, SOURCE_ROLES } from "@/lib/research-api";

// Operator vocabulary for the editorial PURPOSE of a source. `kind` stays
// technical (how content is acquired); role + capabilities say what the
// pipeline may use the source for. Labels live here (not in tr-labels)
// because `trend` / `search` / `taxonomy` are shared keys whose generic
// translation differs from the purpose wording.

export type SourceRole = (typeof SOURCE_ROLES)[number];
export type SourceCapability = (typeof SOURCE_CAPABILITIES)[number];

export const PURPOSE_QUESTION = "Bu kaynak ne için kullanılsın?";

export const SOURCE_ROLE_LABELS: Record<SourceRole, string> = {
  inspiration: "Fikir / İlham",
  turkish_editorial: "Türk editoryal",
  community_intent: "Topluluk / kullanıcı niyeti",
  competitor: "Rakip",
  taxonomy: "Taksonomi / pazar",
  trend: "Trend sinyali",
  search: "Arama sinyali",
};

export const SOURCE_CAPABILITY_LABELS: Record<SourceCapability, string> = {
  inspiration: "Fikir / İlham",
  market: "Türkiye Pazar Sinyali",
  community_need: "Kullanıcı İhtiyacı",
  competition: "Rakip / İçerik Karşılaştırması",
  taxonomy: "Taksonomi",
  trend: "Trend",
  visual_trend: "Görsel Trend",
  search: "Arama Sinyali",
};

export function roleLabel(value: string): string {
  return (SOURCE_ROLE_LABELS as Record<string, string>)[value] ?? "Bilinmiyor";
}

export function capabilityLabel(value: string): string {
  return (
    (SOURCE_CAPABILITY_LABELS as Record<string, string>)[value] ?? "Bilinmiyor"
  );
}

// Community sources never become ResearchEvidence sources (backend
// `SourceRegistryService.evidence_allowed`); the UI only echoes the rule.
export function evidenceAllowed(primaryRole: string): boolean {
  return primaryRole !== "community_intent";
}
