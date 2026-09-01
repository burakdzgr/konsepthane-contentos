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

    expect(screen.getByRole("heading", { name: "Sources" })).toBeTruthy();
    expect(screen.getByText("Örnek Kaynak")).toBeTruthy();
    expect(screen.getByText("ornek-kaynak")).toBeTruthy();
    expect(badge("active")).toBeTruthy();
    expect(badge("paused")).toBeTruthy();
    expect(screen.getByText("4 items")).toBeTruthy();
    expect(
      screen.getByText("1 new · 1 accepted · 1 fetched · 1 failed"),
    ).toBeTruthy();
    // Both fixture rows share the same updated_at timestamp.
    expect(screen.getAllByText("2026-09-01 10:00 UTC")).toHaveLength(2);

    const itemsLink = screen.getByRole("link", { name: "4 items" });
    expect(itemsLink.getAttribute("href")).toBe(
      "/research?source=11111111-2222-4333-8444-555555555555",
    );
    // Read-only: the only button is the GET filter submit.
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["Apply"]);
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

    expect(screen.getByText("Showing 51–100 of 120")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Previous" }).getAttribute("href"),
    ).toBe("/sources?state=active");
    expect(
      screen.getByRole("link", { name: "Next" }).getAttribute("href"),
    ).toBe("/sources?state=active&offset=100");
  });

  it("renders an empty state", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("status").textContent).toMatch(/no sources match/i);
  });

  it("renders unreachable and malformed states without crashing", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByRole("status").textContent).toMatch(
      /cannot be reached/i,
    );

    fetchMock.mockResolvedValue({ kind: "malformed" });
    render(await SourcesPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText(/unexpected data/i)).toBeTruthy();
  });
});
