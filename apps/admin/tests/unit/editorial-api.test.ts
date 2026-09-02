// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchDraftDetail,
  fetchQaReportDetail,
  fetchReviewDetail,
  fetchEligibleEvidence,
  fetchWorkItemDecisions,
  fetchWorkItemDetail,
  fetchWorkItemDrafts,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
  fetchWorkQueue,
} from "@/lib/editorial-api";
import {
  DECISION_CONTENT_HASH,
  WORK_ITEM_ID,
  approvalStatus,
  decisionListPage,
  decisionView,
  OPPORTUNITY_ID,
  DRAFT_ID,
  QA_REPORT_ID,
  REVIEW_ID,
  draftDetail,
  draftListPage,
  draftSummary,
  qaReportDetail,
  qaReportListPage,
  qaReportSummary,
  reviewDetail,
  reviewListPage,
  reviewSummary,
  eligibleEvidenceItem,
  eligiblePage,
  queuePage,
  queueRow,
  workItemDetail,
} from "./editorial-fixtures";

const INTERNAL_HOST = "127.0.0.1";

function jsonResponse(status: number, body: unknown) {
  return {
    status,
    headers: { get: () => null },
    json: async () => body,
  };
}

function stubFetch(implementation: (...args: unknown[]) => unknown) {
  const fetchMock = vi.fn(implementation);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchWorkQueue", () => {
  it("parses a full row and encodes filters", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, queuePage([queueRow()])),
    );

    const result = await fetchWorkQueue({
      workflowState: "briefing",
      opportunityDisposition: "commissioned",
      search: "parti",
      limit: 50,
      offset: 50,
    });

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      const row = result.data.items[0];
      expect(row?.work_item_id).toBe(WORK_ITEM_ID);
      expect(row?.score_eligibility).toBe("commissionable");
      expect(row?.latest_pack_sufficiency).toBe("ready");
    }
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("/internal/editorial/work-items?");
    expect(url).toContain("workflow_state=briefing");
    expect(url).toContain("opportunity_disposition=commissioned");
    expect(url).toContain("search=parti");
    expect(url).toContain("offset=50");
  });

  it("rejects an unknown workflow state as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        queuePage([queueRow({ current_state: "surprise" as never })]),
      ),
    );

    const result = await fetchWorkQueue();
    expect(result.kind).toBe("malformed");
  });

  it("returns a bounded unreachable kind without URL details", async () => {
    stubFetch(async () => {
      throw new Error(`connect ECONNREFUSED ${INTERNAL_HOST}:8000`);
    });

    const result = await fetchWorkQueue();
    expect(result).toEqual({ kind: "unreachable" });
    expect(JSON.stringify(result)).not.toContain(INTERNAL_HOST);
  });
});

describe("fetchWorkItemDetail", () => {
  it("parses the full detail projection", async () => {
    stubFetch(async () => jsonResponse(200, workItemDetail()));

    const result = await fetchWorkItemDetail(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.scores[0]?.effective).toBe(true);
      expect(result.data.evidence_packs[0]?.contradictions).toHaveLength(1);
      expect(result.data.briefs[0]?.claims[0]?.evidence_ids).toHaveLength(1);
      expect(result.data.ai_attempts[0]?.provider).toBe("fake");
    }
  });

  it("treats a junk id as missing without calling the backend", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, {}));
    const result = await fetchWorkItemDetail("junk");
    expect(result).toEqual({ kind: "not_found" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps backend 404 to not_found", async () => {
    stubFetch(async () => jsonResponse(404, { error: {} }));
    const result = await fetchWorkItemDetail(WORK_ITEM_ID);
    expect(result).toEqual({ kind: "not_found" });
  });
});

describe("fetchEligibleEvidence", () => {
  it("parses the page and never carries an excerpt field", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        eligiblePage([
          { ...eligibleEvidenceItem(), excerpt: "should be stripped" } as never,
        ]),
      ),
    );

    const result = await fetchEligibleEvidence(OPPORTUNITY_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      const item = result.data.items[0];
      expect(item?.statement).toContain("konsept");
      expect(item !== undefined && "excerpt" in item).toBe(false);
    }
  });
});

