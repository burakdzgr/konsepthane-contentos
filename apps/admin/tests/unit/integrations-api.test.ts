// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchIntegrations, testIntegration } from "@/lib/integrations-api";

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

const PROVIDER = {
  name: "semrush",
  display_name: "Semrush",
  purpose: "Dış SEO pazar istihbaratı.",
  configured: true,
  verified: true,
  state: "healthy",
  detail: "Bağlı.",
  checked_at: "2026-09-05T10:00:00+00:00",
  last_success_at: "2026-09-05T10:00:00+00:00",
  last_error_class: null,
  freshness: null,
  daily_budget: 200,
  requests_today: 1,
  cache_hours: 72,
  required_env: ["CONTENTOS_SEMRUSH_API_KEY"],
  optional_env: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchIntegrations", () => {
  it("reads the board from the internal API", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [PROVIDER],
      }),
    );

    const result = await fetchIntegrations();

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.providers[0]?.state).toBe("healthy");
    }
    const [url] = fetchMock.mock.calls[0] as [URL];
    expect(String(url)).toBe("http://127.0.0.1:8000/internal/integrations");
  });

  it("rejects an unknown state instead of inventing one", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        generated_at: "2026-09-05T10:00:00+00:00",
        providers: [{ ...PROVIDER, state: "mystery" }],
      }),
    );

    expect(await fetchIntegrations()).toEqual({ kind: "malformed" });
  });

  it("reports an unreachable backend", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED http://internal");
    });

    expect(await fetchIntegrations()).toEqual({ kind: "unreachable" });
  });
});

describe("testIntegration", () => {
  it("POSTs to the provider test endpoint and parses the status", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, PROVIDER));

    const result = await testIntegration("semrush");

    expect(result).toEqual({ kind: "ok", data: PROVIDER });
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toBe(
      "http://127.0.0.1:8000/internal/integrations/semrush/test",
    );
    expect(init.method).toBe("POST");
  });

  it("maps 404 to not-found", async () => {
    stubFetch(async () => jsonResponse(404, { detail: "unknown" }));

    expect(await testIntegration("pinterest_trends")).toEqual({
      kind: "not-found",
    });
  });
});
