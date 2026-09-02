// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkQueue,
} from "@/lib/editorial-api";
import {
  WORK_ITEM_ID,
  OPPORTUNITY_ID,
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
