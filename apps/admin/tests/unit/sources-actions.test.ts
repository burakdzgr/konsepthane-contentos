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
    updateSourcePurpose: vi.fn(),
  };
});

import {
  registerSourceAction,
  runSourceDiscoveryAction,
  transitionSourceLifecycleAction,
  updateSourcePurposeAction,
} from "@/app/sources/actions";
import {
  registerSource,
  runSourceDiscovery,
  transitionSourceLifecycle,
  updateSourcePurpose,
} from "@/lib/research-control-api";

const SOURCE_ID = "11111111-2222-4333-8444-555555555555";

const registerMock = vi.mocked(registerSource);
const transitionMock = vi.mocked(transitionSourceLifecycle);
const discoveryMock = vi.mocked(runSourceDiscovery);
const purposeMock = vi.mocked(updateSourcePurpose);

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

  it("passes the chosen role and checked capabilities, deduplicated", async () => {
    registerMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "registered",
        source_id: SOURCE_ID,
        lifecycle_state: "active",
      },
    });
    const data = form({
      slug: "forum",
      name: "Forum",
      kind: "manual",
      base_url: "https://forum.example.test/",
      trust_tier: "general",
      primary_role: "community_intent",
    });
    data.append("capabilities", "community_need");
    data.append("capabilities", "market");
    data.append("capabilities", "community_need");
    data.append("capabilities", "telepathy");

    await expectRedirect(
      registerSourceAction(data),
      "/sources?notice=source-registered",
    );
    expect(registerMock).toHaveBeenCalledWith(
      expect.objectContaining({
        primaryRole: "community_intent",
        capabilities: ["community_need", "market"],
      }),
    );
  });

  it("rejects an unknown role before calling the backend", async () => {
    await expectRedirect(
      registerSourceAction(
        form({
          slug: "ornek",
          name: "Örnek",
          kind: "manual",
          base_url: "https://x.example.test/",
          trust_tier: "general",
          primary_role: "oracle",
        }),
      ),
      "/sources/new?error=invalid",
    );
    expect(registerMock).not.toHaveBeenCalled();
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

describe("updateSourcePurposeAction", () => {
  it("updates the purpose and redirects with a notice", async () => {
    purposeMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "updated",
        source_id: SOURCE_ID,
        primary_role: "trend",
        capabilities: ["trend", "visual_trend"],
      },
    });
    const data = form({ source_id: SOURCE_ID, primary_role: "trend" });
    data.append("capabilities", "visual_trend");
    data.append("capabilities", "trend");

    await expectRedirect(
      updateSourcePurposeAction(data),
      "/sources?notice=purpose-updated",
    );
    expect(purposeMock).toHaveBeenCalledWith(SOURCE_ID, "trend", [
      "visual_trend",
      "trend",
    ]);
  });

  it("sends no capabilities when none are checked", async () => {
    purposeMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "updated",
        source_id: SOURCE_ID,
        primary_role: "search",
        capabilities: ["search"],
      },
    });

    await expectRedirect(
      updateSourcePurposeAction(
        form({ source_id: SOURCE_ID, primary_role: "search" }),
      ),
      "/sources?notice=purpose-updated",
    );
    expect(purposeMock).toHaveBeenCalledWith(SOURCE_ID, "search", undefined);
  });

  it("refuses an invalid id or role without calling the backend", async () => {
    await expectRedirect(
      updateSourcePurposeAction(
        form({ source_id: "junk", primary_role: "search" }),
      ),
      "/sources?error=invalid",
    );
    await expectRedirect(
      updateSourcePurposeAction(
        form({ source_id: SOURCE_ID, primary_role: "oracle" }),
      ),
      "/sources?error=invalid",
    );
    expect(purposeMock).not.toHaveBeenCalled();
  });

  it("maps backend failures to bounded error redirects", async () => {
    purposeMock.mockResolvedValue({ kind: "not_found" });
    await expectRedirect(
      updateSourcePurposeAction(
        form({ source_id: SOURCE_ID, primary_role: "search" }),
      ),
      "/sources?error=not-found",
    );
    purposeMock.mockResolvedValue({ kind: "invalid" });
    await expectRedirect(
      updateSourcePurposeAction(
        form({ source_id: SOURCE_ID, primary_role: "search" }),
      ),
      "/sources?error=invalid",
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
