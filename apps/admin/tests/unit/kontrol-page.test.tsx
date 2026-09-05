import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/dashboard-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/dashboard-api")>(
    "@/lib/dashboard-api",
  );
  return {
    ...actual,
    fetchDashboardSummary: vi.fn(),
    fetchDashboardAgents: vi.fn(),
    fetchDashboardActivity: vi.fn(),
    fetchDashboardPublications: vi.fn(),
  };
});

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

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return {
    ...actual,
    fetchIntakeRuns: vi.fn(),
    fetchIntakeRunDetail: vi.fn(),
  };
});

import KontrolPage from "@/app/kontrol/page";
import {
  fetchDashboardActivity,
  fetchDashboardAgents,
  fetchDashboardPublications,
  fetchDashboardSummary,
  type AgentView,
  type AgentsPage,
  type DashboardSummary,
} from "@/lib/dashboard-api";
import { fetchWorkQueue, WORKFLOW_STATES } from "@/lib/editorial-api";
import {
  fetchIntakeRunDetail,
  fetchIntakeRuns,
  type IntakeRunView,
} from "@/lib/intake-api";
import {
  fetchRefreshOpportunities,
  fetchStrategySuggestions,
} from "@/lib/performance-api";
import { queuePage, queueRow } from "./editorial-fixtures";

const refreshMock = vi.mocked(fetchRefreshOpportunities);
const suggestionMock = vi.mocked(fetchStrategySuggestions);
const summaryMock = vi.mocked(fetchDashboardSummary);
const agentsMock = vi.mocked(fetchDashboardAgents);
const activityMock = vi.mocked(fetchDashboardActivity);
const publicationsMock = vi.mocked(fetchDashboardPublications);
const queueMock = vi.mocked(fetchWorkQueue);
const runsMock = vi.mocked(fetchIntakeRuns);
const runDetailMock = vi.mocked(fetchIntakeRunDetail);

const AT = "2026-09-03T10:00:00+00:00";

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  const states = Object.fromEntries(
    WORKFLOW_STATES.map((state) => [state, 0]),
  ) as Record<string, number>;
  return {
    generated_at: AT,
    work_item_states: { ...states, drafting: 3, awaiting_human_review: 2 },
    published_today: 1,
    active_intake_runs: 0,
    attention: {
      production_decisions: 0,
      awaiting_human_review: 2,
      approval_expired: 0,
      changes_requested: 0,
    },
    research: {
      active_sources: 2,
      discovery_states: {
        discovered: 4,
        accepted: 1,
        rejected: 0,
        fetched: 7,
        fetch_failed: 1,
      },
    },
    ai: {
      provider: "openai",
      text_provider_configured: true,
      image_provider_configured: true,
      attempts_today: 12,
      failures_today: 1,
      daily_budget: 500,
      remaining_budget: 488,
    },
    publishing: {
      packages_total: 5,
      attempts_today: { succeeded: 2, transport_error: 1 },
      last_attempt_status: "succeeded",
      last_attempt_error_class: null,
      last_attempt_at: AT,
    },
    media: { assets_total: 9, assets_today: 2, active_satisfactions: 4 },
    queue: { depth: null },
    pauses: [],
    ...overrides,
  };
}

function agent(overrides: Partial<AgentView> = {}): AgentView {
  return {
    key: "writer",
    kind: "ai",
    purposes: ["writer_draft"],
    is_paused: false,
    pause_reason: null,
    attempts_today: 4,
    failures_today: 1,
    last_attempt: {
      id: "aa111111-2222-4333-8444-555555555555",
      purpose: "writer_draft",
      status: "succeeded",
      error_class: null,
      provider: "openai",
      model_name: "gpt-5",
      retry_number: 0,
      created_at: AT,
    },
    recent_attempts: [],
    metrics: {},
    ...overrides,
  };
}

function agentsPage(overrides: Partial<AgentsPage> = {}): AgentsPage {
  return {
    generated_at: AT,
    engine_paused: false,
    engine_pause_reason: null,
    agents: [agent()],
    ...overrides,
  };
}

