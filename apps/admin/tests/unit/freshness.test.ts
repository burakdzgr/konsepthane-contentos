import { describe, expect, it } from "vitest";

import {
  describeFreshness,
  freshnessLabel,
  isStale,
  relativeAge,
} from "@/lib/freshness";

const NOW = new Date("2026-09-05T12:00:00Z");

function hoursAgo(hours: number): string {
  return new Date(NOW.getTime() - hours * 3_600_000).toISOString();
}

describe("freshness vocabulary", () => {
  it("names the age in Turkish and never invents a timestamp", () => {
    expect(relativeAge(hoursAgo(1), NOW)).toBe("bugün");
    expect(relativeAge(hoursAgo(30), NOW)).toBe("dün");
    expect(relativeAge(hoursAgo(48), NOW)).toBe("2 gün önce");
    expect(relativeAge("not-a-date", NOW)).toBe("zaman bilinmiyor");
  });

  it("calls data older than twice the provider cache TTL stale", () => {
    // Semrush TTL 72h -> stale after 144h.
    expect(isStale(hoursAgo(100), "semrush", NOW)).toBe(false);
    expect(isStale(hoursAgo(150), "semrush", NOW)).toBe(true);
    // Google Trends TTL 24h -> stale after 48h.
    expect(isStale(hoursAgo(49), "google_trends", NOW)).toBe(true);
    // An explicit TTL from the integrations board wins.
    expect(isStale(hoursAgo(49), "google_trends", NOW, 72)).toBe(false);
    expect(isStale(null, "semrush", NOW)).toBe(false);
  });

  it("renders every provider state as an operator sentence", () => {
    expect(
      describeFreshness({
        provider: "semrush",
        state: "healthy",
        observedAt: hoursAgo(48),
        now: NOW,
      }),
    ).toBe("Semrush · 2 gün önce");
    expect(
      describeFreshness({
        provider: "google_search_console",
        state: "healthy",
        observedAt: "2026-09-05T04:00:00Z",
        now: NOW,
        mode: "date",
      }),
    ).toBe("Search Console · son veri 2026-09-05");
    // Search Console TTL 12h: two-day-old daily data is stale.
    expect(
      describeFreshness({
        provider: "google_search_console",
        state: "healthy",
        observedAt: "2026-09-03T04:00:00Z",
        now: NOW,
        mode: "date",
      }),
    ).toBe("Search Console · son veri 2026-09-03 · eski veri");
    expect(
      describeFreshness({
        provider: "google_trends",
        state: "access_required",
        observedAt: null,
        now: NOW,
      }),
    ).toBe("Google Trends · API erişimi gerekli");
    expect(
      freshnessLabel({
        provider: "pinterest_trends",
        state: "not_configured",
        observedAt: null,
        now: NOW,
      }),
    ).toBe("Yapılandırılmadı");
    expect(
      freshnessLabel({
        provider: "google_trends",
        state: "healthy",
        observedAt: hoursAgo(72),
        now: NOW,
      }),
    ).toBe("3 gün önce · eski veri");
    expect(
      freshnessLabel({
        provider: "semrush",
        state: "rate_limited",
        observedAt: null,
        now: NOW,
      }),
    ).toBe("Kota sınırında · veri yok");
    expect(
      freshnessLabel({
        provider: "semrush",
        state: "degraded",
        observedAt: hoursAgo(2),
        now: NOW,
      }),
    ).toBe("bugün · Kısıtlı");
    expect(
      freshnessLabel({
        provider: "semrush",
        state: "healthy",
        observedAt: null,
        now: NOW,
      }),
    ).toBe("henüz veri yok");
  });
});
