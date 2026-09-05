import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/integrations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/integrations-api")>(
    "@/lib/integrations-api",
  );
  return {
    ...actual,
    fetchIntegrations: vi.fn(),
    fetchTrendDiscovery: vi.fn(),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import IntegrationsPage from "@/app/entegrasyonlar/page";
import {
  fetchIntegrations,
  fetchTrendDiscovery,
  type IntegrationView,
  type TrendDiscovery,
} from "@/lib/integrations-api";

const fetchMock = vi.mocked(fetchIntegrations);
const discoveryMock = vi.mocked(fetchTrendDiscovery);

function discovery(overrides: Partial<TrendDiscovery> = {}): TrendDiscovery {
  return {
    provider: "google_trends_bigquery",
    country: "TR",
    synced: true,
    refresh_date: "2026-09-03",
    last_sync_at: "2026-09-04T15:30:00+00:00",
    total_terms: 50,
    matched_count: 1,
    unique_terms_ever: 3,
    top: [],
    rising: [
      {
        term: "ayıcıklı doğum günü",
        trend_type: "rising",
        rank: 2,
        percent_gain: 250,
        latest_score: 70,
        region_count: 2,
        refresh_date: "2026-09-03",
        matched: true,
        match_kind: "domain",
        strategy_keywords: [],
        domain_terms: ["doğum günü"],
        first_refresh_date: "2026-09-01",
        occurrence_count: 3,
      },
    ],
    matched: [
      {
        term: "ayıcıklı doğum günü",
        trend_type: "rising",
        rank: 2,
        percent_gain: 250,
        latest_score: 70,
        region_count: 2,
        refresh_date: "2026-09-03",
        matched: true,
        match_kind: "domain",
        strategy_keywords: [],
        domain_terms: ["doğum günü"],
        first_refresh_date: "2026-09-01",
        occurrence_count: 3,
      },
    ],
    generated_at: "2026-09-05T10:00:00+00:00",
    ...overrides,
  };
}

const SECRET = "semrush-secret-key-1234567890";

function provider(overrides: Partial<IntegrationView> = {}): IntegrationView {
  return {
    name: "semrush",
    display_name: "Semrush",
    purpose: "Dış SEO pazar istihbaratı.",
    configured: true,
    verified: true,
    state: "healthy",
    detail: "Bağlı. Kalan API birimi: 4242.",
    checked_at: "2026-09-05T10:00:00+00:00",
    last_success_at: "2026-09-05T10:00:00+00:00",
    last_error_class: null,
    freshness: "2026-09-05T08:00:00+00:00",
    daily_budget: 200,
    requests_today: 3,
    cache_hours: 72,
    required_env: ["CONTENTOS_SEMRUSH_API_KEY"],
    optional_env: ["CONTENTOS_SEMRUSH_DATABASE"],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Entegrasyonlar page", () => {
  it("renders one card per provider with Turkish state badges and facts", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [
          provider(),
          provider({
            name: "google_search_console",
            display_name: "Google Search Console",
            configured: false,
            verified: false,
            state: "not_configured",
            detail:
              "Yapılandırılmadı: CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON ve CONTENTOS_GSC_SITE_URL tanımlayın.",
            last_success_at: null,
            freshness: null,
            requests_today: 0,
            daily_budget: 500,
            cache_hours: 12,
            required_env: [
              "CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON",
              "CONTENTOS_GSC_SITE_URL",
            ],
            optional_env: [],
          }),
          provider({
            name: "google_trends",
            display_name: "Google Trends",
            configured: false,
            verified: false,
            state: "access_required",
            detail: "Google Trends API erişimi gerekli (resmi API alfa/izinli)",
            last_success_at: null,
            freshness: null,
            requests_today: 0,
          }),
          provider({
            name: "pinterest_trends",
            display_name: "Pinterest Trends",
            state: "rate_limited",
            last_error_class: "pinterest_trends_http_429",
            requests_today: 200,
          }),
          provider({
            name: "google_analytics",
            display_name: "Google Analytics 4",
            verified: false,
            state: "degraded",
            detail: "Yapılandırıldı, henüz doğrulanmadı: Bağlantıyı Test Et.",
            last_success_at: null,
            freshness: null,
          }),
        ],
      },
    });

    render(await IntegrationsPage({}));

    expect(
      screen.getByRole("heading", { name: "Entegrasyonlar" }),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Semrush" })).toBeTruthy();
    expect(screen.getByText("Bağlı")).toBeTruthy();
    expect(screen.getByText("Yapılandırılmadı")).toBeTruthy();
    expect(screen.getByText("API erişimi gerekli")).toBeTruthy();
    expect(screen.getByText("Kota sınırında")).toBeTruthy();
    expect(screen.getByText("Henüz doğrulanmadı")).toBeTruthy();
    expect(screen.getByText("pinterest_trends_http_429")).toBeTruthy();
    expect(screen.getAllByText("3 / 200").length).toBeGreaterThan(0);
    expect(screen.getByText("200 / 200")).toBeTruthy();
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getAllByRole("button", { name: /bağlantısını test et/i }),
    ).toHaveLength(5);
    // Env variable NAMES are shown, never values; nothing English leaks as a state.
    expect(
      screen.getAllByText("CONTENTOS_SEMRUSH_API_KEY").length,
    ).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain(SECRET);
    expect(document.body.textContent).not.toContain("not_configured");
    expect(document.body.textContent).not.toContain("access_required");
  });

  it("groups Google Trends into discovery (BigQuery) and deep analysis (API alpha)", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [
          provider(),
          provider({
            name: "google_trends",
            display_name: "Google Trends",
            configured: false,
            verified: false,
            state: "access_required",
            detail: "Google Trends API erişimi gerekli (resmi API alfa/izinli)",
            last_success_at: null,
            freshness: null,
            requests_today: 0,
            required_env: ["CONTENTOS_GOOGLE_TRENDS_API_KEY"],
          }),
          provider({
            name: "google_trends_bigquery",
            display_name: "Google Trend Keşfi (BigQuery)",
            state: "healthy",
            detail: "Bağlı. Son TR verisi: 2026-09-03.",
            freshness: "2026-09-04T15:30:00+00:00",
            daily_budget: 20,
            requests_today: 3,
            cache_hours: 24,
            required_env: ["CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON"],
            optional_env: ["CONTENTOS_GOOGLE_CLOUD_PROJECT_ID"],
          }),
        ],
      },
    });
    discoveryMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: discovery(),
    });

    render(await IntegrationsPage({}));

    // The group heading plus the alpha-API card heading share the name.
    expect(
      screen.getAllByRole("heading", { name: "Google Trends" }),
    ).toHaveLength(2);
    expect(
      document.getElementById("integration-google-trends-group"),
    ).toBeTruthy();
    expect(
      screen.getByText("Güncel Trend Keşfi · Google BigQuery"),
    ).toBeTruthy();
    expect(
      screen.getByText("Derin Keyword Trend Analizi · Google Trends API Alpha"),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Google Trend Keşfi (BigQuery)" }),
    ).toBeTruthy();
    // Discovery active (like Semrush), alpha waiting — different badges.
    expect(screen.getAllByText("Bağlı")).toHaveLength(2);
    expect(screen.getByText("API erişimi gerekli")).toBeTruthy();
    // The last sync and the relevant term with its dataset facts.
    expect(screen.getByText("2026-09-03")).toBeTruthy();
    expect(screen.getByText("ayıcıklı doğum günü")).toBeTruthy();
    expect(
      screen.getByText(
        /yükselen · sıra 2 · %250 artış · Konsepthane alanı · 3 gün gözlendi/,
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Google Trend Keşfi senkronunu başlat",
      }),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: /bağlantısını test et/i }),
    ).toHaveLength(3);
    expect(document.body.textContent).not.toContain("not_observed");
    expect(document.body.textContent).not.toContain("access_required");
  });

  it("says a never-synced discovery is not 'low trend'", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [
          provider({
            name: "google_trends_bigquery",
            display_name: "Google Trend Keşfi (BigQuery)",
            configured: false,
            verified: false,
            state: "not_configured",
            freshness: null,
            last_success_at: null,
          }),
        ],
      },
    });
    discoveryMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: discovery({
        synced: false,
        refresh_date: null,
        last_sync_at: null,
        total_terms: 0,
        matched_count: 0,
        rising: [],
        matched: [],
      }),
    });

    render(await IntegrationsPage({}));

    expect(screen.getByText(/Henüz senkron yapılmadı/)).toBeTruthy();
    expect(screen.getByText("Yapılandırılmadı")).toBeTruthy();
  });

  it("shows the outcome notice of a connection test", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [provider()],
      },
    });

    render(
      await IntegrationsPage({
        searchParams: Promise.resolve({
          notice: "test-healthy",
          provider: "semrush",
        }),
      }),
    );

    expect(screen.getByRole("status").textContent).toContain(
      "Bağlantı doğrulandı: sağlayıcı yanıt verdi.",
    );
  });

  it("reports an unreachable backend honestly", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });

    render(await IntegrationsPage({}));

    expect(screen.getByRole("status").textContent).toContain(
      "Backend API'ye şu anda erişilemiyor.",
    );
  });
});
