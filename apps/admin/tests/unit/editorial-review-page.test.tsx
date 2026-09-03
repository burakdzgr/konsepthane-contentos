import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchReviewDetail: vi.fn(),
  };
});

import ReviewDetailPage from "@/app/editorial/[id]/reviews/[reviewId]/page";
import { fetchReviewDetail } from "@/lib/editorial-api";
import {
  REVIEW_ID,
  WORK_ITEM_ID,
  reviewDetail,
  reviewSummary,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchReviewDetail);

async function renderPage() {
  render(
    await ReviewDetailPage({
      params: Promise.resolve({ id: WORK_ITEM_ID, reviewId: REVIEW_ID }),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Editor review detail page", () => {
  it("renders verdict, findings, envelope, and attempts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: reviewDetail(),
      requestId: null,
    });

    await renderPage();

    for (const heading of [
      "Değerlendirme sürümü",
      "Bulgular",
      "Geçersiz kılma denetimi",
      "Editör üretim denemeleri",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    }
    expect(screen.getByText("pass")).toBeTruthy();
    expect(screen.getByText(/asla model yazımı değil/)).toBeTruthy();
    expect(screen.getByText("yeniden hesaplandı")).toBeTruthy();
    expect(screen.getByText("ton-notu")).toBeTruthy();
    expect(screen.getByText(/konsept-detaylari/)).toBeTruthy();
    expect(screen.getByText(/\(factual\)/)).toBeTruthy();
    expect(screen.getByText("succeeded")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "tam taslak sürümünü aç" }),
    ).toBeTruthy();
  });

  it("renders UNKNOWN when the envelope record is absent", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: reviewDetail({
        review: reviewSummary({ writer_envelope_recomputed: null }),
        integrity_gate_result: {},
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByText("BİLİNMİYOR")).toBeTruthy();
  });

  it("keeps deterministic drift findings visible with their origin", async () => {
    const base = reviewDetail();
    detailMock.mockResolvedValue({
      kind: "ok",
      data: reviewDetail({
        findings: [
          {
            ...base.findings[0]!,
            id: "af111111-2222-4333-8444-555555555555",
            finding_key: "drift-handling-coverage",
            dimension: "uncertainty_framing",
            severity: "blocking",
            origin: "deterministic",
            block_id: null,
            brief_claim_id: null,
            claim_key: null,
            claim_kind: null,
          },
        ],
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByText("drift-handling-coverage")).toBeTruthy();
    expect(screen.getByText("deterministic")).toBeTruthy();
    expect(screen.getByText("blocking")).toBeTruthy();
  });

  it("never renders the internal backend URL", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: reviewDetail(),
      requestId: null,
    });
    const { container } = render(
      await ReviewDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID, reviewId: REVIEW_ID }),
      }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
