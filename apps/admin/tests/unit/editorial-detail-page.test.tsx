import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return {
    ...actual,
    fetchWorkItemDetail: vi.fn(),
    fetchEligibleEvidence: vi.fn(),
    fetchWorkItemDrafts: vi.fn(),
    fetchWorkItemReviews: vi.fn(),
    fetchWorkItemQaReports: vi.fn(),
    fetchWorkItemDecisions: vi.fn(),
    fetchWorkItemMedia: vi.fn(),
    fetchWorkItemPublication: vi.fn(),
  };
});

vi.mock("@/lib/auth-api", () => ({
  fetchCurrentUser: vi.fn(),
}));

import EditorialDetailPage from "@/app/editorial/[id]/page";
import { fetchCurrentUser } from "@/lib/auth-api";
import {
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkItemDecisions,
  fetchWorkItemDrafts,
  fetchWorkItemMedia,
  fetchWorkItemPublication,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
} from "@/lib/editorial-api";
import {
  DECISION_CONTENT_HASH,
  REVIEWER_USER_ID,
  WORK_ITEM_ID,
  approvalStatus,
  briefView,
  decisionListPage,
  decisionView,
  mediaCoveragePage,
  mediaSatisfaction,
  publicationAttempt,
  publicationPackage,
  publicationPage,
  draftListPage,
  draftSummary,
  qaReportListPage,
  qaReportSummary,
  reviewListPage,
  reviewSummary,
  eligibleEvidenceItem,
  eligiblePage,
  workItemDetail,
  scoreView,
} from "./editorial-fixtures";

const detailMock = vi.mocked(fetchWorkItemDetail);
const evidenceMock = vi.mocked(fetchEligibleEvidence);
const draftsMock = vi.mocked(fetchWorkItemDrafts);
const reviewsMock = vi.mocked(fetchWorkItemReviews);
const qaMock = vi.mocked(fetchWorkItemQaReports);
const decisionsMock = vi.mocked(fetchWorkItemDecisions);
const mediaMock = vi.mocked(fetchWorkItemMedia);
const publicationMock = vi.mocked(fetchWorkItemPublication);
const currentUserMock = vi.mocked(fetchCurrentUser);

