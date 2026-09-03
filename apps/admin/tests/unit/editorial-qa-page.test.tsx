import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchQaReportDetail: vi.fn(),
  };
});

import QaReportDetailPage from "@/app/editorial/[id]/qa-reports/[reportId]/page";
import { fetchQaReportDetail } from "@/lib/editorial-api";
import {
  QA_REPORT_ID,
  WORK_ITEM_ID,
  qaReportDetail,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchQaReportDetail);

async function renderPage() {
  render(
    await QaReportDetailPage({
      params: Promise.resolve({ id: WORK_ITEM_ID, reportId: QA_REPORT_ID }),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("QA report detail page", () => {
  it("renders outcome, gates, waivers, and package links", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: qaReportDetail(),
      requestId: null,
    });

    await renderPage();
    for (const heading of [
      "Rapor sürümü",
      "Katı kapılar",
      "Denetlenen vazgeçmeler",
      "Geçersiz kılma denetimi",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    }
    expect(screen.getByText("not_ready")).toBeTruthy();
    expect(
      screen.getByText(/tarafından deterministik olarak hesaplandı/),
    ).toBeTruthy();
    // The truthful media gate is visible and never softened.
    expect(screen.getByText("unsatisfied")).toBeTruthy();
    expect(screen.getByRole("link", { name: "taslak" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "editör değerlendirmesi" }),
    ).toBeTruthy();
  });

  it("renders UNKNOWN for a malformed gate record, never a pass", async () => {
    const base = qaReportDetail();
    detailMock.mockResolvedValue({
      kind: "ok",
      data: qaReportDetail({
        gate_results: { ...base.gate_results, media_needs: "garbled" },
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByText("BİLİNMİYOR")).toBeTruthy();
  });

  it("keeps waivers visible with their reasons", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: qaReportDetail({
        waivers: [
          {
            id: "b1111111-2222-4333-8444-555555555556",
            gate_key: "media_needs",
            reason: "görsel gereksinimi bilinçli olarak ertelendi",
            request_id: null,
            created_at: "2026-09-01T12:00:00+00:00",
          },
        ],
      }),
      requestId: null,
    });
    await renderPage();
    expect(
      screen.getByText("görsel gereksinimi bilinçli olarak ertelendi"),
    ).toBeTruthy();
  });

  it("never renders the internal backend URL", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: qaReportDetail(),
      requestId: null,
    });
    const { container } = render(
      await QaReportDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID, reportId: QA_REPORT_ID }),
      }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
