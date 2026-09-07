import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/editorial-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/editorial-api")>(
    "@/lib/editorial-api",
  );
  return { ...actual, fetchWorkQueue: vi.fn() };
});

import Page from "@/app/yayina-hazir/page";
import { fetchWorkQueue } from "@/lib/editorial-api";
import { queuePage, queueRow, WORK_ITEM_ID } from "./editorial-fixtures";

const fetchMock = vi.mocked(fetchWorkQueue);

beforeEach(() => vi.resetAllMocks());

describe("Yayına Hazır", () => {
  it("shows only the actual human-review state with a direct decision link", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: queuePage([queueRow({ current_state: "awaiting_human_review" })]),
    });
    render(await Page({ searchParams: Promise.resolve({}) }));
    expect(fetchMock).toHaveBeenCalledWith({
      workflowState: "awaiting_human_review",
      limit: 50,
    });
    expect(
      screen.getByRole("heading", { name: "Yayına hazır içerikler" }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "İçeriği incele ve karar ver" })
        .getAttribute("href"),
    ).toBe(`/editorial/${WORK_ITEM_ID}`);
    expect(screen.getByText("Onay · Değişiklik iste · Reddet")).toBeTruthy();
  });

  it("has separate approved and scheduled tabs", async () => {
    fetchMock.mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: queuePage([]),
    });
    render(
      await Page({ searchParams: Promise.resolve({ gorunum: "sirada" }) }),
    );
    expect(fetchMock).toHaveBeenCalledWith({
      workflowState: "scheduled",
      limit: 50,
    });
    expect(
      screen
        .getByRole("link", { name: "Yayın sırası" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("fails honestly when the backend cannot be read", async () => {
    fetchMock.mockResolvedValue({ kind: "unreachable" });
    render(await Page({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("alert").textContent).toContain("okunamıyor");
  });
});
