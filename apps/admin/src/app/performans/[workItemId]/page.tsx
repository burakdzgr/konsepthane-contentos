import Link from "next/link";

import { formatUtcTimestamp } from "@/lib/format";
import {
  assessmentTone,
  fetchContentPerformance,
  metricNumber,
  numberOrUnknown,
  pctOrUnknown,
  positionOrUnknown,
  ratioOrUnknown,
  type AssessmentView,
  type SeriesPoint,
} from "@/lib/performance-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { trLabel } from "@/lib/tr-labels";
import { ControlNotice } from "../../notices";
import { Empty, RefreshCard } from "../cards";
import { Sparkline } from "../sparkline";

export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {
  "refresh-approved":
    "Güncelleme onaylandı; içerik yeniden araştırma rotasına alındı. Yayın kararı ayrıca verilir.",
  "refresh-dismissed": "Güncelleme fırsatı şimdilik geçildi.",
};

function series(points: SeriesPoint[], key: string): (number | null)[] {
  return points.map((point) => metricNumber(point.metrics, key));
}

function last(points: SeriesPoint[]): SeriesPoint | null {
  return points.length > 0 ? (points[points.length - 1] ?? null) : null;
}

function AssessmentBadges({ rows }: { rows: AssessmentView[] }) {
  if (rows.length === 0) {
    return <Empty>Henüz değerlendirme yok: Bilinmiyor.</Empty>;
  }
  return (
    <ul className="performance-assessments">
      {rows.map((row) => (
        <li key={row.id}>
          <strong>{row.window_days} gün</strong>{" "}
          <span className="badge" data-tone={assessmentTone(row.status)}>
            {trLabel(row.status)}
          </span>{" "}
          <small>{formatUtcTimestamp(row.assessed_at)}</small>
        </li>
      ))}
      <li>
        <details className="detail-fold">
          <summary>Gelişmiş</summary>
          <ul className="plain-list">
            {rows.map((row) => (
              <li key={row.id}>
                {row.window_days} gün ·{" "}
                <span className="mono">
                  {row.engine_name}/{row.engine_version}
                </span>
              </li>
            ))}
          </ul>
        </details>
      </li>
    </ul>
  );
}

function Metric({
  label,
  value,
  chart,
}: {
  label: string;
  value: string;
  chart: React.ReactNode;
}) {
  return (
    <div className="performance-metric">
      <span className="performance-metric-label">{label}</span>
      <strong>{value}</strong>
      {chart}
    </div>
  );
}

