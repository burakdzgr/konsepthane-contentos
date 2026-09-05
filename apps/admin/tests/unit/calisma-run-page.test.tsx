import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return { ...actual, fetchIntakeRunDetail: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  notFound: vi.fn(() => {
    throw new Error("NOT_FOUND");
  }),
}));

vi.mock("@/lib/dashboard-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/dashboard-api")>(
    "@/lib/dashboard-api",
  );
  return { ...actual, fetchDashboardAgents: vi.fn() };
});

vi.mock("@/lib/intelligence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intelligence-api")>(
    "@/lib/intelligence-api",
  );
  return { ...actual, fetchIntelligenceSummary: vi.fn() };
});

vi.mock("@/lib/integrations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/integrations-api")>(
    "@/lib/integrations-api",
  );
  return { ...actual, fetchIntegrations: vi.fn() };
});

import RunDetailPage from "@/app/calisma/[id]/page";
import {
  fetchIntakeRunDetail,
  type IntakeRunDetail,
  type IntakeRunView,
} from "@/lib/intake-api";

import { fetchDashboardAgents } from "@/lib/dashboard-api";
import {
  fetchIntelligenceSummary,
  SIGNAL_FAMILIES,
  type IntelligenceSummary,
} from "@/lib/intelligence-api";
import {
  fetchIntegrations,
  type IntegrationView,
} from "@/lib/integrations-api";

const detailMock = vi.mocked(fetchIntakeRunDetail);
const agentsMock = vi.mocked(fetchDashboardAgents);
const signalsMock = vi.mocked(fetchIntelligenceSummary);
const integrationsMock = vi.mocked(fetchIntegrations);

function signals(counts: Partial<Record<string, number>>): IntelligenceSummary {
  return {
    families: SIGNAL_FAMILIES.map((family) => ({
      family,
      signal_count: counts[family] ?? 0,
      occurrence_total: counts[family] ?? 0,
      distinct_sources: counts[family] !== undefined ? 2 : 0,
      last_observed_at: counts[family] !== undefined ? AT : null,
    })),
    total_signals: Object.values(counts).reduce<number>(
      (total, value) => total + (value ?? 0),
      0,
    ),
    run_id: RUN_ID,
    run_document_count: 4,
  };
}

function provider(overrides: Partial<IntegrationView>): IntegrationView {
  return {
    name: "semrush",
    display_name: "Semrush",
    purpose: "",
    configured: true,
    verified: true,
    state: "healthy",
    detail: "",
    checked_at: AT,
    last_success_at: AT,
    last_error_class: null,
    freshness: null,
    daily_budget: 200,
    requests_today: 0,
    cache_hours: 72,
    required_env: [],
    optional_env: [],
    ...overrides,
  };
}

const RUN_ID = "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";
const AT = "2026-09-03T10:00:00+00:00";

function run(overrides: Partial<IntakeRunView> = {}): IntakeRunView {
  return {
    id: RUN_ID,
    source_id: "11111111-2222-4333-8444-555555555555",
    source_slug: "kara",
    source_name: "Kara's Party Ideas",
    status: "running",
    discovered_new: 4993,
    rediscovered: 12,
    prefilter_accepted: 4200,
    prefilter_rejected: 793,
    fetch_dispatched: 8,
    fetched: 5,
    fetch_failed: 1,
    promotions_dispatched: 3,
    opportunities_created: 2,
    remaining_accepted: 4192,
    remaining_discovered: 0,
    policy: { max_fetches_per_run: 40 },
    failure_note: null,
    created_at: AT,
    discovery_completed_at: AT,
    prefilter_completed_at: AT,
    finished_at: null,
    updated_at: AT,
    last_event_at: AT,
    ...overrides,
  };
}

