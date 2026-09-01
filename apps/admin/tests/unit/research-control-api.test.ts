// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptDiscoveryItem,
  registerSource,
  requeueDiscoveryItem,
  rejectDiscoveryItem,
  runSourceDiscovery,
  startDiscoveryItemFetch,
  transitionSourceLifecycle,
} from "@/lib/research-control-api";

const SOURCE_ID = "11111111-2222-4333-8444-555555555555";
const ITEM_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

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

describe("registerSource", () => {
  it("POSTs a JSON body and parses the registration response", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "registered",
        source_id: SOURCE_ID,
        lifecycle_state: "active",
      }),
    );

    const result = await registerSource({
      slug: "ornek",
      name: "Örnek",
      kind: "rss_feed",
      baseUrl: "https://ornek.example.test/feed",
      trustTier: "general",
      termsNotes: "kullanım şartları incelendi",
    });

    expect(result).toEqual({
      kind: "ok",
      data: {
        status: "registered",
        source_id: SOURCE_ID,
        lifecycle_state: "active",
      },
    });
    const [url, init] = fetchMock.mock.calls[0] as [
      URL,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(String(url)).toBe("http://127.0.0.1:8000/internal/research/sources");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      slug: "ornek",
      name: "Örnek",
      kind: "rss_feed",
      base_url: "https://ornek.example.test/feed",
      trust_tier: "general",
      terms_notes: "kullanım şartları incelendi",
    });
  });

  it("maps backend statuses to bounded result kinds", async () => {
    const input = {
      slug: "x",
      name: "X",
      kind: "manual",
      baseUrl: "https://x.example.test/",
      trustTier: "general",
    } as const;

    stubFetch(async () => jsonResponse(409, { error: { code: "conflict" } }));
    expect(await registerSource(input)).toEqual({ kind: "conflict" });

    stubFetch(async () =>
      jsonResponse(422, { error: { code: "validation_error" } }),
    );
    expect(await registerSource(input)).toEqual({ kind: "invalid" });

    stubFetch(async () =>
      jsonResponse(500, { error: { code: "internal_error" } }),
    );
    expect(await registerSource(input)).toEqual({ kind: "malformed" });

    stubFetch(async () => jsonResponse(200, { status: "unexpected" }));
    expect(await registerSource(input)).toEqual({ kind: "malformed" });

    stubFetch(async () => {
      throw new Error("boom http://secret-internal:8000");
    });
    expect(await registerSource(input)).toEqual({ kind: "unreachable" });
  });
});

describe("lifecycle and admission clients", () => {
  it("posts a lifecycle transition and parses the response", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        source_id: SOURCE_ID,
        lifecycle_state: "paused",
      }),
    );

    const result = await transitionSourceLifecycle(
      SOURCE_ID,
      "paused",
      "bakım",
    );

    expect(result.kind).toBe("ok");
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toContain(
      `/internal/research/sources/${SOURCE_ID}/lifecycle`,
    );
    expect(JSON.parse(String(init.body))).toEqual({
      new_state: "paused",
      reason: "bakım",
    });
  });

  it("refuses junk UUIDs without calling the backend", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, {}));

    expect(await transitionSourceLifecycle("../etc", "paused", "x")).toEqual({
      kind: "not_found",
    });
    expect(await acceptDiscoveryItem("junk")).toEqual({ kind: "not_found" });
    expect(await startDiscoveryItemFetch("junk")).toEqual({
      kind: "not_found",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("posts accept/reject/requeue and parses item mutations", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        discovery_item_id: ITEM_ID,
        lifecycle_state: "accepted",
      }),
    );
    expect((await acceptDiscoveryItem(ITEM_ID)).kind).toBe("ok");

    const rejectFetch = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        discovery_item_id: ITEM_ID,
        lifecycle_state: "rejected",
      }),
    );
    expect(
      (await rejectDiscoveryItem(ITEM_ID, "out_of_scope", "not relevant")).kind,
    ).toBe("ok");
    const [, rejectInit] = rejectFetch.mock.calls[0] as [URL, RequestInit];
    expect(JSON.parse(String(rejectInit.body))).toEqual({
      reason: "out_of_scope",
      note: "not relevant",
    });

    stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        discovery_item_id: ITEM_ID,
        lifecycle_state: "accepted",
      }),
    );
    expect((await requeueDiscoveryItem(ITEM_ID, "kaynak düzeldi")).kind).toBe(
      "ok",
    );
  });
});

describe("task triggers", () => {
  it("parses a queued discovery response", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "discover_source",
        entity_id: SOURCE_ID,
      }),
    );
    expect(await runSourceDiscovery(SOURCE_ID)).toEqual({
      kind: "ok",
      data: { status: "queued", task: "discover_source", entity_id: SOURCE_ID },
    });
  });

  it("maps a queue failure to a bounded result", async () => {
    stubFetch(async () => jsonResponse(503, { error: { code: "http_error" } }));
    expect(await startDiscoveryItemFetch(ITEM_ID)).toEqual({
      kind: "queue_failed",
    });
  });

  it("maps a missing entity to not_found", async () => {
    stubFetch(async () => jsonResponse(404, { error: { code: "not_found" } }));
    expect(await runSourceDiscovery(SOURCE_ID)).toEqual({ kind: "not_found" });
  });
});
