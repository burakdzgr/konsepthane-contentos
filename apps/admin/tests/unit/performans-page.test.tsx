import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/performance-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/performance-api")>(
    "@/lib/performance-api",
  );
  return {
    ...actual,
    fetchPerformanceOverview: vi.fn(),
    fetchRefreshOpportunities: vi.fn(),
    fetchStrategySuggestions: vi.fn(),
  };
});

import PerformancePage from "@/app/performans/page";
import {
  fetchPerformanceOverview,
  fetchRefreshOpportunities,
  fetchStrategySuggestions,
  type PerformanceOverview,
  type PublishedContentRow,
  type RefreshOpportunity,
  type StrategySuggestion,
} from "@/lib/performance-api";

const overviewMock = vi.mocked(fetchPerformanceOverview);
const refreshMock = vi.mocked(fetchRefreshOpportunities);
const suggestionMock = vi.mocked(fetchStrategySuggestions);

const WORK_ITEM = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";
const CONTENT = "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

function row(
  overrides: Partial<PublishedContentRow> = {},
): PublishedContentRow {
  return {
    published_content_id: CONTENT,
    work_item_id: WORK_ITEM,
    title_working_label: "Balon temalı doğum günü planı",
    current_state: "published",
    canonical_url: null,
    canonical_url_missing: true,
    remote_publication_ref: "konsepthane-pub-1",
    published_at: "2026-07-07T09:00:00+00:00",
    age_days: 60,
    topic_cluster_id: null,
    cluster_name: "Doğum Günü",
    audience_id: null,
    audience_name: null,
    theme_key: null,
    content_format: null,
    assessment: {
      id: "2f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      window_days: 28,
      status: "rising",
      assessed_at: "2026-09-05T04:00:00+00:00",
      engine_name: "performance-classifier",
      engine_version: "1",
      basis: {},
    },
    impressions: 1120,
    clicks: 140,
    position: 5.5,
    ctr: 0.125,
    impressions_pct: 1,
    clicks_pct: 1.5,
    has_open_refresh: false,
    ...overrides,
  };
}

function overview(
  overrides: Partial<PerformanceOverview> = {},
): PerformanceOverview {
  return {
    generated_at: "2026-09-05T06:00:00+00:00",
    window_days: 28,
    totals: {
      published: 2,
      rising: 1,
      stable: 0,
      declining: 0,
      volatile: 0,
      new: 1,
      insufficient: 1,
      unknown: 0,
    },
    rising: [row()],
    declining: [],
    stable: [],
    volatile: [],
    new: [
      row({
        published_content_id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        work_item_id: "4f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        title_working_label: "Yeni yayın",
        age_days: 2,
        assessment: null,
        impressions: null,
        clicks: null,
        position: null,
        ctr: null,
        impressions_pct: null,
        clicks_pct: null,
      }),
    ],
    insufficient: [],
    clusters: [
      {
        cluster_id: "5f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        cluster_name: "Doğum Günü",
        published: 1,
        rising: 1,
        stable: 0,
        declining: 0,
        volatile: 0,
        new: 0,
        insufficient: 0,
        unknown: 0,
        sufficient: true,
      },
    ],
    freshness: [
      {
        provider: "google_search_console",
        last_observed_at: "2026-09-05T03:00:00+00:00",
        state: "healthy",
      },
      { provider: "google_analytics", last_observed_at: null, state: null },
      { provider: "semrush", last_observed_at: null, state: "not_configured" },
      {
        provider: "google_trends",
        last_observed_at: null,
        state: "access_required",
      },
      { provider: "pinterest_trends", last_observed_at: null, state: null },
    ],
    pending_refresh_decisions: 1,
    pending_strategy_suggestions: 1,
    schedule_enabled: true,
    ...overrides,
  };
}

function refresh(): RefreshOpportunity {
  return {
    id: "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    published_content_id: CONTENT,
    work_item_id: WORK_ITEM,
    title_working_label: "Balon temalı doğum günü planı",
    current_state: "published",
    status: "proposed",
    trigger_assessment_id: "7f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    window_days: 28,
    diagnosis: {
      position_movement: { previous: 3.9, current: 9.5, delta: 5.6 },
      impressions_pct: -0.34,
      query_changes: { available: true, lost_queries: ["evde parti süsleme"] },
      new_signals: [],
    },
    recommendation:
      "Ortalama pozisyon 3.9 → 9.5. Öneri: içeriği araştırma yenileme rotasına almak; yayın kararı ayrıdır.",
    proposed_at: "2026-09-05T04:10:00+00:00",
    decided_at: null,
    decided_by_display_name: null,
    decision_reason: null,
  };
}

