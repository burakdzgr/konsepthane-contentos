import { formatUtcTimestamp } from "@/lib/format";
import { freshnessLabel } from "@/lib/freshness";
import {
  fetchIntegrations,
  PROVIDER_HINTS,
  PROVIDER_STATE_LABELS,
  PROVIDER_STATE_TONES,
  UNVERIFIED_LABEL,
  type IntegrationView,
} from "@/lib/integrations-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";
import { testIntegrationAction } from "./actions";

// Entegrasyonlar: one card per external intelligence provider with its
// honest state, last successful sync, last check, last error class, today's
// usage against the daily budget, and a single "Bağlantıyı Test Et"
// command. Secrets never reach this page — only the NAMES of the variables
// the operator has to set.
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

function ProviderCard({ item, now }: { item: IntegrationView; now: Date }) {
  const headingId = `integration-${item.name}`;
  return (
    <section className="ops-card" data-span="6" aria-labelledby={headingId}>
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

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchIntegrations();
  const now = new Date();
  return (
    <section className="panel panel-wide" aria-labelledby="integrations-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Dış istihbarat sağlayıcıları</p>
          <h1 id="integrations-title">Entegrasyonlar</h1>
          <p className="muted">
            Semrush, Google Search Console, Google Analytics 4, Google Trends ve
            Pinterest Trends bağlantılarının dürüst durumu. Kimlik bilgileri
            yalnızca .env dosyasında tanımlanır; bu ekran hiçbir gizli değeri
            göstermez. Eksik veri her zaman &quot;Bilinmiyor&quot; kalır, asla 0
            olarak yazılmaz.
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
          {result.data.providers.map((item) => (
            <ProviderCard key={item.name} item={item} now={now} />
          ))}
        </div>
      )}
    </section>
  );
}
