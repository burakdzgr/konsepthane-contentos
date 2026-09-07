import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

const record = z.record(z.string(), z.unknown());

const missionSchema = z.object({
  id: z.string().uuid(),
  topic: z.string(),
  goal: z.string(),
  audience: z.string(),
  seed_keyword: z.string().nullable(),
  topic_cluster_id: z.string().uuid().nullable(),
  locale: z.string(),
  market: z.string(),
  status: z.string(),
  stage: z.string(),
  plan: record,
  query_plan: z.array(record),
  keyword_plan: z.array(record),
  surface_summary: record,
  elimination_summary: record,
  result_summary: record,
  progress_log: z.array(record),
  failure_reason: z.string().nullable(),
});

const signalSchema = z.object({
  id: z.string().uuid(),
  surface_kind: z.string(),
  title: z.string(),
  snippet: z.string().nullable(),
  reference_url: z.string().nullable(),
  query: z.string().nullable(),
  signal_role: z.string(),
  normalized_document_id: z.string().uuid().nullable(),
  provenance: record,
});

const candidateSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  angle: z.string(),
  candidate_kind: z.string(),
  cluster_key: z.string(),
  primitives: z.array(record),
  implementation_steps: z.array(z.string()),
  factual_claims_needed: z.array(z.string()),
  signal_ids: z.array(z.string()),
  is_cliche: z.boolean(),
  cliche_reason: z.string().nullable(),
  idea_quality: z.number(),
  quality_factors: record,
  idea_confidence: z.string(),
  factual_evidence_confidence: z.string(),
  recommendation: z.string(),
  merged_into_id: z.string().uuid().nullable(),
  opportunity_id: z.string().uuid().nullable(),
  work_item_id: z.string().uuid().nullable().optional(),
  rationale: z.string(),
});

const detailSchema = z.object({
  mission: missionSchema,
  signals: z.array(signalSchema),
  candidates: z.array(candidateSchema),
});

const queuedSchema = z.object({ mission: missionSchema, queued: z.boolean() });

export type ResearchMission = z.infer<typeof missionSchema>;
export type MissionSignal = z.infer<typeof signalSchema>;
export type MissionCandidate = z.infer<typeof candidateSchema>;
export type MissionDetail = z.infer<typeof detailSchema>;

export type MissionCreateInput = {
  topic: string;
  goal: string;
  audience: string;
  seed_keyword: string | null;
  topic_cluster_id: string | null;
};

export async function fetchMissions(): Promise<
  BackendResult<ResearchMission[]>
> {
  const response = await requestBackend("/internal/research-missions");
  if (!response) return { kind: "unreachable" };
  return parseBackendResponse(response, z.array(missionSchema), [200]);
}

export async function fetchMission(
  id: string,
): Promise<BackendResult<MissionDetail>> {
  const response = await requestBackend(`/internal/research-missions/${id}`);
  if (!response) return { kind: "unreachable" };
  return parseBackendResponse(response, detailSchema, [200]);
}

/** Creates the mission; the backend queues the run itself. */
export async function createMission(
  body: MissionCreateInput,
): Promise<{ id: string; queued: boolean } | null> {
  const response = await requestBackend("/internal/research-missions", {
    method: "POST",
    jsonBody: body,
  });
  if (!response || response.status !== 201) return null;
  const parsed = queuedSchema.safeParse(await response.json());
  return parsed.success
    ? { id: parsed.data.mission.id, queued: parsed.data.queued }
    : null;
}

export async function runMission(id: string): Promise<boolean> {
  const response = await requestBackend(
    `/internal/research-missions/${id}/run`,
    {
      method: "POST",
    },
  );
  return response?.status === 200;
}

export const MISSION_STAGE_LABELS: Record<string, string> = {
  planning: "Konu analiz ediliyor",
  keywords: "Anahtar kelimeler araştırılıyor",
  searching: "Web ve kayıtlı kaynaklar taranıyor",
  extracting: "Fikirler çıkarılıyor",
  clustering: "Benzer fikirler gruplanıyor",
  evaluating: "Fırsatlar değerlendiriliyor",
  grounding: "Güçlü fikirlerin sayfaları getiriliyor",
  promoting: "İçerik fırsatları açılıyor",
  completed: "Tamamlandı",
};

export const MISSION_STATUS_LABELS: Record<string, string> = {
  draft: "Taslak",
  queued: "Kuyrukta",
  running: "Çalışıyor",
  grounding: "Sayfalar getiriliyor",
  completed: "Tamamlandı",
  needs_more_research: "Daha fazla araştırma gerekli",
  failed: "Başarısız",
};

export const SURFACE_LABELS: Record<string, string> = {
  registered_source: "Kayıtlı kaynak",
  open_web: "Açık web",
  visual_inspiration: "Görsel ilham",
  community_need: "Topluluk ihtiyacı",
  trend_market: "Trend / pazar",
};

export const RECOMMENDATION_LABELS: Record<string, string> = {
  promote: "Güçlü aday",
  continue_research: "Araştırmaya devam",
  eliminate: "Elendi",
  merged: "Birleştirildi",
};

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
  unknown: "Bilinmiyor",
  not_required: "Gerekmiyor",
  pending: "Bekliyor",
};

export function stateLabel(
  map: Record<string, string>,
  value: unknown,
): string {
  return typeof value === "string" ? (map[value] ?? value) : "Bilinmiyor";
}