async function renderPage(params: Record<string, string> = {}) {
  render(
    await EditorialDetailPage({
      params: Promise.resolve({ id: WORK_ITEM_ID }),
      searchParams: Promise.resolve(params),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  evidenceMock.mockResolvedValue({
    kind: "ok",
    data: eligiblePage([]),
    requestId: null,
  });
  draftsMock.mockResolvedValue({
    kind: "ok",
    data: draftListPage([]),
    requestId: null,
  });
  reviewsMock.mockResolvedValue({
    kind: "ok",
    data: reviewListPage([]),
    requestId: null,
  });
  qaMock.mockResolvedValue({
    kind: "ok",
    data: qaReportListPage([]),
    requestId: null,
  });
  decisionsMock.mockResolvedValue({
    kind: "ok",
    data: decisionListPage(),
    requestId: null,
  });
  mediaMock.mockResolvedValue({
    kind: "ok",
    data: mediaCoveragePage(),
    requestId: null,
  });
  publicationMock.mockResolvedValue({
    kind: "ok",
    data: publicationPage(),
    requestId: null,
  });
  currentUserMock.mockResolvedValue({
    kind: "ok",
    data: {
      id: REVIEWER_USER_ID,
      username: "smoke-reviewer",
      display_name: "Smoke Reviewer",
      roles: ["operator", "reviewer"],
    },
    requestId: null,
  });
});

describe("Editorial detail page", () => {
  it("renders all explainability sections for a full item", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();

    for (const heading of [
      "İş akışı",
      "Fırsat ve skor",
      "Araştırma girdileri",
      "Fikirler",
      "Kanıt paketleri",
      "Arama niyeti",
      "Brief'ler ve iddialar",
      "Yazar taslakları",
      "Editör değerlendirmeleri",
      "QA raporları",
      "Medya",
      "İnsan kararları",
      "Yayın",
      "Yapay zeka denemeleri",
      "İş akışı geçmişi",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    }

    // Score explainability: band + eligibility + UNKNOWN stays Bilinmiyor.
    expect(screen.getByText("strong / commissionable")).toBeTruthy();
    expect(screen.getByText("(geçerli)")).toBeTruthy();
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThan(0);
    expect(screen.getByText("Gözlemlenmedi")).toBeTruthy();

    // Idea selection state + generation provenance.
    expect(screen.getByText("(seçili)")).toBeTruthy();
    expect(screen.getAllByText("passed").length).toBeGreaterThan(0);

    // Pack members + unresolved contradiction stays visible.
    expect(screen.getByText("unresolved")).toBeTruthy();
    expect(
      screen.getByText("Kaynaklar hazırlık süresinde uyuşmuyor."),
    ).toBeTruthy();

    // Intent: known vs missing signals + honest cannibalization wording.
    expect(screen.getByText("search_volume, trend")).toBeTruthy();
    expect(screen.getByText("Kontrol edilmedi")).toBeTruthy();

    // Brief claim map with exact evidence links.
    expect(screen.getByText("konsept-detaylari")).toBeTruthy();

    // AI attempt safe metadata; never prompt/output.
    expect(
      screen.getByText("fake/deterministic-structured-test-model"),
    ).toBeTruthy();
    expect(screen.getByText("input_tokens: 100")).toBeTruthy();
  });

  it("keeps accept-for-drafting wording distinct from publication", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("button", { name: "Taslak için kabul et" }),
    ).toBeTruthy();
    expect(screen.getByText(/İçerik YAYINLAMAZ/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /yayınla/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /onayla/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /yayına al/i })).toBeNull();
  });

  it("offers commissioning with score context only while decidable", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "idea_scoring",
        },
        opportunity: {
          ...workItemDetail().opportunity!,
          disposition: "open",
          disposition_reason: null,
        },
        ideas: [],
        evidence_packs: [],
        intent_analyses: [],
        briefs: [],
        total_briefs: 0,
        total_ideas: 0,
        total_evidence_packs: 0,
        total_intent_analyses: 0,
        effective_selected_idea_id: null,
        selection_events: [],
        total_selection_events: 0,
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByRole("button", { name: "Görevlendir" })).toBeTruthy();
    expect(
      screen.getByText(/Geçerli skor: strong \/ commissionable/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fırsatı reddet" })).toBeTruthy();
  });

  it("hides commissioning once commissioned and shows the pack builder gate", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "evidence_building",
        },
        evidence_packs: [],
        total_evidence_packs: 0,
        intent_analyses: [],
        total_intent_analyses: 0,
        briefs: [],
        total_briefs: 0,
      }),
      requestId: null,
    });
    evidenceMock.mockResolvedValue({
      kind: "ok",
      data: eligiblePage([eligibleEvidenceItem()]),
      requestId: null,
    });

    await renderPage();

    expect(screen.queryByRole("button", { name: "Görevlendir" })).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Seçimden kanıt paketi oluştur",
      }),
    ).toBeTruthy();
    expect(screen.getByText(/Kanıtı açıkça siz seçersiniz/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Fikir adayları üret" }),
    ).toBeTruthy();
  });

  it("shows blocked reason, derived resume target, and only accepted controls", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "blocked",
          blocked_reason: "kanıt paketi yetersiz",
          blocked_resume_state: "evidence_building",
        },
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("kanıt paketi yetersiz")).toBeTruthy();
    expect(screen.getByText("Geçerli devam hedefi")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Engeli çöz" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Engellenen öğeyi reddet" }),
    ).toBeTruthy();
    // No arbitrary target selector exists anywhere.
    expect(screen.queryByLabelText(/hedef durum/i)).toBeNull();
  });

  it("marks unknown score values as Bilinmiyor, never zero", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        scores: [scoreView({ overall_value: null })],
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThan(0);
  });

  it("shows writer commands in DRAFTING with an accepted brief", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "drafting",
        },
        briefs: [briefView({ status: "accepted_for_drafting" })],
      }),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([draftSummary()]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("button", { name: "Yazar taslağı üret" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Operatör taslağını gönder" }),
    ).toBeTruthy();
    // The listed draft keeps its truthful verdicts and links to detail.
    expect(screen.getByText("evaluated")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Taslağı aç" })).toBeTruthy();
    // No rework commands outside their states.
    expect(
      screen.queryByRole("button", { name: "Yeniden çalışma iste" }),
    ).toBeNull();
  });

  it("shows rework in EDITING and routing in CHANGES_REQUESTED", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "editing",
        },
      }),
      requestId: null,
    });
    await renderPage();
    expect(
      screen.getByRole("button", { name: "Yeniden çalışma iste" }),
    ).toBeTruthy();

    vi.mocked(detailMock).mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "changes_requested",
        },
      }),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([]),
      requestId: null,
    });
    render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(
      screen.getByRole("button", { name: "Yeniden çalışmayı yönlendir" }),
    ).toBeTruthy();
  });

  it("renders UNKNOWN for drafts without persisted verdicts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    draftsMock.mockResolvedValue({
      kind: "ok",
      data: draftListPage([
        draftSummary({
          uncertainty_coverage_status: null,
          originality_outcome: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getAllByText("BİLİNMİYOR").length).toBe(2);
  });

  it("shows editor review commands and truthful verdicts in EDITING", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "editing",
        },
      }),
      requestId: null,
    });
    reviewsMock.mockResolvedValue({
      kind: "ok",
      data: reviewListPage([reviewSummary({ verdict: "revise" })]),
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByRole("button", { name: "Editör değerlendirmesi üret" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Değerlendirmeyi kabul et" }),
    ).toBeTruthy();
    expect(screen.getByText("revise")).toBeTruthy();
    expect(screen.getByText(/arka uç reddedecektir/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Değerlendirmeyi aç" }),
    ).toBeTruthy();
  });

  it("hides review commands outside EDITING", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    await renderPage();
    expect(
      screen.queryByRole("button", { name: "Editör değerlendirmesi üret" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Değerlendirmeyi kabul et" }),
    ).toBeNull();
  });

  it("shows QA commands and truthful gate badges in QA_REVIEW", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });
    qaMock.mockResolvedValue({
      kind: "ok",
      data: qaReportListPage([qaReportSummary()]),
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByRole("button", { name: "QA kapılarını çalıştır" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Medya kapısını atla" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Yeniden çalışma iste" }),
    ).toBeTruthy();
    expect(screen.getByText(/media_needs: unsatisfied/)).toBeTruthy();
    expect(screen.getByText("not_ready")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Raporu aç" })).toBeTruthy();
  });

  it("states the pending human decision in AWAITING_HUMAN_REVIEW", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "awaiting_human_review",
        },
      }),
      requestId: null,
    });
    qaMock.mockResolvedValue({
      kind: "ok",
      data: qaReportListPage([
        qaReportSummary({
          outcome: "ready_for_human_review",
          gate_summary: {
            ...qaReportSummary().gate_summary,
            media_needs: "waived_by_human",
          },
        }),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("İnsan kararı bekleniyor.")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "QA kapılarını çalıştır" }),
    ).toBeNull();

    // The reviewer decision surface, gated on the reviewer role.
    expect(screen.getByRole("button", { name: "Paketi onayla" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Değişiklik iste" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Paketi reddet" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Onayı geri çek" })).toBeNull();
    // The routing choice is bounded to the three named responsible states.
    const select = screen.getByLabelText(
      "Karar sorumlu durumu",
    ) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      "drafting",
      "editing",
      "qa_review",
    ]);
  });

  it("hides decision commands without the reviewer role and says why", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "awaiting_human_review",
        },
      }),
      requestId: null,
    });
    currentUserMock.mockResolvedValue({
      kind: "ok",
      data: {
        id: REVIEWER_USER_ID,
        username: "smoke-operator",
        display_name: "Smoke Operator",
        roles: ["operator"],
      },
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByText(/Değerlendirici rolü olmadan oturum açtınız/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Paketi onayla" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Değişiklik iste" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Paketi reddet" })).toBeNull();
  });

  it("shows the approval record, its validity, and revoke on APPROVED", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approved",
        },
      }),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage(
        [decisionView()],
        approvalStatus({
          approved: true,
          current: true,
          decision_id: decisionView().id,
          approved_content_hash: DECISION_CONTENT_HASH,
          active_content_hash: DECISION_CONTENT_HASH,
        }),
      ),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("Kayıtlı onay")).toBeTruthy();
    expect(screen.getByText("güncel")).toBeTruthy();
    expect(screen.getByText("Smoke Reviewer")).toBeTruthy();
    expect(screen.getAllByText("approved").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Onayı geri çek" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Paketi onayla" })).toBeNull();
  });

  it("renders a stale approval honestly when the hash no longer matches", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approved",
        },
      }),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage(
        [decisionView()],
        approvalStatus({
          approved: true,
          current: false,
          decision_id: decisionView().id,
          approved_content_hash: DECISION_CONTENT_HASH,
          active_content_hash: `sha256:${"e".repeat(64)}`,
        }),
      ),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("bayat")).toBeTruthy();
    expect(
      screen.getByText(/onaylanan içerik hash'iyle artık eşleşmiyor/),
    ).toBeTruthy();
  });

  it("shows the decision history including revocations", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });
    decisionsMock.mockResolvedValue({
      kind: "ok",
      data: decisionListPage([
        decisionView({
          id: "d1000000-0000-4000-8000-00000000000d",
          decision: "approval_revoked",
          reason: "kaynak güncellendi",
          revokes_decision_id: decisionView().id,
        }),
        decisionView(),
      ]),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("approval_revoked")).toBeTruthy();
    expect(screen.getByText("kaynak güncellendi")).toBeTruthy();
    expect(
      screen.getByText(new RegExp(`revokes=${decisionView().id}`)),
    ).toBeTruthy();
  });

  it("names the human actor in workflow history and keeps UNKNOWN honest", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    await renderPage();
    // Fixture: the operator event carries a resolved name; a hypothetical
    // pre-governance operator event without one must render UNKNOWN.
    expect(screen.getByText("operator · Smoke Reviewer")).toBeTruthy();

    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        workflow_events: workItemDetail().workflow_events.map((event) => ({
          ...event,
          actor_user_id: null,
          actor_display_name: null,
        })),
      }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByText("operator · BİLİNMİYOR")).toBeTruthy();
  });

  it("offers the media binding commands for an unsatisfied need", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText("Kapsam: 0 / 1 ihtiyaç karşılandı.")).toBeTruthy();
    expect(screen.getByText("Karşılanmadı")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yükle ve bağla" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Mevcut varlığı bağla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Görsel üret" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Bağlamayı kaldır" }),
    ).toBeNull();
  });

  it("shows the bound asset through the admin proxy and allows unbinding", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "qa_review",
        },
      }),
      requestId: null,
    });
    mediaMock.mockResolvedValue({
      kind: "ok",
      data: mediaCoveragePage({
        needs: [
          {
            need_index: 0,
            role: "kapak görseli",
            purpose: "Balon temasını görselleştirmek.",
            constraints: null,
            satisfaction: mediaSatisfaction(),
          },
        ],
      }),
      requestId: null,
    });

    const { container } = render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(screen.getByText("Kapsam: 1 / 1 ihtiyaç karşılandı.")).toBeTruthy();
    const image = screen.getByAltText(
      "Balon süslemeli parti masası",
    ) as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(
      `/editorial/media-assets/${mediaSatisfaction().asset.id}/content`,
    );
    expect(screen.getByText(/Bağlayan: Smoke Reviewer/)).toBeTruthy();
    expect(screen.getByText("Lisans: Konsepthane arşivi")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Bağlamayı kaldır" }),
    ).toBeTruthy();
    // The bytes come only from the admin's own proxy route.
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
  });

  it("freezes media commands under terminal review", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "awaiting_human_review",
        },
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByText(/Medya komutları/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Yükle ve bağla" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Görsel üret" })).toBeNull();
  });

  it("offers assembly and scheduling on APPROVED with the package pinned", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approved",
        },
      }),
      requestId: null,
    });
    publicationMock.mockResolvedValue({
      kind: "ok",
      data: publicationPage({
        packages: [publicationPackage()],
        latest_package_approval_current: true,
      }),
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByRole("button", { name: "Yayın paketini birleştir" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yayını zamanla" })).toBeTruthy();
    expect(
      screen.getByText(/vazgeçilen karşılanmamış ihtiyaçlar: 0/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Şimdi yayınla" })).toBeNull();
  });

  it("offers the governed dispatch on SCHEDULED and shows honest attempts", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "scheduled",
        },
      }),
      requestId: null,
    });
    publicationMock.mockResolvedValue({
      kind: "ok",
      data: publicationPage({
        packages: [
          publicationPackage({
            attempts: [
              publicationAttempt({
                status: "rejected_by_api",
                error_class: "publishing_api_rejected_422",
                remote_publication_ref: null,
              }),
            ],
          }),
        ],
        latest_package_approval_current: true,
      }),
      requestId: null,
    });

    await renderPage();
    expect(screen.getByRole("button", { name: "Şimdi yayınla" })).toBeTruthy();
    expect(screen.getByText("rejected_by_api")).toBeTruthy();
    expect(screen.getByText(/publishing_api_rejected_422/)).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Yayın paketini birleştir" }),
    ).toBeNull();
  });

  it("renders the derived expiry resolution on APPROVAL_EXPIRED", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail({
        work_item: {
          ...workItemDetail().work_item,
          current_state: "approval_expired",
        },
      }),
      requestId: null,
    });
    publicationMock.mockResolvedValue({
      kind: "ok",
      data: publicationPage({
        packages: [publicationPackage()],
        latest_package_approval_current: false,
      }),
      requestId: null,
    });

    await renderPage();
    expect(
      screen.getByRole("button", { name: "Süresi dolan onayı çöz" }),
    ).toBeTruthy();
    expect(screen.getByText(/artık güncel bir onayla eşleşmiyor/)).toBeTruthy();
    expect(screen.getByText(/Hedef TÜRETİLİR/)).toBeTruthy();
  });

  it("never renders the internal backend URL", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: workItemDetail(),
      requestId: null,
    });

    const { container } = render(
      await EditorialDetailPage({
        params: Promise.resolve({ id: WORK_ITEM_ID }),
        searchParams: Promise.resolve({}),
      }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
