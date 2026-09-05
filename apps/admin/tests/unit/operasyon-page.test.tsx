import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/operations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/operations-api")>(
    "@/lib/operations-api",
  );
  return { ...actual, fetchLiveOperations: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return { ...actual, fetchIntakeRunDetail: vi.fn() };
});

vi.mock("@/lib/intelligence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intelligence-api")>(
    "@/lib/intelligence-api",
  );
  return { ...actual, fetchIntelligenceSummary: vi.fn() };
});

vi.mock("@/lib/integrations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/integrations-api")>(
    "@/lib/integrations-api",
  );
  return { ...actual, fetchIntegrations: vi.fn() };
});

import LiveOperationsPage from "@/app/operasyon/page";
import { fetchIntakeRunDetail } from "@/lib/intake-api";
import { fetchIntelligenceSummary } from "@/lib/intelligence-api";
import { fetchIntegrations } from "@/lib/integrations-api";
import { fetchLiveOperations, type LiveOperations } from "@/lib/operations-api";

const liveMock = vi.mocked(fetchLiveOperations);
const detailMock = vi.mocked(fetchIntakeRunDetail);
const signalsMock = vi.mocked(fetchIntelligenceSummary);
const integrationsMock = vi.mocked(fetchIntegrations);

const WORK_ITEM_ID = "d1111111-2222-4333-8444-555555555555";
const RUN_ID = "d2111111-2222-4333-8444-555555555555";
const SOURCE_ID = "d3111111-2222-4333-8444-555555555555";

function live(overrides: Partial<LiveOperations> = {}): LiveOperations {
  return {
    generated_at: "2026-09-05T00:00:00+00:00",
    autopilot: {
      mode: "supervised",
      actor_display_name: "Burak",
      reason: "ilk denetimli tur",
      updated_at: "2026-09-05T00:00:00+00:00",
    },
    intake_runs: [
      {
        id: RUN_ID,
        source_id: SOURCE_ID,
        source_slug: "kara",
        source_name: "Kara's Party Ideas",
        status: "running",
        discovered_new: 12,
        rediscovered: 3,
        prefilter_accepted: 9,
        prefilter_rejected: 6,
        fetch_dispatched: 8,
        fetched: 5,
        fetch_failed: 0,
        promotions_dispatched: 4,
        opportunities_created: 2,
        remaining_accepted: 1,
        remaining_discovered: 0,
        policy: {},
        failure_note: null,
        started_at: "2026-09-05T00:00:00+00:00",
        updated_at: "2026-09-05T00:00:00+00:00",
        finished_at: null,
        started_by_display_name: null,
        stopped_reason: null,
        paused_reason: null,
      } as unknown as LiveOperations["intake_runs"][number],
    ],
    items: [
      {
        work_item_id: WORK_ITEM_ID,
        title: "Paddington Bear Birthday Party",
        state: "evidence_building",
        entered_at: "2026-09-05T00:00:00+00:00",
        blocked_reason: null,
        autopilot: {
          kind: "waiting",
          action: "idea_selection",
          reason: "fikir seçimi operatörde",
          at: "2026-09-05T00:01:00+00:00",
        },
      },
    ],
    feed: [
      {
        at: "2026-09-05T00:01:00+00:00",
        source: "autopilot",
        work_item_id: WORK_ITEM_ID,
        title: "Paddington Bear Birthday Party",
        summary: "Bekliyor: fikir seçimi operatörde",
        tone: "warn",
      },
      {
        at: "2026-09-05T00:00:30+00:00",
        source: "ai",
        work_item_id: null,
        title: null,
        summary:
          "Yapay zeka: fikir adayları — succeeded (subcontractor/chatgpt)",
        tone: "ok",
      },
    ],
    gateway: {
      configured: true,
      reachable: true,
      status: "ok",
      provider: "subcontractor",
      base_url_host: "host.docker.internal",
      accounts: [
        {
          id: "acc_1",
          provider: "chatgpt",
          label: "ChatGPT #1",
          enabled: true,
          blocked_by: null,
          busy: true,
        },
      ],
      queued: 1,
      running: 1,
      ready_accounts: 1,
      jobs: [
        {
          job_id: "5004da4d-ef11-4702-b69f-cdab02f89db4",
          status: "running",
          phase: "ChatGPT yanıtlıyor",
          model: "chatgpt",
          job_type: "text",
          started_at: null,
        },
      ],
      error: null,
    },
    ...overrides,
  };
}

