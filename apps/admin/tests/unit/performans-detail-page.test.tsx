import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/performance-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/performance-api")>(
    "@/lib/performance-api",
  );
  return { ...actual, fetchContentPerformance: vi.fn() };
});

import ContentPerformancePage from "@/app/performans/[workItemId]/page";
import {
  fetchContentPerformance,
  type ContentPerformanceDetail,
  type SeriesPoint,
} from "@/lib/performance-api";

const fetchMock = vi.mocked(fetchContentPerformance);
const WORK_ITEM = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

function daily(days: number): SeriesPoint[] {
  return Array.from({ length: days }, (_, index) => {
    const day = `2026-08-${String(index + 1).padStart(2, "0")}`;
    return {
      period_start: day,
      period_end: day,
      observed_at: "2026-09-05T03:00:00+00:00",
      metrics: {
        impressions: 20 + index,
        clicks: 2 + (index % 3),
        ctr: 0.1,
        position: 9 - index * 0.2,
      },
    };
  });
}

function detail(
  overrides: Partial<ContentPerformanceDetail> = {},
): ContentPerformanceDetail {
  return {
    content: {
      published_content_id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      work_item_id: WORK_ITEM,
      title_working_label: "Balon temalı doğum günü planı",
      current_state: "published",
      canonical_url: "https://konsepthane.net/balon",
      canonical_url_missing: false,
      remote_publication_ref: "https://konsepthane.net/balon",
      published_at: "2026-07-07T09:00:00+00:00",
      age_days: 60,
      topic_cluster_id: null,
      cluster_name: "Doğum Günü",
      audience_id: null,
      audience_name: null,
      theme_key: "balon",
      content_format: "planning_guide",
      assessment: null,
      impressions: 560,
      clicks: 60,
      position: 9.5,
      ctr: 0.1,
      impressions_pct: -0.34,
      clicks_pct: -0.29,
      has_open_refresh: true,
    },
    assessments: [
      {
        id: "2f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        window_days: 7,
        status: "insufficient_data",
        assessed_at: "2026-09-05T04:00:00+00:00",
        engine_name: "performance-classifier",
        engine_version: "1",
        basis: {},
      },
      {
        id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        window_days: 28,
        status: "declining",
        assessed_at: "2026-09-05T04:00:00+00:00",
        engine_name: "performance-classifier",
        engine_version: "1",
        basis: {},
      },
    ],
    search_console_daily: daily(10),
    search_console_summary: [
      {
        period_start: "2026-08-01",
        period_end: "2026-08-28",
        observed_at: "2026-09-05T03:00:00+00:00",
        metrics: { impressions: 560, clicks: 60, ctr: 0.107, position: 9.5 },
      },
    ],
    top_queries: [
      {
        query: "balon temalı doğum günü",
        clicks: 10,
        impressions: 200,
        position: 9.5,
      },
    ],
    analytics: [],
    google_trends: [
      {
        period_start: "2026-09-05",
        period_end: "2026-09-05",
        observed_at: "2026-09-05T03:30:00+00:00",
        metrics: {
          terms: [{ term: "balon temalı doğum günü", direction: "rising" }],
        },
      },
    ],
    pinterest_trends: [],
    semrush: [],
    refresh: {
      id: "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      published_content_id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      work_item_id: WORK_ITEM,
      title_working_label: "Balon temalı doğum günü planı",
      current_state: "published",
      status: "proposed",
      trigger_assessment_id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      window_days: 28,
      diagnosis: {
        position_movement: { previous: 3.9, current: 9.5, delta: 5.6 },
        impressions_pct: -0.34,
        query_changes: { available: false },
        new_signals: [],
      },
      recommendation: "Öneri: içeriği araştırma yenileme rotasına almak.",
      proposed_at: "2026-09-05T04:10:00+00:00",
      decided_at: null,
      decided_by_display_name: null,
      decision_reason: null,
    },
    refresh_history: [],
    historical_signal: { band: "unknown", outcome: null, priority_only: true },
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Performans content detail page", () => {
  it("renders Google, GA4, Trend and SEO Market sections from real snapshots", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: detail(),
    });

    render(
      await ContentPerformancePage({
        params: Promise.resolve({ workItemId: WORK_ITEM }),
        searchParams: Promise.resolve({}),
      }),
    );

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Balon temalı doğum günü planı",
      }),
    ).toBeTruthy();
    for (const name of [
      "Google",
      "Site Davranışı",
      "Trend",
      "SEO Market",
      "Güncelleme Fırsatı",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeTruthy();
    }
    expect(screen.getByText("Yetersiz veri")).toBeTruthy();
    expect(screen.getByText("Düşüyor")).toBeTruthy();
    expect(screen.queryByText("declining")).toBeNull();
    expect(
      screen.getByRole("img", { name: /Gösterim: 10 nokta/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("img", { name: /Pozisyon: 10 nokta/ }),
    ).toBeTruthy();
    expect(screen.getAllByText("balon temalı doğum günü").length).toBe(2);
    expect(screen.getByText("GA4 verisi yok: Bilinmiyor.")).toBeTruthy();
    expect(screen.getByText("Semrush verisi yok: Bilinmiyor.")).toBeTruthy();
    expect(screen.getByText(/Google Trends: Yükseliyor/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Güncellemeyi Onayla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Şimdilik Geç" })).toBeTruthy();
    expect(screen.getByText(/yalnızca öncelik, asla filtre/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "https://konsepthane.net/balon" }),
    ).toBeTruthy();
  });

  it("says the address is unknown and reports insufficient sparkline data", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: detail({
        content: {
          ...detail().content,
          canonical_url: null,
          canonical_url_missing: true,
        },
        search_console_daily: daily(1),
        refresh: null,
      }),
    });

    render(
      await ContentPerformancePage({
        params: Promise.resolve({ workItemId: WORK_ITEM }),
      }),
    );

    expect(screen.getByText("Yayın adresi bilinmiyor")).toBeTruthy();
    expect(screen.getAllByText("Yetersiz veri").length).toBeGreaterThan(1);
    expect(screen.getByText("Bekleyen güncelleme kararı yok.")).toBeTruthy();
  });

  it("renders not-found and failure states honestly", async () => {
    fetchMock.mockResolvedValue({ kind: "not_found" });
    render(
      await ContentPerformancePage({
        params: Promise.resolve({ workItemId: WORK_ITEM }),
      }),
    );
    expect(
      screen.getByRole("heading", { name: "Yayın bulunamadı" }),
    ).toBeTruthy();

    fetchMock.mockResolvedValue({ kind: "unreachable" });
    render(
      await ContentPerformancePage({
        params: Promise.resolve({ workItemId: WORK_ITEM }),
      }),
    );
    expect(
      screen.getByText("Performans verileri şu anda alınamıyor."),
    ).toBeTruthy();
  });
});
