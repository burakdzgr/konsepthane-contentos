import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/research-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/research-api")>(
      "@/lib/research-api",
    );
  return { ...actual, fetchPipelineItems: vi.fn() };
});

import ResearchPage from "@/app/research/page";
import { fetchPipelineItems } from "@/lib/research-api";
import {
  ITEM_ID,
  SOURCE_ID,
  pipelineItem,
  pipelinePage,
} from "./research-fixtures";

const fetchMock = vi.mocked(fetchPipelineItems);

async function renderPage(params: Record<string, string> = {}) {
  render(await ResearchPage({ searchParams: Promise.resolve(params) }));
}

// Filter <option> elements repeat enum text, so stage assertions must target
// the rendered badge, not any text node.
function badge(text: string): HTMLElement | undefined {
  return screen
    .getAllByText(text)
    .find((element) => element.classList.contains("badge"));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Research Pipeline page", () => {
  it("renders each stage explicitly for a full chain", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([pipelineItem()]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Research Pipeline" }),
    ).toBeTruthy();
    expect(badge("fetched")).toBeTruthy();
    expect(badge("success 200")).toBeTruthy();
    expect(badge("succeeded")).toBeTruthy();
    expect(badge("unique")).toBeTruthy();
    expect(badge("2")).toBeTruthy();
    expect(screen.getByText("2026-09-01 12:30 UTC")).toBeTruthy();

    const link = screen.getByRole("link", {
      name: "https://ornek.example.test/haber/uzun-baslik",
    });
    expect(link.getAttribute("href")).toBe(`/research/${ITEM_ID}`);
  });

  it("shows truthful per-stage placeholders and failure detail", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([
        pipelineItem({
          lifecycle_state: "rejected",
          rejection_reason: "out_of_scope",
          fetch_snapshot_id: null,
          fetch_outcome: null,
          fetched_at: null,
          status_code: null,
          retry_classification: null,
          normalized_document_id: null,
          normalization_status: null,
          normalization_failure_code: null,
          normalized_at: null,
          duplicate_decision_id: null,
          duplicate_outcome: null,
          duplicate_evaluated_at: null,
          evidence_count: 0,
          latest_evidence_at: null,
        }),
        pipelineItem({
          id: "8f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          canonical_url: "https://ornek.example.test/bozuk",
          lifecycle_state: "fetched",
          normalization_status: "failed",
          normalization_failure_code: "unsupported_content",
          duplicate_outcome: null,
          duplicate_decision_id: null,
          duplicate_evaluated_at: null,
          evidence_count: 0,
          latest_evidence_at: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(badge("rejected")).toBeTruthy();
    expect(screen.getByText("out_of_scope")).toBeTruthy();
    expect(badge("failed (unsupported_content)")).toBeTruthy();
    // No fake overall status: unfetched stages render explicit placeholders.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("passes parsed filters to the API", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([]),
      requestId: null,
    });

    await renderPage({
      source: SOURCE_ID,
      state: "fetched",
      method: "manual",
      fetch: "success",
      normalize: "succeeded",
      duplicate: "unique",
      evidence: "true",
      q: "haber",
      offset: "100",
    });

    expect(fetchMock).toHaveBeenCalledWith({
      sourceId: SOURCE_ID,
      lifecycleState: "fetched",
      discoveryMethod: "manual",
      fetchOutcome: "success",
      normalizationStatus: "succeeded",
      duplicateOutcome: "unique",
      hasEvidence: true,
      urlContains: "haber",
      limit: 50,
      offset: 100,
    });
  });

  it("drops an invalid source uuid and invalid enum filters", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([]),
      requestId: null,
    });

    await renderPage({ source: "DROP TABLE", state: "exploded" });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: undefined,
        lifecycleState: undefined,
      }),
    );
  });

  it("renders pagination preserving filters", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([pipelineItem()], { total: 80, offset: 50 }),
      requestId: null,
    });

    await renderPage({ state: "fetched", offset: "50" });

    expect(screen.getByText("Showing 51–51 of 80")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Previous" }).getAttribute("href"),
    ).toBe("/research?state=fetched");
  });

  it("renders empty, unreachable, and malformed states", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([]),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByRole("status").textContent).toMatch(
      /no discovery items match/i,
    );

    fetchMock.mockResolvedValue({ kind: "unreachable" });
    render(await ResearchPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText(/cannot be reached/i)).toBeTruthy();

    fetchMock.mockResolvedValue({ kind: "malformed" });
    render(await ResearchPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText(/unexpected data/i)).toBeTruthy();
  });
});
