// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/contentos-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/contentos-api")>(
    "@/lib/contentos-api",
  );
  return { ...actual, requestBackend: vi.fn() };
});

import { requestBackend } from "@/lib/contentos-api";
import {
  assessmentTone,
  boundedWindow,
  decideRefresh,
  decideSuggestion,
  fetchContentPerformance,
  fetchPerformanceOverview,
  fetchRefreshOpportunities,
  metricNumber,
  numberOrUnknown,
  pctOrUnknown,
  positionOrUnknown,
  ratioOrUnknown,
  triggerPerformanceSync,
} from "@/lib/performance-api";

const requestMock = vi.mocked(requestBackend);

function response(status: number, body: unknown) {
  return {
    status,
    headers: { get: () => "req-1" },
    json: async () => body,
  };
}

function overviewBody() {
  return {
    generated_at: "2026-09-05T06:00:00+00:00",
    window_days: 28,
    totals: {
      published: 0,
      rising: 0,
      stable: 0,
      declining: 0,
      volatile: 0,
      new: 0,
      insufficient: 0,
      unknown: 0,
    },
    rising: [],
    declining: [],
    stable: [],
    volatile: [],
    new: [],
    insufficient: [],
    clusters: [],
    freshness: [
      {
        provider: "google_search_console",
        last_observed_at: null,
        state: null,
      },
    ],
    pending_refresh_decisions: 0,
    pending_strategy_suggestions: 0,
    schedule_enabled: true,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("performance-api reads", () => {
  it("fetches the overview for a bounded window", async () => {
    requestMock.mockResolvedValue(response(200, overviewBody()));
    const result = await fetchPerformanceOverview(boundedWindow("7"));
    expect(requestMock).toHaveBeenCalledWith(
      "/internal/performance/overview?window=7",
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.freshness[0]?.last_observed_at).toBeNull();
    }
  });

  it("treats malformed and unreachable overviews honestly", async () => {
    requestMock.mockResolvedValue(response(200, { totals: "nope" }));
    expect((await fetchPerformanceOverview(28)).kind).toBe("malformed");
    requestMock.mockResolvedValue(null);
    expect((await fetchPerformanceOverview(28)).kind).toBe("unreachable");
  });

  it("maps a missing content detail to not_found", async () => {
    requestMock.mockResolvedValue(response(404, { detail: "no" }));
    expect(
      (await fetchContentPerformance("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"))
        .kind,
    ).toBe("not_found");
  });

  it("lists refresh opportunities with a status filter", async () => {
    requestMock.mockResolvedValue(response(200, []));
    const result = await fetchRefreshOpportunities("proposed");
    expect(requestMock).toHaveBeenCalledWith(
      "/internal/performance/refresh-opportunities?status=proposed",
    );
    expect(result.kind).toBe("ok");
    await fetchRefreshOpportunities(null);
    expect(requestMock).toHaveBeenLastCalledWith(
      "/internal/performance/refresh-opportunities",
    );
  });
});

describe("performance-api decisions", () => {
  it("posts the reason and maps statuses", async () => {
    requestMock.mockResolvedValue(response(200, {}));
    expect(
      await decideRefresh(
        "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
        "approve",
        "x",
      ),
    ).toEqual({ kind: "ok" });
    expect(requestMock).toHaveBeenCalledWith(
      "/internal/performance/refresh-opportunities/6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0/approve",
      { method: "POST", jsonBody: { reason: "x" } },
    );
    for (const [status, kind] of [
      [404, "not_found"],
      [409, "conflict"],
      [422, "invalid"],
      [500, "malformed"],
    ] as const) {
      requestMock.mockResolvedValue(response(status, {}));
      expect(
        (
          await decideSuggestion(
            "8f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            "ignore",
            "x",
          )
        ).kind,
      ).toBe(kind);
    }
    requestMock.mockResolvedValue(null);
    expect(
      (
        await decideSuggestion(
          "8f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          "accept",
          "x",
        )
      ).kind,
    ).toBe("unreachable");
  });

  it("triggers the sync and maps a queue failure", async () => {
    requestMock.mockResolvedValue(
      response(200, {
        status: "queued",
        backfilled_published: 2,
        tasks: ["contentos.performance.sync_all"],
      }),
    );
    const ok = await triggerPerformanceSync();
    expect(ok.kind).toBe("ok");
    if (ok.kind === "ok") {
      expect(ok.data.backfilled_published).toBe(2);
    }
    requestMock.mockResolvedValue(response(503, { detail: "queue" }));
    expect((await triggerPerformanceSync()).kind).toBe("queue_failed");
  });
});

describe("display helpers", () => {
  it("never renders absent values as zero", () => {
    expect(numberOrUnknown(null)).toBe("Bilinmiyor");
    expect(numberOrUnknown(1234)).toBe("1.234");
    expect(positionOrUnknown(undefined)).toBe("Bilinmiyor");
    expect(positionOrUnknown(5.55)).toBe("5.5");
    expect(pctOrUnknown(null)).toBe("Bilinmiyor");
    expect(pctOrUnknown(-0.34)).toBe("%-34");
    expect(pctOrUnknown(0.5)).toBe("+%50");
    expect(ratioOrUnknown(0.125)).toBe("%12.5");
    expect(metricNumber({ impressions: 3, ctr: "x" }, "impressions")).toBe(3);
    expect(metricNumber({ impressions: 3, ctr: "x" }, "ctr")).toBeNull();
  });

  it("maps statuses to the existing badge tones", () => {
    expect(assessmentTone("rising")).toBe("ok");
    expect(assessmentTone("declining")).toBe("bad");
    expect(assessmentTone("volatile")).toBe("warn");
    expect(assessmentTone("unknown")).toBe("info");
    expect(assessmentTone(undefined)).toBe("info");
    expect(boundedWindow("90")).toBe(90);
    expect(boundedWindow("x")).toBe(28);
  });
});