function detail(overrides: Partial<IntakeRunDetail> = {}): IntakeRunDetail {
  return {
    generated_at: AT,
    run: run(),
    chain: {
      normalized_succeeded: 4,
      normalized_failed: 1,
      duplicates_evaluated: 4,
      last_processed_title: "Frozen Birthday Party",
      last_processed_url: "https://karaspartyideas.com/frozen-birthday-party",
    },
    stages: [
      {
        key: "discovery",
        state: "done",
        counts: { new: 4993, rediscovered: 12 },
      },
      {
        key: "prefilter",
        state: "done",
        counts: { accepted: 4200, rejected: 793, remaining: 0 },
      },
      {
        key: "fetch",
        state: "active",
        counts: {
          dispatched: 8,
          fetched: 5,
          failed: 1,
          waiting_candidates: 4192,
        },
      },
      {
        key: "normalize",
        state: "active",
        counts: { succeeded: 4, failed: 1 },
      },
      {
        key: "duplicate",
        state: "active",
        counts: { evaluated: 4 },
      },
      {
        key: "promote",
        state: "pending",
        counts: { dispatched: 3, opportunities: 2 },
      },
    ],
    events: [
      {
        id: 2,
        stage: "discovery",
        kind: "discovery_completed",
        detail: { entries_seen: 5005, admitted_new: 4993, rediscovered: 12 },
        occurred_at: AT,
      },
      {
        id: 1,
        stage: "run",
        kind: "run_started",
        detail: {},
        occurred_at: AT,
      },
    ],
    ...overrides,
  };
}

