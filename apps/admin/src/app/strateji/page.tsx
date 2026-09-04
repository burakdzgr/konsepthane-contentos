import { fetchStrategyOverview, type StrategyStatus } from "@/lib/strategy-api";

import { trLabel } from "@/lib/tr-labels";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import {
  saveAudienceAction,
  saveClusterAction,
  saveKeywordAction,
} from "./actions";

export const dynamic = "force-dynamic";

const NOTICES = { saved: "Strateji kaydedildi." };

function StatusSelect({ value = "active" }: { value?: StrategyStatus }) {
  return (
    <select name="status" defaultValue={value} aria-label="Durum">
      <option value="active">Aktif</option>
      <option value="paused">Beklemede</option>
      <option value="archived">Arşivde</option>
    </select>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty-note">{children}</p>;
}

export default async function StrategyPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams ? await searchParams : {};
  const result = await fetchStrategyOverview();
  const data = result.kind === "ok" ? result.data : null;
  return (
    <main className="strategy-page" aria-labelledby="strategy-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Editoryal pusula</p>
          <h1 id="strategy-title">Strateji</h1>
          <p>
            ContentOS&apos;un önce hangi kitle ve konulara odaklanacağını
            belirleyin. Bunlar yazara kelime tekrar talimatı vermez.
          </p>
        </div>
      </header>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      {data === null && <Empty>Strateji verileri şu anda alınamıyor.</Empty>}
      {data !== null && (
        <div className="strategy-layout">
          <section className="console-card strategy-section">
            <div className="console-card-heading">
              <div>
                <h2>Hedef Kitleler</h2>
                <p>Öncelikle kimin için değer üretmek istediğimizi gösterir.</p>
              </div>
            </div>
            <form action={saveAudienceAction} className="strategy-form">
              <input name="name" required placeholder="Örn. Çocuklu anneler" />
              <input
                name="priority"
                type="number"
                min="0"
                max="100"
                defaultValue="80"
                aria-label="Öncelik"
              />
              <StatusSelect />
              <input name="notes" placeholder="Kısa not (isteğe bağlı)" />
              <button type="submit">Hedef kitle ekle</button>
            </form>
            {data.audiences.length === 0 ? (
              <Empty>Henüz hedef kitle yok.</Empty>
            ) : (
              <ul className="strategy-list">
                {data.audiences.map((row) => (
                  <li key={row.id}>
                    <strong>{row.name}</strong>
                    <span>Öncelik {row.priority}</span>
                    <span className="badge">{trLabel(row.status)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="console-card strategy-section">
            <div className="console-card-heading">
              <div>
                <h2>Konu Kümeleri</h2>
                <p>Birlikte büyütmek istediğimiz içerik ailesidir.</p>
              </div>
            </div>
            <form action={saveClusterAction} className="strategy-form">
              <input name="name" required placeholder="Örn. 1 Yaş Doğum Günü" />
              <input
                name="priority"
                type="number"
                min="0"
                max="100"
                defaultValue="80"
                aria-label="Öncelik"
              />
              <StatusSelect />
              <input name="notes" placeholder="Kısa not (isteğe bağlı)" />
              <button type="submit">Konu kümesi ekle</button>
            </form>
            {data.clusters.length === 0 ? (
              <Empty>Henüz konu kümesi yok.</Empty>
            ) : (
              <ul className="strategy-list">
                {data.clusters.map((row) => {
                  const count = data.keywords.filter(
                    (keyword) => keyword.topic_cluster_id === row.id,
                  ).length;
                  return (
                    <li key={row.id}>
                      <strong>{row.name}</strong>
                      <span>{count} hedef konu</span>
                      <span>Öncelik {row.priority}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="console-card strategy-section strategy-keywords">
            <div className="console-card-heading">
              <div>
                <h2>Keyword / Konu Hedefleri</h2>
                <p>
                  Keşif ve planlamaya yön verir; içerikte tekrar kotası
                  oluşturmaz.
                </p>
              </div>
            </div>
            <form action={saveKeywordAction} className="strategy-form">
              <input
                name="phrase"
                required
                placeholder="Örn. ilginç evlilik teklifleri"
              />
              <input
                name="priority"
                type="number"
                min="0"
                max="100"
                defaultValue="80"
                aria-label="Öncelik"
              />
              <select
                name="topic_cluster_id"
                defaultValue=""
                aria-label="Konu kümesi"
              >
                <option value="">Küme seçilmedi</option>
                {data.clusters.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
              <input name="notes" placeholder="Kısa not (isteğe bağlı)" />
              <button type="submit">Hedef konu ekle</button>
            </form>
            {data.keywords.length === 0 ? (
              <Empty>Henüz hedef konu yok.</Empty>
            ) : (
              <ul className="strategy-list">
                {data.keywords.map((row) => (
                  <li key={row.id}>
                    <strong>{row.phrase}</strong>
                    <span>
                      {data.clusters.find(
                        (cluster) => cluster.id === row.topic_cluster_id,
                      )?.name ?? "Kümesiz"}
                    </span>
                    <span>Öncelik {row.priority}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
