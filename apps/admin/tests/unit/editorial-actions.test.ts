// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/editorial-control-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/editorial-control-api")
  >("@/lib/editorial-control-api");
  return {
    ...actual,
    commissionOpportunity: vi.fn(),
    rejectOpportunity: vi.fn(),
    buildEvidencePack: vi.fn(),
    acceptBriefForDrafting: vi.fn(),
    resolveWorkItemBlock: vi.fn(),
  };
});

import {
  acceptBriefAction,
  buildEvidencePackAction,
  commissionOpportunityAction,
  resolveBlockAction,
} from "@/app/editorial/[id]/actions";
import {
  acceptBriefForDrafting,
  buildEvidencePack,
  commissionOpportunity,
  resolveWorkItemBlock,
} from "@/lib/editorial-control-api";
import {
  BRIEF_ID,
  EVIDENCE_ID,
  IDEA_ID,
  OPPORTUNITY_ID,
  WORK_ITEM_ID,
} from "./editorial-fixtures";

const commissionMock = vi.mocked(commissionOpportunity);
const buildPackMock = vi.mocked(buildEvidencePack);
const acceptMock = vi.mocked(acceptBriefForDrafting);
const resolveBlockMock = vi.mocked(resolveWorkItemBlock);

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

describe("commissionOpportunityAction", () => {
  it("commissions with the operator's reason and redirects with a notice", async () => {
    commissionMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "commissioned",
        opportunity_id: OPPORTUNITY_ID,
        disposition: "commissioned",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "evidence_building",
        opportunity_score_id: null,
      },
    });

    await expectRedirect(
      commissionOpportunityAction(
        form({
          work_item_id: WORK_ITEM_ID,
          opportunity_id: OPPORTUNITY_ID,
          reason: "güçlü skor",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=commissioned`,
    );
    expect(commissionMock).toHaveBeenCalledWith(OPPORTUNITY_ID, "güçlü skor");
  });

  it("refuses an empty reason without calling the backend", async () => {
    await expectRedirect(
      commissionOpportunityAction(
        form({
          work_item_id: WORK_ITEM_ID,
          opportunity_id: OPPORTUNITY_ID,
          reason: "  ",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(commissionMock).not.toHaveBeenCalled();
  });

  it("maps a backend gate conflict to a bounded error", async () => {
    commissionMock.mockResolvedValue({ kind: "conflict" });
    await expectRedirect(
      commissionOpportunityAction(
        form({
          work_item_id: WORK_ITEM_ID,
          opportunity_id: OPPORTUNITY_ID,
          reason: "yine de",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=conflict`,
    );
  });
});

describe("buildEvidencePackAction", () => {
  it("collects only the checked rows into the exact command", async () => {
    buildPackMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "build_evidence_pack",
        entity_id: OPPORTUNITY_ID,
      },
    });
    const data = form({
      work_item_id: WORK_ITEM_ID,
      opportunity_id: OPPORTUNITY_ID,
      idea_id: IDEA_ID,
    });
    data.set(`select-${EVIDENCE_ID}`, "on");
    data.set(`role-${EVIDENCE_ID}`, "key_fact");
    data.set(`cluster-${EVIDENCE_ID}`, "detaylar");
    data.set(`note-${EVIDENCE_ID}`, "");
    // An unchecked row's inputs must be ignored entirely.
    data.set("role-b9111111-2222-4333-8444-555555555555", "supporting");
    data.set("cluster-b9111111-2222-4333-8444-555555555555", "boş");

    await expectRedirect(
      buildEvidencePackAction(data),
      `/editorial/${WORK_ITEM_ID}?notice=pack-queued`,
    );
    expect(buildPackMock).toHaveBeenCalledWith(OPPORTUNITY_ID, IDEA_ID, [
      {
        researchEvidenceId: EVIDENCE_ID,
        role: "key_fact",
        claimCluster: "detaylar",
        displayNote: undefined,
      },
    ]);
  });

  it("refuses an empty selection: the operator must choose evidence", async () => {
    await expectRedirect(
      buildEvidencePackAction(
        form({
          work_item_id: WORK_ITEM_ID,
          opportunity_id: OPPORTUNITY_ID,
          idea_id: IDEA_ID,
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(buildPackMock).not.toHaveBeenCalled();
  });

  it("refuses a checked row without a claim cluster", async () => {
    const data = form({
      work_item_id: WORK_ITEM_ID,
      opportunity_id: OPPORTUNITY_ID,
      idea_id: IDEA_ID,
    });
    data.set(`select-${EVIDENCE_ID}`, "on");
    data.set(`role-${EVIDENCE_ID}`, "key_fact");

    await expectRedirect(
      buildEvidencePackAction(data),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(buildPackMock).not.toHaveBeenCalled();
  });
});

describe("acceptBriefAction", () => {
  it("accepts with a reason and reports the truthful result", async () => {
    acceptMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "accepted",
        brief_id: BRIEF_ID,
        brief_status: "accepted_for_drafting",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "drafting",
      },
    });

    await expectRedirect(
      acceptBriefAction(
        form({
          work_item_id: WORK_ITEM_ID,
          brief_id: BRIEF_ID,
          reason: "kapsam eksiksiz",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=brief-accepted`,
    );
    expect(acceptMock).toHaveBeenCalledWith(BRIEF_ID, "kapsam eksiksiz");
  });
});

describe("resolveBlockAction", () => {
  it("resolves with a reason and no caller-supplied target", async () => {
    resolveBlockMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "evidence_building",
      },
    });

    await expectRedirect(
      resolveBlockAction(
        form({ work_item_id: WORK_ITEM_ID, reason: "kanıt tamamlandı" }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=block-resolved`,
    );
    expect(resolveBlockMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "kanıt tamamlandı",
    );
  });

  it("refuses a junk work item id", async () => {
    await expectRedirect(
      resolveBlockAction(form({ work_item_id: "junk", reason: "x" })),
      "/editorial?error=invalid",
    );
    expect(resolveBlockMock).not.toHaveBeenCalled();
  });
});
