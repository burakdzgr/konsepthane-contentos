// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptBriefForDrafting,
  acceptEditorReview,
  approvePackage,
  rejectPackage,
  requestChangesDecision,
  revokeApproval,
  generateEditorReview,
  generateWriterDraft,
  runQaGates,
  waiveQaGate,
  requestWriterRework,
  resolveChangesRequested,
  submitOperatorDraft,
  analyzeSearchIntent,
  buildEvidencePack,
  commissionOpportunity,
  composeContentBrief,
  promoteResearchDocument,
  rejectOpportunity,
  reopenDuplicateDocument,
  resolveContradiction,
  resolveWorkItemBlock,
  selectIdea,
} from "@/lib/editorial-control-api";
import {
  ANALYSIS_ID,
  BRIEF_ID,
  DRAFT_ID,
  REVIEW_ID,
  CONTRADICTION_ID,
  DOCUMENT_ID,
  EVIDENCE_ID,
  IDEA_ID,
  OPPORTUNITY_ID,
  PACK_ID,
  SIGNAL_ID,
  WORK_ITEM_ID,
} from "./editorial-fixtures";

const INTERNAL_HOST = "127.0.0.1";

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

function requestOf(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as [
    URL,
    { method: string; body?: string },
  ];
  return {
    url: String(url),
    method: init.method,
    body: init.body !== undefined ? JSON.parse(init.body) : undefined,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("queue commands", () => {
  it("promote posts to the exact backend path", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "promote_research",
        entity_id: DOCUMENT_ID,
      }),
    );

    const result = await promoteResearchDocument(DOCUMENT_ID);
    expect(result.kind).toBe("ok");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/research/${DOCUMENT_ID}/promote`,
    );
    expect(request.method).toBe("POST");
  });

  it("build pack sends the exact bounded selection command", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "build_evidence_pack",
        entity_id: OPPORTUNITY_ID,
      }),
    );

    await buildEvidencePack(OPPORTUNITY_ID, IDEA_ID, [
      {
        researchEvidenceId: EVIDENCE_ID,
        role: "key_fact",
        claimCluster: "detaylar",
      },
    ]);
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/opportunities/${OPPORTUNITY_ID}/evidence-packs/build`,
    );
    expect(request.body).toEqual({
      idea_id: IDEA_ID,
      selections: [
        {
          research_evidence_id: EVIDENCE_ID,
          role: "key_fact",
          claim_cluster: "detaylar",
          display_note: null,
        },
      ],
    });
  });

  it("analyze intent pins exact ids and signals", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "analyze_search_intent",
        entity_id: OPPORTUNITY_ID,
      }),
    );

    await analyzeSearchIntent(OPPORTUNITY_ID, {
      ideaId: IDEA_ID,
      evidencePackId: PACK_ID,
      searchSignalIds: [SIGNAL_ID],
    });
    const request = requestOf(fetchMock);
    expect(request.body).toEqual({
      idea_id: IDEA_ID,
      evidence_pack_id: PACK_ID,
      search_signal_ids: [SIGNAL_ID],
    });
  });

  it("compose brief pins the full artifact chain", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "compose_content_brief",
        entity_id: WORK_ITEM_ID,
      }),
    );

    await composeContentBrief(WORK_ITEM_ID, {
      ideaId: IDEA_ID,
      evidencePackId: PACK_ID,
      searchIntentAnalysisId: ANALYSIS_ID,
    });
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/compose-brief`,
    );
    expect(request.body).toEqual({
      idea_id: IDEA_ID,
      evidence_pack_id: PACK_ID,
      search_intent_analysis_id: ANALYSIS_ID,
    });
  });

  it("maps 503 to queue_failed without leaking transport details", async () => {
    stubFetch(async () => jsonResponse(503, { error: {} }));
    const result = await promoteResearchDocument(DOCUMENT_ID);
    expect(result).toEqual({ kind: "queue_failed" });
    expect(JSON.stringify(result)).not.toContain(INTERNAL_HOST);
  });
});

describe("direct commands", () => {
  it("commission posts the reason and parses the truthful result", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "commissioned",
        opportunity_id: OPPORTUNITY_ID,
        disposition: "commissioned",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "evidence_building",
        opportunity_score_id: null,
      }),
    );

    const result = await commissionOpportunity(OPPORTUNITY_ID, "güçlü skor");
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.work_item_state).toBe("evidence_building");
    }
    expect(requestOf(fetchMock).body).toEqual({ reason: "güçlü skor" });
  });

  it("maps a commissioning gate failure to conflict", async () => {
    stubFetch(async () => jsonResponse(409, { error: {} }));
    const result = await commissionOpportunity(OPPORTUNITY_ID, "yine de");
    expect(result).toEqual({ kind: "conflict" });
  });

  it("reject posts to the explicit reject path", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "rejected",
        opportunity_id: OPPORTUNITY_ID,
        disposition: "rejected",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "rejected",
      }),
    );

    await rejectOpportunity(OPPORTUNITY_ID, "uygun değil");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/opportunities/${OPPORTUNITY_ID}/reject`,
    );
  });

  it("select idea, contradiction resolve, block resolve, accept brief hit exact paths", async () => {
    const responses: Record<string, unknown> = {
      select: {
        status: "selected",
        idea_id: IDEA_ID,
        opportunity_id: OPPORTUNITY_ID,
      },
      resolve: {
        status: "resolved",
        contradiction_id: CONTRADICTION_ID,
        pack_id: PACK_ID,
        resolution_status: "resolved_cautious_wording",
        note: "unchanged",
      },
      "resolve-block": {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "evidence_building",
      },
      accept: {
        status: "accepted",
        brief_id: BRIEF_ID,
        brief_status: "accepted_for_drafting",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "drafting",
      },
    };
    const urls: string[] = [];
    stubFetch(async (url: unknown) => {
      const value = String(url);
      urls.push(value);
      const key = Object.keys(responses).find((suffix) =>
        value.includes(suffix),
      );
      return jsonResponse(200, key !== undefined ? responses[key] : {});
    });

    await selectIdea(IDEA_ID, "en iyi açı");
    await resolveContradiction(
      CONTRADICTION_ID,
      "resolved_cautious_wording",
      "aralık verilecek",
    );
    await resolveWorkItemBlock(WORK_ITEM_ID, "kanıt tamam");
    await acceptBriefForDrafting(BRIEF_ID, "kapsam eksiksiz");

    expect(urls[0]).toContain(`/internal/editorial/ideas/${IDEA_ID}/select`);
    expect(urls[1]).toContain(
      `/internal/editorial/contradictions/${CONTRADICTION_ID}/resolve`,
    );
    expect(urls[2]).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/resolve-block`,
    );
    expect(urls[3]).toContain(`/internal/editorial/briefs/${BRIEF_ID}/accept`);
  });

  it("reopen duplicate posts reason and distinct angle", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "created",
        work_item_id: WORK_ITEM_ID,
        opportunity_id: OPPORTUNITY_ID,
        duplicate_outcome: "duplicate",
      }),
    );

    await reopenDuplicateDocument(DOCUMENT_ID, "farklı açı", "bütçe odaklı");
    expect(requestOf(fetchMock).body).toEqual({
      reason: "farklı açı",
      distinct_angle: "bütçe odaklı",
    });
  });

  it("refuses junk ids locally without a backend call", async () => {
    const fetchMock = stubFetch(async () => jsonResponse(200, {}));
    const result = await selectIdea("junk", "sebep");
    expect(result).toEqual({ kind: "not_found" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("writer draft commands", () => {
  it("generate-draft posts the exact bounded command", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "generate_writer_draft",
        entity_id: BRIEF_ID,
      }),
    );

    const result = await generateWriterDraft(BRIEF_ID, {
      retryNumber: 1,
      supersedeReason: "yeniden uretim",
    });
    expect(result.kind).toBe("ok");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/briefs/${BRIEF_ID}/generate-draft`,
    );
    expect(request.body).toEqual({
      retry_number: 1,
      supersede_reason: "yeniden uretim",
    });
  });

  it("submit-draft posts reason, title and sections verbatim", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "created",
        content_draft_id: DRAFT_ID,
        draft_version: 1,
        draft_origin: "operator",
        draft_status: "active",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "editing",
      }),
    );

    const sections = [{ key: "giris", heading: "Giris", blocks: [] }];
    const result = await submitOperatorDraft(BRIEF_ID, {
      reason: "operator taslagi",
      titleProposal: "Baslik",
      sections,
    });
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.work_item_state).toBe("editing");
    }
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/briefs/${BRIEF_ID}/submit-draft`,
    );
    expect(request.body).toEqual({
      reason: "operator taslagi",
      title_proposal: "Baslik",
      sections,
    });
  });

  it("submit-draft maps a 422 policy violation to invalid", async () => {
    stubFetch(async () => jsonResponse(422, { detail: "policy" }));
    const result = await submitOperatorDraft(BRIEF_ID, {
      reason: "r",
      sections: [],
    });
    expect(result.kind).toBe("invalid");
  });

  it("request-rework and resolve post to their exact paths", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "changes_requested",
      }),
    );
    await requestWriterRework(WORK_ITEM_ID, "yeniden yazilmali");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/request-rework`,
    );

    const resolveFetch = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "drafting",
      }),
    );
    const resolved = await resolveChangesRequested(WORK_ITEM_ID, "yonlendir");
    expect(resolved.kind).toBe("ok");
    expect(requestOf(resolveFetch).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/resolve-changes-requested`,
    );
  });

  it("rework outside EDITING maps a 409 to conflict", async () => {
    stubFetch(async () => jsonResponse(409, { detail: "not allowed" }));
    const result = await requestWriterRework(WORK_ITEM_ID, "erken");
    expect(result.kind).toBe("conflict");
  });
});

describe("editor review commands", () => {
  it("generate-editor-review posts the exact bounded command", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "generate_editor_review",
        entity_id: WORK_ITEM_ID,
      }),
    );
    const result = await generateEditorReview(WORK_ITEM_ID, {
      retryNumber: 1,
      supersedeReason: "yeniden inceleme",
    });
    expect(result.kind).toBe("ok");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/generate-editor-review`,
    );
    expect(request.body).toEqual({
      retry_number: 1,
      supersede_reason: "yeniden inceleme",
    });
  });

  it("accept-review posts the reason and parses the advance", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "accepted",
        work_item_id: WORK_ITEM_ID,
        work_item_state: "qa_review",
        editorial_review_id: REVIEW_ID,
        review_verdict: "pass",
      }),
    );
    const result = await acceptEditorReview(WORK_ITEM_ID, "inceleme temiz");
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.work_item_state).toBe("qa_review");
      expect(result.data.review_verdict).toBe("pass");
    }
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/accept-review`,
    );
    expect(request.body).toEqual({ reason: "inceleme temiz" });
  });

  it("accept-review maps a revise 409 to conflict", async () => {
    stubFetch(async () => jsonResponse(409, { detail: "revise" }));
    const result = await acceptEditorReview(WORK_ITEM_ID, "denemek");
    expect(result.kind).toBe("conflict");
  });
});

describe("qa commands", () => {
  it("run-qa posts to the exact backend path", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "run_qa_gates",
        entity_id: WORK_ITEM_ID,
      }),
    );
    const result = await runQaGates(WORK_ITEM_ID);
    expect(result.kind).toBe("ok");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/run-qa`,
    );
  });

  it("waive-qa-gate posts the bounded gate key and reason", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "waived",
        work_item_id: WORK_ITEM_ID,
        gate_key: "media_needs",
        note: "The waiver is recorded and audited; gates were NOT re-run.",
      }),
    );
    const result = await waiveQaGate(
      WORK_ITEM_ID,
      "media_needs",
      "gorsel bilincli ertelendi",
    );
    expect(result.kind).toBe("ok");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/waive-qa-gate`,
    );
    expect(request.body).toEqual({
      gate_key: "media_needs",
      reason: "gorsel bilincli ertelendi",
    });
  });

  it("rework carries the bounded responsible-state choice", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "changes_requested",
      }),
    );
    const { requestWriterRework } = await import("@/lib/editorial-control-api");
    await requestWriterRework(WORK_ITEM_ID, "editore donmeli", "editing");
    expect(requestOf(fetchMock).body).toEqual({
      reason: "editore donmeli",
      responsible_state: "editing",
    });
  });
});

describe("human decision commands", () => {
  function decidedResponse(decision: string, state: string) {
    return jsonResponse(200, {
      status: "decided",
      decision,
      human_decision_id: "d0000000-0000-4000-8000-00000000000d",
      work_item_id: WORK_ITEM_ID,
      work_item_state: state,
      reviewer_username: "smoke-reviewer",
    });
  }

  it("approve posts the reason to the exact governed path", async () => {
    const fetchMock = stubFetch(async () =>
      decidedResponse("approved", "approved"),
    );
    const result = await approvePackage(
      WORK_ITEM_ID,
      "paket dogru ve eksiksiz",
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.work_item_state).toBe("approved");
      expect(result.data.reviewer_username).toBe("smoke-reviewer");
    }
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/approve`,
    );
    expect(request.body).toEqual({ reason: "paket dogru ve eksiksiz" });
  });

  it("request-changes carries the bounded responsible state", async () => {
    const fetchMock = stubFetch(async () =>
      decidedResponse("changes_requested", "changes_requested"),
    );
    const result = await requestChangesDecision(
      WORK_ITEM_ID,
      "giris bolumu zayif",
      "editing",
    );
    expect(result.kind).toBe("ok");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/request-changes`,
    );
    expect(request.body).toEqual({
      reason: "giris bolumu zayif",
      responsible_state: "editing",
    });
  });

  it("reject and revoke post to their exact paths", async () => {
    let fetchMock = stubFetch(async () =>
      decidedResponse("rejected", "rejected"),
    );
    await rejectPackage(WORK_ITEM_ID, "konu artik geçerli degil");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/reject-package`,
    );

    fetchMock = stubFetch(async () =>
      decidedResponse("approval_revoked", "changes_requested"),
    );
    await revokeApproval(WORK_ITEM_ID, "kaynak guncellendi", "qa_review");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/revoke-approval`,
    );
    expect(request.body).toEqual({
      reason: "kaynak guncellendi",
      responsible_state: "qa_review",
    });
  });

  it("maps a decision gate 409 to conflict and junk ids stay local", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(409, { detail: "approval requires a ready QA report" }),
    );
    const conflicted = await approvePackage(WORK_ITEM_ID, "gerekce");
    expect(conflicted.kind).toBe("conflict");
    expect((await approvePackage("junk", "gerekce")).kind).toBe("not_found");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("media commands", () => {
  it("upload posts multipart and parses the honest dedupe result", async () => {
    const { uploadMediaAsset } = await import("@/lib/editorial-control-api");
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "already_exists",
        media_asset_id: "c2000000-0000-4000-8000-00000000000c",
        content_sha256: "a".repeat(64),
        media_type: "image/png",
        byte_size: 2048,
      }),
    );
    const form = new FormData();
    form.set("file", new Blob([new Uint8Array([1, 2, 3])]), "kapak.png");
    form.set("alt_text", "Balon masası");
    form.set("license_note", "Arşiv");
    const result = await uploadMediaAsset(form);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.data.status).toBe("already_exists");
    }
    const [url, init] = fetchMock.mock.calls[0] as [URL, { body?: unknown }];
    expect(String(url)).toContain("/internal/editorial/media-assets");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("satisfy/unsatisfy/generate hit the exact need-scoped paths", async () => {
    const { generateMediaImage, satisfyMediaNeed, unsatisfyMediaNeed } =
      await import("@/lib/editorial-control-api");
    let fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "satisfied",
        work_item_id: WORK_ITEM_ID,
        need_index: 0,
        satisfaction_id: "c3000000-0000-4000-8000-00000000000c",
        media_asset_id: "c2000000-0000-4000-8000-00000000000c",
      }),
    );
    await satisfyMediaNeed(
      WORK_ITEM_ID,
      0,
      "c2000000-0000-4000-8000-00000000000c",
      "kapak karşılandı",
    );
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/media-needs/0/satisfy`,
    );
    expect(request.body).toEqual({
      media_asset_id: "c2000000-0000-4000-8000-00000000000c",
      reason: "kapak karşılandı",
    });

    fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "unsatisfied",
        work_item_id: WORK_ITEM_ID,
        need_index: 0,
        satisfaction_id: "c3000000-0000-4000-8000-00000000000c",
        media_asset_id: "c2000000-0000-4000-8000-00000000000c",
      }),
    );
    await unsatisfyMediaNeed(WORK_ITEM_ID, 0, "lisans şüphesi");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/media-needs/0/unsatisfy`,
    );

    fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "generate_media_image",
        entity_id: WORK_ITEM_ID,
      }),
    );
    const queued = await generateMediaImage(WORK_ITEM_ID, 0);
    expect(queued.kind).toBe("ok");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/media-needs/0/generate-image`,
    );
  });

  it("maps a frozen-state 409 to conflict", async () => {
    const { satisfyMediaNeed } = await import("@/lib/editorial-control-api");
    stubFetch(async () => jsonResponse(409, { detail: "terminal review" }));
    const result = await satisfyMediaNeed(
      WORK_ITEM_ID,
      0,
      "c2000000-0000-4000-8000-00000000000c",
      "geç bağlama",
    );
    expect(result).toEqual({ kind: "conflict" });
  });
});

