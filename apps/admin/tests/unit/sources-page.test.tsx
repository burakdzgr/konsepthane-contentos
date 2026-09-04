import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/research-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/research-api")>(
      "@/lib/research-api",
    );
  return { ...actual, fetchResearchSources: vi.fn() };
});

import SourcesPage from "@/app/sources/page";
import { fetchResearchSources } from "@/lib/research-api";
import { sourceItem, sourcePage } from "./research-fixtures";

const fetchMock = vi.mocked(fetchResearchSources);

async function renderPage(params: Record<string, string> = {}) {
  render(await SourcesPage({ searchParams: Promise.resolve(params) }));
}

// Filter <option> elements repeat enum text, so state assertions must target
// the rendered badge, not any text node.
function badge(text: string): HTMLElement | undefined {
  return screen
    .getAllByText(text)
    .find((element) => element.classList.contains("badge"));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Sources page", () => {
  it("renders registry rows with counts and no action buttons", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([
        sourceItem(),
        sourceItem({
          id: "91111111-2222-4333-8444-555555555555",
          slug: "durmus-kaynak",
          name: "Durmuş Kaynak",
          lifecycle_state: "paused",
          total_discovery_items: 0,
          discovered_count: 0,
          accepted_count: 0,
          fetched_count: 0,
          fetch_failed_count: 0,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("heading", { name: "Kaynaklar" })).toBeTruthy();
    expect(screen.getByText("Örnek Kaynak")).toBeTruthy();
    expect(screen.getByText("ornek-kaynak")).toBeTruthy();
    expect(badge("Etkin")).toBeTruthy();
    expect(badge("Duraklatıldı")).toBeTruthy();
    expect(screen.getByText("4 öğe")).toBeTruthy();
    expect(
      screen.getByText("1 yeni · 1 kabul edildi · 1 getirildi · 1 başarısız"),
    ).toBeTruthy();
    // Both fixture rows share the same updated_at timestamp.
    expect(screen.getAllByText("2026-09-01 10:00 UTC")).toHaveLength(2);

    const itemsLink = screen.getByRole("link", { name: "4 öğe" });
    expect(itemsLink.getAttribute("href")).toBe(
      "/research?source=11111111-2222-4333-8444-555555555555",
    );
    // Controls are the GET filter submit plus one lifecycle form per row;
    // neither manual source is eligible for "Keşfi başlat".
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Uygula",
      "Durumu uygula",
      "Durumu uygula",
    ]);
    expect(screen.queryByRole("button", { name: "Keşfi başlat" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Kaynak kaydet" }).getAttribute("href"),
    ).toBe("/sources/new");
  });

  it("shows Keşfi başlat only for active automated sources", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([
        sourceItem({
          id: "61111111-2222-4333-8444-555555555555",
          slug: "aktif-akis",
          kind: "rss_feed",
          discovery_strategy: "feed",
          lifecycle_state: "active",
        }),
        sourceItem({
          id: "71111111-2222-4333-8444-555555555555",
          slug: "durgun-akis",
          kind: "rss_feed",
          discovery_strategy: "feed",
          lifecycle_state: "paused",
        }),
        sourceItem({
          id: "81111111-2222-4333-8444-555555555555",
          slug: "elle-kaynak",
          kind: "manual",
          discovery_strategy: "manual",
          lifecycle_state: "active",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    // Exactly one eligible source: active rss_feed with feed strategy.
    expect(
      screen.getAllByRole("button", { name: "Keşfi başlat" }),
    ).toHaveLength(1);
  });

  it("renders success notices and bounded error notices", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([]),
      requestId: null,
    });

    await renderPage({ notice: "discovery-queued" });
    expect(screen.getByText("Keşif kuyruğa alındı.")).toBeTruthy();

    render(
      await SourcesPage({
        searchParams: Promise.resolve({ error: "conflict" }),
      }),
    );
    // The error text lives in the shared notices module; assert on the
    // bounded error banner's tone rather than its exact wording.
    expect(document.querySelector('.notice[data-tone="bad"]')).toBeTruthy();
  });

  it("passes parsed filters to the API and drops invalid values", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([]),
      requestId: null,
    });

    await renderPage({
      state: "paused",
      kind: "not-a-kind",
      strategy: "feed",
      q: "gezi",
      offset: "50",
    });

    expect(fetchMock).toHaveBeenCalledWith({
      lifecycleState: "paused",
      kind: undefined,
      discoveryStrategy: "feed",
      search: "gezi",
      limit: 50,
      offset: 50,
    });
  });

  it("renders pagination links preserving filters", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage(
        Array.from({ length: 50 }, (_, index) =>
          sourceItem({
            id: `5111111${index}-2222-4333-8444-55555555555${index % 10}`.slice(
              0,
              36,
            ),
            slug: `kaynak-${index}`,
          }),
        ),
        { total: 120, offset: 50 },
      ),
      requestId: null,
    });

    await renderPage({ state: "active", offset: "50" });

    expect(screen.getByText("51–100 / 120 gösteriliyor")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Önceki" }).getAttribute("href"),
    ).toBe("/sources?state=active");
    expect(
      screen.getByRole("link", { name: "Sonraki" }).getAttribute("href"),
    ).toBe("/sources?state=active&offset=100");
  });

  it("renders an empty state", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("status").textContent).toMatch(
      /eşleşen kaynak yok/,
    );
  });

  it("renders unreachable and malformed states without crashing", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByRole("status").textContent).toMatch(/ulaşılamıyor/);

    fetchMock.mockResolvedValue({ kind: "malformed" });
    render(await SourcesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText(/beklenmeyen veri/)).toBeTruthy();
  });
});
