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
    fetchWorkItemReviews: vi.fn(),
    fetchWorkItemQaReports: vi.fn(),
    fetchWorkItemDecisions: vi.fn(),
    fetchWorkItemMedia: vi.fn(),
  };
});

vi.mock("@/lib/auth-api", () => ({
  fetchCurrentUser: vi.fn(),
}));

import EditorialDetailPage from "@/app/editorial/[id]/page";
import { fetchCurrentUser } from "@/lib/auth-api";
import {
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkItemDecisions,
  fetchWorkItemDrafts,
  fetchWorkItemMedia,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
} from "@/lib/editorial-api";
import {
  DECISION_CONTENT_HASH,
  REVIEWER_USER_ID,
  WORK_ITEM_ID,
  approvalStatus,
  briefView,
  decisionListPage,
  decisionView,
  mediaCoveragePage,
  mediaSatisfaction,
  draftListPage,
  draftSummary,
  qaReportListPage,
  qaReportSummary,
  reviewListPage,
  reviewSummary,
  eligibleEvidenceItem,
  eligiblePage,
  workItemDetail,
  scoreView,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchWorkItemDetail);
const evidenceMock = vi.mocked(fetchEligibleEvidence);
const draftsMock = vi.mocked(fetchWorkItemDrafts);
const reviewsMock = vi.mocked(fetchWorkItemReviews);
const qaMock = vi.mocked(fetchWorkItemQaReports);
const decisionsMock = vi.mocked(fetchWorkItemDecisions);
const mediaMock = vi.mocked(fetchWorkItemMedia);
const currentUserMock = vi.mocked(fetchCurrentUser);

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
  decisionsMock.mockResolvedValue({
    kind: "ok",
    data: decisionListPage(),
    requestId: null,
  });
  mediaMock.mockResolvedValue({
    kind: "ok",
    data: mediaCoveragePage(),
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
      "Editor reviews",
      "QA reports",
      "Media",
      "Human decisions",
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

  it("shows editor review commands and truthful verdicts in EDITING", async () => {
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
    reviewsMock.mockResolvedValue({
      kind: "ok",
      data: reviewListPage([reviewSummary({ verdict: "revise" })]),
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByRole("button", { name: "Generate editor review" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Accept review" })).toBeTruthy();
    expect(screen.getByText("revise")).toBeTruthy();
    expect(screen.getByText(/backend will refuse/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open review" })).toBeTruthy();
  });

  it("hides review commands outside EDITING", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    await renderPage();
    expect(
      screen.queryByRole("button", { name: "Generate editor review" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept review" })).toBeNull();
  });

  it("shows QA commands and truthful gate badges in QA_REVIEW", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });
    qaMock.mockResolvedValue({
      kind: "ok",
      data: qaReportListPage([qaReportSummary()]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByRole("button", { name: "Run QA gates" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Waive media gate" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Request rework" })).toBeTruthy();
    expect(screen.getByText(/media_needs: unsatisfied/)).toBeTruthy();
    expect(screen.getByText("not_ready")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open report" })).toBeTruthy();
  });

  it("states the pending human decision in AWAITING_HUMAN_REVIEW", async () => {
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
    qaMock.mockResolvedValue({
      kind: "ok",
      data: qaReportListPage([
        qaReportSummary({
          outcome: "ready_for_human_review",
          gate_summary: {
            ...qaReportSummary().gate_summary,
            media_needs: "waived_by_human",
          },
        }),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("Human decision pending.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run QA gates" })).toBeNull();

    // The reviewer decision surface, gated on the reviewer role.
    expect(
      screen.getByRole("button", { name: "Approve package" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Request changes" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject package" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Revoke approval" }),
    ).toBeNull();
    // The routing choice is bounded to the three named responsible states.
    const select = screen.getByLabelText(
      "Decision responsible state",
    ) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      "drafting",
      "editing",
      "qa_review",
    ]);
  });

  it("hides decision commands without the reviewer role and says why", async () => {
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
    expect(
      screen.getByText(/signed in without the reviewer role/i),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Approve package" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Request changes" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject package" })).toBeNull();
  });

  it("shows the approval record, its validity, and revoke on APPROVED", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approved",
        },
      }),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage(
        [decisionView()],
        approvalStatus({
          approved: true,
          current: true,
          decision_id: decisionView().id,
          approved_content_hash: DECISION_CONTENT_HASH,
          active_content_hash: DECISION_CONTENT_HASH,
        }),
      ),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("Approval on record")).toBeTruthy();
    expect(screen.getByText("current")).toBeTruthy();
    expect(screen.getByText("Smoke Reviewer")).toBeTruthy();
    expect(screen.getAllByText("approved").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Revoke approval" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Approve package" }),
    ).toBeNull();
  });

  it("renders a stale approval honestly when the hash no longer matches", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approved",
        },
      }),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage(
        [decisionView()],
        approvalStatus({
          approved: true,
          current: false,
          decision_id: decisionView().id,
          approved_content_hash: DECISION_CONTENT_HASH,
          active_content_hash: `sha256:${"e".repeat(64)}`,
        }),
      ),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("stale")).toBeTruthy();
    expect(
      screen.getByText(/no longer matches the approved content hash/i),
    ).toBeTruthy();
  });

  it("shows the decision history including revocations", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage([
        decisionView({
          id: "d1000000-0000-4000-8000-00000000000d",
          decision: "approval_revoked",
          reason: "kaynak güncellendi",
          revokes_decision_id: decisionView().id,
        }),
        decisionView(),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("approval_revoked")).toBeTruthy();
    expect(screen.getByText("kaynak güncellendi")).toBeTruthy();
    expect(
      screen.getByText(new RegExp(`revokes=${decisionView().id}`)),
    ).toBeTruthy();
  });

  it("names the human actor in workflow history and keeps UNKNOWN honest", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();
    // Fixture: the operator event carries a resolved name; a hypothetical
    // pre-governance operator event without one must render UNKNOWN.
    expect(screen.getByText("operator · Smoke Reviewer")).toBeTruthy();

    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        workflow_events: workItemDetail().workflow_events.map((event) => ({
          ...event,
          actor_user_id: null,
          actor_display_name: null,
        })),
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByText("operator · UNKNOWN")).toBeTruthy();
  });

  it("offers the media binding commands for an unsatisfied need", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("Coverage: 0 / 1 needs satisfied.")).toBeTruthy();
    expect(screen.getByText("Unsatisfied")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Upload & bind" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Bind existing asset" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generate image" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Unbind" })).toBeNull();
  });

  it("shows the bound asset through the admin proxy and allows unbinding", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });
    mediaMock.mockResolvedValue({
      kind: "ok",
      data: mediaCoveragePage({
        needs: [
          {
            need_index: 0,
            role: "kapak görseli",
            purpose: "Balon temasını görselleştirmek.",
            constraints: null,
            satisfaction: mediaSatisfaction(),
          },
        ],
      }),
      requestId: null,
    });

    const { container } = render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(screen.getByText("Coverage: 1 / 1 needs satisfied.")).toBeTruthy();
    const image = screen.getByAltText(
      "Balon süslemeli parti masası",
    ) as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(
      `/editorial/media-assets/${mediaSatisfaction().asset.id}/content`,
    );
    expect(screen.getByText(/Bound by Smoke Reviewer/)).toBeTruthy();
    expect(screen.getByText("License: Konsepthane arşivi")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unbind" })).toBeTruthy();
    // The bytes come only from the admin's own proxy route.
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
  });

  it("freezes media commands under terminal review", async () => {
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
    expect(screen.getByText(/Media commands are closed/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Upload & bind" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate image" })).toBeNull();
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
