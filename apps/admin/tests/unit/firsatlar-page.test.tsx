import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return { ...actual, fetchWorkQueue: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/lib/performance-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/performance-api")>(
    "@/lib/performance-api",
  );
  return {
    ...actual,
    fetchRefreshOpportunities: vi.fn(),
    fetchStrategySuggestions: vi.fn(),
  };
});

import OpportunityReviewPage from "@/app/firsatlar/page";
import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import {
  fetchRefreshOpportunities,
  fetchStrategySuggestions,
} from "@/lib/performance-api";
import { intelligenceView, queuePage, queueRow } from "./editorial-fixtures";

const queueMock = vi.mocked(fetchWorkQueue);
const refreshMock = vi.mocked(fetchRefreshOpportunities);
const suggestionMock = vi.mocked(fetchStrategySuggestions);

async function renderPage(query: Record<string, string> = {}) {
  render(await OpportunityReviewPage({ searchParams: Promise.resolve(query) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  refreshMock.mockResolvedValue({ kind: "ok", data: [], requestId: null });
  suggestionMock.mockResolvedValue({ kind: "ok", data: [], requestId: null });
});

describe("Opportunity review page", () => {
  it("lists the other genuine human decisions above the production inbox", async () => {
    const approval = queueRow({
      work_item_id: "e1111111-2222-4333-8444-555555555555",
      title_working_label: "Yayına hazır rehber",
      current_state: "awaiting_human_review",
      disposition: "commissioned",
    });
    queueMock.mockImplementation(async (filters) => ({
      kind: "ok",
      requestId: null,
      data: queuePage(
        filters?.workflowState === "awaiting_human_review"
          ? [approval]
          : ([] as WorkQueueRow[]),
      ),
    }));
    refreshMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: [
        {
          id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          published_content_id: "4f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          work_item_id: "5f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          title_working_label: "Düşen doğum günü rehberi",
          current_state: "published",
          status: "proposed",
          trigger_assessment_id: "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          window_days: 28,
          diagnosis: {},
          recommendation: "Yeni sinyallerle güncelle.",
          proposed_at: "2026-09-05T04:00:00+00:00",
          decided_at: null,
          decided_by_display_name: null,
          decision_reason: null,
        },
      ],
    });
    suggestionMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: [
        {
          id: "7f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          kind: "keyword_add",
          title: "'balon kemeri' anahtar kelimesini ekle",
          rationale: "Üç yayının 90 günlük verisi yükseliyor.",
          basis: {},
          status: "proposed",
          proposed_at: "2026-09-05T04:00:00+00:00",
          decided_at: null,
          decided_by_display_name: null,
          decision_reason: null,
        },
      ],
    });

    await renderPage();

    expect(queueMock).toHaveBeenCalledWith({
      workflowState: "awaiting_human_review",
      limit: 50,
    });
    expect(refreshMock).toHaveBeenCalledWith("proposed");
    expect(suggestionMock).toHaveBeenCalledWith("proposed");
    // Three groups, each with its count, above the inbox and in the tab row.
    expect(
      screen.getByRole("heading", { name: "Yayın onayı bekleyen (1)" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Güncelleme kararı bekleyen (1)" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Strateji önerileri (1)" }),
    ).toBeTruthy();
    const tabs = screen.getByRole("navigation", { name: "Fırsat grupları" });
    expect(
      within(tabs)
        .getByRole("link", { name: "Yayın onayı (1)" })
        .getAttribute("href"),
    ).toBe("/firsatlar#yayin-onayi");
    expect(
      within(tabs).getByRole("link", { name: "Güncelleme kararı (1)" }),
    ).toBeTruthy();
    expect(
      within(tabs).getByRole("link", { name: "Strateji önerisi (1)" }),
    ).toBeTruthy();
    // The approval links to the item; the other two decide in place and
    // come back to this inbox.
    expect(
      screen
        .getByRole("link", { name: "Yayına hazır rehber" })
        .getAttribute("href"),
    ).toBe("/editorial/e1111111-2222-4333-8444-555555555555");
    expect(screen.getByText(/İnsan onayı bekliyor/)).toBeTruthy();
    const approve = screen.getByRole("button", { name: "Güncellemeyi Onayla" });
    expect(
      (
        approve
          .closest("form")
          ?.querySelector('input[name="return_to"]') as HTMLInputElement
      ).value,
    ).toBe("/firsatlar");
    expect(
      screen.getByRole("button", { name: "Stratejiye Ekle" }),
    ).toBeTruthy();
    expect(screen.queryByText(/awaiting_human_review|proposed/)).toBeNull();
  });

  it("hides the other decision groups while they are empty", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([]),
      requestId: null,
    });

    await renderPage();

    expect(screen.queryByText(/Yayın onayı bekleyen/)).toBeNull();
    expect(screen.queryByText(/Güncelleme kararı bekleyen/)).toBeNull();
    expect(screen.queryByText(/Strateji önerileri/)).toBeNull();
  });

  it("asks the production question with the explainable score", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "produce",
          commission_eligible: true,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Benden Bekleyenler" }),
    ).toBeTruthy();
    expect(queueMock).toHaveBeenCalledWith({
      workflowState: "idea_scoring",
      opportunityDisposition: "open",
      limit: 50,
    });
    expect(screen.getByText("İÇERİK ÜRET")).toBeTruthy();
    expect(screen.getByText("Yüksek")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reddet" })).toBeTruthy();
    // Both decisions demand a written reason.
    expect(screen.getByPlaceholderText("üretim gerekçesi")).toBeTruthy();
    expect(screen.getByPlaceholderText("ret gerekçesi")).toBeTruthy();
  });

  it("never offers commissioning the backend gate would refuse", async () => {
    // Real-world inconsistency: an inspiration verdict next to a weak /
    // not_commissionable effective score used to render the approve button,
    // and the commission request came back 409. The card now mirrors the
    // domain gate (commission_eligible) and explains the refusal instead.
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "human_review",
          inspiration_band: "medium",
          score_band: "weak",
          score_eligibility: "not_commissionable",
          score_missing_signals: ["search_demand"],
          commission_eligible: false,
          commission_override_possible: true,
        }),
      ]),
      requestId: null,
    });

    await renderPage({ durum: "elenecek" });

    expect(screen.getByText("İNSAN İNCELEMESİ")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
    expect(screen.queryByPlaceholderText("üretim gerekçesi")).toBeNull();
    expect(screen.getByRole("note").textContent).toContain(
      "Üretim onayı kapalı: kaynak tabanı Zayıf / Görevlendirilemez",
    );
    expect(screen.getByRole("note").textContent).toContain("Arama talebi");
    expect(screen.getByRole("note").textContent).not.toContain("search_demand");
    // Rejection stays available: the reject command has no score gate.
    expect(screen.getByRole("button", { name: "Reddet" })).toBeTruthy();
    // ADR 0010: the named override is offered as an explicit, reasoned form.
    const override = screen.getByRole("button", {
      name: "Yine de içerik üret",
    });
    const form = override.closest("form")!;
    expect(
      (form.querySelector('input[name="override_gate"]') as HTMLInputElement)
        .value,
    ).toBe("true");
    expect(screen.getByText("GEREKÇEYLE ÜRETİLEBİLİR")).toBeTruthy();
  });

  it("never offers the override on an unscored card", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "human_review",
          score_id: null,
          score_band: null,
          score_eligibility: null,
          commission_eligible: false,
          commission_override_possible: false,
        }),
      ]),
      requestId: null,
    });

    await renderPage({ durum: "elenecek" });

    expect(
      screen.queryByRole("button", { name: "Yine de içerik üret" }),
    ).toBeNull();
    expect(screen.getByText("ONAY KAPALI")).toBeTruthy();
  });

  it("filters the inbox by the commissioning gate and offers bulk decisions", async () => {
    const eligible = queueRow({
      work_item_id: "c1111111-2222-4333-8444-555555555555",
      opportunity_id: "c2111111-2222-4333-8444-555555555555",
      title_working_label: "Onaylanabilir fırsat",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "produce",
      commission_eligible: true,
    });
    const blocked = queueRow({
      work_item_id: "c3111111-2222-4333-8444-555555555555",
      opportunity_id: "c4111111-2222-4333-8444-555555555555",
      title_working_label: "Kapalı fırsat",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "human_review",
      score_band: "weak",
      score_eligibility: "not_commissionable",
      commission_eligible: false,
    });
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([eligible, blocked]),
      requestId: null,
    });

    await renderPage({ durum: "elenecek" });

    // Group tabs reflect the URL and report honest counts.
    const current = screen.getByRole("link", { name: "Elenecekler (1)" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(
      screen.getByRole("link", { name: "Karar bekleyen (1)" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Tümü (2)" })).toBeTruthy();
    expect(screen.getByText("Kapalı fırsat")).toBeTruthy();
    expect(screen.queryByText("Onaylanabilir fırsat")).toBeNull();
    expect(screen.getByText("ONAY KAPALI")).toBeTruthy();
    // No English status vocabulary anywhere on the card.
    expect(
      screen.queryByText(/not_commissionable|human_review|weak/),
    ).toBeNull();
    expect(screen.getByText("Zayıf / Görevlendirilemez")).toBeTruthy();

    // Bulk form: per-card checkbox bound to the bulk form, the listed ids as
    // hidden scope, reject always available, approve disabled with no
    // eligible card in the listing.
    const checkbox = screen.getByRole("checkbox", {
      name: "Kapalı fırsat toplu işlem için seç",
    });
    expect(checkbox.getAttribute("form")).toBe("toplu-islem");
    const bulk = screen.getByRole("form", { name: "Toplu işlem" });
    expect(bulk.id).toBe("toplu-islem");
    expect(bulk.querySelectorAll('input[name="listelenen"]').length).toBe(1);
    expect(bulk.querySelectorAll('input[name="onaylanabilir"]').length).toBe(0);
    expect(
      screen.getByRole("button", { name: "Seçilenleri reddet" }),
    ).toBeTruthy();
    const approve = screen.getByRole("button", {
      name: "Seçilenleri onayla (0 uygun)",
    }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(
      screen.getByRole("radio", { name: /Listelenen 1 kartın tümü/ }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Toplu işlem gerekçesi")).toBeTruthy();
  });

  it("keeps weak source bases out of the default decision inbox", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "human_review",
          score_band: "weak",
          score_eligibility: "not_commissionable",
          commission_eligible: false,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    // Default group is "karar": nothing decidable, and the empty state says
    // where the weak card went instead of pretending the inbox is empty.
    expect(screen.queryByRole("button", { name: "Reddet" })).toBeNull();
    expect(
      screen.getByText(
        /1 açık fırsatın kaynak tabanı görevlendirilebilir değil/,
      ),
    ).toBeTruthy();
    const current = screen.getByRole("link", { name: "Karar bekleyen (0)" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Elenecekler (1)" })).toBeTruthy();
  });

  it("reports a bulk outcome truthfully from the redirect query", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([]),
      requestId: null,
    });

    await renderPage({
      toplu: "ret",
      basarili: "3",
      atlanan: "0",
      celisen: "1",
      hatali: "0",
    });

    expect(screen.getByRole("status").textContent).toContain(
      "3 fırsat reddedildi; 1 kart arka uçtaki güncel durumla çeliştiği için reddedildi",
    );
  });

  it("keeps machine continuation out of the human decision inbox", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "continue_research",
          inspiration_band: "low",
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByText(/sistem otomatik olarak araştırmayı sürdürüyor/),
    ).toBeTruthy();
    expect(screen.queryByText("ARAŞTIRMAYA DEVAM ET")).toBeNull();
    expect(
      screen.getByText(/şu anda sizden karar bekleyen bir iş yok/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
  });

  it("explains the opportunity in Turkish sections with honest unknowns", async () => {
    const base = intelligenceView();
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "human_review",
          commission_eligible: true,
          intelligence: intelligenceView({
            recommendation: "human_review",
            search_intelligence: {
              ...base.search_intelligence,
              semrush_potential_band: "high",
              search_keyword: "doğum günü partisi",
              search_volume: 1900,
              keyword_difficulty: 32,
              google_trends_direction: "rising",
              provider_freshness: {
                semrush: {
                  state: "healthy",
                  observed_at: twoDaysAgo,
                  error_class: null,
                  region: "tr",
                },
                google_trends: {
                  state: "stored",
                  observed_at: twoDaysAgo,
                  error_class: null,
                  region: "TR",
                },
                pinterest_trends: {
                  state: "rate_limited",
                  observed_at: null,
                  error_class: "pinterest_trends_daily_budget",
                  region: null,
                },
              },
            },
            konsepthane_data: {
              similar_content_performance_band: "medium",
              cannibalization_status: "not_checked",
              historical_outcome: "positive",
            },
            research: {
              independent_sources: 5,
              signal_families: 4,
              evidence_state: "insufficient",
            },
            why: "İlham değeri yüksek; arama fırsatı güçlü. Dayanaklar — Semrush: hacim 1.900, zorluk 32 (tr, 2 gün önce).",
          }),
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    // Four sections, each in Turkish, each value a band or an honest unknown.
    for (const name of [
      "İçerik Değeri",
      "Arama İstihbaratı",
      "Konsepthane Verisi",
      "Araştırma",
    ]) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
    const search = screen.getByRole("region", { name: "Arama İstihbaratı" });
    expect(search.textContent).toContain("Semrush Arama Potansiyeli");
    expect(search.textContent).toContain("2 gün önce");
    expect(search.textContent).toContain("2 gün önce (kayıtlı)");
    expect(search.textContent).toContain("1.900");
    expect(search.textContent).toContain("Yükseliyor");
    expect(search.textContent).toContain("Kota sınırında");
    expect(search.textContent).toContain("Rekabet");
    const content = screen.getByRole("region", { name: "İçerik Değeri" });
    expect(content.textContent).toContain("Topluluk İhtiyacı");
    expect(content.textContent).toContain("Çok yüksek");
    const data = screen.getByRole("region", { name: "Konsepthane Verisi" });
    expect(data.textContent).toContain("Kontrol edilmedi");
    expect(data.textContent).toContain("Olumlu");
    const research = screen.getByRole("region", { name: "Araştırma" });
    expect(research.textContent).toContain("5");
    expect(research.textContent).toContain("Eksik");
    // "Neden?" names the concrete bases; the factor detail is folded.
    expect(screen.getByText(/Semrush: hacim 1\.900, zorluk 32/)).toBeTruthy();
    expect(screen.getByText("Ayrıntı")).toBeTruthy();
    expect(screen.getByText("Türkiye pazarına uygunluk")).toBeTruthy();
    // Unknowns are words, never zeros; no English enum leaks.
    expect(screen.getAllByText("Bilinmiyor").length).toBeGreaterThan(0);
    expect(screen.queryByText("0")).toBeNull();
    expect(
      screen.queryByText(/very_high|rising|rate_limited|not_checked|positive/),
    ).toBeNull();
  });

  it("says so when the intelligence block is not computed yet", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          recommendation: "human_review",
          intelligence: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage({ durum: "hepsi" });

    expect(
      screen.getByText(/Fırsat istihbaratı henüz hesaplanmadı/),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Araştırma" })).toBeNull();
  });

  it("keeps unscored opportunities out with an honest note", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([
        queueRow({
          current_state: "idea_scoring",
          disposition: "open",
          inspiration_evaluation_id: null,
          recommendation: null,
        }),
      ]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByText(/1 fırsatı ContentOS değerlendiriyor/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "İçerik üretimini onayla" }),
    ).toBeNull();
  });
});