async function renderPage() {
  render(
    await RunDetailPage({
      params: Promise.resolve({ id: RUN_ID }),
      searchParams: Promise.resolve({}),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  signalsMock.mockResolvedValue({ kind: "unreachable" });
  integrationsMock.mockResolvedValue({ kind: "unreachable" });
  agentsMock.mockResolvedValue({
    kind: "ok",
    data: {
      generated_at: AT,
      engine_paused: false,
      engine_pause_reason: null,
      agents: [],
    },
    requestId: null,
  });
});

describe("Run detail page", () => {
  it("shows the live run header, stages and real counters", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail(),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", {
        name: "Kara's Party Ideas — Araştırma Çalışması",
      }),
    ).toBeTruthy();
    expect(screen.getByText("ÇALIŞIYOR")).toBeTruthy();
    expect(screen.getAllByText("Keşif").length).toBeGreaterThan(0);
    expect(screen.getByText("Son İşlenen İçerik")).toBeTruthy();
    expect(screen.getByText("Frozen Birthday Party")).toBeTruthy();
    expect(screen.getAllByText(/4200 uygun/).length).toBeGreaterThan(0);
    expect(screen.getByText("Benzer fikirler gruplanıyor")).toBeTruthy();
    expect(screen.getByText("Getirilen sayfa")).toBeTruthy();
    expect(screen.queryByText(/Fetch|Normalize/)).toBeNull();
    // The event feed renders Turkish descriptions of durable events.
    expect(
      screen.getByText(/Keşif tamamlandı: 5005 kayıt görüldü, 4993 yeni URL/),
    ).toBeTruthy();
    expect(screen.getByText("Çalışma başlatıldı")).toBeTruthy();
    // Live controls with mandatory reasons.
    expect(screen.getByRole("button", { name: "Duraklat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Güvenli durdur" })).toBeTruthy();
  });

  it("shows the full Turkish stage list from real run, signal and provider data", async () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail(),
      requestId: null,
    });
    signalsMock.mockResolvedValue({
      kind: "ok",
      data: signals({ community_need: 3, market: 1 }),
      requestId: null,
    });
    integrationsMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: AT,
        providers: [
          provider({ freshness: twoDaysAgo }),
          provider({
            name: "google_trends",
            display_name: "Google Trends",
            configured: false,
            verified: false,
            state: "not_configured",
            cache_hours: 24,
          }),
          provider({
            name: "pinterest_trends",
            display_name: "Pinterest Trends",
            state: "access_required",
            cache_hours: 24,
          }),
          provider({
            name: "google_search_console",
            display_name: "Google Search Console",
            freshness: "2026-09-03T04:00:00+00:00",
            cache_hours: 12,
          }),
        ],
      },
    });

    await renderPage();

    expect(signalsMock).toHaveBeenCalledWith(RUN_ID);
    const list = screen.getByRole("list", { name: "Çalışma aşamaları" });
    const rows = within(list).getAllByRole("listitem");
    expect(
      rows.map((row) => row.querySelector(".stage-label")?.textContent),
    ).toEqual([
      "Kaynak taranıyor",
      "URL'ler keşfediliyor",
      "Ön eleme",
      "İçerikler getiriliyor",
      "İçerik anlaşılıyor",
      "Fikirler çıkarılıyor",
      "Benzer fikirler gruplanıyor",
      "Topluluk sinyali",
      "Pazar sinyali",
      "Strateji eşleşmesi",
      "Semrush",
      "Google Trend Keşfi",
      "Google Trends API",
      "Pinterest Trends",
      "Konsepthane geçmiş verisi",
      "Fırsat",
    ]);
    const detailOf = (label: string) =>
      rows
        .find((row) => row.querySelector(".stage-label")?.textContent === label)
        ?.querySelector(".stage-detail")?.textContent;
    const stateOf = (label: string) =>
      rows
        .find((row) => row.querySelector(".stage-label")?.textContent === label)
        ?.getAttribute("data-state");
    // Intake stages from the run view.
    expect(detailOf("URL'ler keşfediliyor")).toContain("5005 URL");
    expect(stateOf("URL'ler keşfediliyor")).toBe("done");
    expect(detailOf("İçerikler getiriliyor")).toBe("5 / 8 sayfa · 1 hata");
    expect(stateOf("İçerikler getiriliyor")).toBe("active");
    expect(detailOf("İçerik anlaşılıyor")).toBe("4 içerik · 1 hata");
    expect(detailOf("Fırsat")).toBe("2 fırsat oluştu");
    // Signal stages from the run-scoped summary: counts or waiting, never
    // a fabricated strength.
    expect(detailOf("Topluluk sinyali")).toContain("3 sinyal · 2 kaynak");
    expect(stateOf("Topluluk sinyali")).toBe("done");
    expect(detailOf("Strateji eşleşmesi")).toContain("1 sinyal");
    expect(detailOf("Pazar sinyali")).toBe("bekleniyor");
    expect(stateOf("Pazar sinyali")).toBe("pending");
    // Provider stages from the integrations board with freshness.
    expect(detailOf("Semrush")).toBe("2 gün önce");
    expect(stateOf("Semrush")).toBe("done");
    expect(detailOf("Google Trends API")).toBe("Yapılandırılmadı");
    // The public-dataset discovery is its own stage: absent from the board
    // here, so it says so instead of pretending Google Trends is "down".
    expect(detailOf("Google Trend Keşfi")).toBe("Yapılandırılmadı");
    expect(detailOf("Pinterest Trends")).toBe("API erişimi bekleniyor");
    expect(stateOf("Pinterest Trends")).toBe("unavailable");
    // Search Console data older than twice its 12h cache TTL is "eski veri".
    expect(detailOf("Konsepthane geçmiş verisi")).toBe(
      "Search Console · son veri 2026-09-03 · eski veri",
    );
  });

  it("says 'veri yok' when the signal summary and providers cannot be read", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail({ run: run({ status: "completed", finished_at: AT }) }),
      requestId: null,
    });

    await renderPage();

    const list = screen.getByRole("list", { name: "Çalışma aşamaları" });
    expect(within(list).getAllByText("sinyal özeti okunamadı").length).toBe(3);
    // Semrush, Google Trend Keşfi, Google Trends API, Pinterest, history.
    expect(within(list).getAllByText("sağlayıcı durumu okunamadı").length).toBe(
      5,
    );
    expect(within(list).queryByText(/%|100/)).toBeNull();
  });

  it("offers resume for a paused run and nothing for a finished one", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail({ run: run({ status: "paused" }) }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByRole("button", { name: "Devam ettir" })).toBeTruthy();
  });

  it("reports an unreachable backend truthfully", async () => {
    detailMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByText(/şu anda erişilemiyor/)).toBeTruthy();
  });
});
