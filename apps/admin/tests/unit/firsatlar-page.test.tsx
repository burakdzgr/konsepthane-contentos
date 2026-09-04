import { render, screen } from "@testing-library/react";
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

import OpportunityReviewPage from "@/app/firsatlar/page";
import { fetchWorkQueue } from "@/lib/editorial-api";
import { queuePage, queueRow } from "./editorial-fixtures";

const queueMock = vi.mocked(fetchWorkQueue);

async function renderPage(query: Record<string, string> = {}) {
  render(await OpportunityReviewPage({ searchParams: Promise.resolve(query) }));
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Opportunity review page", () => {
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
