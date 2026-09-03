import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intake-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/intake-api")>(
      "@/lib/intake-api",
    );
  return { ...actual, fetchIntakeRunDetail: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  notFound: vi.fn(() => {
    throw new Error("NOT_FOUND");
  }),
}));

import RunDetailPage from "@/app/calisma/[id]/page";
import {
  fetchIntakeRunDetail,
  type IntakeRunDetail,
  type IntakeRunView,
} from "@/lib/intake-api";

const detailMock = vi.mocked(fetchIntakeRunDetail);

const RUN_ID = "1f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";
const AT = "2026-09-03T10:00:00+00:00";

function run(overrides: Partial<IntakeRunView> = {}): IntakeRunView {
  return {
    id: RUN_ID,
    source_id: "11111111-2222-4333-8444-555555555555",
    source_slug: "kara",
    source_name: "Kara's Party Ideas",
    status: "running",
    discovered_new: 4993,
    rediscovered: 12,
    prefilter_accepted: 4200,
    prefilter_rejected: 793,
    fetch_dispatched: 8,
    fetched: 5,
    fetch_failed: 1,
    promotions_dispatched: 3,
    opportunities_created: 2,
    remaining_accepted: 4192,
    remaining_discovered: 0,
    policy: { max_fetches_per_run: 40 },
    failure_note: null,
    created_at: AT,
    discovery_completed_at: AT,
    prefilter_completed_at: AT,
    finished_at: null,
    updated_at: AT,
    last_event_at: AT,
    ...overrides,
  };
}

function detail(overrides: Partial<IntakeRunDetail> = {}): IntakeRunDetail {
  return {
    generated_at: AT,
    run: run(),
    stages: [
      {
        key: "discovery",
        state: "done",
        counts: { new: 4993, rediscovered: 12 },
      },
      {
        key: "prefilter",
        state: "done",
        counts: { accepted: 4200, rejected: 793, remaining: 0 },
      },
      {
        key: "fetch",
        state: "active",
        counts: {
          dispatched: 8,
          fetched: 5,
          failed: 1,
          waiting_candidates: 4192,
        },
      },
      {
        key: "promote",
        state: "pending",
        counts: { dispatched: 3, opportunities: 2 },
      },
    ],
    events: [
      {
        id: 2,
        stage: "discovery",
        kind: "discovery_completed",
        detail: { entries_seen: 5005, admitted_new: 4993, rediscovered: 12 },
        occurred_at: AT,
      },
      {
        id: 1,
        stage: "run",
        kind: "run_started",
        detail: {},
        occurred_at: AT,
      },
    ],
    ...overrides,
  };
}

async function renderPage() {
  render(
    await RunDetailPage({
      params: Promise.resolve({ id: RUN_ID }),
      searchParams: Promise.resolve({}),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Run detail page", () => {
  it("shows the live run header, stages and real counters", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail(),
      requestId: null,
    });

    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Kara's Party Ideas" }),
    ).toBeTruthy();
    expect(screen.getByText("ÇALIŞIYOR")).toBeTruthy();
    expect(screen.getAllByText("Keşif").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/4993 yeni/).length).toBeGreaterThan(0);
    expect(screen.getByText(/4200 uygun/)).toBeTruthy();
    // The event feed renders Turkish descriptions of durable events.
    expect(
      screen.getByText(/Keşif tamamlandı: 5005 kayıt görüldü, 4993 yeni URL/),
    ).toBeTruthy();
    expect(screen.getByText("Çalışma başlatıldı")).toBeTruthy();
    // Live controls with mandatory reasons.
    expect(screen.getByRole("button", { name: "Duraklat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Güvenli durdur" })).toBeTruthy();
  });

  it("offers resume for a paused run and nothing for a finished one", async () => {
    detailMock.mockResolvedValue({
      kind: "ok",
      data: detail({ run: run({ status: "paused" }) }),
      requestId: null,
    });
    await renderPage();
    expect(screen.getByRole("button", { name: "Devam ettir" })).toBeTruthy();
  });

  it("reports an unreachable backend truthfully", async () => {
    detailMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByText(/şu anda erişilemiyor/)).toBeTruthy();
  });
});
