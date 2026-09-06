import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("@/lib/operations-api", () => ({
  fetchAutopilotState: vi.fn(),
  AUTOPILOT_MODE_LABELS: {
    off: "Kapalı",
    supervised: "Denetimli",
    autonomous: "Otonom",
  },
}));
import Page from "@/app/baslangic/page";
import { fetchAutopilotState } from "@/lib/operations-api";
afterEach(cleanup);
describe("operator starting guide", () => {
  it("does not claim production is running when the API is unavailable", async () => {
    vi.mocked(fetchAutopilotState).mockResolvedValue({ kind: "unreachable" });
    render(await Page());
    expect(
      screen.getByText(/Üretimin çalıştığını doğrulayamıyoruz/),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: /Otomasyon ayarları/ })
        .getAttribute("href"),
    ).toBe("/operasyon");
  });
  it("explains why discovery alone cannot start an off autopilot", async () => {
    vi.mocked(fetchAutopilotState).mockResolvedValue({
      kind: "ok",
      requestId: null,
      data: {
        mode: "off",
        actor_user_id: null,
        actor_display_name: null,
        reason: null,
        updated_at: null,
        events: [],
      },
    });
    render(await Page());
    expect(
      screen.getByText(/Kaynak keşfi başlatmak tek başına yazarı çalıştırmaz/),
    ).toBeTruthy();
  });
});
