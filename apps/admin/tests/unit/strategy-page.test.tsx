import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/strategy-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/strategy-api")>(
      "@/lib/strategy-api",
    );
  return { ...actual, fetchStrategyOverview: vi.fn() };
});

import StrategyPage from "@/app/strateji/page";
import { fetchStrategyOverview } from "@/lib/strategy-api";

const fetchMock = vi.mocked(fetchStrategyOverview);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Strategy page", () => {
  it("renders Turkish operator concepts and cluster context", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        audiences: [
          {
            id: "11111111-2222-4333-8444-555555555555",
            name: "Çocuklu anneler",
            priority: 100,
            status: "active",
            notes: null,
          },
        ],
        clusters: [
          {
            id: "21111111-2222-4333-8444-555555555555",
            name: "1 Yaş Doğum Günü",
            slug: "1-yas-dogum-gunu",
            priority: 95,
            status: "active",
            notes: null,
          },
        ],
        keywords: [
          {
            id: "31111111-2222-4333-8444-555555555555",
            phrase: "1 yaş doğum günü konseptleri",
            priority: 100,
            status: "active",
            topic_cluster_id: "21111111-2222-4333-8444-555555555555",
            notes: null,
          },
        ],
      },
    });

    render(await StrategyPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("heading", { name: "Strateji" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Hedef Kitleler" }),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Konu Kümeleri" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Keyword / Konu Hedefleri" }),
    ).toBeTruthy();
    expect(screen.getByText("Çocuklu anneler")).toBeTruthy();
    expect(screen.getAllByText("1 Yaş Doğum Günü").length).toBeGreaterThan(0);
    expect(screen.getByText("1 yaş doğum günü konseptleri")).toBeTruthy();
    expect(screen.getByText(/kelime tekrar talimatı vermez/)).toBeTruthy();
    expect(screen.getByText("1 hedef konu")).toBeTruthy();
  });

  it("renders a bounded failure state", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });

    render(await StrategyPage({ searchParams: Promise.resolve({}) }));

    expect(
      screen.getByText("Strateji verileri şu anda alınamıyor."),
    ).toBeTruthy();
  });
});
