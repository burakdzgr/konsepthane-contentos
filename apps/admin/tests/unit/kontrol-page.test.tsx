import { render, screen } from "@testing-library/react";
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

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return { ...actual, fetchIntakeRuns: vi.fn() };
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
import { fetchIntakeRuns } from "@/lib/intake-api";
import { queuePage, queueRow } from "./editorial-fixtures";

const summaryMock = vi.mocked(fetchDashboardSummary);
const agentsMock = vi.mocked(fetchDashboardAgents);
const activityMock = vi.mocked(fetchDashboardActivity);
const publicationsMock = vi.mocked(fetchDashboardPublications);
const queueMock = vi.mocked(fetchWorkQueue);
const runsMock = vi.mocked(fetchIntakeRuns);

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
});

describe("Kontrol Merkezi page", () => {
  it("renders real KPI values and the full pipeline", async () => {
    await renderPage();

    expect(
      screen.getByRole("heading", { name: "ContentOS Motoru" }),
    ).toBeTruthy();
    expect(screen.getByText("İçerik Üretim Kontrol Merkezi")).toBeTruthy();
    // KPI cards carry the summary's actual numbers.
    const drafting = screen.getByRole("link", { name: /3 Drafting/ });
    expect(drafting.getAttribute("href")).toBe("/editorial?state=drafting");
    expect(screen.getByRole("link", { name: /2 İnsan Onayı/ })).toBeTruthy();
    // The pipeline shows all eleven stages.
    for (const label of [
      "Research",
      "Opportunity",
      "Evidence",
      "Brief",
      "Writer",
      "Editor",
      "QA",
      "Human Review",
      "Package",
      "Schedule",
      "Publish",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("1 getirme hatası")).toBeTruthy();
  });

  it("shows the agent card with honest status and controls", async () => {
    await renderPage();

    expect(screen.getByText("Writer Ajanı")).toBeTruthy();
    expect(screen.getByText("AKTİF")).toBeTruthy();
    expect(screen.getByText("openai/gpt-5")).toBeTruthy();
    expect(screen.getByText("%75")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Yeni işi durdur" }),
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

    expect(screen.getByText("MOTOR DURDU")).toBeTruthy();
    expect(
      screen.getByText(/Motor durduruldu — hiçbir ajan yeni iş almaz/),
    ).toBeTruthy();
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

    expect(screen.getByText("Evde doğum günü partisi rehberi")).toBeTruthy();
    expect(screen.getAllByText("Brief hazırlama").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "İncele" })).toBeTruthy();
  });

  it("surfaces alerts from real counts only", async () => {
    summaryMock.mockResolvedValue({
      kind: "ok",
      data: summary({
        work_item_states: {
          ...summary().work_item_states,
          blocked: 2,
          awaiting_human_review: 0,
        },
      }),
      requestId: null,
    });

    await renderPage();

    const blocked = screen.getByRole("link", { name: /Bloke içerik 2/ });
    expect(blocked.getAttribute("href")).toBe("/editorial?state=blocked");
    expect(
      screen.queryByRole("link", { name: /İnsan onayı bekleyen/ }),
    ).toBeNull();
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
