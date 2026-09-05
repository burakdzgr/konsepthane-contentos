import {
  boundedWindow,
  fetchPerformanceOverview,
  fetchRefreshOpportunities,
  fetchStrategySuggestions,
  PERFORMANCE_WINDOWS,
  type PerformanceOverview,
} from "@/lib/performance-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { syncPerformanceAction } from "./actions";
import {
  ContentList,
  Empty,
  freshnessText,
  PROVIDER_SHORT,
  RefreshCard,
  SuggestionCard,
} from "./cards";

export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {
  "refresh-approved":
    "Güncelleme onaylandı; içerik yeniden araştırma rotasına alındı. Yayın kararı ayrıca ve insan onayıyla verilir.",
  "refresh-dismissed": "Güncelleme fırsatı şimdilik geçildi; karar kaydedildi.",
  "suggestion-accepted": "Öneri stratejiye eklendi.",
  "suggestion-ignored": "Öneri yoksayıldı; karar kaydedildi.",
  "sync-queued":
    "Senkronizasyon kuyruğa alındı; sağlayıcı verileri birkaç dakika içinde güncellenir.",
};

function Overview({ data }: { data: PerformanceOverview }) {
  const totals = data.totals;
  return (
    <section className="console-card" aria-labelledby="genel-gorunum">
      <div className="console-card-heading">
        <div>
          <h2 id="genel-gorunum">Genel Görünüm</h2>
          <p>
            Son {data.window_days} gün, önceki eşit pencereyle karşılaştırıldı.
            Yayınlandı demek bitti demek değildir; ölçüm burada başlar.
          </p>
        </div>
      </div>
      <dl className="performance-totals">
        <div>
          <dt>Yayında</dt>
          <dd>{totals.published}</dd>
        </div>
        <div>
          <dt>Yükselen</dt>
          <dd>{totals.rising}</dd>
        </div>
        <div>
          <dt>Stabil</dt>
          <dd>{totals.stable}</dd>
        </div>
        <div>
          <dt>Düşen</dt>
          <dd>{totals.declining}</dd>
        </div>
        <div>
          <dt>Dalgalı</dt>
          <dd>{totals.volatile}</dd>
        </div>
        <div>
          <dt>Yeni</dt>
          <dd>{totals.new}</dd>
        </div>
        <div>
          <dt>Yetersiz veri</dt>
          <dd>{totals.insufficient + totals.unknown}</dd>
        </div>
      </dl>
      <h3>Kümeler</h3>
      {data.clusters.length === 0 ? (
        <Empty>Henüz yayınlanmış içerik yok.</Empty>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Küme</th>
                <th>Yayın</th>
                <th>Yükselen</th>
                <th>Stabil</th>
                <th>Düşen</th>
                <th>Yeni</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {data.clusters.map((cluster) => (
                <tr key={cluster.cluster_id ?? "none"}>
                  <td>{cluster.cluster_name}</td>
                  <td>{cluster.published}</td>
                  <td>{cluster.rising}</td>
                  <td>{cluster.stable}</td>
                  <td>{cluster.declining}</td>
                  <td>{cluster.new}</td>
                  <td>{cluster.sufficient ? "Ölçülüyor" : "Yetersiz veri"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default async function PerformancePage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams ? await searchParams : {};
  const window = boundedWindow(firstParam(query.window));
  const [overview, refreshes, suggestions] = await Promise.all([
    fetchPerformanceOverview(window),
    fetchRefreshOpportunities("proposed"),
    fetchStrategySuggestions("proposed"),
  ]);
  const data = overview.kind === "ok" ? overview.data : null;
  const refreshRows = refreshes.kind === "ok" ? refreshes.data : null;
  const suggestionRows = suggestions.kind === "ok" ? suggestions.data : null;
  return (
    <main
      className="strategy-page performance-page"
      aria-labelledby="performans-title"
    >
      <header className="page-heading">
        <div>
          <p className="eyebrow">Ölç → Öğren → İyileştir</p>
          <h1 id="performans-title">Performans</h1>
          <p>
            Yayınlanan içeriklerin gerçek verisi. Eksik sağlayıcı verisi
            &quot;Bilinmiyor&quot; olarak kalır; hiçbir değer tahmin edilmez.
          </p>
        </div>
        <form action={syncPerformanceAction} className="control-form">
          <input type="hidden" name="return_to" value="/performans" />
          <button type="submit">Şimdi senkronize et</button>
        </form>
      </header>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      <form method="get" className="filter-form" aria-label="Pencere filtresi">
        <label>
          Pencere
          <select name="window" defaultValue={String(window)}>
            {PERFORMANCE_WINDOWS.map((days) => (
              <option key={days} value={days}>
                {days} gün
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Uygula</button>
      </form>
      {data === null && <Empty>Performans verileri şu anda alınamıyor.</Empty>}
      {data !== null && (
        <>
          <p className="performance-freshness" role="status">
            {data.freshness.map((row, index) => (
              <span key={row.provider}>
                {index > 0 ? " · " : ""}
                {PROVIDER_SHORT[row.provider]}: {freshnessText(row)}
              </span>
            ))}
            {!data.schedule_enabled && " · Otomatik senkron kapalı"}
          </p>
          <Overview data={data} />
          <section className="console-card" aria-labelledby="yukselen">
            <div className="console-card-heading">
              <div>
                <h2 id="yukselen">Yükselen İçerikler</h2>
                <p>Gösterim veya tıklama arttı, pozisyon kötüleşmedi.</p>
              </div>
            </div>
            <ContentList
              rows={data.rising}
              empty="Bu pencerede yükselen içerik yok."
            />
          </section>
          <section className="console-card" aria-labelledby="dusen">
            <div className="console-card-heading">
              <div>
                <h2 id="dusen">Düşen İçerikler</h2>
                <p>Gösterim veya tıklama düştü VE pozisyon kötüleşti.</p>
              </div>
            </div>
            <ContentList
              rows={data.declining}
              empty="Bu pencerede düşen içerik yok."
            />
          </section>
          <section className="console-card" aria-labelledby="yeni">
            <div className="console-card-heading">
              <div>
                <h2 id="yeni">Yeni Yayınlananlar</h2>
                <p>
                  Son {data.window_days} günde yayınlandı; yeterli veri birikene
                  kadar &quot;Yetersiz veri&quot; kalır, asla
                  &quot;düşüyor&quot; sayılmaz.
                </p>
              </div>
            </div>
            <ContentList rows={data.new} empty="Bu pencerede yeni yayın yok." />
          </section>
        </>
      )}
      <section
        className="console-card"
        id="guncelleme"
        aria-labelledby="guncelleme-baslik"
      >
        <div className="console-card-heading">
          <div>
            <h2 id="guncelleme-baslik">Güncelleme Fırsatları</h2>
            <p>
              Düşen içerikler için teşhis ve öneri. Onay yalnızca yeniden
              araştırmayı başlatır; yayın kararı ayrıdır.
            </p>
          </div>
        </div>
        {refreshRows === null && (
          <Empty>Güncelleme fırsatları alınamıyor.</Empty>
        )}
        {refreshRows !== null && refreshRows.length === 0 && (
          <Empty>Bekleyen güncelleme kararı yok.</Empty>
        )}
        {refreshRows !== null &&
          refreshRows.map((row) => <RefreshCard key={row.id} row={row} />)}
      </section>
      <section
        className="console-card"
        id="strateji"
        aria-labelledby="strateji-baslik"
      >
        <div className="console-card-heading">
          <div>
            <h2 id="strateji-baslik">Strateji Önerileri</h2>
            <p>
              En az üç yayının 90 günlük gerçek verisinden türetilir; strateji
              yalnızca sizin kararınızla değişir.
            </p>
          </div>
        </div>
        {suggestionRows === null && (
          <Empty>Strateji önerileri alınamıyor.</Empty>
        )}
        {suggestionRows !== null && suggestionRows.length === 0 && (
          <Empty>Bekleyen strateji önerisi yok.</Empty>
        )}
        {suggestionRows !== null &&
          suggestionRows.map((row) => (
            <SuggestionCard key={row.id} row={row} />
          ))}
      </section>
    </main>
  );
}
