import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchWorkQueue: vi.fn(),
    fetchWorkItemDetail: vi.fn(),
    fetchWorkItemDrafts: vi.fn(),
    fetchWorkItemReviews: vi.fn(),
    fetchWorkItemQaReports: vi.fn(),
    fetchWorkItemMedia: vi.fn(),
    fetchWorkItemPublication: vi.fn(),
  };
});

vi.mock("@/lib/research-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/research-api")>(
      "@/lib/research-api",
    );
  return {
    ...actual,
    fetchResearchSources: vi.fn(),
    fetchPipelineItems: vi.fn(),
  };
});

vi.mock("@/lib/auth-api", () => ({
  fetchCurrentUser: vi.fn(),
}));

import MotorPage from "@/app/motor/page";
import { fetchCurrentUser } from "@/lib/auth-api";
import {
  fetchWorkItemDetail,
  fetchWorkItemDrafts,
  fetchWorkItemMedia,
  fetchWorkItemPublication,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
  fetchWorkQueue,
} from "@/lib/editorial-api";
import { fetchPipelineItems, fetchResearchSources } from "@/lib/research-api";
import {
  REVIEWER_USER_ID,
  WORK_ITEM_ID,
  draftListPage,
  mediaCoveragePage,
  publicationPage,
  qaReportListPage,
  queuePage,
  queueRow,
  reviewListPage,
  workItemDetail,
} from "./editorial-fixtures";
import {
  pipelineItem,
  pipelinePage,
  sourceItem,
  sourcePage,
} from "./research-fixtures";

const queueMock = vi.mocked(fetchWorkQueue);
const detailMock = vi.mocked(fetchWorkItemDetail);
const draftsMock = vi.mocked(fetchWorkItemDrafts);
const reviewsMock = vi.mocked(fetchWorkItemReviews);
const qaMock = vi.mocked(fetchWorkItemQaReports);
const mediaMock = vi.mocked(fetchWorkItemMedia);
const publicationMock = vi.mocked(fetchWorkItemPublication);
const sourcesMock = vi.mocked(fetchResearchSources);
const pipelineMock = vi.mocked(fetchPipelineItems);
const currentUserMock = vi.mocked(fetchCurrentUser);

async function renderPage(params: Record<string, string> = {}) {
  render(await MotorPage({ searchParams: Promise.resolve(params) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  sourcesMock.mockResolvedValue({
    kind: "ok",
    data: sourcePage([]),
    requestId: null,
  });
  pipelineMock.mockResolvedValue({
    kind: "ok",
    data: pipelinePage([]),
    requestId: null,
  });
  queueMock.mockResolvedValue({
    kind: "ok",
    data: queuePage([]),
    requestId: null,
  });
  detailMock.mockResolvedValue({
    kind: "ok",
    data: workItemDetail(),
    requestId: null,
  });
  draftsMock.mockResolvedValue({
    kind: "ok",
    data: draftListPage([]),
    requestId: null,
  });
  reviewsMock.mockResolvedValue({
    kind: "ok",
    data: reviewListPage([]),
    requestId: null,
  });
  qaMock.mockResolvedValue({
    kind: "ok",
    data: qaReportListPage([]),
    requestId: null,
  });
  mediaMock.mockResolvedValue({
    kind: "ok",
    data: mediaCoveragePage(),
    requestId: null,
  });
  publicationMock.mockResolvedValue({
    kind: "ok",
    data: publicationPage(),
    requestId: null,
  });
  currentUserMock.mockResolvedValue({
    kind: "ok",
    data: {
      id: REVIEWER_USER_ID,
      username: "smoke-reviewer",
      display_name: "Smoke Reviewer",
      roles: ["operator", "reviewer"],
    },
    requestId: null,
  });
});

describe("Motor page", () => {
  it("renders empty pipeline honestly with no selected work", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { name: "Üretim Motoru" })).toBeTruthy();
    expect(screen.getByText(/Henüz iş öğesi yok/)).toBeTruthy();
    expect(screen.getByText(/Seçili iş yok/)).toBeTruthy();
    expect(detailMock).not.toHaveBeenCalled();
  });

  it("focuses the first queue item and offers exactly the briefing steps", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow()]),
      requestId: null,
    });

    await renderPage();

    // The stepper shows all six stages; briefing sits in stage 3.
    expect(screen.getByText("SEO & Brief")).toBeTruthy();
    expect(screen.getByText("Yayın")).toBeTruthy();
    // Default detail fixture: briefing with a draft brief.
    expect(screen.getByText("Brief'i kabul et")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Kabul et" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Brief oluştur" })).toBeTruthy();
    // The state badge renders the Turkish label, never invented progress.
    expect(screen.getAllByText("Brief hazırlama").length).toBeGreaterThan(0);
    expect(detailMock).toHaveBeenCalledWith(WORK_ITEM_ID);
  });

  it("selects an explicit item from the query and links its detail page", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow()]),
      requestId: null,
    });

    await renderPage({ item: WORK_ITEM_ID });

    const detailLink = screen.getByRole("link", { name: "Detay" });
    expect(detailLink.getAttribute("href")).toBe(`/editorial/${WORK_ITEM_ID}`);
  });

  it("withholds the human decision from non-reviewers", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow({ current_state: "awaiting_human_review" })]),
      requestId: null,
    });
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "awaiting_human_review",
        },
      }),
      requestId: null,
    });
    currentUserMock.mockResolvedValue({
      kind: "ok",
      data: {
        id: REVIEWER_USER_ID,
        username: "smoke-operator",
        display_name: "Smoke Operator",
        roles: ["operator"],
      },
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText(/reviewer rolü yok/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });

  it("offers the decision forms to a reviewer", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow({ current_state: "awaiting_human_review" })]),
      requestId: null,
    });
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "awaiting_human_review",
        },
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("button", { name: "Onayla" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Değişiklik iste" }),
    ).toBeTruthy();
  });

  it("surfaces intake work: discover, accept and promote", async () => {
    sourcesMock.mockResolvedValue({
      kind: "ok",
      data: sourcePage([
        sourceItem({ kind: "rss_feed", discovery_strategy: "feed" }),
      ]),
      requestId: null,
    });
    pipelineMock.mockResolvedValue({
      kind: "ok",
      data: pipelinePage([
        pipelineItem({
          lifecycle_state: "discovered",
          fetch_outcome: null,
          normalization_status: null,
          normalized_document_id: null,
        }),
        pipelineItem({
          id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          canonical_url: "https://ornek.example.test/hazir",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("button", { name: "Keşfi başlat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Kabul et" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yükselt" })).toBeTruthy();
  });

  it("reports an unreachable backend truthfully", async () => {
    sourcesMock.mockResolvedValue({ kind: "unreachable" });
    pipelineMock.mockResolvedValue({ kind: "unreachable" });
    queueMock.mockResolvedValue({ kind: "unreachable" });
    currentUserMock.mockResolvedValue({ kind: "unreachable" });

    await renderPage();

    expect(screen.getByText(/şu anda erişilemiyor/)).toBeTruthy();
    expect(detailMock).not.toHaveBeenCalled();
  });
});
