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
          score_eligibility: "commissionable",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Fırsat İncelemesi" }),
    ).toBeTruthy();
    expect(queueMock).toHaveBeenCalledWith({
      workflowState: "idea_scoring",
      opportunityDisposition: "open",
      limit: 50,
    });
    expect(screen.getByText("ÜRET")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reddet" })).toBeTruthy();
    // Both decisions demand a written reason.
    expect(screen.getByPlaceholderText("üretim gerekçesi")).toBeTruthy();
    expect(screen.getByPlaceholderText("ret gerekçesi")).toBeTruthy();
  });

  it("maps score eligibilities to honest recommendations", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          score_eligibility: "needs_operator_review",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("İNCELE")).toBeTruthy();
  });

  it("keeps unscored opportunities out with an honest note", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          score_id: null,
          score_eligibility: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText(/1 fırsat henüz skorlanıyor/)).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
  });
});
