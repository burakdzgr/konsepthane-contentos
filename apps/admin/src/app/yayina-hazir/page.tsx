import Link from "next/link";

import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { formatUtcTimestamp } from "@/lib/format";
import { trLabel } from "@/lib/tr-labels";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";

type ReadyView = "hazir" | "onaylanan" | "sirada";

const VIEWS: Record<
  ReadyView,
  { state: "awaiting_human_review" | "approved" | "scheduled"; label: string }
> = {
  hazir: { state: "awaiting_human_review", label: "İncelemeye hazır" },
  onaylanan: { state: "approved", label: "Onaylananlar" },
  sirada: { state: "scheduled", label: "Yayın sırası" },
};

function viewOf(raw: string | string[] | undefined): ReadyView {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === "onaylanan" || value === "sirada" ? value : "hazir";
}

function ReadyCard({ row, view }: { row: WorkQueueRow; view: ReadyView }) {
  const inspiration = row.inspiration_band
    ? trLabel(row.inspiration_band)
    : "Bilinmiyor";
  const search = row.search_opportunity
    ? trLabel(row.search_opportunity)
    : "Bilinmiyor";
  return (
    <article className={styles.card}>
      <div className={styles.cardTop}>
        <span className={styles.readyMark}>
          {view === "hazir"
            ? "YAYIN İNCELEMESİ"
            : VIEWS[view].label.toLocaleUpperCase("tr-TR")}
        </span>
        <time>{formatUtcTimestamp(row.current_state_entered_at)}</time>
      </div>
      <h2>
        <Link href={`/editorial/${row.work_item_id}`}>
          {row.title_working_label}
        </Link>
      </h2>
      <p>{row.topic_summary ?? "İçerik özeti hazırlanmadı."}</p>
      <dl>
        <div>
          <dt>İlham değeri</dt>
          <dd>{inspiration}</dd>
        </div>
        <div>
          <dt>Arama fırsatı</dt>
          <dd>{search}</dd>
        </div>
        <div>
          <dt>Fikir sinyali</dt>
          <dd>{row.inspiration_signal_count}</dd>
        </div>
        <div>
          <dt>Kanıt paketi</dt>
          <dd>
            {row.latest_pack_sufficiency
              ? trLabel(row.latest_pack_sufficiency)
              : "Bilinmiyor"}
          </dd>
        </div>
      </dl>
      <div className={styles.cardActions}>
        <Link
          className={styles.primary}
          href={`/editorial/${row.work_item_id}`}
        >
          {view === "hazir" ? "İçeriği incele ve karar ver" : "İçeriği aç"}
        </Link>
        {view === "hazir" && <span>Onay · Değişiklik iste · Reddet</span>}
      </div>
    </article>
  );
}

export default async function ReadyPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = searchParams ? await searchParams : {};
  const active = viewOf(params.gorunum);
  const selected = VIEWS[active];
  const result = await fetchWorkQueue({
    workflowState: selected.state,
    limit: 50,
  });
  const rows = result.kind === "ok" ? result.data.items : null;
  const total = result.kind === "ok" ? result.data.total : null;

  return (
    <section className={styles.page} aria-labelledby="ready-title">
      <header className={styles.hero}>
        <div>
          <span>YAYIN MASASI</span>
          <h1 id="ready-title">Yayına hazır içerikler</h1>
          <p>
            Botun araştırma, yazım, editör ve kalite kontrollerini tamamladığı
            içerikler. Son karar sizde.
          </p>
        </div>
        <div className={styles.heroCount}>
          <strong>{total ?? "—"}</strong>
          <span>{selected.label.toLocaleLowerCase("tr-TR")}</span>
        </div>
      </header>
      <nav className={styles.tabs} aria-label="Yayın görünümü">
        {(
          Object.entries(VIEWS) as [ReadyView, (typeof VIEWS)[ReadyView]][]
        ).map(([key, item]) => (
          <Link
            key={key}
            href={`/yayina-hazir?gorunum=${key}`}
            aria-current={active === key ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {rows === null && (
        <div className={styles.empty} role="alert">
          <h2>Yayın listesi şu anda okunamıyor.</h2>
          <p>
            Herhangi bir karar kaydedilmedi. Bağlantıyı kontrol edip tekrar
            deneyin.
          </p>
        </div>
      )}
      {rows?.length === 0 && (
        <div className={styles.empty}>
          <span>✓</span>
          <h2>Bu listede içerik yok.</h2>
          <p>
            {active === "hazir"
              ? "Bot kontrolleri tamamladığında yeni içerikler burada görünecek."
              : "Bu aşamaya ulaşan içerikler burada görünecek."}
          </p>
          <Link href="/bot">Botun çalışmasını izle</Link>
        </div>
      )}
      {rows && rows.length > 0 && (
        <div className={styles.grid}>
          {rows.map((row) => (
            <ReadyCard key={row.work_item_id} row={row} view={active} />
          ))}
        </div>
      )}
    </section>
  );
}