export default async function ContentPerformancePage({
  params,
  searchParams,
}: {
  params: Promise<{ workItemId: string }>;
  searchParams?: Promise<RawSearchParams>;
}) {
  const { workItemId } = await params;
  const query = searchParams ? await searchParams : {};
  const result = await fetchContentPerformance(workItemId);
  if (result.kind === "not_found") {
    return (
      <main className="strategy-page performance-page">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Performans</p>
            <h1>Yayın bulunamadı</h1>
            <p>
              Bu içerik için ölçüm kaydı yok. Yayınlanmamış olabilir ya da
              &quot;Şimdi senkronize et&quot; henüz çalışmadı.
            </p>
          </div>
        </header>
        <Link href="/performans">← Performans</Link>
      </main>
    );
  }
  if (result.kind !== "ok") {
    return (
      <main className="strategy-page performance-page">
        <header className="page-heading">
          <div>
            <h1>Performans</h1>
          </div>
        </header>
        <Empty>Performans verileri şu anda alınamıyor.</Empty>
      </main>
    );
  }
  const detail = result.data;
  const content = detail.content;
  const daily = detail.search_console_daily;
  const summary = last(detail.search_console_summary);
  const analytics = detail.analytics.filter(
    (point) => point.period_start === point.period_end,
  );
  const analyticsSummary = last(
    detail.analytics.filter((point) => point.period_start !== point.period_end),
  );
  const trends = last(detail.google_trends);
  const pinterest = last(detail.pinterest_trends);
  const semrush = last(detail.semrush);
  const history = detail.historical_signal;
  const returnTo = `/performans/${content.work_item_id}`;
  return (
    <main
      className="strategy-page performance-page"
      aria-labelledby="icerik-performans"
    >
      <header className="page-heading">
        <div>
          <p className="eyebrow">
            <Link href="/performans">Performans</Link> ·{" "}
            <Link href={`/editorial/${content.work_item_id}`}>İçerik</Link>
          </p>
          <h1 id="icerik-performans">{content.title_working_label}</h1>
          <p>
            {trLabel(content.current_state)} · yayın{" "}
            {formatUtcTimestamp(content.published_at)} · {content.age_days} gün
            ·{" "}
            {content.canonical_url_missing ? (
              <span className="muted">Yayın adresi bilinmiyor</span>
            ) : (
              <a href={content.canonical_url ?? "#"} rel="noreferrer">
                {content.canonical_url}
              </a>
            )}
          </p>
          <p>
            Küme: {content.cluster_name ?? "Bilinmiyor"} · Kitle:{" "}
            {content.audience_name ?? "Bilinmiyor"} · Tema:{" "}
            {content.theme_key ?? "Bilinmiyor"} · Format:{" "}
            {content.content_format
              ? trLabel(content.content_format)
              : "Bilinmiyor"}
          </p>
        </div>
      </header>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      <section className="console-card" aria-labelledby="degerlendirme">
        <div className="console-card-heading">
          <div>
            <h2 id="degerlendirme">Değerlendirme</h2>
            <p>Pencere başına en güncel sınıflandırma ve motor kimliği.</p>
          </div>
        </div>
        <AssessmentBadges rows={detail.assessments} />
        <p className="muted">
          Geçmiş sinyali (yalnızca öncelik, asla filtre):{" "}
          {trLabel(typeof history.band === "string" ? history.band : "unknown")}
          {typeof history.outcome === "string"
            ? ` · ${trLabel(history.outcome)}`
            : ""}
        </p>
      </section>
      <section className="console-card" aria-labelledby="google">
        <div className="console-card-heading">
          <div>
            <h2 id="google">Google</h2>
            <p>Search Console günlük gözlemleri; toplamlar son 28 gün.</p>
          </div>
        </div>
        {daily.length === 0 ? (
          <Empty>Search Console verisi yok: Bilinmiyor.</Empty>
        ) : (
          <div className="performance-metrics">
            <Metric
              label="Gösterim"
              value={numberOrUnknown(
                summary ? metricNumber(summary.metrics, "impressions") : null,
              )}
              chart={
                <Sparkline
                  values={series(daily, "impressions")}
                  label="Gösterim"
                />
              }
            />
            <Metric
              label="Tıklama"
              value={numberOrUnknown(
                summary ? metricNumber(summary.metrics, "clicks") : null,
              )}
              chart={
                <Sparkline values={series(daily, "clicks")} label="Tıklama" />
              }
            />
            <Metric
              label="CTR"
              value={ratioOrUnknown(
                summary ? metricNumber(summary.metrics, "ctr") : null,
              )}
              chart={<Sparkline values={series(daily, "ctr")} label="CTR" />}
            />
            <Metric
              label="Pozisyon"
              value={positionOrUnknown(
                summary ? metricNumber(summary.metrics, "position") : null,
              )}
              chart={
                <Sparkline
                  values={series(daily, "position")}
                  label="Pozisyon"
                  lowerIsBetter
                />
              }
            />
          </div>
        )}
        <h3>En çok sorgular</h3>
        {detail.top_queries.length === 0 ? (
          <Empty>Sorgu verisi yok.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sorgu</th>
                  <th>Tıklama</th>
                  <th>Gösterim</th>
                  <th>Pozisyon</th>
                </tr>
              </thead>
              <tbody>
                {detail.top_queries.map((entry, index) => (
                  <tr key={`${String(entry.query)}-${index}`}>
                    <td>{String(entry.query ?? "")}</td>
                    <td>{numberOrUnknown(metricNumber(entry, "clicks"))}</td>
                    <td>
                      {numberOrUnknown(metricNumber(entry, "impressions"))}
                    </td>
                    <td>
                      {positionOrUnknown(metricNumber(entry, "position"))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="console-card" aria-labelledby="site-davranisi">
        <div className="console-card-heading">
          <div>
            <h2 id="site-davranisi">Site Davranışı</h2>
            <p>GA4 günlük gözlemleri; toplamlar son 28 gün.</p>
          </div>
        </div>
        {analytics.length === 0 ? (
          <Empty>GA4 verisi yok: Bilinmiyor.</Empty>
        ) : (
          <div className="performance-metrics">
            <Metric
              label="Kullanıcı"
              value={numberOrUnknown(
                analyticsSummary
                  ? metricNumber(analyticsSummary.metrics, "users")
                  : null,
              )}
              chart={
                <Sparkline
                  values={series(analytics, "users")}
                  label="Kullanıcı"
                />
              }
            />
            <Metric
              label="Oturum"
              value={numberOrUnknown(
                analyticsSummary
                  ? metricNumber(analyticsSummary.metrics, "sessions")
                  : null,
              )}
              chart={
                <Sparkline
                  values={series(analytics, "sessions")}
                  label="Oturum"
                />
              }
            />
            <Metric
              label="Görüntüleme"
              value={numberOrUnknown(
                analyticsSummary
                  ? metricNumber(analyticsSummary.metrics, "views")
                  : null,
              )}
              chart={
                <Sparkline
                  values={series(analytics, "views")}
                  label="Görüntüleme"
                />
              }
            />
            <Metric
              label="Etkileşim"
              value={ratioOrUnknown(
                analyticsSummary
                  ? metricNumber(analyticsSummary.metrics, "engagement_rate")
                  : null,
              )}
              chart={
                <Sparkline
                  values={series(analytics, "engagement_rate")}
                  label="Etkileşim"
                />
              }
            />
          </div>
        )}
      </section>
      <section className="console-card" aria-labelledby="trend">
        <div className="console-card-heading">
          <div>
            <h2 id="trend">Trend</h2>
            <p>Google Trends göreli ilgi; Pinterest görsel eğilim.</p>
          </div>
        </div>
        {trends === null ? (
          <Empty>Google Trends verisi yok: Bilinmiyor.</Empty>
        ) : (
          <ul className="strategy-list">
            {(Array.isArray(trends.metrics.terms)
              ? trends.metrics.terms
              : []
            ).map((term, index) => {
              const entry = term as Record<string, unknown>;
              return (
                <li key={`${String(entry.term)}-${index}`}>
                  <strong>{String(entry.term ?? "")}</strong>
                  <span>
                    Google Trends:{" "}
                    {typeof entry.direction === "string"
                      ? trLabel(entry.direction)
                      : "Bilinmiyor"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {pinterest === null ? (
          <Empty>Pinterest verisi yok: Bilinmiyor.</Empty>
        ) : (
          <ul className="strategy-list">
            {(Array.isArray(pinterest.metrics.keywords)
              ? pinterest.metrics.keywords
              : []
            ).map((keyword, index) => {
              const entry = keyword as Record<string, unknown>;
              return (
                <li key={`${String(entry.keyword)}-${index}`}>
                  <strong>{String(entry.keyword ?? "")}</strong>
                  <span>
                    Pinterest haftalık değişim{" "}
                    {typeof entry.growth_pct_wow === "number"
                      ? `%${entry.growth_pct_wow}`
                      : "Bilinmiyor"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section className="console-card" aria-labelledby="seo-market">
        <div className="console-card-heading">
          <div>
            <h2 id="seo-market">SEO Market</h2>
            <p>
              Semrush anahtar kelime gözlemleri; Search Console gerçeğinin
              yerine geçmez.
            </p>
          </div>
        </div>
        {semrush === null ? (
          <Empty>Semrush verisi yok: Bilinmiyor.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Anahtar kelime</th>
                  <th>Hacim</th>
                  <th>Zorluk</th>
                </tr>
              </thead>
              <tbody>
                {(Array.isArray(semrush.metrics.keywords)
                  ? semrush.metrics.keywords
                  : []
                ).map((keyword, index) => {
                  const entry = keyword as Record<string, unknown>;
                  return (
                    <tr key={`${String(entry.keyword)}-${index}`}>
                      <td>{String(entry.keyword ?? "")}</td>
                      <td>
                        {numberOrUnknown(metricNumber(entry, "search_volume"))}
                      </td>
                      <td>
                        {positionOrUnknown(
                          metricNumber(entry, "keyword_difficulty"),
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section
        className="console-card"
        id="guncelleme"
        aria-labelledby="guncelleme-baslik"
      >
        <div className="console-card-heading">
          <div>
            <h2 id="guncelleme-baslik">Güncelleme Fırsatı</h2>
            <p>
              Değişim {pctOrUnknown(content.impressions_pct)} (gösterim). Onay
              yalnızca yeniden araştırmayı başlatır; yayın kararı ayrıdır.
            </p>
          </div>
        </div>
        {detail.refresh === null ? (
          <Empty>Bekleyen güncelleme kararı yok.</Empty>
        ) : (
          <RefreshCard row={detail.refresh} returnTo={returnTo} />
        )}
        {detail.refresh_history.filter((row) => row.status !== "proposed")
          .length > 0 && (
          <ul className="strategy-list">
            {detail.refresh_history
              .filter((row) => row.status !== "proposed")
              .map((row) => (
                <li key={row.id}>
                  <strong>{trLabel(row.status)}</strong>
                  <span>{formatUtcTimestamp(row.decided_at)}</span>
                  <span>{row.decision_reason ?? ""}</span>
                </li>
              ))}
          </ul>
        )}
      </section>
    </main>
  );
}
