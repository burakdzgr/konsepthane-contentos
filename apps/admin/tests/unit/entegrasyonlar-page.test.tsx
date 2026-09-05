import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/integrations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/integrations-api")>(
    "@/lib/integrations-api",
  );
  return { ...actual, fetchIntegrations: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import IntegrationsPage from "@/app/entegrasyonlar/page";
import {
  fetchIntegrations,
  type IntegrationView,
} from "@/lib/integrations-api";

const fetchMock = vi.mocked(fetchIntegrations);

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
