import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/lib/bot-api", () => ({ fetchDailyPlan: vi.fn() }));
vi.mock("@/app/bot/actions", () => ({ saveBotAction: vi.fn() }));
vi.mock("@/app/bot/refresh", () => ({ BotRefresh: () => null }));
import Page from "@/app/bot/page";
import { fetchDailyPlan } from "@/lib/bot-api";
afterEach(cleanup);

it("does not fabricate a running bot on an unavailable backend", async () => {
  vi.mocked(fetchDailyPlan).mockResolvedValue({ kind: "unreachable" });
  render(await Page({}));
  expect(screen.getByRole("alert").textContent).toContain(
    "Botun durumu okunamadı",
  );
  expect(screen.queryByRole("button")).toBeNull();
});

it("renders the real target, selected source and human publication gate", async () => {
  vi.mocked(fetchDailyPlan).mockResolvedValue({
    kind: "ok",
    requestId: null,
    data: {
      target: 10,
      mode: "autonomous",
      day: "2026-09-06",
      timezone: "Europe/Istanbul",
      completed: 0,
      in_progress: 3,
      research: [],
      sources: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          name: "Kara's Party Ideas",
          selected: true,
          active: true,
        },
      ],
      items: [],
    },
  });
  render(await Page({}));
  expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("10");
  expect(
    (screen.getByRole("checkbox", { hidden: true }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByText(/Yayın onayı her zaman sizde/)).toBeTruthy();
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("0");
  expect(
    screen.getByRole("button", { name: "Kaydet ve botu çalıştır" }),
  ).toBeTruthy();
});
