import { trLabel } from "@/lib/tr-labels";

// One vocabulary for "how fresh is this provider's data" wherever the admin
// shows provider-backed values: "Semrush · 2 gün önce", "Search Console ·
// son veri 2026-09-03", "Google Trends · API erişimi gerekli". Data older
// than twice the provider's cache TTL is called out as "eski veri". Nothing
// here invents a timestamp: no observation means "henüz veri yok".

export const PROVIDER_SHORT_NAMES: Record<string, string> = {
  semrush: "Semrush",
  google_search_console: "Search Console",
  google_analytics: "GA4",
  google_trends: "Google Trends",
  pinterest_trends: "Pinterest Trends",
};

// Backend response-cache TTLs (hours) per provider; the stale threshold is
// twice this. Kept in sync with `contentos.integrations` defaults.
export const PROVIDER_CACHE_HOURS: Record<string, number> = {
  semrush: 72,
  google_search_console: 12,
  google_analytics: 12,
  google_trends: 24,
  pinterest_trends: 24,
};

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

export const NOT_CONFIGURED_LABEL = "Yapılandırılmadı";
export const ACCESS_REQUIRED_LABEL = "API erişimi gerekli";
export const STALE_LABEL = "eski veri";
export const NO_DATA_LABEL = "henüz veri yok";

export function providerShortName(provider: string): string {
  return PROVIDER_SHORT_NAMES[provider] ?? trLabel(provider);
}

// "bugün" / "dün" / "N gün önce"; an unparseable stamp is said so.
export function relativeAge(observedAt: string, now: Date): string {
  const observed = new Date(observedAt);
  if (Number.isNaN(observed.getTime())) {
    return "zaman bilinmiyor";
  }
  const days = Math.max(
    0,
    Math.floor((now.getTime() - observed.getTime()) / DAY_MS),
  );
  if (days === 0) {
    return "bugün";
  }
  if (days === 1) {
    return "dün";
  }
  return `${days} gün önce`;
}

export function isStale(
  observedAt: string | null,
  provider: string,
  now: Date,
  cacheHours?: number,
): boolean {
  if (observedAt === null) {
    return false;
  }
  const observed = new Date(observedAt);
  if (Number.isNaN(observed.getTime())) {
    return false;
  }
  const ttl = cacheHours ?? PROVIDER_CACHE_HOURS[provider] ?? 24;
  return now.getTime() - observed.getTime() > ttl * 2 * HOUR_MS;
}

export type FreshnessInput = {
  provider: string;
  // Provider state vocabulary: healthy | stored | not_configured |
  // access_required | rate_limited | degraded | error | not_requested ...
  state: string | null;
  observedAt: string | null;
  now: Date;
  cacheHours?: number;
  // "relative" -> "2 gün önce"; "date" -> "son veri 2026-09-03".
  mode?: "relative" | "date";
};

// The freshness phrase WITHOUT the provider name.
export function freshnessLabel(input: FreshnessInput): string {
  const { provider, state, observedAt, now } = input;
  if (state === "not_configured") {
    return NOT_CONFIGURED_LABEL;
  }
  if (state === "access_required") {
    return ACCESS_REQUIRED_LABEL;
  }
  const age =
    observedAt === null
      ? null
      : input.mode === "date"
        ? `son veri ${observedAt.slice(0, 10)}`
        : relativeAge(observedAt, now);
  const stale = isStale(observedAt, provider, now, input.cacheHours);
  if (state === "rate_limited") {
    return age === null
      ? "Kota sınırında · veri yok"
      : `${age} · kota sınırında`;
  }
  if (state === "degraded" || state === "error") {
    return age === null
      ? `${trLabel(state)} · veri yok`
      : `${age} · ${trLabel(state)}`;
  }
  if (age === null) {
    return NO_DATA_LABEL;
  }
  return stale ? `${age} · ${STALE_LABEL}` : age;
}

// "Semrush · 2 gün önce" — provider name plus the phrase.
export function describeFreshness(input: FreshnessInput): string {
  return `${providerShortName(input.provider)} · ${freshnessLabel(input)}`;
}