function suggestion(): StrategySuggestion {
  return {
    id: "8f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    kind: "cluster_focus",
    title: "Soft Animal 1 Yaş kümesine odaklan",
    rationale:
      "Soft Animal 1 Yaş kümesindeki 3 yayının 3 tanesi son 90 günde yükseliyor → bu kümenin alt konu araştırmasını artır.",
    basis: {},
    status: "proposed",
    proposed_at: "2026-09-05T04:30:00+00:00",
    decided_at: null,
    decided_by_display_name: null,
    decision_reason: null,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Performans page", () => {
  it("renders the sections, Turkish statuses, freshness and decisions", async () => {
    overviewMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: overview(),
    });
    refreshMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: [refresh()],
    });
    suggestionMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: [suggestion()],
    });

    render(
      await PerformancePage({
        searchParams: Promise.resolve({ window: "28" }),
      }),
    );

    expect(screen.getByRole("heading", { name: "Performans" })).toBeTruthy();
    for (const name of [
      "Genel Görünüm",
      "Yükselen İçerikler",
      "Düşen İçerikler",
      "Yeni Yayınlananlar",
      "Güncelleme Fırsatları",
      "Strateji Önerileri",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeTruthy();
    }
    expect(overviewMock).toHaveBeenCalledWith(28);
    expect(
      screen.getByRole("button", { name: "Şimdi senkronize et" }),
    ).toBeTruthy();
    const freshness = screen.getByText(/Search Console: son veri/).closest("p");
    expect(freshness?.textContent).toContain("Semrush: Yapılandırılmadı");
    expect(freshness?.textContent).toContain(
      "Google Trends: API erişimi gerekli",
    );
    expect(freshness?.textContent).toContain("GA4: henüz veri yok");
    expect(screen.getAllByText("Yükseliyor").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Yayın adresi bilinmiyor").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/rising/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Güncellemeyi Onayla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Şimdilik Geç" })).toBeTruthy();
    expect(
      screen.getByText(/Kaybedilen sorgular: evde parti süsleme/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Stratejiye Ekle" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yoksay" })).toBeTruthy();
    expect(screen.getByText("Soft Animal 1 Yaş kümesine odaklan")).toBeTruthy();
    expect(screen.getByText("Küme odağı")).toBeTruthy();
    const links = screen.getAllByRole("link", {
      name: "Balon temalı doğum günü planı",
    });
    expect(links[0]?.getAttribute("href")).toBe(`/performans/${WORK_ITEM}`);
  });

  it("falls back to the 28-day window and shows honest empty states", async () => {
    overviewMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: overview({
        rising: [],
        new: [],
        clusters: [],
        totals: {
          published: 0,
          rising: 0,
          stable: 0,
          declining: 0,
          volatile: 0,
          new: 0,
          insufficient: 0,
          unknown: 0,
        },
        schedule_enabled: false,
      }),
    });
    refreshMock.mockResolvedValue({ kind: "ok", requestId: null, data: [] });
    suggestionMock.mockResolvedValue({ kind: "ok", requestId: null, data: [] });

    render(
      await PerformancePage({
        searchParams: Promise.resolve({ window: "12" }),
      }),
    );

    expect(overviewMock).toHaveBeenCalledWith(28);
    expect(screen.getByText("Henüz yayınlanmış içerik yok.")).toBeTruthy();
    expect(screen.getByText("Bekleyen güncelleme kararı yok.")).toBeTruthy();
    expect(screen.getByText("Bekleyen strateji önerisi yok.")).toBeTruthy();
    expect(screen.getByText(/Otomatik senkron kapalı/)).toBeTruthy();
  });

  it("renders a bounded failure state", async () => {
    overviewMock.mockResolvedValue({ kind: "unreachable" });
    refreshMock.mockResolvedValue({ kind: "unreachable" });
    suggestionMock.mockResolvedValue({ kind: "malformed" });

    render(await PerformancePage({ searchParams: Promise.resolve({}) }));

    expect(
      screen.getByText("Performans verileri şu anda alınamıyor."),
    ).toBeTruthy();
    expect(screen.getByText("Güncelleme fırsatları alınamıyor.")).toBeTruthy();
    expect(screen.getByText("Strateji önerileri alınamıyor.")).toBeTruthy();
  });
});
