// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptBriefForDrafting,
  acceptEditorReview,
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
