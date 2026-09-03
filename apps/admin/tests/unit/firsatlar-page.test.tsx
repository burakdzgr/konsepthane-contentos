import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return { ...actual, fetchWorkQueue: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import OpportunityReviewPage from "@/app/firsatlar/page";
import { fetchWorkQueue } from "@/lib/editorial-api";
import { queuePage, queueRow } from "./editorial-fixtures";

const queueMock = vi.mocked(fetchWorkQueue);

async function renderPage() {
  render(await OpportunityReviewPage({ searchParams: Promise.resolve({}) }));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Opportunity review page", () => {
  it("asks the production question with the explainable score", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "produce",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Benden Bekleyenler" }),
    ).toBeTruthy();
    expect(queueMock).toHaveBeenCalledWith({
      workflowState: "idea_scoring",
      opportunityDisposition: "open",
      limit: 50,
    });
    expect(screen.getByText("İÇERİK ÜRET")).toBeTruthy();
    expect(screen.getByText("Yüksek")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reddet" })).toBeTruthy();
    // Both decisions demand a written reason.
    expect(screen.getByPlaceholderText("üretim gerekçesi")).toBeTruthy();
    expect(screen.getByPlaceholderText("ret gerekçesi")).toBeTruthy();
  });

  it("keeps machine continuation out of the human decision inbox", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "continue_research",
          inspiration_band: "low",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByText(/sistem otomatik olarak araştırmayı sürdürüyor/),
    ).toBeTruthy();
    expect(screen.queryByText("ARAŞTIRMAYA DEVAM ET")).toBeNull();
    expect(
      screen.getByText(/şu anda sizden karar bekleyen bir iş yok/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
  });

  it("keeps unscored opportunities out with an honest note", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          inspiration_evaluation_id: null,
          recommendation: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByText(/1 fırsatı ContentOS değerlendiriyor/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
  });
});
