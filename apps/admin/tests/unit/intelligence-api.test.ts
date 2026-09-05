import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/contentos-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/contentos-api")>(
    "@/lib/contentos-api",
  );
  return { ...actual, requestBackend: vi.fn() };
});

import { requestBackend } from "@/lib/contentos-api";
import {
  familySummary,
  fetchIntelligenceSummary,
  SIGNAL_FAMILIES,
} from "@/lib/intelligence-api";

const requestMock = vi.mocked(requestBackend);

const RUN_ID = "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

function response(status: number, payload: unknown) {
  return {
    status,
    headers: { get: () => null },
    json: async () => payload,
  };
}

function summaryPayload() {
  return {
    families: SIGNAL_FAMILIES.map((family) => ({
      family,
      signal_count: family === "community_need" ? 3 : 0,
      occurrence_total: family === "community_need" ? 7 : 0,
      distinct_sources: family === "community_need" ? 2 : 0,
      last_observed_at:
        family === "community_need" ? "2026-09-05T01:00:00+00:00" : null,
    })),
    total_signals: 3,
    run_id: RUN_ID,
    run_document_count: 4,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("intelligence summary client", () => {
  it("reads the run-scoped summary and exposes per-family tallies", async () => {
    requestMock.mockResolvedValue(response(200, summaryPayload()));

    const result = await fetchIntelligenceSummary(RUN_ID);

    expect(requestMock).toHaveBeenCalledWith(
      `/internal/intelligence/summary?run_id=${RUN_ID}`,
    );
    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;
    expect(result.data.run_document_count).toBe(4);
    expect(familySummary(result.data, "community_need")?.signal_count).toBe(3);
    expect(familySummary(result.data, "search")?.signal_count).toBe(0);
    expect(familySummary(null, "search")).toBeNull();
  });

  it("reads the unbounded summary without a query", async () => {
    requestMock.mockResolvedValue(
      response(200, {
        ...summaryPayload(),
        run_id: null,
        run_document_count: null,
      }),
    );
    const result = await fetchIntelligenceSummary();
    expect(requestMock).toHaveBeenCalledWith("/internal/intelligence/summary");
    expect(result.kind).toBe("ok");
  });

  it("maps 404, malformed payloads and transport failures honestly", async () => {
    requestMock.mockResolvedValue(response(404, { detail: "not found" }));
    expect((await fetchIntelligenceSummary(RUN_ID)).kind).toBe("not_found");

    requestMock.mockResolvedValue(
      response(200, { families: [{ family: "weather" }], total_signals: 0 }),
    );
    expect((await fetchIntelligenceSummary(RUN_ID)).kind).toBe("malformed");

    requestMock.mockResolvedValue(null);
    expect((await fetchIntelligenceSummary(RUN_ID)).kind).toBe("unreachable");
  });
});
