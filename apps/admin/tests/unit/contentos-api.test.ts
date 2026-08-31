// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchBackendLiveness,
  fetchBackendReadiness,
} from "@/lib/contentos-api";

const INTERNAL_HOST = "127.0.0.1";

function jsonResponse(
  status: number,
  body: unknown,
  requestId: string | null = "backend-req-1",
) {
  return {
    status,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "x-request-id" ? requestId : null,
    },
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

describe("fetchBackendLiveness", () => {
  it("parses a valid liveness response and preserves the request id", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "ok",
        service: "Konsepthane ContentOS",
        version: "0.1.0",
      }),
    );

    const result = await fetchBackendLiveness();

    expect(result).toEqual({
      kind: "ok",
      data: {
        status: "ok",
        service: "Konsepthane ContentOS",
        version: "0.1.0",
      },
      requestId: "backend-req-1",
    });

    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [url, init] = call as [
      URL,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(String(url)).toBe("http://127.0.0.1:8000/health/live");
    expect(init.cache).toBe("no-store");
    expect(init.headers["X-Request-ID"]).toMatch(/^admin-[0-9a-f-]+$/);
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("treats an unexpected liveness status code as malformed", async () => {
    stubFetch(async () => jsonResponse(503, { anything: true }));

    expect(await fetchBackendLiveness()).toEqual({ kind: "malformed" });
  });
});

describe("fetchBackendReadiness", () => {
  it("parses a ready response", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        status: "ready",
        checks: { postgres: "ok", pgvector: "ok", redis: "ok" },
      }),
    );

    const result = await fetchBackendReadiness();

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.status).toBe("ready");
      expect(result.data.checks.redis).toBe("ok");
    }
  });

  it("parses a not_ready 503 response", async () => {
    stubFetch(async () =>
      jsonResponse(503, {
        status: "not_ready",
        checks: { postgres: "failed", pgvector: "unknown", redis: "ok" },
      }),
    );

    const result = await fetchBackendReadiness();

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.status).toBe("not_ready");
      expect(result.data.checks.postgres).toBe("failed");
      expect(result.data.checks.pgvector).toBe("unknown");
    }
  });

  it("rejects malformed readiness payloads safely", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        status: "ready",
        checks: { postgres: "great", pgvector: "ok", redis: "ok" },
      }),
    );

    expect(await fetchBackendReadiness()).toEqual({ kind: "malformed" });
  });

  it("rejects non-JSON bodies safely", async () => {
    stubFetch(async () => ({
      status: 200,
      headers: { get: () => null },
      json: async () => {
        throw new SyntaxError("Unexpected token < in JSON");
      },
    }));

    expect(await fetchBackendReadiness()).toEqual({ kind: "malformed" });
  });
});

describe("failure isolation", () => {
  it("turns network failures into a bare unreachable result", async () => {
    stubFetch(async () => {
      throw new Error(`connect ECONNREFUSED ${INTERNAL_HOST}:8000`);
    });

    const liveness = await fetchBackendLiveness();
    const readiness = await fetchBackendReadiness();

    expect(liveness).toEqual({ kind: "unreachable" });
    expect(readiness).toEqual({ kind: "unreachable" });
    const serialized = JSON.stringify({ liveness, readiness });
    expect(serialized).not.toContain(INTERNAL_HOST);
    expect(serialized).not.toContain("8000");
    expect(serialized).not.toContain("ECONNREFUSED");
    expect(serialized).not.toContain("http");
  });

  it("turns timeouts into a bare unreachable result", async () => {
    stubFetch(async () => {
      throw new DOMException("The operation was aborted.", "TimeoutError");
    });

    expect(await fetchBackendLiveness()).toEqual({ kind: "unreachable" });
  });
});
