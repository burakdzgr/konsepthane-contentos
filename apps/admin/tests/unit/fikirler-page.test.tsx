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

import IdeasPage from "@/app/fikirler/page";
import { ideaGroupOf } from "@/app/fikirler/groups";
import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { intelligenceView, queuePage, queueRow } from "./editorial-fixtures";

const queueMock = vi.mocked(fetchWorkQueue);

async function renderPage() {
  render(await IdeasPage());
}

function id(n: number): string {
  return `${String(n).padStart(8, "0")}-2222-4333-8444-555555555555`;
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Fikirler page", () => {
  it("groups everything the system found by its own verdict", async () => {
    const strong = queueRow({
      work_item_id: id(1),
      title_working_label: "Dönme dolapta evlilik teklifi",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "produce",
      commission_eligible: true,
      intelligence: intelligenceView({ recommendation: "produce" }),
    });
    const review = queueRow({
      work_item_id: id(2),
      title_working_label: "Balon kemeri fikirleri",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "human_review",
      inspiration_band: "medium",
      intelligence: intelligenceView({
        recommendation: "human_review",
        content_value: {
          ...intelligenceView().content_value,
          inspiration_band: "medium",
        },
      }),
    });
    const researching = queueRow({
      work_item_id: id(3),
      title_working_label: "Restoranda teklif",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "continue_research",
      inspiration_band: "low",
      intelligence: null,
    });
    const eliminated = queueRow({
      work_item_id: id(4),
      title_working_label: "Klişe kutlama",
      current_state: "idea_scoring",
      disposition: "open",
      recommendation: "eliminate",
      inspiration_band: "low",
      intelligence: intelligenceView({ recommendation: "eliminate" }),
    });
    const commissioned = queueRow({
      work_item_id: id(5),
      title_working_label: "Gökyüzü temalı parti",
      current_state: "evidence_building",
      disposition: "commissioned",
      recommendation: "produce",
      selected_idea_title: "Bulut şeklinde balonlarla tavan dekoru",
      selected_idea_originality: "passed",
      intelligence: intelligenceView({ recommendation: "produce" }),
    });
    queueMock.mockImplementation(async (filters) => {
      const byState: Record<string, WorkQueueRow[]> = {
        idea_scoring: [strong, review, researching, eliminated],
        evidence_building: [commissioned],
        seo_research: [],
        briefing: [],
      };
      return {
        kind: "ok",
        data: queuePage(byState[filters?.workflowState ?? ""] ?? []),
        requestId: null,
      };
    });

    await renderPage();

    expect(screen.getByRole("heading", { name: "Fikirler" })).toBeTruthy();
    for (const state of [
      "idea_scoring",
      "evidence_building",
      "seo_research",
      "briefing",
    ]) {
      expect(queueMock).toHaveBeenCalledWith({
        workflowState: state,
        limit: 50,
      });
    }
    // Tab row with honest counts.
    const tabs = screen.getByRole("navigation", { name: "Fikir grupları" });
    expect(
      within(tabs).getByRole("link", { name: "Güçlü fikirler (2)" }),
    ).toBeTruthy();
    expect(
      within(tabs).getByRole("link", { name: "İncelenmeli (1)" }),
    ).toBeTruthy();
    expect(
      within(tabs).getByRole("link", { name: "Araştırma sürüyor (1)" }),
    ).toBeTruthy();
    expect(
      within(tabs).getByRole("link", { name: "Elenenler (1)" }),
    ).toBeTruthy();
    // Cards land in their groups.
    const strongGroup = screen.getByRole("region", {
      name: "Güçlü fikirler (2)",
    });
    expect(
      within(strongGroup).getByText("Dönme dolapta evlilik teklifi"),
    ).toBeTruthy();
    expect(within(strongGroup).getByText("Gökyüzü temalı parti")).toBeTruthy();
    expect(within(strongGroup).getByText("ÜRETİMDE")).toBeTruthy();
    expect(
      within(strongGroup).getByText(/Bulut şeklinde balonlarla tavan dekoru/),
    ).toBeTruthy();
    expect(within(strongGroup).getByText("Kanıt toplama")).toBeTruthy();
    expect(
      within(strongGroup).getByRole("link", { name: "Üretim kararını ver →" }),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "İncelenmeli (1)" })).getByText(
        "Balon kemeri fikirleri",
      ),
    ).toBeTruthy();
    const researchGroup = screen.getByRole("region", {
      name: "Araştırma sürüyor (1)",
    });
    expect(within(researchGroup).getByText("Restoranda teklif")).toBeTruthy();
    expect(within(researchGroup).getByText(/henüz hesaplanmadı/)).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Elenenler (1)" })).getByText(
        "Klişe kutlama",
      ),
    ).toBeTruthy();
    // The Turkish intelligence sections and the reason are on the cards.
    expect(
      screen.getAllByRole("region", { name: "İçerik Değeri" }).length,
    ).toBe(4);
    expect(
      screen.getAllByRole("region", { name: "Arama İstihbaratı" }).length,
    ).toBe(4);
    expect(
      screen.getAllByRole("region", { name: "Konsepthane Verisi" }).length,
    ).toBe(4);
    expect(screen.getAllByRole("region", { name: "Araştırma" }).length).toBe(4);
    expect(screen.getAllByText("Sistem Önerisi").length).toBe(4);
    expect(screen.getAllByText(/Neden\?/).length).toBe(4);
    // No production decision forms here; no English vocabulary.
    expect(
      screen.queryByRole("button", { name: /onayla|reddet|üret/i }),
    ).toBeNull();
    expect(screen.queryByPlaceholderText(/gerekçe/)).toBeNull();
    expect(
      screen.queryByText(/idea_scoring|evidence_building|human_review/),
    ).toBeNull();
  });

  it("treats a high inspiration band as strong even without a produce verdict", () => {
    const row = queueRow({
      recommendation: "human_review",
      inspiration_band: "high",
      intelligence: intelligenceView({ recommendation: "human_review" }),
    });
    expect(ideaGroupOf(row)).toBe("guclu");
    expect(
      ideaGroupOf(
        queueRow({
          recommendation: null,
          inspiration_evaluation_id: null,
          intelligence: null,
        }),
      ),
    ).toBe("arastirma");
  });

  it("reports an unreachable backend and a partial read honestly", async () => {
    queueMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByRole("status").textContent).toContain("erişilemiyor");

    vi.resetAllMocks();
    queueMock.mockImplementation(async (filters) =>
      filters?.workflowState === "briefing"
        ? { kind: "unreachable" }
        : { kind: "ok", data: queuePage([]), requestId: null },
    );
    render(await IdeasPage());
    expect(screen.getByText(/liste eksik olabilir/)).toBeTruthy();
    expect(screen.getByText(/Henüz değerlendirilen fikir yok/)).toBeTruthy();
  });
});
