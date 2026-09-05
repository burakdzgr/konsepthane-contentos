import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/performance-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/performance-api")>(
    "@/lib/performance-api",
  );
  return {
    ...actual,
    decideRefresh: vi.fn(),
    decideSuggestion: vi.fn(),
    triggerPerformanceSync: vi.fn(),
  };
});

import {
  decideRefreshAction,
  decideSuggestionAction,
  syncPerformanceAction,
} from "@/app/performans/actions";
import {
  decideRefresh,
  decideSuggestion,
  triggerPerformanceSync,
} from "@/lib/performance-api";

const refreshMock = vi.mocked(decideRefresh);
const suggestionMock = vi.mocked(decideSuggestion);
const syncMock = vi.mocked(triggerPerformanceSync);

const REFRESH_ID = "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";
const SUGGESTION_ID = "8f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function redirectTarget(promise: Promise<void>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    const message = (error as Error).message;
    if (message.startsWith("REDIRECT:")) {
      return message.slice("REDIRECT:".length);
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("refresh decisions", () => {
  it("approves with a reason and lands on the refresh section", async () => {
    refreshMock.mockResolvedValue({ kind: "ok" });
    const target = await redirectTarget(
      decideRefreshAction(
        formData({
          refresh_id: REFRESH_ID,
          action: "approve",
          reason: "sorgular kaybedildi",
        }),
      ),
    );
    expect(refreshMock).toHaveBeenCalledWith(
      REFRESH_ID,
      "approve",
      "sorgular kaybedildi",
    );
    expect(target).toBe("/performans?notice=refresh-approved#guncelleme");
  });

  it("dismisses back to the detail page when return_to is given", async () => {
    refreshMock.mockResolvedValue({ kind: "ok" });
    const target = await redirectTarget(
      decideRefreshAction(
        formData({
          refresh_id: REFRESH_ID,
          action: "dismiss",
          reason: "mevsimsel",
          return_to: "/performans/abc",
        }),
      ),
    );
    expect(target).toBe("/performans/abc?notice=refresh-dismissed#guncelleme");
  });

  it("refuses a missing reason or an unknown action without calling the API", async () => {
    expect(
      await redirectTarget(
        decideRefreshAction(
          formData({ refresh_id: REFRESH_ID, action: "approve", reason: " " }),
        ),
      ),
    ).toBe("/performans?error=invalid#guncelleme");
    expect(
      await redirectTarget(
        decideRefreshAction(
          formData({ refresh_id: REFRESH_ID, action: "publish", reason: "x" }),
        ),
      ),
    ).toBe("/performans?error=invalid#guncelleme");
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("maps backend outcomes to bounded error codes", async () => {
    for (const [kind, code] of [
      ["conflict", "conflict"],
      ["not_found", "not-found"],
      ["invalid", "invalid"],
      ["unreachable", "unreachable"],
      ["malformed", "malformed"],
    ] as const) {
      refreshMock.mockResolvedValue({ kind });
      expect(
        await redirectTarget(
          decideRefreshAction(
            formData({
              refresh_id: REFRESH_ID,
              action: "approve",
              reason: "x",
            }),
          ),
        ),
      ).toBe(`/performans?error=${code}#guncelleme`);
    }
  });

  it("ignores a return_to outside the performance pages", async () => {
    refreshMock.mockResolvedValue({ kind: "ok" });
    const target = await redirectTarget(
      decideRefreshAction(
        formData({
          refresh_id: REFRESH_ID,
          action: "approve",
          reason: "x",
          return_to: "https://evil.example/phish",
        }),
      ),
    );
    expect(target).toBe("/performans?notice=refresh-approved#guncelleme");
  });
});

describe("strategy suggestion decisions", () => {
  it("accepts and ignores with a reason", async () => {
    suggestionMock.mockResolvedValue({ kind: "ok" });
    expect(
      await redirectTarget(
        decideSuggestionAction(
          formData({
            suggestion_id: SUGGESTION_ID,
            action: "accept",
            reason: "odak artsın",
          }),
        ),
      ),
    ).toBe("/performans?notice=suggestion-accepted#strateji");
    expect(suggestionMock).toHaveBeenCalledWith(
      SUGGESTION_ID,
      "accept",
      "odak artsın",
    );
    expect(
      await redirectTarget(
        decideSuggestionAction(
          formData({
            suggestion_id: SUGGESTION_ID,
            action: "ignore",
            reason: "şimdilik",
          }),
        ),
      ),
    ).toBe("/performans?notice=suggestion-ignored#strateji");
  });

  it("refuses an unknown action", async () => {
    expect(
      await redirectTarget(
        decideSuggestionAction(
          formData({
            suggestion_id: SUGGESTION_ID,
            action: "delete",
            reason: "x",
          }),
        ),
      ),
    ).toBe("/performans?error=invalid#strateji");
    expect(suggestionMock).not.toHaveBeenCalled();
  });
});

describe("sync now", () => {
  it("queues the sync and reports it", async () => {
    syncMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        backfilled_published: 1,
        tasks: ["contentos.performance.sync_all"],
      },
    });
    expect(await redirectTarget(syncPerformanceAction(formData({})))).toBe(
      "/performans?notice=sync-queued",
    );
  });

  it("maps queue failures", async () => {
    syncMock.mockResolvedValue({ kind: "queue_failed" });
    expect(await redirectTarget(syncPerformanceAction(formData({})))).toBe(
      "/performans?error=queue-failed",
    );
    syncMock.mockResolvedValue({ kind: "unreachable" });
    expect(await redirectTarget(syncPerformanceAction(formData({})))).toBe(
      "/performans?error=unreachable",
    );
  });
});
