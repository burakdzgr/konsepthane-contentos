import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchWorkItemDetail: vi.fn(),
    fetchEligibleEvidence: vi.fn(),
    fetchWorkItemDrafts: vi.fn(),
  };
});

import EditorialDetailPage from "@/app/editorial/[id]/page";
import {
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkItemDrafts,
} from "@/lib/editorial-api";
import {
  WORK_ITEM_ID,
  briefView,
  draftListPage,
  draftSummary,
  eligibleEvidenceItem,
  eligiblePage,
  workItemDetail,
  scoreView,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchWorkItemDetail);
const evidenceMock = vi.mocked(fetchEligibleEvidence);
const draftsMock = vi.mocked(fetchWorkItemDrafts);

async function renderPage(params: Record<string, string> = {}) {
  render(
    await EditorialDetailPage({
      params: Promise.resolve({ id: WORK_ITEM_ID }),
      searchParams: Promise.resolve(params),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  evidenceMock.mockResolvedValue({
    kind: "ok",
    data: eligiblePage([]),
    requestId: null,
  });
  draftsMock.mockResolvedValue({
    kind: "ok",
    data: draftListPage([]),
    requestId: null,
  });
});

describe("Editorial detail page", () => {
  it("renders all explainability sections for a full item", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();

    for (const heading of [
      "Workflow",
      "Opportunity & score",
      "Research inputs",
      "Ideas",
      "Evidence packs",
      "Search intent",
      "Briefs & claims",
      "Writer drafts",
      "AI attempts",
      "Workflow history",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    }

    // Score explainability: band + eligibility + UNKNOWN stays Unknown.
    expect(screen.getByText("strong / commissionable")).toBeTruthy();
    expect(screen.getByText("(effective)")).toBeTruthy();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(screen.getByText("Not observed")).toBeTruthy();

    // Idea selection state + generation provenance.
    expect(screen.getByText("(selected)")).toBeTruthy();
    expect(screen.getAllByText("passed").length).toBeGreaterThan(0);

    // Pack members + unresolved contradiction stays visible.
    expect(screen.getByText("unresolved")).toBeTruthy();
    expect(
      screen.getByText("Kaynaklar hazırlık süresinde uyuşmuyor."),
    ).toBeTruthy();

    // Intent: known vs missing signals + honest cannibalization wording.
    expect(screen.getByText("search_volume, trend")).toBeTruthy();
    expect(screen.getByText("Not checked")).toBeTruthy();

    // Brief claim map with exact evidence links.
    expect(screen.getByText("konsept-detaylari")).toBeTruthy();

    // AI attempt safe metadata; never prompt/output.
    expect(
      screen.getByText("fake/deterministic-structured-test-model"),
    ).toBeTruthy();
    expect(screen.getByText("input_tokens: 100")).toBeTruthy();
  });

  it("keeps accept-for-drafting wording distinct from publication", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("button", { name: "Accept for drafting" }),
    ).toBeTruthy();
    expect(screen.getByText(/does NOT publish content/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /publish/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /go live/i })).toBeNull();
  });

  it("offers commissioning with score context only while decidable", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "idea_scoring",
        },
        opportunity: {
          ...workItemDetail().opportunity!,
          disposition: "open",
          disposition_reason: null,
        },
        ideas: [],
        evidence_packs: [],
        intent_analyses: [],
        briefs: [],
        total_briefs: 0,
        total_ideas: 0,
        total_evidence_packs: 0,
        total_intent_analyses: 0,
        effective_selected_idea_id: null,
        selection_events: [],
        total_selection_events: 0,
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("button", { name: "Commission" })).toBeTruthy();
    expect(
      screen.getByText(/Effective score: strong \/ commissionable/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Reject opportunity" }),
    ).toBeTruthy();
  });

  it("hides commissioning once commissioned and shows the pack builder gate", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "evidence_building",
        },
        evidence_packs: [],
        total_evidence_packs: 0,
        intent_analyses: [],
        total_intent_analyses: 0,
        briefs: [],
        total_briefs: 0,
      }),
      requestId: null,
    });
    evidenceMock.mockResolvedValue({
      kind: "ok",
      data: eligiblePage([eligibleEvidenceItem()]),
      requestId: null,
    });

    await renderPage();

    expect(screen.queryByRole("button", { name: "Commission" })).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Build evidence pack from selection",
      }),
    ).toBeTruthy();
    expect(screen.getByText(/You select the evidence explicitly/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Generate idea candidates" }),
    ).toBeTruthy();
  });

  it("shows blocked reason, derived resume target, and only accepted controls", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "blocked",
          blocked_reason: "kanıt paketi yetersiz",
          blocked_resume_state: "evidence_building",
        },
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("kanıt paketi yetersiz")).toBeTruthy();
    expect(screen.getByText("Legal resume target")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Resolve block" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Reject blocked item" }),
    ).toBeTruthy();
    // No arbitrary target selector exists anywhere.
    expect(screen.queryByLabelText(/target state/i)).toBeNull();
  });

  it("marks unknown score values as Unknown, never zero", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        scores: [scoreView({ overall_value: null })],
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
  });

  it("shows writer commands in DRAFTING with an accepted brief", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "drafting",
        },
        briefs: [briefView({ status: "accepted_for_drafting" })],
      }),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([draftSummary()]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("button", { name: "Generate writer draft" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Submit operator draft" }),
    ).toBeTruthy();
    // The listed draft keeps its truthful verdicts and links to detail.
    expect(screen.getByText("evaluated")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open draft" })).toBeTruthy();
    // No rework commands outside their states.
    expect(screen.queryByRole("button", { name: "Request rework" })).toBeNull();
  });

  it("shows rework in EDITING and routing in CHANGES_REQUESTED", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "editing",
        },
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByRole("button", { name: "Request rework" })).toBeTruthy();

    vi.mocked(detailMock).mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "changes_requested",
        },
      }),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([]),
      requestId: null,
    });
    render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(screen.getByRole("button", { name: "Route rework" })).toBeTruthy();
  });

  it("renders UNKNOWN for drafts without persisted verdicts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([
        draftSummary({
          uncertainty_coverage_status: null,
          originality_outcome: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getAllByText("UNKNOWN").length).toBe(2);
  });

  it("never renders the internal backend URL", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    const { container } = render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
