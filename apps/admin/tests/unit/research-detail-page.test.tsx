import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/research-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/research-api")>(
      "@/lib/research-api",
    );
  return { ...actual, fetchPipelineDetail: vi.fn() };
});

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

import ResearchDetailPage from "@/app/research/[id]/page";
import { fetchPipelineDetail } from "@/lib/research-api";
import { notFound } from "next/navigation";
import { ITEM_ID, pipelineDetail } from "./research-fixtures";

const fetchMock = vi.mocked(fetchPipelineDetail);
const notFoundMock = vi.mocked(notFound);

async function renderPage(id: string = ITEM_ID) {
  render(await ResearchDetailPage({ params: Promise.resolve({ id }) }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Research detail page", () => {
  it("renders all five sections for a complete pipeline", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelineDetail(),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Discovery item" }),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Discovery" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Fetch history" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Normalization history" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Duplicate decisions" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Evidence summary" }),
    ).toBeTruthy();

    expect(screen.getAllByText("Örnek Kaynak").length).toBeGreaterThan(0);
    expect(screen.getByText("Uzun Başlık")).toBeTruthy();
    expect(screen.getByText("success")).toBeTruthy();
    expect(screen.getByText("2048 B")).toBeTruthy();
    expect(screen.getByText("html-basic/1")).toBeTruthy();
    expect(screen.getByText("İstanbul Rehberi")).toBeTruthy();
    expect(screen.getByText("Ayşe Yılmaz")).toBeTruthy();
    expect(screen.getByText("duplicate-engine/1")).toBeTruthy();
    expect(screen.getByText("no_candidates")).toBeTruthy();
    expect(screen.getByText("unverified: 2")).toBeTruthy();
    expect(screen.getByText("observation: 2")).toBeTruthy();
    expect(screen.getByText(ITEM_ID)).toBeTruthy();
    // Statements/excerpts never render; the page says counts only.
    expect(
      screen.getByText(/statements and excerpts are not shown/i),
    ).toBeTruthy();
    // Read-only: no buttons at all on the detail page.
    expect(screen.queryAllByRole("button")).toEqual([]);
  });

  it("shows a truncation note for bounded histories", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelineDetail({
        total_fetch_attempts: 22,
        fetch_attempts_truncated: true,
      }),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByText("Showing the latest 1 of 22 fetch attempts."),
    ).toBeTruthy();
  });

  it("renders empty section notes when stages never ran", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelineDetail({
        fetch_attempts: [],
        total_fetch_attempts: 0,
        normalization_attempts: [],
        total_normalization_attempts: 0,
        duplicate_decisions: [],
        total_duplicate_decisions: 0,
        evidence: {
          total: 0,
          by_verification_status: {},
          by_evidence_type: {},
          latest_extracted_at: null,
        },
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("No fetch attempts recorded.")).toBeTruthy();
    expect(
      screen.getByText("No normalization attempts recorded."),
    ).toBeTruthy();
    expect(screen.getByText("No duplicate decisions recorded.")).toBeTruthy();
  });

  it("raises the framework not-found flow for a missing item", async () => {
    fetchMock.mockResolvedValue({ kind: "not_found" });

    await expect(renderPage()).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalledTimes(1);
  });

  it("renders unreachable and malformed states without crashing", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByRole("status").textContent).toMatch(
      /cannot be reached/i,
    );

    fetchMock.mockResolvedValue({ kind: "malformed" });
    render(
      await ResearchDetailPage({ params: Promise.resolve({ id: ITEM_ID }) }),
    );
    expect(screen.getByText(/unexpected data/i)).toBeTruthy();
  });
});