async function renderPage(params: Record<string, string> = {}) {
  render(await KontrolPage({ searchParams: Promise.resolve(params) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  summaryMock.mockResolvedValue({
    kind: "ok",
    data: summary(),
    requestId: null,
  });
  agentsMock.mockResolvedValue({
    kind: "ok",
    data: agentsPage(),
    requestId: null,
  });
  activityMock.mockResolvedValue({
    kind: "ok",
    data: { generated_at: AT, entries: [] },
    requestId: null,
  });
  publicationsMock.mockResolvedValue({
    kind: "ok",
    data: { generated_at: AT, rows: [] },
    requestId: null,
  });
  queueMock.mockResolvedValue({
    kind: "ok",
    data: queuePage([]),
    requestId: null,
  });
  runsMock.mockResolvedValue({
    kind: "ok",
    data: { generated_at: AT, runs: [] },
    requestId: null,
  });
  runDetailMock.mockResolvedValue({ kind: "unreachable" });
  refreshMock.mockResolvedValue({ kind: "ok", data: [], requestId: null });
  suggestionMock.mockResolvedValue({ kind: "ok", data: [], requestId: null });
});

describe("Kontrol Merkezi page", () => {
  it("focuses the latest live run and uses its durable progress", async () => {
    const liveRun: IntakeRunView = {
      id: "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
      source_id: "11111111-2222-4333-8444-555555555555",
      source_slug: "kara",
      source_name: "Kara's Party Ideas",
      status: "running",
      discovered_new: 4993,
      rediscovered: 0,
      prefilter_accepted: 4201,
      prefilter_rejected: 792,
      fetch_dispatched: 50,
      fetched: 18,
      fetch_failed: 0,
      promotions_dispatched: 11,
      opportunities_created: 11,
      remaining_accepted: 4151,
      remaining_discovered: 0,
      policy: {},
      failure_note: null,
      created_at: AT,
      discovery_completed_at: AT,
      prefilter_completed_at: AT,
      finished_at: null,
      updated_at: AT,
      last_event_at: AT,
    };
    runsMock.mockResolvedValue({
      kind: "ok",
      data: { generated_at: AT, runs: [liveRun] },
      requestId: null,
    });
    runDetailMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        generated_at: AT,
        run: liveRun,
        chain: {
          normalized_succeeded: 18,
          normalized_failed: 0,
          duplicates_evaluated: 11,
          last_processed_title: "Frozen Birthday Party",
          last_processed_url:
            "https://karaspartyideas.com/frozen-birthday-party",
        },
        stages: [
          { key: "discovery", state: "done", counts: { new: 4993 } },
          { key: "prefilter", state: "done", counts: { accepted: 4201 } },
          { key: "fetch", state: "active", counts: { fetched: 18 } },
          { key: "normalize", state: "active", counts: { succeeded: 18 } },
          { key: "duplicate", state: "active", counts: { evaluated: 11 } },
          { key: "promote", state: "done", counts: { opportunities: 11 } },
        ],
        events: [
          {
            id: 1,
            stage: "discovery",
            kind: "discovery_completed",
            detail: { entries_seen: 4993 },
            occurred_at: AT,
          },
        ],
      },
    });

    await renderPage();

    expect(
      screen.getByRole("heading", {
        name: "Kara's Party Ideas — Araştırma Çalışması #1f1e",
      }),
    ).toBeTruthy();
    expect(screen.getByText("ÇALIŞIYOR")).toBeTruthy();
    expect(screen.getAllByText("4.993").length).toBeGreaterThan(0);
    expect(screen.getByText("Frozen Birthday Party")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Duraklat/ })).toBeTruthy();
    expect(runDetailMock).toHaveBeenCalledWith(liveRun.id);
  });

  it("renders real KPI values and the compact operations pipeline", async () => {
    await renderPage();

    expect(
      screen.getByRole("heading", { name: "ContentOS Motoru" }),
    ).toBeTruthy();
    expect(screen.getByText("İçerik Üretim Kontrol Merkezi")).toBeTruthy();
    expect(screen.getByText("Çalışma İstatistikleri")).toBeTruthy();
    expect(screen.getByText("Keşfedilen URL")).toBeTruthy();
    expect(screen.getByText("Getirilen Sayfa")).toBeTruthy();
    // The control center groups the durable workflow into nine Turkish
    // stages; no technical stage vocabulary (fetch, normalize) leaks.
    for (const label of [
      "Keşif",
      "Ön Eleme",
      "Getirme",
      "Anlama",
      "Gruplama",
      "Fırsat",
      "Kanıt",
      "SEO / Niyet",
      "Editoryal",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.queryByText(/Fetch|Normalize/)).toBeNull();
    expect(screen.getAllByText("1 hata").length).toBeGreaterThan(0);
  });

  it("shows the agent card with honest status and controls", async () => {
    await renderPage();

    expect(screen.getByText("Yazar ajanı")).toBeTruthy();
    expect(screen.getByText("AKTİF")).toBeTruthy();
    expect(screen.queryByText(/RUNNING|IDLE|PAUSED|ERROR/)).toBeNull();
    expect(screen.getByText("openai/gpt-5")).toBeTruthy();
    expect(screen.getByText(/%75/)).toBeTruthy();
    expect(
      screen.getByText(/Yeni İş Alımını Durdur/, { selector: "summary" }),
    ).toBeTruthy();
  });

  it("shows paused agents and the paused engine truthfully", async () => {
    agentsMock.mockResolvedValue({
      kind: "ok",
      data: agentsPage({
        engine_paused: true,
        engine_pause_reason: "acil bakım",
        agents: [agent({ is_paused: true, pause_reason: "model rotasyonu" })],
      }),
      requestId: null,
    });

    await renderPage();

    expect(screen.getByText("DURDURULDU")).toBeTruthy();
    expect(screen.getByText(/Motor durduruldu: acil bakım/)).toBeTruthy();
    expect(screen.getByText(/acil bakım/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "▶ Motoru Başlat" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Acil Durdurma/ })).toBeNull();
  });

  it("offers the emergency stop with a mandatory reason when running", async () => {
    await renderPage();

    const stop = screen.getByRole("button", { name: /Acil Durdurma/ });
    expect(stop).toBeTruthy();
    expect(
      screen.getByLabelText("Acil durdurma gerekçesi").hasAttribute("required"),
    ).toBe(true);
    expect(screen.getByText(/yalnızca YENİ iş alımını keser/)).toBeTruthy();
  });

  it("lists live work items with Turkish state labels and wait times", async () => {
    queueMock.mockResolvedValue({
      kind: "ok",
      data: queuePage([queueRow()]),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getAllByText("Evde doğum günü partisi rehberi").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Brief hazırlama").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "İncele" })).toBeTruthy();
  });

  it("lists only the four genuine human decisions with real counts", async () => {
    summaryMock.mockResolvedValue({
      kind: "ok",
      data: summary({
        work_item_states: {
          ...summary().work_item_states,
          blocked: 2,
          awaiting_human_review: 0,
        },
        attention: {
          production_decisions: 4,
          awaiting_human_review: 0,
          approval_expired: 1,
          changes_requested: 0,
          refresh_decisions: 3,
          strategy_suggestions: 1,
        },
      }),
      requestId: null,
    });

    await renderPage();

    const panel = screen.getByRole("region", { name: "Benden bekleyenler" });
    const links = within(panel).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-label"))).toEqual([
      "Üretim kararı 4",
      "Yayın onayı 0",
      "Güncelleme kararı 3",
      "Strateji önerisi 1",
    ]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/firsatlar",
      "/firsatlar#yayin-onayi",
      "/firsatlar#guncelleme",
      "/firsatlar#strateji",
    ]);
    // Counts came with the summary: no extra performance reads.
    expect(refreshMock).not.toHaveBeenCalled();
    expect(suggestionMock).not.toHaveBeenCalled();
    // Blocked content is a health fact, not a decision.
    expect(within(panel).queryByText(/Bloke|Engellenen/)).toBeNull();
    const blocked = screen.getByRole("link", { name: "2 içerik" });
    expect(blocked.getAttribute("href")).toBe("/editorial?state=blocked");
  });

  it("falls back to the performance lists when the summary lacks the counts", async () => {
    refreshMock.mockResolvedValue({
      kind: "ok",
      data: [
        {
          id: "3f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          published_content_id: "4f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          work_item_id: "5f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          title_working_label: "Düşen içerik",
          current_state: "published",
          status: "proposed",
          trigger_assessment_id: "6f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
          window_days: 28,
          diagnosis: {},
          recommendation: "Güncelle",
          proposed_at: AT,
          decided_at: null,
          decided_by_display_name: null,
          decision_reason: null,
        },
      ],
      requestId: null,
    });
    suggestionMock.mockResolvedValue({ kind: "unreachable" });

    await renderPage();

    expect(
      screen.getByRole("link", { name: "Güncelleme kararı 1" }),
    ).toBeTruthy();
    // An unreadable count is said so, never shown as zero.
    expect(
      screen.getByRole("link", { name: "Strateji önerisi okunamadı" })
        .textContent,
    ).toContain("sayı şu anda okunamıyor");
  });

  it("renders honest empty and unavailable states", async () => {
    summaryMock.mockResolvedValue({ kind: "unreachable" });
    agentsMock.mockResolvedValue({ kind: "unreachable" });
    activityMock.mockResolvedValue({ kind: "unreachable" });
    publicationsMock.mockResolvedValue({ kind: "unreachable" });
    queueMock.mockResolvedValue({ kind: "unreachable" });

    await renderPage();

    expect(screen.getByText(/kontrol merkezi verisi yok/)).toBeTruthy();
  });

  it("reports the unmeasurable queue depth as such, never as zero", async () => {
    await renderPage();
    expect(screen.getByText("ölçülemedi")).toBeTruthy();
  });
});
