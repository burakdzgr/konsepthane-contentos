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
    generateWriterDraft: vi.fn(),
    generateEditorReview: vi.fn(),
    acceptEditorReview: vi.fn(),
    runQaGates: vi.fn(),
    waiveQaGate: vi.fn(),
    submitOperatorDraft: vi.fn(),
    requestWriterRework: vi.fn(),
    resolveChangesRequested: vi.fn(),
    approvePackage: vi.fn(),
    requestChangesDecision: vi.fn(),
    rejectPackage: vi.fn(),
    revokeApproval: vi.fn(),
    uploadMediaAsset: vi.fn(),
    satisfyMediaNeed: vi.fn(),
    unsatisfyMediaNeed: vi.fn(),
    generateMediaImage: vi.fn(),
  };
});

import {
  acceptBriefAction,
  acceptReviewAction,
  generateEditorReviewAction,
  runQaAction,
  waiveQaGateAction,
  approvePackageAction,
  bindMediaAssetAction,
  generateMediaImageAction,
  unbindMediaAction,
  uploadAndBindMediaAction,
  requestChangesDecisionAction,
  rejectPackageAction,
  revokeApprovalAction,
  buildEvidencePackAction,
  commissionOpportunityAction,
  generateDraftAction,
  requestReworkAction,
  resolveBlockAction,
  resolveChangesRequestedAction,
  submitDraftAction,
} from "@/app/editorial/[id]/actions";
import {
  acceptBriefForDrafting,
  acceptEditorReview,
  approvePackage,
  buildEvidencePack,
  commissionOpportunity,
  generateEditorReview,
  generateWriterDraft,
  runQaGates,
  satisfyMediaNeed,
  unsatisfyMediaNeed,
  uploadMediaAsset,
  generateMediaImage,
  waiveQaGate,
  rejectPackage,
  requestChangesDecision,
  requestWriterRework,
  resolveChangesRequested,
  resolveWorkItemBlock,
  revokeApproval,
  submitOperatorDraft,
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
const generateDraftMock = vi.mocked(generateWriterDraft);
const generateReviewMock = vi.mocked(generateEditorReview);
const acceptReviewMock = vi.mocked(acceptEditorReview);
const runQaMock = vi.mocked(runQaGates);
const waiveMock = vi.mocked(waiveQaGate);
const submitDraftMock = vi.mocked(submitOperatorDraft);
const requestReworkMock = vi.mocked(requestWriterRework);
const resolveChangesMock = vi.mocked(resolveChangesRequested);
const approvePackageMock = vi.mocked(approvePackage);
const requestChangesDecisionMock = vi.mocked(requestChangesDecision);
const rejectPackageMock = vi.mocked(rejectPackage);
const revokeApprovalMock = vi.mocked(revokeApproval);
const uploadMediaMock = vi.mocked(uploadMediaAsset);
const satisfyMediaMock = vi.mocked(satisfyMediaNeed);
const unsatisfyMediaMock = vi.mocked(unsatisfyMediaNeed);
const generateMediaImageMock = vi.mocked(generateMediaImage);

function decidedResult(
  decision: "approved" | "changes_requested" | "rejected" | "approval_revoked",
  state: "approved" | "changes_requested" | "rejected",
) {
  return {
    kind: "ok" as const,
    data: {
      status: "decided" as const,
      decision,
      human_decision_id: "d0000000-0000-4000-8000-00000000000d",
      work_item_id: WORK_ITEM_ID,
      work_item_state: state,
      reviewer_username: "smoke-reviewer",
    },
  };
}

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

describe("writer draft actions", () => {
  it("generateDraftAction queues with retry number and supersede reason", async () => {
    generateDraftMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "generate_writer_draft",
        entity_id: BRIEF_ID,
      },
    });
    await expectRedirect(
      generateDraftAction(
        form({
          work_item_id: WORK_ITEM_ID,
          brief_id: BRIEF_ID,
          retry_number: "1",
          supersede_reason: "yeniden uretim",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=draft-queued`,
    );
    expect(generateDraftMock).toHaveBeenCalledWith(BRIEF_ID, {
      retryNumber: 1,
      supersedeReason: "yeniden uretim",
    });
  });

  it("submitDraftAction parses the sections JSON and submits", async () => {
    submitDraftMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "created",
        content_draft_id: BRIEF_ID,
        draft_version: 1,
        draft_origin: "operator",
        draft_status: "active",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "editing",
      },
    });
    await expectRedirect(
      submitDraftAction(
        form({
          work_item_id: WORK_ITEM_ID,
          brief_id: BRIEF_ID,
          reason: "operator taslagi",
          title_proposal: "Baslik",
          sections_json: '[{"key":"giris","heading":"Giris","blocks":[]}]',
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=draft-submitted`,
    );
    expect(submitDraftMock).toHaveBeenCalledWith(BRIEF_ID, {
      reason: "operator taslagi",
      titleProposal: "Baslik",
      supersedeReason: undefined,
      sections: [{ key: "giris", heading: "Giris", blocks: [] }],
    });
  });

  it("submitDraftAction rejects malformed JSON without any backend call", async () => {
    await expectRedirect(
      submitDraftAction(
        form({
          work_item_id: WORK_ITEM_ID,
          brief_id: BRIEF_ID,
          reason: "r",
          sections_json: "not json",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(submitDraftMock).not.toHaveBeenCalled();
  });

  it("requestReworkAction requires a reason", async () => {
    await expectRedirect(
      requestReworkAction(form({ work_item_id: WORK_ITEM_ID })),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(requestReworkMock).not.toHaveBeenCalled();
  });

  it("resolveChangesRequestedAction routes with the reason", async () => {
    resolveChangesMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "drafting",
      },
    });
    await expectRedirect(
      resolveChangesRequestedAction(
        form({ work_item_id: WORK_ITEM_ID, reason: "yonlendir" }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=changes-request-resolved`,
    );
    expect(resolveChangesMock).toHaveBeenCalledWith(WORK_ITEM_ID, "yonlendir");
  });
});

describe("editor review actions", () => {
  it("generateEditorReviewAction queues with options", async () => {
    generateReviewMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "generate_editor_review",
        entity_id: WORK_ITEM_ID,
      },
    });
    await expectRedirect(
      generateEditorReviewAction(
        form({
          work_item_id: WORK_ITEM_ID,
          retry_number: "0",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=review-queued`,
    );
    expect(generateReviewMock).toHaveBeenCalledWith(WORK_ITEM_ID, {
      retryNumber: 0,
      supersedeReason: undefined,
    });
  });

  it("acceptReviewAction requires a reason", async () => {
    await expectRedirect(
      acceptReviewAction(form({ work_item_id: WORK_ITEM_ID })),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(acceptReviewMock).not.toHaveBeenCalled();
  });

  it("acceptReviewAction surfaces conflicts truthfully", async () => {
    acceptReviewMock.mockResolvedValue({ kind: "conflict" });
    await expectRedirect(
      acceptReviewAction(form({ work_item_id: WORK_ITEM_ID, reason: "temiz" })),
      `/editorial/${WORK_ITEM_ID}?error=conflict`,
    );
  });
});

describe("qa actions", () => {
  it("runQaAction queues the run", async () => {
    runQaMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "run_qa_gates",
        entity_id: WORK_ITEM_ID,
      },
    });
    await expectRedirect(
      runQaAction(form({ work_item_id: WORK_ITEM_ID })),
      `/editorial/${WORK_ITEM_ID}?notice=qa-queued`,
    );
    expect(runQaMock).toHaveBeenCalledWith(WORK_ITEM_ID);
  });

  it("waiveQaGateAction requires the bounded gate key and reason", async () => {
    await expectRedirect(
      waiveQaGateAction(
        form({
          work_item_id: WORK_ITEM_ID,
          gate_key: "provenance_chain",
          reason: "asla",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(waiveMock).not.toHaveBeenCalled();

    waiveMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "waived",
        work_item_id: WORK_ITEM_ID,
        gate_key: "media_needs",
        note: "not re-run",
      },
    });
    await expectRedirect(
      waiveQaGateAction(
        form({
          work_item_id: WORK_ITEM_ID,
          gate_key: "media_needs",
          reason: "bilinçli erteleme",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=qa-gate-waived`,
    );
    expect(waiveMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "media_needs",
      "bilinçli erteleme",
    );
  });
});

describe("human decision actions", () => {
  it("approvePackageAction requires a reason and never calls the backend without one", async () => {
    await expectRedirect(
      approvePackageAction(form({ work_item_id: WORK_ITEM_ID })),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(approvePackageMock).not.toHaveBeenCalled();
  });

  it("approvePackageAction records and redirects on success", async () => {
    approvePackageMock.mockResolvedValue(decidedResult("approved", "approved"));
    await expectRedirect(
      approvePackageAction(
        form({ work_item_id: WORK_ITEM_ID, reason: "paket eksiksiz" }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=package-approved`,
    );
    expect(approvePackageMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "paket eksiksiz",
    );
  });

  it("requestChangesDecisionAction bounds the responsible state", async () => {
    requestChangesDecisionMock.mockResolvedValue(
      decidedResult("changes_requested", "changes_requested"),
    );
    await expectRedirect(
      requestChangesDecisionAction(
        form({
          work_item_id: WORK_ITEM_ID,
          reason: "giris zayif",
          responsible_state: "publishing" /* out of bounds -> drafting */,
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=decision-changes-requested`,
    );
    expect(requestChangesDecisionMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "giris zayif",
      "drafting",
    );
  });

  it("rejectPackageAction and revokeApprovalAction route with their reasons", async () => {
    rejectPackageMock.mockResolvedValue(decidedResult("rejected", "rejected"));
    await expectRedirect(
      rejectPackageAction(
        form({ work_item_id: WORK_ITEM_ID, reason: "konu geçersiz" }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=package-rejected`,
    );
    expect(rejectPackageMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "konu geçersiz",
    );

    revokeApprovalMock.mockResolvedValue(
      decidedResult("approval_revoked", "changes_requested"),
    );
    await expectRedirect(
      revokeApprovalAction(
        form({
          work_item_id: WORK_ITEM_ID,
          reason: "kaynak güncellendi",
          responsible_state: "qa_review",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=approval-revoked`,
    );
    expect(revokeApprovalMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      "kaynak güncellendi",
      "qa_review",
    );
  });

  it("maps a decision conflict to the error redirect", async () => {
    approvePackageMock.mockResolvedValue({ kind: "conflict" });
    await expectRedirect(
      approvePackageAction(
        form({ work_item_id: WORK_ITEM_ID, reason: "gerekce" }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=conflict`,
    );
  });
});

describe("media actions", () => {
  const SATISFIED = {
    kind: "ok" as const,
    data: {
      status: "satisfied" as const,
      work_item_id: WORK_ITEM_ID,
      need_index: 0,
      satisfaction_id: "c3000000-0000-4000-8000-00000000000c",
      media_asset_id: "c2000000-0000-4000-8000-00000000000c",
    },
  };

  it("uploadAndBindMediaAction uploads then binds with the reason", async () => {
    uploadMediaMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "registered",
        media_asset_id: "c2000000-0000-4000-8000-00000000000c",
        content_sha256: "a".repeat(64),
        media_type: "image/png",
        byte_size: 3,
      },
    });
    satisfyMediaMock.mockResolvedValue(SATISFIED);
    const data = form({
      work_item_id: WORK_ITEM_ID,
      need_index: "0",
      alt_text: "Balon masası",
      license_note: "Arşiv",
      reason: "kapak karşılandı",
    });
    data.set("file", new File([new Uint8Array([1, 2, 3])], "kapak.png"));
    await expectRedirect(
      uploadAndBindMediaAction(data),
      `/editorial/${WORK_ITEM_ID}?notice=media-bound`,
    );
    const sent = uploadMediaMock.mock.calls[0]?.[0] as FormData;
    expect(sent.get("alt_text")).toBe("Balon masası");
    expect(sent.get("license_note")).toBe("Arşiv");
    expect(satisfyMediaMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      0,
      "c2000000-0000-4000-8000-00000000000c",
      "kapak karşılandı",
    );
  });

  it("uploadAndBindMediaAction refuses a missing file or fields locally", async () => {
    await expectRedirect(
      uploadAndBindMediaAction(
        form({
          work_item_id: WORK_ITEM_ID,
          need_index: "0",
          alt_text: "a",
          license_note: "b",
          reason: "c",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
    expect(uploadMediaMock).not.toHaveBeenCalled();
  });

  it("bind, unbind and generate route with bounded indexes", async () => {
    satisfyMediaMock.mockResolvedValue(SATISFIED);
    await expectRedirect(
      bindMediaAssetAction(
        form({
          work_item_id: WORK_ITEM_ID,
          need_index: "0",
          media_asset_id: "c2000000-0000-4000-8000-00000000000c",
          reason: "mevcut görsel uygun",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=media-bound`,
    );

    unsatisfyMediaMock.mockResolvedValue({
      kind: "ok",
      data: { ...SATISFIED.data, status: "unsatisfied" },
    });
    await expectRedirect(
      unbindMediaAction(
        form({
          work_item_id: WORK_ITEM_ID,
          need_index: "0",
          reason: "lisans şüphesi",
        }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=media-unbound`,
    );
    expect(unsatisfyMediaMock).toHaveBeenCalledWith(
      WORK_ITEM_ID,
      0,
      "lisans şüphesi",
    );

    generateMediaImageMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "queued",
        task: "generate_media_image",
        entity_id: WORK_ITEM_ID,
      },
    });
    await expectRedirect(
      generateMediaImageAction(
        form({ work_item_id: WORK_ITEM_ID, need_index: "0" }),
      ),
      `/editorial/${WORK_ITEM_ID}?notice=media-image-queued`,
    );

    await expectRedirect(
      generateMediaImageAction(
        form({ work_item_id: WORK_ITEM_ID, need_index: "abc" }),
      ),
      `/editorial/${WORK_ITEM_ID}?error=invalid`,
    );
  });
});
