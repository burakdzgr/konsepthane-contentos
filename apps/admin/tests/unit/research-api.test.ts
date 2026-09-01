// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchPipelineDetail,
  fetchPipelineItems,
  fetchResearchSources,
  isUuid,
} from "@/lib/research-api";

const ITEM_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

function sourceRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-2222-4333-8444-555555555555",
    slug: "ornek-kaynak",
    name: "Örnek Kaynak",
    kind: "manual",
    locale: "tr-TR",
    market: "TR",
    lifecycle_state: "active",
    trust_tier: "general",
    discovery_strategy: "manual",
    base_url: "https://ornek.example.test",
    created_at: "2026-09-01T12:00:00+00:00",
    updated_at: "2026-09-01T12:00:00+00:00",
    total_discovery_items: 3,
    discovered_count: 1,
    accepted_count: 1,
    fetched_count: 1,
    fetch_failed_count: 0,
    rejected_count: 0,
    ...overrides,
  };
}

function pipelineRow(overrides: Record<string, unknown> = {}) {
  return {
    id: ITEM_ID,
    source_id: "11111111-2222-4333-8444-555555555555",
    source_slug: "ornek-kaynak",
    source_name: "Örnek Kaynak",
    canonical_url: "https://ornek.example.test/haber",
    discovery_method: "manual",
    lifecycle_state: "fetched",
    rejection_reason: null,
    discovered_at: "2026-09-01T12:00:00+00:00",
    last_seen_at: "2026-09-01T12:30:00+00:00",
    external_published_at: null,
    fetch_snapshot_id: "21111111-2222-4333-8444-555555555555",
    fetch_outcome: "success",
    fetched_at: "2026-09-01T12:05:00+00:00",
    status_code: 200,
    retry_classification: "not_applicable",
    normalized_document_id: "31111111-2222-4333-8444-555555555555",
    normalization_status: "succeeded",
    normalization_failure_code: null,
    normalized_at: "2026-09-01T12:06:00+00:00",
    duplicate_decision_id: "41111111-2222-4333-8444-555555555555",
    duplicate_outcome: "unique",
    duplicate_evaluated_at: "2026-09-01T12:07:00+00:00",
    evidence_count: 2,
    latest_evidence_at: "2026-09-01T12:08:00+00:00",
    ...overrides,
  };
}

function page(items: unknown[], total = items.length) {
  return { items, total, limit: 50, offset: 0 };
}

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

describe("fetchResearchSources", () => {
  it("parses a valid page and encodes filters as query parameters", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, page([sourceRow()])),
    );

    const result = await fetchResearchSources({
      lifecycleState: "active",
      kind: "rss_feed",
      discoveryStrategy: "feed",
      search: "gezi",
      limit: 50,
      offset: 100,
    });

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.items[0]?.slug).toBe("ornek-kaynak");
      expect(result.data.total).toBe(1);
    }
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("/internal/research/sources?");
    expect(url).toContain("lifecycle_state=active");
    expect(url).toContain("kind=rss_feed");
    expect(url).toContain("discovery_strategy=feed");
    expect(url).toContain("search=gezi");
    expect(url).toContain("limit=50");
    expect(url).toContain("offset=100");
  });

  it("omits absent filters entirely", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, page([])));

    await fetchResearchSources();

    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url.endsWith("/internal/research/sources")).toBe(true);
  });

  it("rejects an unknown enum value as malformed", async () => {
    stubFetch(async () =>
      jsonResponse(200, page([sourceRow({ lifecycle_state: "exploded" })])),
    );

    expect(await fetchResearchSources()).toEqual({ kind: "malformed" });
  });

  it("treats a network failure as unreachable", async () => {
    stubFetch(async () => {
      throw new Error("connection refused with http://secret-internal:8000");
    });

    expect(await fetchResearchSources()).toEqual({ kind: "unreachable" });
  });

  it("treats an unexpected status as malformed", async () => {
    stubFetch(async () => jsonResponse(500, { error: "boom" }));

    expect(await fetchResearchSources()).toEqual({ kind: "malformed" });
  });
});

describe("fetchPipelineItems", () => {
  it("parses a full projection row", async () => {
    stubFetch(async () => jsonResponse(200, page([pipelineRow()])));

    const result = await fetchPipelineItems();

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      const row = result.data.items[0];
      expect(row?.fetch_outcome).toBe("success");
      expect(row?.duplicate_outcome).toBe("unique");
      expect(row?.evidence_count).toBe(2);
    }
  });

  it("parses null projections for a discovery-only row", async () => {
    stubFetch(async () =>
      jsonResponse(
        200,
        page([
          pipelineRow({
            lifecycle_state: "discovered",
            fetch_snapshot_id: null,
            fetch_outcome: null,
            fetched_at: null,
            status_code: null,
            retry_classification: null,
            normalized_document_id: null,
            normalization_status: null,
            normalization_failure_code: null,
            normalized_at: null,
            duplicate_decision_id: null,
            duplicate_outcome: null,
            duplicate_evaluated_at: null,
            evidence_count: 0,
            latest_evidence_at: null,
          }),
        ]),
      ),
    );

    const result = await fetchPipelineItems();

    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.items[0]?.fetch_outcome).toBeNull();
    }
  });

  it("encodes every supported filter", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, page([])));

    await fetchPipelineItems({
      sourceId: "11111111-2222-4333-8444-555555555555",
      lifecycleState: "fetched",
      discoveryMethod: "feed",
      fetchOutcome: "timeout",
      normalizationStatus: "failed",
      duplicateOutcome: "duplicate",
      hasEvidence: false,
      urlContains: "haber",
      offset: 50,
    });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain("source_id=11111111-2222-4333-8444-555555555555");
    expect(url).toContain("lifecycle_state=fetched");
    expect(url).toContain("discovery_method=feed");
    expect(url).toContain("fetch_outcome=timeout");
    expect(url).toContain("normalization_status=failed");
    expect(url).toContain("duplicate_outcome=duplicate");
    expect(url).toContain("has_evidence=false");
    expect(url).toContain("url_contains=haber");
    expect(url).toContain("offset=50");
  });

  it("rejects a missing pagination field as malformed", async () => {
    stubFetch(async () => jsonResponse(200, { items: [], total: 0 }));

    expect(await fetchPipelineItems()).toEqual({ kind: "malformed" });
  });
});

describe("fetchPipelineDetail", () => {
  it("returns not_found for a non-UUID id without calling the backend", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, {}));

    expect(await fetchPipelineDetail("../../etc/passwd")).toEqual({
      kind: "not_found",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns not_found for a backend 404", async () => {
    stubFetch(async () => jsonResponse(404, { error: { code: "not_found" } }));

    expect(await fetchPipelineDetail(ITEM_ID)).toEqual({ kind: "not_found" });
  });

  it("treats a detail body missing sections as malformed", async () => {
    stubFetch(async () => jsonResponse(200, { discovery_item: {} }));

    expect(await fetchPipelineDetail(ITEM_ID)).toEqual({ kind: "malformed" });
  });
});

describe("isUuid", () => {
  it("accepts canonical UUIDs and rejects junk", () => {
    expect(isUuid(ITEM_ID)).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("")).toBe(false);
  });
});
