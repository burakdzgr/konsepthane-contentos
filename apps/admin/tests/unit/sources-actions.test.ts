// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/research-control-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/research-control-api")
  >("@/lib/research-control-api");
  return {
    ...actual,
    registerSource: vi.fn(),
    transitionSourceLifecycle: vi.fn(),
    runSourceDiscovery: vi.fn(),
  };
});

import {
  registerSourceAction,
  runSourceDiscoveryAction,
  transitionSourceLifecycleAction,
} from "@/app/sources/actions";
import {
  registerSource,
  runSourceDiscovery,
  transitionSourceLifecycle,
} from "@/lib/research-control-api";

const SOURCE_ID = "11111111-2222-4333-8444-555555555555";

const registerMock = vi.mocked(registerSource);
const transitionMock = vi.mocked(transitionSourceLifecycle);
const discoveryMock = vi.mocked(runSourceDiscovery);

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function expectRedirect(
  promise: Promise<void>,
  url: string,
): Promise<void> {
  await expect(promise).rejects.toThrow(`REDIRECT:${url}`);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("registerSourceAction", () => {
  it("registers and redirects with a success notice", async () => {
    registerMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "registered",
        source_id: SOURCE_ID,
        lifecycle_state: "active",
      },
    });

    await expectRedirect(
      registerSourceAction(
        form({
          slug: "ornek",
          name: "Örnek Kaynak",
          kind: "rss_feed",
          base_url: "https://ornek.example.test/feed",
          trust_tier: "general",
          locale: "tr-TR",
          market: "TR",
          terms_notes: "şartlar okundu",
        }),
      ),
      "/sources?notice=source-registered",
    );
    expect(registerMock).toHaveBeenCalledWith({
      slug: "ornek",
      name: "Örnek Kaynak",
      kind: "rss_feed",
      baseUrl: "https://ornek.example.test/feed",
      trustTier: "general",
      locale: "tr-TR",
      market: "TR",
      termsNotes: "şartlar okundu",
    });
  });

  it("reports an idempotent registration as existing", async () => {
    registerMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "existing",
        source_id: SOURCE_ID,
        lifecycle_state: "active",
      },
    });

    await expectRedirect(
      registerSourceAction(
        form({
          slug: "ornek",
          name: "Örnek Kaynak",
          kind: "manual",
          base_url: "https://ornek.example.test/",
          trust_tier: "general",
        }),
      ),
      "/sources?notice=source-existing",
    );
  });

  it("rejects an unregistrable kind before calling the backend", async () => {
    await expectRedirect(
      registerSourceAction(
        form({
          slug: "ornek",
          name: "Örnek",
          kind: "trend_provider",
          base_url: "https://x.example.test/",
          trust_tier: "general",
        }),
      ),
      "/sources/new?error=invalid",
    );
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("maps a backend conflict to a bounded error redirect", async () => {
    registerMock.mockResolvedValue({ kind: "conflict" });

    await expectRedirect(
      registerSourceAction(
        form({
          slug: "ornek",
          name: "Örnek",
          kind: "manual",
          base_url: "https://x.example.test/",
          trust_tier: "general",
        }),
      ),
      "/sources/new?error=conflict",
    );
  });
});

describe("transitionSourceLifecycleAction", () => {
  it("applies a transition and redirects with a notice", async () => {
    transitionMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "updated",
        source_id: SOURCE_ID,
        lifecycle_state: "paused",
      },
    });

    await expectRedirect(
      transitionSourceLifecycleAction(
        form({ source_id: SOURCE_ID, new_state: "paused", reason: "bakım" }),
      ),
      "/sources?notice=lifecycle-updated",
    );
    expect(transitionMock).toHaveBeenCalledWith(SOURCE_ID, "paused", "bakım");
  });

  it("refuses an invalid source id or state without calling the backend", async () => {
    await expectRedirect(
      transitionSourceLifecycleAction(
        form({ source_id: "junk", new_state: "paused", reason: "x" }),
      ),
      "/sources?error=invalid",
    );
    await expectRedirect(
      transitionSourceLifecycleAction(
        form({ source_id: SOURCE_ID, new_state: "exploded", reason: "x" }),
      ),
      "/sources?error=invalid",
    );
    expect(transitionMock).not.toHaveBeenCalled();
  });

  it("maps a domain conflict to a bounded error redirect", async () => {
    transitionMock.mockResolvedValue({ kind: "conflict" });

    await expectRedirect(
      transitionSourceLifecycleAction(
        form({ source_id: SOURCE_ID, new_state: "paused", reason: "x" }),
      ),
      "/sources?error=conflict",
    );
  });
});

describe("runSourceDiscoveryAction", () => {
  it("queues discovery and redirects with a notice", async () => {
    discoveryMock.mockResolvedValue({
      kind: "ok",
      data: { status: "queued", task: "discover_source", entity_id: SOURCE_ID },
    });

    await expectRedirect(
      runSourceDiscoveryAction(form({ source_id: SOURCE_ID })),
      "/sources?notice=discovery-queued",
    );
  });

  it("maps a queue failure to a bounded error redirect", async () => {
    discoveryMock.mockResolvedValue({ kind: "queue_failed" });

    await expectRedirect(
      runSourceDiscoveryAction(form({ source_id: SOURCE_ID })),
      "/sources?error=queue-failed",
    );
  });
});