describe("publication commands", () => {
  it("assemble/schedule/publish/resolve hit the exact governed paths", async () => {
    const {
      assemblePublicationPackage,
      publishWorkItem,
      resolveApprovalExpired,
      schedulePublication,
    } = await import("@/lib/editorial-control-api");
    const PACKAGE_ID = "c4000000-0000-4000-8000-00000000000c";

    let fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "assembled",
        publication_package_id: PACKAGE_ID,
        work_item_id: WORK_ITEM_ID,
        version: 1,
        package_hash: "f".repeat(64),
        content_hash: "c".repeat(64),
      }),
    );
    const assembled = await assemblePublicationPackage(WORK_ITEM_ID);
    expect(assembled.kind).toBe("ok");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/assemble-publication-package`,
    );

    fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "scheduled",
      }),
    );
    await schedulePublication(WORK_ITEM_ID, PACKAGE_ID, "yayin planina alindi");
    const request = requestOf(fetchMock);
    expect(request.url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/schedule-publication`,
    );
    expect(request.body).toEqual({
      publication_package_id: PACKAGE_ID,
      reason: "yayin planina alindi",
    });

    fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "queued",
        task: "publish_package",
        entity_id: WORK_ITEM_ID,
      }),
    );
    const queued = await publishWorkItem(WORK_ITEM_ID);
    expect(queued.kind).toBe("ok");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/publish`,
    );

    fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "updated",
        work_item_id: WORK_ITEM_ID,
        current_state: "awaiting_human_review",
      }),
    );
    await resolveApprovalExpired(WORK_ITEM_ID, "yeniden incelemeye don");
    expect(requestOf(fetchMock).url).toContain(
      `/internal/editorial/work-items/${WORK_ITEM_ID}/resolve-approval-expired`,
    );
  });

  it("maps a stale-approval 409 to conflict", async () => {
    const { schedulePublication } = await import("@/lib/editorial-control-api");
    stubFetch(async () => jsonResponse(409, { detail: "stale" }));
    const result = await schedulePublication(
      WORK_ITEM_ID,
      "c4000000-0000-4000-8000-00000000000c",
      "bayat onay",
    );
    expect(result).toEqual({ kind: "conflict" });
  });
});
