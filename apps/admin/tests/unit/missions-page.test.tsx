import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/missions-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/missions-api")>("@/lib/missions-api");
  return { ...actual, fetchMissions: vi.fn(), fetchMission: vi.fn() };
});
vi.mock("@/lib/strategy-api", () => ({
  fetchStrategyOverview: vi.fn(async () => ({
    kind: "ok",
    data: { clusters: [{ id: "c1", name: "Evlilik Teklifi" }] },
  })),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: (path: string) => {
    throw new Error(`REDIRECT:${path}`);
  },
}));

import MissionDetailPage from "@/app/research/[id]/page";
import ResearchMissionsPage from "@/app/research/page";
import { fetchMission, fetchMissions } from "@/lib/missions-api";

const MISSION_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

const mission = {
  id: MISSION_ID,
  topic: "İlginç Evlilik Teklifleri",
  goal: "Türkiye için yaratıcı 20 fikir bul.",
  audience: "20–35 yaş çiftler",
  seed_keyword: "ilginç evlilik teklifleri",
  topic_cluster_id: null,
  locale: "tr-TR",
  market: "TR",
  status: "completed",
  stage: "completed",
  plan: { intent_summary: "Klişe olmayan fikir arayışı", cliche_patterns: ["sahilde teklif"] },
  query_plan: [],
  keyword_plan: [
    {
      keyword: "yaratıcı evlilik teklifi",
      demand: { state: "unknown" },
      trend: { state: "not_observed" },
    },
  ],
  surface_summary: { counts: { open_web: 3, registered_source: 2 }, unavailable: [] },
  elimination_summary: {
    found: 25,
    generic_eliminated: 8,
    merged: 6,
    weak_eliminated: 0,
    retained: 11,
    promotable: 4,
  },
  result_summary: { ideas: 25, promotable: 4, promoted: 1, search_demand: "unknown", factual_evidence: "not_evaluated" },
  progress_log: [
    { stage: "planning", status: "done", note: "12 anahtar ifade, 8 sorgu (model)" },
    { stage: "completed", status: "done", note: "1 fırsat açıldı" },
  ],
  failure_reason: null,
};

const candidate = {
  id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f1",
  title: "Dönme dolabın tepesinde açılan gizli mesaj teklifi",
  angle: "Kabin tam tepedeyken mesajla teklif.",
  candidate_kind: "synthesized",
  cluster_key: "height-reveal",
  primitives: [{ key: "height", label: "Yükseklik" }],
  implementation_steps: ["Kabini ayırt", "Mesajı gizle"],
  factual_claims_needed: ["Dönme dolap kuralları"],
  signal_ids: [],
  is_cliche: false,
  cliche_reason: null,
  idea_quality: 84,
  quality_factors: { novelty: 88, usefulness: 80 },
  idea_confidence: "high",
  factual_evidence_confidence: "unknown",
  recommendation: "promote",
  merged_into_id: null,
  opportunity_id: "2f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f2",
  work_item_id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f3",
  rationale: "Yükseklik ve sürpriz zamanlaması birleşiyor.",
};

describe("Research missions page", () => {
  beforeEach(() => {
    vi.mocked(fetchMissions).mockReset();
    vi.mocked(fetchMission).mockReset();
  });

  it("asks only for the goal fields and lists missions with their outcomes", async () => {
    vi.mocked(fetchMissions).mockResolvedValue({ kind: "ok", data: [mission], requestId: null });
    render(await ResearchMissionsPage({}));
    expect(screen.getByRole("heading", { name: "Yeni araştırma başlat" })).toBeTruthy();
    expect(screen.getByPlaceholderText("Örn. İlginç evlilik teklifleri")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: /Kaynak/ })).toBeNull();
    expect(screen.queryByText(/Fetch et|Normalize et/)).toBeNull();
    const link = screen.getByRole("link", { name: /İlginç Evlilik Teklifleri/ });
    expect(link.getAttribute("href")).toBe(`/research/${MISSION_ID}`);
    expect(screen.getByText("Tamamlandı · Tamamlandı")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Araştırma hattı (gelişmiş)" }).getAttribute("href")).toBe(
      "/research/hat",
    );
  });

  it("shows live progress, elimination counts, keywords and promoted ideas", async () => {
    vi.mocked(fetchMission).mockResolvedValue({
      kind: "ok",
      data: { mission, signals: [], candidates: [candidate] },
      requestId: null,
    });
    render(await MissionDetailPage({ params: Promise.resolve({ id: MISSION_ID }) }));
    expect(screen.getByText("12 anahtar ifade, 8 sorgu (model)")).toBeTruthy();
    expect(screen.getByText("Klişe elendi").nextElementSibling?.textContent).toBe("8");
    expect(screen.getByText("Birleştirildi").nextElementSibling?.textContent).toBe("6");
    expect(screen.getByText("yaratıcı evlilik teklifi")).toBeTruthy();
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThan(0);
    expect(screen.getByText("Listede yok")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "İçerik fırsatını aç →" }).getAttribute("href"),
    ).toBe(`/editorial/${candidate.work_item_id}`);
    expect(screen.getByText("Kanıt güveni: Bilinmiyor")).toBeTruthy();
    expect(screen.getByText("Fikir güveni: Yüksek")).toBeTruthy();
  });

  it("maps an unknown mission to not found", async () => {
    vi.mocked(fetchMission).mockResolvedValue({ kind: "not_found" } as never);
    await expect(
      MissionDetailPage({ params: Promise.resolve({ id: MISSION_ID }) }),
    ).rejects.toThrow("NOT_FOUND");
  });
});