async function renderPage(query: Record<string, string> = {}) {
  render(await LiveOperationsPage({ searchParams: Promise.resolve(query) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  detailMock.mockResolvedValue({ kind: "unreachable" });
  signalsMock.mockResolvedValue({ kind: "unreachable" });
  integrationsMock.mockResolvedValue({ kind: "unreachable" });
});

describe("Canlı Operasyon page", () => {
  it("renders the full Turkish stage list under each live run from real reads", async () => {
    liveMock.mockResolvedValue({ kind: "ok", data: live(), requestId: null });

    await renderPage();

    expect(detailMock).toHaveBeenCalledWith(RUN_ID);
    expect(signalsMock).toHaveBeenCalledWith(RUN_ID);
    expect(integrationsMock).toHaveBeenCalledTimes(1);
    const list = screen.getByRole("list", {
      name: "Kara's Party Ideas aşamaları",
    });
    const labels = within(list)
      .getAllByRole("listitem")
      .map((row) => row.querySelector(".stage-label")?.textContent);
    expect(labels[0]).toBe("Kaynak taranıyor");
    expect(labels).toContain("Semrush");
    expect(labels).toContain("Pinterest Trends");
    expect(labels[labels.length - 1]).toBe("Fırsat");
    // Unreadable summary / providers are said so; nothing is faked.
    expect(within(list).getAllByText("sinyal özeti okunamadı").length).toBe(3);
    expect(within(list).getByText("2 fırsat oluştu")).toBeTruthy();
  });

  it("shows the autopilot mode, the gateway, the line and the feed in one place", async () => {
    liveMock.mockResolvedValue({ kind: "ok", data: live(), requestId: null });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Canlı Operasyon" }),
    ).toBeTruthy();
    // Mode card: current mode, accountable operator, the switch form.
    expect(screen.getAllByText("Denetimli").length).toBeGreaterThan(0);
    expect(screen.getByText("Burak")).toBeTruthy();
    const select = screen.getByRole("combobox", {
      name: "Otopilot modu",
    }) as HTMLSelectElement;
    expect(select.value).toBe("supervised");
    expect(screen.getByRole("button", { name: "Modu uygula" })).toBeTruthy();
    expect(screen.getByLabelText("Otopilot mod gerekçesi")).toBeTruthy();
    // Gateway card: reachable, account state, running job phase.
    expect(screen.getByText("Çalışıyor")).toBeTruthy();
    expect(screen.getByText("meşgul")).toBeTruthy();
    expect(screen.getByText(/ChatGPT yanıtlıyor/)).toBeTruthy();
    // Line: Turkish stage + the autopilot's last word.
    expect(screen.getByText("Kanıt toplama")).toBeTruthy();
    expect(screen.getByText("bekliyor — fikir seçimi operatörde")).toBeTruthy();
    // Intake run and feed.
    expect(screen.getByText("Kara's Party Ideas")).toBeTruthy();
    expect(screen.getByText(/fikir adayları — succeeded/)).toBeTruthy();
    // No English status vocabulary leaks from the line table.
    expect(screen.queryByText("evidence_building")).toBeNull();
  });

  it("names an unconfigured or unreachable gateway honestly", async () => {
    liveMock.mockResolvedValue({
      kind: "ok",
      data: live({
        gateway: {
          ...live().gateway,
          reachable: false,
          status: null,
          accounts: [],
          jobs: [],
          error: "ConnectError",
        },
        items: [],
        intake_runs: [],
        feed: [],
      }),
      requestId: null,
    });

    await renderPage({ notice: "mode-autonomous" });

    expect(screen.getByText(/Erişilemiyor \(ConnectError\)/)).toBeTruthy();
    expect(screen.getByText("Hatta iş öğesi yok.")).toBeTruthy();
    expect(screen.getByText(/otonom modda/)).toBeTruthy();
  });

  it("reports the backend being unreachable", async () => {
    liveMock.mockResolvedValue({ kind: "unreachable" });

    await renderPage();

    expect(screen.getByRole("status").textContent).toContain("erişilemiyor");
  });
});
