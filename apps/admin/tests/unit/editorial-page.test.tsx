import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return { ...actual, fetchWorkQueue: vi.fn() };
});

import EditorialPage from "@/app/editorial/page";
import { fetchWorkQueue } from "@/lib/editorial-api";
import { WORK_ITEM_ID, queuePage, queueRow } from "./editorial-fixtures";

const fetchMock = vi.mocked(fetchWorkQueue);

async function renderPage(params: Record<string, string> = {}) {
  render(await EditorialPage({ searchParams: Promise.resolve(params) }));
}

function badge(text: string): HTMLElement | undefined {
  return screen
    .getAllByText(text)
    .find((element) => element.classList.contains("badge"));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Editorial work queue page", () => {
  it("renders one full row with explainable projections", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow()]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Editoryal İş Kuyruğu" }),
    ).toBeTruthy();
    expect(badge("Brif hazırlığı")).toBeTruthy();
    expect(badge("Güçlü / Görevlendirilebilir")).toBeTruthy();
    expect(screen.getByText("1 eksik sinyal")).toBeTruthy();
    expect(screen.getByText("Balon temalı plan")).toBeTruthy();
    expect(screen.getByText("özgünlük: Geçti")).toBeTruthy();
    expect(badge("v1 Hazır")).toBeTruthy();
    expect(badge("v1 Taslak")).toBeTruthy();
    const link = screen.getByRole("link", {
      name: "Evde doğum günü partisi rehberi",
    });
    expect(link.getAttribute("href")).toBe(`/editorial/${WORK_ITEM_ID}`);
  });

  it("renders absent artifacts as absent, never as progress", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          score_id: null,
          score_band: null,
          score_eligibility: null,
          score_overall_value: null,
          score_missing_signals: [],
          score_evaluated_at: null,
          score_engine_name: null,
          score_engine_version: null,
          selected_idea_id: null,
          selected_idea_title: null,
          selected_idea_originality: null,
          latest_pack_id: null,
          latest_pack_version: null,
          latest_pack_sufficiency: null,
          latest_analysis_id: null,
          latest_analysis_version: null,
          latest_brief_id: null,
          latest_brief_version: null,
          latest_brief_status: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("Değerlendirilmedi")).toBeTruthy();
    expect(screen.getByText("Seçim yok")).toBeTruthy();
    expect(screen.getByText("Paket yok")).toBeTruthy();
    expect(screen.getByText("Brief yok")).toBeTruthy();
  });

  it("shows the blocked reason on blocked rows", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "blocked",
          blocked_reason: "kanıt paketi yetersiz: eksikler var",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(badge("Engellendi")).toBeTruthy();
    expect(
      screen.getByText("kanıt paketi yetersiz: eksikler var"),
    ).toBeTruthy();
  });

  it("passes parsed filters to the API and drops junk", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([]),
      requestId: null,
    });

    await renderPage({
      state: "briefing",
      disposition: "commissioned",
      q: "parti",
      offset: "50",
      bogus: "x",
    });

    expect(fetchMock).toHaveBeenCalledWith({
      workflowState: "briefing",
      opportunityDisposition: "commissioned",
      search: "parti",
      limit: 50,
      offset: 50,
    });
  });

  it("renders truthful failure states", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(
      screen.getByText("Arka uç API'sine şu anda ulaşılamıyor."),
    ).toBeTruthy();
  });
});
