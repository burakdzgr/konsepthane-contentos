import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchDraftDetail: vi.fn(),
  };
});

import DraftDetailPage from "@/app/editorial/[id]/drafts/[draftId]/page";
import { fetchDraftDetail } from "@/lib/editorial-api";
import {
  DRAFT_ID,
  EVIDENCE_ID,
  WORK_ITEM_ID,
  draftDetail,
  draftSummary,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchDraftDetail);

async function renderPage() {
  render(
    await DraftDetailPage({
      params: Promise.resolve({ id: WORK_ITEM_ID, draftId: DRAFT_ID }),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Writer draft detail page", () => {
  it("renders body, claim chain, audit, and attempts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: draftDetail(),
      requestId: null,
    });

    await renderPage();

    for (const heading of [
      "Taslak sürümü",
      "Gövde",
      "İddia → kanıt zinciri",
      "Geçersiz kılma denetimi",
      "Yazar üretim denemeleri",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    }

    // The body block with its provenance annotations.
    expect(
      screen.getByText("Evde parti hem samimi hem butce dostudur."),
    ).toBeTruthy();
    // Claim chain resolves to ResearchEvidence identities.
    expect(screen.getByText(EVIDENCE_ID)).toBeTruthy();
    expect(screen.getByText("konsept-detaylari")).toBeTruthy();
    // Verdicts stay explicit.
    expect(screen.getByText("evaluated")).toBeTruthy();
    expect(screen.getByText("passed")).toBeTruthy();
  });

  it("renders UNKNOWN when the record carries no verdicts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: draftDetail({
        draft: draftSummary({
          uncertainty_coverage_status: null,
          originality_outcome: null,
        }),
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getAllByText("BİLİNMİYOR").length).toBe(2);
  });

  it("keeps failed attempts visible with their error class", async () => {
    const detail = draftDetail();
    detailMock.mockResolvedValue({
      kind: "ok",
      data: draftDetail({
        generation_attempts: [
          {
            ...detail.generation_attempts[0]!,
            id: "ac111111-2222-4333-8444-555555555555",
            status: "validation_failed",
            error_class: "domain_validation",
          },
          detail.generation_attempts[0]!,
        ],
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("validation_failed")).toBeTruthy();
    expect(screen.getByText("(domain_validation)")).toBeTruthy();
    expect(screen.getByText("succeeded")).toBeTruthy();
  });

  it("never renders the internal backend URL", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: draftDetail(),
      requestId: null,
    });

    const { container } = render(
      await DraftDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID, draftId: DRAFT_ID }),
      }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
