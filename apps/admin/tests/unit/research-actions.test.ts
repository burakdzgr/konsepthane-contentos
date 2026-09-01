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
    acceptDiscoveryItem: vi.fn(),
    rejectDiscoveryItem: vi.fn(),
    requeueDiscoveryItem: vi.fn(),
    startDiscoveryItemFetch: vi.fn(),
  };
});

import {
  acceptDiscoveryItemAction,
  rejectDiscoveryItemAction,
  requeueDiscoveryItemAction,
  startDiscoveryItemFetchAction,
} from "@/app/research/[id]/actions";
import {
  acceptDiscoveryItem,
  rejectDiscoveryItem,
  requeueDiscoveryItem,
  startDiscoveryItemFetch,
} from "@/lib/research-control-api";

const ITEM_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";

const acceptMock = vi.mocked(acceptDiscoveryItem);
const rejectMock = vi.mocked(rejectDiscoveryItem);
const requeueMock = vi.mocked(requeueDiscoveryItem);
const fetchTriggerMock = vi.mocked(startDiscoveryItemFetch);

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

function updated(state: string) {
  return {
    kind: "ok" as const,
    data: {
      status: "updated" as const,
      discovery_item_id: ITEM_ID,
      lifecycle_state: state as never,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("acceptDiscoveryItemAction", () => {
  it("accepts and redirects to the detail page with a notice", async () => {
    acceptMock.mockResolvedValue(updated("accepted"));

    await expectRedirect(
      acceptDiscoveryItemAction(form({ discovery_item_id: ITEM_ID })),
      `/research/${ITEM_ID}?notice=accepted`,
    );
    expect(acceptMock).toHaveBeenCalledWith(ITEM_ID);
  });

  it("maps a wrong-state conflict to a bounded error redirect", async () => {
    acceptMock.mockResolvedValue({ kind: "conflict" });

    await expectRedirect(
      acceptDiscoveryItemAction(form({ discovery_item_id: ITEM_ID })),
      `/research/${ITEM_ID}?error=conflict`,
    );
  });

  it("refuses a junk item id without calling the backend", async () => {
    await expectRedirect(
      acceptDiscoveryItemAction(form({ discovery_item_id: "junk" })),
      "/research?error=invalid",
    );
    expect(acceptMock).not.toHaveBeenCalled();
  });
});

describe("rejectDiscoveryItemAction", () => {
  it("rejects with a coded reason and optional note", async () => {
    rejectMock.mockResolvedValue(updated("rejected"));

    await expectRedirect(
      rejectDiscoveryItemAction(
        form({
          discovery_item_id: ITEM_ID,
          reason: "out_of_scope",
          note: "kapsam dışı",
        }),
      ),
      `/research/${ITEM_ID}?notice=rejected`,
    );
    expect(rejectMock).toHaveBeenCalledWith(
      ITEM_ID,
      "out_of_scope",
      "kapsam dışı",
    );
  });

  it("refuses an unknown rejection reason before calling the backend", async () => {
    await expectRedirect(
      rejectDiscoveryItemAction(
        form({ discovery_item_id: ITEM_ID, reason: "made_up" }),
      ),
      `/research/${ITEM_ID}?error=invalid`,
    );
    expect(rejectMock).not.toHaveBeenCalled();
  });
});

describe("requeueDiscoveryItemAction", () => {
  it("requeues with a required reason", async () => {
    requeueMock.mockResolvedValue(updated("accepted"));

    await expectRedirect(
      requeueDiscoveryItemAction(
        form({ discovery_item_id: ITEM_ID, reason: "kaynak düzeldi" }),
      ),
      `/research/${ITEM_ID}?notice=requeued`,
    );
    expect(requeueMock).toHaveBeenCalledWith(ITEM_ID, "kaynak düzeldi");
  });

  it("refuses a blank reason before calling the backend", async () => {
    await expectRedirect(
      requeueDiscoveryItemAction(
        form({ discovery_item_id: ITEM_ID, reason: "   " }),
      ),
      `/research/${ITEM_ID}?error=invalid`,
    );
    expect(requeueMock).not.toHaveBeenCalled();
  });
});

describe("startDiscoveryItemFetchAction", () => {
  it("queues fetch and redirects with a notice", async () => {
    fetchTriggerMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "fetch_discovery_item",
        entity_id: ITEM_ID,
      },
    });

    await expectRedirect(
      startDiscoveryItemFetchAction(form({ discovery_item_id: ITEM_ID })),
      `/research/${ITEM_ID}?notice=fetch-queued`,
    );
  });

  it("maps queue failure to a bounded error redirect", async () => {
    fetchTriggerMock.mockResolvedValue({ kind: "queue_failed" });

    await expectRedirect(
      startDiscoveryItemFetchAction(form({ discovery_item_id: ITEM_ID })),
      `/research/${ITEM_ID}?error=queue-failed`,
    );
  });
});
