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

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return { ...actual, fetchIntakeRuns: vi.fn() };
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
import { fetchIntakeRuns } from "@/lib/intake-api";
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

const queueMock = vi.mocked(fetchWorkQueue);
const detailMock = vi.mocked(fetchWorkItemDetail);
const draftsMock = vi.mocked(fetchWorkItemDrafts);
const reviewsMock = vi.mocked(fetchWorkItemReviews);
const qaMock = vi.mocked(fetchWorkItemQaReports);
const mediaMock = vi.mocked(fetchWorkItemMedia);
const publicationMock = vi.mocked(fetchWorkItemPublication);
const runsMock = vi.mocked(fetchIntakeRuns);
const currentUserMock = vi.mocked(fetchCurrentUser);

async function renderPage(params: Record<string, string> = {}) {
  render(await MotorPage({ searchParams: Promise.resolve(params) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  runsMock.mockResolvedValue({
    kind: "ok",
    data: { generated_at: "2026-09-03T10:00:00+00:00", runs: [] },
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

  it("shows the autonomous intake monitor instead of raw URL controls", async () => {
    runsMock.mockResolvedValue({
      kind: "ok",
      data: {
        generated_at: "2026-09-03T10:00:00+00:00",
        runs: [
          {
            id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            source_id: "11111111-2222-4333-8444-555555555555",
            source_slug: "kara",
            source_name: "Kara's Party Ideas",
            status: "running",
            discovered_new: 4993,
            rediscovered: 0,
            prefilter_accepted: 120,
            prefilter_rejected: 30,
            fetch_dispatched: 8,
            fetched: 5,
            fetch_failed: 0,
            promotions_dispatched: 2,
            opportunities_created: 2,
            remaining_accepted: 100,
            remaining_discovered: 0,
            policy: {},
            failure_note: null,
            created_at: "2026-09-03T10:00:00+00:00",
            discovery_completed_at: "2026-09-03T10:01:00+00:00",
            prefilter_completed_at: null,
            finished_at: null,
            updated_at: "2026-09-03T10:02:00+00:00",
            last_event_at: "2026-09-03T10:02:00+00:00",
          },
        ],
      },
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("1 aktif çalışma")).toBeTruthy();
    const runLink = screen.getByRole("link", {
      name: /Kara's Party Ideas: 5\/8 getirildi/,
    });
    expect(runLink.getAttribute("href")).toBe(
      "/calisma/1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    );
    // The raw URL approval workflow is gone from the Motor.
    expect(screen.queryByRole("button", { name: "Kabul et" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Yükselt" })).toBeNull();
  });

  it("reports an unreachable backend truthfully", async () => {
    runsMock.mockResolvedValue({ kind: "unreachable" });
    queueMock.mockResolvedValue({ kind: "unreachable" });
    currentUserMock.mockResolvedValue({ kind: "unreachable" });

    await renderPage();

    expect(screen.getByText(/şu anda erişilemiyor/)).toBeTruthy();
    expect(detailMock).not.toHaveBeenCalled();
  });
});
