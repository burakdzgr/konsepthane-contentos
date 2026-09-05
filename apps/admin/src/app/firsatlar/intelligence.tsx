import type {
  IntelligenceView,
  ProviderFreshnessView,
} from "@/lib/editorial-api";
import { STALE_LABEL, isStale, relativeAge } from "@/lib/freshness";
import { trLabel } from "@/lib/tr-labels";

// Opportunity Intelligence: the explainable Turkish sections an operator
// reads BEFORE deciding. Every value is a band or an honest "Bilinmiyor";
// nothing here is an opaque score, and an unknown is never rendered as 0.
// Shared by the /firsatlar card and the work-item detail "Fırsat ve skor".

export const RECOMMENDATION: Record<
  string,
  { label: string; tone: string; hint: string }
> = {
  produce: {
    label: "İÇERİK ÜRET",
    tone: "ok",
    hint: "Fikir seti, araştırma ve strateji eşleşmesi üretim kararı için yeterli.",
  },
  continue_research: {
    label: "ARAŞTIRMAYA DEVAM ET",
    tone: "warn",
    hint: "Konu umut veriyor; mevcut fikirler veya kanıtlar henüz yeterince güçlü değil.",
  },
  human_review: {
    label: "İNSAN İNCELEMESİ",
    tone: "warn",
    hint: "Sinyaller dengeli değil; editoryal değerlendirme gerekiyor.",
  },
  eliminate: {
    label: "ELE",
    tone: "bad",
    hint: "İlham ve temel uygunluk birlikte zayıf.",
  },
};

const FACTOR_LABELS: Record<string, string> = {
  novelty: "Özgünlük",
  usefulness: "Fayda",
  specificity: "Somutluk",
  visual_potential: "Görsel potansiyel",
  shareability: "Paylaşılabilirlik",
  emotional_impact: "Duygusal etki",
  audience_fit: "Hedef kitle uyumu",
  turkish_market_applicability: "Türkiye pazarına uygunluk",
  variation_potential: "Varyasyon potansiyeli",
  strategic_fit: "Stratejik uyum",
};

const EVIDENCE_LABELS: Record<string, string> = {
  sufficient: "Yeterli",
  insufficient: "Eksik",
};

const numberFormat = new Intl.NumberFormat("tr-TR");

// "2 gün önce", "2 gün önce (kayıtlı)", "Yapılandırılmadı", "API erişimi
// gerekli", ... — the provider state and observation time behind a band,
// never a fabricated timestamp. Data older than twice the provider's cache
// TTL is called "eski veri".
export function providerFreshness(
  entry: ProviderFreshnessView | undefined,
  now: Date,
  provider?: string,
): string {
  if (entry === undefined) {
    return "Bilinmiyor";
  }
  if (entry.state === "healthy" || entry.state === "stored") {
    if (entry.observed_at === null) {
      return entry.state === "stored" ? "Kayıtlı gözlem" : "Bağlı";
    }
    const age = relativeAge(entry.observed_at, now);
    const stale =
      provider !== undefined && isStale(entry.observed_at, provider, now)
        ? ` · ${STALE_LABEL}`
        : "";
    return entry.state === "stored"
      ? `${age} (kayıtlı)${stale}`
      : `${age}${stale}`;
  }
  return trLabel(entry.state);
}

function Fact({
  name,
  value,
  note,
  title,
}: {
  name: string;
  value: string;
  note?: string;
  title?: string;
}) {
  return (
    <div>
      <dt title={title}>{name}</dt>
      <dd>
        {value}
        {note !== undefined && <small>{note}</small>}
      </dd>
    </div>
  );
}

function count(value: number | null): string {
  return value === null ? "Bilinmiyor" : String(value);
}

