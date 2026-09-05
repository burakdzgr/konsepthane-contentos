import type { ReactNode } from "react";

import { formatUtcTimestamp } from "@/lib/format";
import { freshnessLabel, relativeAge } from "@/lib/freshness";
import {
  fetchIntegrations,
  fetchTrendDiscovery,
  PROVIDER_HINTS,
  PROVIDER_STATE_LABELS,
  PROVIDER_STATE_TONES,
  UNVERIFIED_LABEL,
  type IntegrationView,
  type TrendDiscovery,
  type TrendTerm,
} from "@/lib/integrations-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { trLabel } from "@/lib/tr-labels";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";
import { syncTrendDiscoveryAction, testIntegrationAction } from "./actions";

// Entegrasyonlar: one card per external intelligence provider with its
// honest state, last successful sync, last check, last error class, today's
// usage against the daily budget, and a single "Bağlantıyı Test Et"
// command. Google Trends is shown as ONE group with two separate
// capabilities — "Güncel Trend Keşfi" (BigQuery public dataset, usable
// today) and "Derin Keyword Trend Analizi" (Google Trends API alpha,
// access-gated) — so nobody reads "Google Trends is down" when only the
// alpha API is waiting. Secrets never reach this page — only the NAMES of
// the variables the operator has to set.
export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {
  "test-healthy": "Bağlantı doğrulandı: sağlayıcı yanıt verdi.",
  "test-not_configured":
    "Sağlayıcı yapılandırılmadı; gerekli ortam değişkenlerini tanımlayıp servisleri yeniden başlatın.",
  "test-access_required":
    "API erişimi reddedildi ya da eksik; anahtar/yetki ayarlarını kontrol edin.",
  "test-rate_limited":
    "Sağlayıcı kota sınırında; istekler geçici olarak durduruldu.",
  "test-degraded":
    "Sağlayıcı yanıt vermedi (zaman aşımı ya da sunucu hatası); daha sonra yeniden deneyin.",
  "test-error": "Sağlayıcı beklenmedik bir hata döndürdü.",
  "sync-queued":
    "Google Trend Keşfi senkronu kuyruğa alındı; sonuç birkaç dakika içinde bu ekranda görünür.",
};

function stateBadge(item: IntegrationView) {
  const unverified = item.configured && !item.verified;
  const tone = unverified ? "neutral" : PROVIDER_STATE_TONES[item.state];
  const label = unverified
    ? UNVERIFIED_LABEL
    : PROVIDER_STATE_LABELS[item.state];
  return (
    <span className="badge" data-tone={tone}>
      {label}
    </span>
  );
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatUtcTimestamp(iso);
}