describe("draft reads", () => {
  it("parses the draft list with truthful null verdicts", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(
        200,
        draftListPage([
          draftSummary({
            uncertainty_coverage_status: null,
            originality_outcome: null,
          }),
        ]),
      ),
    );

    const result = await fetchWorkItemDrafts(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.drafts[0]?.uncertainty_coverage_status).toBeNull();
      expect(result.data.drafts[0]?.originality_outcome).toBeNull();
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/drafts`,
    );
  });

  it("parses the full draft detail with the provenance chain", async () => {
    stubFetch(async () => jsonResponse(200, draftDetail()));

    const result = await fetchDraftDetail(DRAFT_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.body.sections[0]?.blocks[0]?.kind).toBe("paragraph");
      expect(result.data.claim_usages[0]?.research_evidence_ids.length).toBe(1);
      expect(result.data.generation_attempts[0]?.purpose).toBe("writer_draft");
    }
  });

  it("rejects an unknown draft status as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        draftListPage([draftSummary({ status: "weird" as never })]),
      ),
    );
    const result = await fetchWorkItemDrafts(WORK_ITEM_ID);
    expect(result.kind).toBe("malformed");
  });

  it("maps 404s to not_found and bad ids never hit the network", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(404, {}));
    const missing = await fetchDraftDetail(DRAFT_ID);
    expect(missing.kind).toBe("not_found");
    const invalid = await fetchWorkItemDrafts("not-a-uuid");
    expect(invalid.kind).toBe("not_found");
    expect(fetchMock.mock.calls.length).toBe(1);
  });
});

describe("review reads", () => {
  it("parses the review list and truthful UNKNOWN envelope", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(
        200,
        reviewListPage([reviewSummary({ writer_envelope_recomputed: null })]),
      ),
    );
    const result = await fetchWorkItemReviews(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.reviews[0]?.writer_envelope_recomputed).toBeNull();
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/reviews`,
    );
  });

  it("parses the review detail with anchors and attempts", async () => {
    stubFetch(async () => jsonResponse(200, reviewDetail()));
    const result = await fetchReviewDetail(REVIEW_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.findings[0]?.claim_key).toBe("konsept-detaylari");
      expect(result.data.generation_attempts[0]?.purpose).toBe("editor_review");
    }
  });

  it("rejects an unknown verdict as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        reviewListPage([reviewSummary({ verdict: "reject" as never })]),
      ),
    );
    const result = await fetchWorkItemReviews(WORK_ITEM_ID);
    expect(result.kind).toBe("malformed");
  });
});

describe("qa report reads", () => {
  it("parses the report list with truthful gate summaries", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, qaReportListPage([qaReportSummary()])),
    );
    const result = await fetchWorkItemQaReports(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.reports[0]?.gate_summary["media_needs"]).toBe(
        "unsatisfied",
      );
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/qa-reports`,
    );
  });

  it("parses the report detail with policy and gates", async () => {
    stubFetch(async () => jsonResponse(200, qaReportDetail()));
    const result = await fetchQaReportDetail(QA_REPORT_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.gate_policy_snapshot["version"]).toBe("qa-gates/1");
      expect(result.data.gate_results["media_needs"]).toEqual({
        result: "unsatisfied",
        needs: 2,
      });
    }
  });

  it("rejects an unknown outcome as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        qaReportListPage([qaReportSummary({ outcome: "approved" as never })]),
      ),
    );
    const result = await fetchWorkItemQaReports(WORK_ITEM_ID);
    expect(result.kind).toBe("malformed");
  });
});

describe("decision reads", () => {
  it("parses decisions with reviewer names and hash-bound status", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(
        200,
        decisionListPage(
          [decisionView()],
          approvalStatus({
            approved: true,
            current: true,
            decision_id: decisionView().id,
            approved_content_hash: DECISION_CONTENT_HASH,
            active_content_hash: DECISION_CONTENT_HASH,
          }),
        ),
      ),
    );
    const result = await fetchWorkItemDecisions(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.decisions[0]?.reviewer.display_name).toBe(
        "Smoke Reviewer",
      );
      expect(result.data.approval_status.current).toBe(true);
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/decisions`,
    );
  });

  it("rejects an unknown decision kind as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        decisionListPage([decisionView({ decision: "published" as never })]),
      ),
    );
    const result = await fetchWorkItemDecisions(WORK_ITEM_ID);
    expect(result.kind).toBe("malformed");
  });

  it("maps 404s to not_found and bad ids never hit the network", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(404, {}));
    expect((await fetchWorkItemDecisions(WORK_ITEM_ID)).kind).toBe("not_found");
    expect((await fetchWorkItemDecisions("junk")).kind).toBe("not_found");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("media coverage reads", () => {
  it("parses coverage with honest unsatisfied needs", async () => {
    const { fetchWorkItemMedia } = await import("@/lib/editorial-api");
    const { mediaCoveragePage } = await import("./editorial-fixtures");
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, mediaCoveragePage()),
    );
    const result = await fetchWorkItemMedia(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.total_needs).toBe(1);
      expect(result.data.satisfied_needs).toBe(0);
      expect(result.data.needs[0]?.satisfaction).toBeNull();
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/media`,
    );
  });

  it("rejects an unknown origin as malformed and bad ids stay local", async () => {
    const { fetchWorkItemMedia } = await import("@/lib/editorial-api");
    const { mediaCoveragePage, mediaSatisfaction } =
      await import("./editorial-fixtures");
    stubFetch(async () =>
      jsonResponse(
        200,
        mediaCoveragePage({
          needs: [
            {
              need_index: 0,
              role: "kapak",
              purpose: "tema",
              constraints: null,
              satisfaction: mediaSatisfaction({
                asset: {
                  ...mediaSatisfaction().asset,
                  origin: "scraped" as never,
                },
              }),
            },
          ],
        }),
      ),
    );
    expect((await fetchWorkItemMedia(WORK_ITEM_ID)).kind).toBe("malformed");
    const fetchMock = stubFetch(async () => jsonResponse(200, {}));
    expect((await fetchWorkItemMedia("junk")).kind).toBe("not_found");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