export function OpportunityIntelligence({
  intelligence,
  now = new Date(),
  showVerdict = true,
}: {
  intelligence: IntelligenceView;
  now?: Date;
  showVerdict?: boolean;
}) {
  const content = intelligence.content_value;
  const search = intelligence.search_intelligence;
  const data = intelligence.konsepthane_data;
  const research = intelligence.research;
  const freshness = search.provider_freshness;
  const recommendation = RECOMMENDATION[intelligence.recommendation] ?? null;
  return (
    <div className="intel" data-engine-version={intelligence.engine_version}>
      <div className="intel-sections">
        <section className="intel-section" aria-label="İçerik Değeri">
          <h4>İçerik Değeri</h4>
          <dl className="agent-facts">
            <Fact
              name="İlham Değeri"
              value={trLabel(content.inspiration_band)}
              title="Bir fikrin ne kadar özgün, uygulanabilir ve paylaşılabilir olduğunu değerlendirir."
            />
            <Fact
              name="Kitle Uyumu"
              value={trLabel(content.audience_fit_band)}
            />
            <Fact
              name="Stratejik Uyum"
              value={trLabel(content.strategy_fit_band)}
              title="Bu içeriğin Konsepthane'nin büyümek istediği konu alanlarıyla ilişkisi."
            />
            <Fact
              name="Türkiye Pazar Sinyali"
              value={trLabel(content.market_band)}
            />
            <Fact
              name="Topluluk İhtiyacı"
              value={trLabel(content.community_need_band)}
              title="Forumlarda dile getirilen ihtiyaç; arama talebi değildir."
            />
          </dl>
        </section>
        <section className="intel-section" aria-label="Arama İstihbaratı">
          <h4>Arama İstihbaratı</h4>
          <dl className="agent-facts">
            <Fact
              name="Semrush Arama Potansiyeli"
              value={trLabel(search.semrush_potential_band)}
              note={providerFreshness(freshness.semrush, now, "semrush")}
            />
            <Fact
              name="Arama Hacmi"
              value={
                search.search_volume === null
                  ? "Bilinmiyor"
                  : numberFormat.format(search.search_volume)
              }
              note={search.search_keyword ?? undefined}
            />
            <Fact
              name="Anahtar Kelime Zorluğu"
              value={
                search.keyword_difficulty === null
                  ? "Bilinmiyor"
                  : numberFormat.format(Math.round(search.keyword_difficulty))
              }
            />
            <Fact
              name="Google Trends"
              value={trLabel(search.google_trends_direction)}
              note={providerFreshness(
                freshness.google_trends,
                now,
                "google_trends",
              )}
            />
            <Fact
              name="Pinterest Trend"
              value={trLabel(search.pinterest_trend_band)}
              note={providerFreshness(
                freshness.pinterest_trends,
                now,
                "pinterest_trends",
              )}
            />
            <Fact name="Rekabet" value={trLabel(search.competition_band)} />
          </dl>
        </section>
        <section className="intel-section" aria-label="Konsepthane Verisi">
          <h4>Konsepthane Verisi</h4>
          <dl className="agent-facts">
            <Fact
              name="Benzer içerik performansı"
              value={trLabel(data.similar_content_performance_band)}
            />
            <Fact
              name="Kanibalizasyon"
              value={trLabel(data.cannibalization_status)}
            />
            <Fact
              name="Geçmiş başarı"
              value={trLabel(data.historical_outcome)}
              title="Öncelik sinyalidir; hiçbir fikri tek başına elemez."
            />
          </dl>
        </section>
        <section className="intel-section" aria-label="Araştırma">
          <h4>Araştırma</h4>
          <dl className="agent-facts">
            <Fact
              name="Bağımsız kaynak"
              value={count(research.independent_sources)}
            />
            <Fact name="Sinyal türü" value={count(research.signal_families)} />
            <Fact
              name="Kanıt"
              value={EVIDENCE_LABELS[research.evidence_state] ?? "Bilinmiyor"}
            />
          </dl>
        </section>
      </div>
      {showVerdict && (
        <div className="intel-verdict">
          <strong>Sistem Önerisi</strong>
          {recommendation !== null ? (
            <span className="badge" data-tone={recommendation.tone}>
              {recommendation.label}
            </span>
          ) : (
            <span className="badge">
              {trLabel(intelligence.recommendation)}
            </span>
          )}
        </div>
      )}
      <p className="intel-why">
        <strong>Neden?</strong> {intelligence.why}
      </p>
      <details className="intel-detail">
        <summary>Ayrıntı</summary>
        <dl className="agent-facts">
          {intelligence.factor_bands.map((factor) => (
            <div key={factor.factor}>
              <dt>{FACTOR_LABELS[factor.factor] ?? trLabel(factor.factor)}</dt>
              <dd title={factor.basis}>{trLabel(factor.band)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
