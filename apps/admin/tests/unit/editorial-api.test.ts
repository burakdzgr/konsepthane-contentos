// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchDraftDetail,
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkItemDrafts,
  fetchWorkQueue,
} from "@/lib/editorial-api";
import {
  WORK_ITEM_ID,
  OPPORTUNITY_ID,
  DRAFT_ID,
  draftDetail,
  draftListPage,
  draftSummary,
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