function ProviderCard({
  item,
  now,
  eyebrow,
  span = "6",
  children,
}: {
  item: IntegrationView;
  now: Date;
  eyebrow?: string;
  span?: string;
  children?: ReactNode;
}) {
  const headingId = `integration-${item.name}`;
  return (
    <section className="ops-card" data-span={span} aria-labelledby={headingId}>
      {eyebrow !== undefined && <p className="eyebrow">{eyebrow}</p>}
      <h2 id={headingId}>{item.display_name}</h2>
      <p>
        {stateBadge(item)} <span className="muted">{item.purpose}</span>
      </p>
      <p className="muted">{item.detail}</p>
      <dl className="ops-facts">
        <div>
          <dt>Son başarılı senkron</dt>
          <dd>{when(item.last_success_at)}</dd>
        </div>
        <div>
          <dt>Son kontrol</dt>
          <dd>{when(item.checked_at)}</dd>
        </div>
        <div>
          <dt>Son hata</dt>
          <dd>
            {item.last_error_class !== null ? (
              <span className="mono" title="Teknik hata sınıfı">
                {item.last_error_class}
              </span>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt>Bugünkü istek / günlük bütçe</dt>
          <dd>
            {item.requests_today} / {item.daily_budget}
          </dd>
        </div>
        <div>
          <dt>Veri tazeliği</dt>
          <dd>
            {item.freshness === null
              ? "Bilinmiyor"
              : `${when(item.freshness)} · ${freshnessLabel({
                  provider: item.name,
                  state: item.state,
                  observedAt: item.freshness,
                  now,
                  cacheHours: item.cache_hours,
                })}`}
          </dd>
        </div>
        <div>
          <dt>Önbellek</dt>
          <dd>{item.cache_hours} saat</dd>
        </div>
      </dl>
      {children}
      <p className="muted">{PROVIDER_HINTS[item.name]}</p>
      <p className="muted">
        Gerekli:{" "}
        {item.required_env.map((name) => (
          <span key={name} className="mono">
            {name}{" "}
          </span>
        ))}
        {item.optional_env.length > 0 && (
          <>
            · İsteğe bağlı:{" "}
            {item.optional_env.map((name) => (
              <span key={name} className="mono">
                {name}{" "}
              </span>
            ))}
          </>
        )}
      </p>
      <form action={testIntegrationAction} className="control-form">
        <input type="hidden" name="provider" value={item.name} />
        <button
          type="submit"
          aria-label={`${item.display_name} bağlantısını test et`}
        >
          Bağlantıyı Test Et
        </button>
        <span className="muted">
          {item.configured
            ? "Tek bir ucuz gerçek çağrı yapar ve sonucu kaydeder."
            : "Yapılandırılmadan çağrı yapılmaz; durum olduğu gibi raporlanır."}
        </span>
      </form>
    </section>
  );
}

function termLine(term: TrendTerm): string {
  const parts = [term.trend_type === "rising" ? "yükselen" : "en çok aranan"];
  if (term.rank !== null) {
    parts.push(`sıra ${term.rank}`);
  }
  if (term.percent_gain !== null) {
    parts.push(`%${Math.round(term.percent_gain)} artış`);
  }
  if (term.match_kind !== null) {
    parts.push(trLabel(term.match_kind));
  }
  if (term.occurrence_count !== null && term.occurrence_count > 1) {
    parts.push(`${term.occurrence_count} gün gözlendi`);
  }
  return parts.join(" · ");
}

// What the daily sync found: last refresh date, counts and the terms that
// relate to Konsepthane. "Gözlenmedi" is never shown as "düşük".
function DiscoverySummary({
  discovery,
  now,
}: {
  discovery: TrendDiscovery | null;
  now: Date;
}) {
  return (
    <div className="detail-fold" data-kind="trend-discovery">
      <h3>Türkiye En Çok Aranan / Yükselen sorguları</h3>
      {discovery === null && (
        <p className="muted" role="status">
          Trend keşfi özeti şu anda okunamadı.
        </p>
      )}
      {discovery !== null && !discovery.synced && (
        <p className="muted">
          Henüz senkron yapılmadı. İlk günlük senkron Google&apos;ın yayınladığı
          Türkiye trend setlerini getirir; listede olmayan bir ifade &quot;düşük
          trend&quot; sayılmaz, yalnızca gözlenmemiş olur.
        </p>
      )}
      {discovery !== null && discovery.synced && (
        <>
          <dl className="ops-facts">
            <div>
              <dt>Son veri (refresh)</dt>
              <dd>{discovery.refresh_date ?? "Bilinmiyor"}</dd>
            </div>
            <div>
              <dt>Son senkronizasyon</dt>
              <dd>
                {discovery.last_sync_at === null
                  ? "Bilinmiyor"
                  : `${when(discovery.last_sync_at)} · ${relativeAge(discovery.last_sync_at, now)}`}
              </dd>
            </div>
            <div>
              <dt>Gözlenen sorgu</dt>
              <dd>
                {discovery.total_terms} ({discovery.top.length} en çok aranan,{" "}
                {discovery.rising.length} yükselen)
              </dd>
            </div>
            <div>
              <dt>Konsepthane ile ilişkili</dt>
              <dd>{discovery.matched_count}</dd>
            </div>
          </dl>
          {discovery.matched.length > 0 ? (
            <ul
              className="agent-list"
              aria-label="Konsepthane ile ilişkili trendler"
            >
              {discovery.matched.map((term) => (
                <li key={`${term.trend_type}-${term.term}`}>
                  <strong>{term.term}</strong>{" "}
                  <span className="muted">{termLine(term)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              Bu setlerde Konsepthane ile ilişkili bir sorgu gözlenmedi.
            </p>
          )}
        </>
      )}
      <form action={syncTrendDiscoveryAction} className="control-form">
        <button type="submit" aria-label="Google Trend Keşfi senkronunu başlat">
          Şimdi Senkronize Et
        </button>
        <span className="muted">
          Günlük senkron zaten planlı; bu düğme aynı sınırlı işi hemen kuyruğa
          alır (aynı gün için tekrar veri çekmez).
        </span>
      </form>
    </div>
  );
}

function GoogleTrendsGroup({
  discoveryProvider,
  apiProvider,
  discovery,
  now,
}: {
  discoveryProvider: IntegrationView;
  apiProvider: IntegrationView;
  discovery: TrendDiscovery | null;
  now: Date;
}) {
  return (
    <section
      className="ops-card"
      data-span="12"
      aria-labelledby="integration-google-trends-group"
    >
      <h2 id="integration-google-trends-group">Google Trends</h2>
      <p className="muted">
        İki ayrı yetenek, iki ayrı bağlantı: <strong>Güncel Trend Keşfi</strong>{" "}
        Google&apos;ın resmi BigQuery Public Dataset&apos;inden Türkiye&apos;nin
        günlük En Çok Aranan / Yükselen sorgu setlerini alır ve bugün
        kullanılabilir. <strong>Derin Keyword Trend Analizi</strong> seçilen bir
        ifadenin göreli ilgi eğilimini resmi Google Trends API (alfa) ile ölçer
        ve erişim verilene kadar bekler. İkisi aynı veri değildir ve birbirinin
        yerine geçmez.
      </p>
      <div className="ops-grid">
        <ProviderCard
          item={discoveryProvider}
          now={now}
          eyebrow="Güncel Trend Keşfi · Google BigQuery"
        >
          <DiscoverySummary discovery={discovery} now={now} />
        </ProviderCard>
        <ProviderCard
          item={apiProvider}
          now={now}
          eyebrow="Derin Keyword Trend Analizi · Google Trends API Alpha"
        />
      </div>
    </section>
  );
}

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchIntegrations();
  const now = new Date();
  const providers = result.kind === "ok" ? result.data.providers : [];
  const discoveryProvider =
    providers.find((item) => item.name === "google_trends_bigquery") ?? null;
  const apiProvider =
    providers.find((item) => item.name === "google_trends") ?? null;
  const grouped = discoveryProvider !== null && apiProvider !== null;
  let discovery: TrendDiscovery | null = null;
  if (discoveryProvider !== null) {
    const discoveryResult = await fetchTrendDiscovery();
    discovery = discoveryResult.kind === "ok" ? discoveryResult.data : null;
  }
  return (
    <section className="panel panel-wide" aria-labelledby="integrations-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Dış istihbarat sağlayıcıları</p>
          <h1 id="integrations-title">Entegrasyonlar</h1>
          <p className="muted">
            Semrush, Google Search Console, Google Analytics 4, Google Trends
            (güncel keşif + derin analiz) ve Pinterest Trends bağlantılarının
            dürüst durumu. Kimlik bilgileri yalnızca .env dosyasında tanımlanır;
            bu ekran hiçbir gizli değeri göstermez. Eksik veri her zaman
            &quot;Bilinmiyor&quot; kalır, asla 0 olarak yazılmaz.
          </p>
        </div>
        <AutoRefresh
          generatedAt={new Date().toISOString()}
          intervalMs={30000}
        />
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      {result.kind !== "ok" && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      {result.kind === "ok" && (
        <div className="ops-grid">
          {providers.map((item) => {
            if (grouped && item.name === "google_trends_bigquery") {
              return null;
            }
            if (grouped && item.name === "google_trends") {
              return (
                <GoogleTrendsGroup
                  key="google-trends-group"
                  discoveryProvider={discoveryProvider}
                  apiProvider={item}
                  discovery={discovery}
                  now={now}
                />
              );
            }
            if (item.name === "google_trends_bigquery") {
              return (
                <ProviderCard key={item.name} item={item} now={now}>
                  <DiscoverySummary discovery={discovery} now={now} />
                </ProviderCard>
              );
            }
            return <ProviderCard key={item.name} item={item} now={now} />;
          })}
        </div>
      )}
    </section>
  );
}
