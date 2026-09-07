import Link from "next/link";
import { fetchDailyPlan } from "@/lib/bot-api";
import { STATE_LABELS_TR } from "@/lib/motor-plan";
import { saveBotAction } from "./actions";
import styles from "./page.module.css";
import { BotRefresh } from "./refresh";

export const dynamic = "force-dynamic";

export default async function BotPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await fetchDailyPlan();
  const query: Record<string, string | string[] | undefined> = searchParams
    ? await searchParams
    : {};
  if (result.kind !== "ok")
    return (
      <section className="panel">
        <h1>İçerik Botu</h1>
        <p role="alert">
          Botun durumu okunamadı. Ayarlarınız değiştirilmedi. Bağlantıyı kontrol
          edip sayfayı yenileyin.
        </p>
      </section>
    );
  const plan = result.data;
  const target = plan.target ?? 10;
  const running = plan.mode === "autonomous" && plan.target !== null;
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>KONSEPTHANE · İÇERİK STÜDYOSU</span>
          <h1>
            Fikirler hazır olsun.
            <br />
            Siz son sözü söyleyin.
          </h1>
          <p>
            Kaynaklarınızı seçin, günlük hedefinizi belirleyin. Bot araştırsın,
            yazsın ve kontrol etsin.
          </p>
        </div>
        <span className={running ? styles.live : styles.paused}>
          {running ? "● Günlük plan açık" : "○ Günlük plan kapalı"}
        </span>
      </header>
      {query.error && (
        <p className={styles.notice} role="alert">
          {query.error === "queue_failed"
            ? "Ayarlar kaydedildi ancak bot başlatılamadı. Bağlantı düzeldiğinde tekrar başlatın."
            : "Ayarlar kaydedilemedi. Aktif bir kaynak ve 1–50 arasında günlük hedef seçin."}
        </p>
      )}
      {query.saved && (
        <p className={styles.notice} role="status">
          {query.saved === "started"
            ? "Günlük plan kaydedildi. Bot her gün bu hedefle çalışacak."
            : "Plan duraklatıldı. Başlamış işler güvenle tamamlanabilir."}
        </p>
      )}
      <div className={styles.layout}>
        <section className={styles.card} aria-labelledby="bot-settings">
          <span className={styles.eyebrow}>01 / BOTU AYARLA</span>
          <h2 id="bot-settings">Her gün ne hazırlayalım?</h2>
          <form action={saveBotAction}>
            <label className={styles.target}>
              Günlük içerik hedefi
              <input
                name="target"
                type="number"
                min="1"
                max="50"
                required
                defaultValue={target}
              />
            </label>
            <p className={styles.hint}>
              Hedef, yazımı ve kontrolleri tamamlanıp yayın incelemesine gelen
              içerik sayısıdır. Türkiye saatine göre her gün yenilenir.
            </p>
            <details
              open={plan.target === null}
              className={styles.sourcePicker}
            >
              <summary>
                Kaynaklar ·{" "}
                {plan.sources.filter((source) => source.selected).length} seçili
              </summary>
              <fieldset className={styles.sources}>
                <legend>Hangi kaynakları kullansın?</legend>
                {plan.sources.map((source) => (
                  <label key={source.id}>
                    <input
                      type="checkbox"
                      name="sources"
                      value={source.id}
                      defaultChecked={source.selected}
                      disabled={!source.active}
                    />
                    <span>
                      {source.name}
                      {!source.active && <small>Duraklatılmış kaynak</small>}
                    </span>
                  </label>
                ))}
                {plan.sources.length === 0 && (
                  <p>Önce bir araştırma kaynağı ekleyin.</p>
                )}
              </fieldset>
            </details>
            <Link className={styles.textLink} href="/sources">
              Kaynak ekle veya düzenle →
            </Link>
            <div className={styles.actions}>
              <button name="intent" value="start" className={styles.primary}>
                Kaydet ve botu çalıştır
              </button>
              <button name="intent" value="pause">
                Duraklat
              </button>
            </div>
            <p className={styles.hint}>
              Yayın onayı her zaman sizde. Kalite, kanıt veya lisans sorunu
              varsa bot bunu aşarak yayın yapmaz.
            </p>
          </form>
        </section>
        <section className={styles.card} aria-labelledby="today-title">
          <span className={styles.eyebrow}>02 / BUGÜNÜ TAKİP ET</span>
          <h2 id="today-title">Bugünün hazırlıkları</h2>
          <p className={styles.hint}>{plan.day} · Türkiye saati</p>
          <div className={styles.progress}>
            <strong>
              {plan.completed}
              <small> / {target}</small>
            </strong>
            <span>içerik hazır</span>
          </div>
          <progress value={Math.min(plan.completed, target)} max={target} />
          <div className={styles.stats}>
            <div>
              <strong>{plan.in_progress}</strong>
              <span>Hazırlanıyor / araştırılıyor</span>
            </div>
            <div>
              <strong>{Math.max(0, target - plan.completed)}</strong>
              <span>Hedefe kalan</span>
            </div>
          </div>
          <p className={styles.hint}>
            Yarım kalan işler ertesi güne taşınır. Yeterli güçlü fikir veya
            kanıt yoksa hedef eksik kalabilir; sayı doldurmak için düşük
            kaliteli içerik üretilmez.
          </p>
          <div className={styles.next}>
            <h3>Sizin yapacağınız tek son adım</h3>
            <p>
              Hazırlanan içeriği okuyun, uygun bulduğunuzda yayınını onaylayın.
            </p>
            <Link href="/firsatlar#yayin-onayi">Yayın incelemesini aç →</Link>
          </div>
          {(plan.research ?? []).map((run, index) => (
            <p key={`${run.source}-${index}`} className={styles.hint}>
              <strong>{run.source}</strong>:{" "}
              {run.status === "running"
                ? "Araştırılıyor"
                : run.status === "completed"
                  ? "Tarama tamamlandı"
                  : run.status === "failed"
                    ? "Tarama sorunu var"
                    : "Tarama beklemede"}{" "}
              · {run.fetched} içerik incelendi · {run.opportunities} fırsat
            </p>
          ))}
          <BotRefresh />
        </section>
      </div>
      <section className={styles.card}>
        <div className={styles.listHeader}>
          <div>
            <span className={styles.eyebrow}>03 / İÇERİKLERİNİZ</span>
            <h2>Botun çalışma masası</h2>
          </div>
          <Link href="/editorial">Tüm içerikler →</Link>
        </div>
        {plan.items.length === 0 ? (
          <div className={styles.empty}>
            <h3>İlk hazırlıklar burada görünecek.</h3>
            <p>
              Planı başlattığınızda bot seçtiğiniz kaynakları tarar ve uygun
              fikirleri günlük hedefe alır.
            </p>
          </div>
        ) : (
          <ul className={styles.items}>
            {plan.items.map((item) => (
              <li key={item.id}>
                <div>
                  <Link href={`/editorial/${item.id}`}>{item.title}</Link>
                  {item.reason && <p>{item.reason}</p>}
                </div>
                <span>
                  {item.completed
                    ? "Yayın incelemesine hazır"
                    : STATE_LABELS_TR[item.state]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <footer className={styles.footer}>
        <span>
          Özgün fikirler · Türkiye’ye uygun anlatım · İnsan onaylı yayın
        </span>
        <details>
          <summary>Gelişmiş seçenekler</summary>
          <Link href="/kontrol">Canlı kontrol merkezi</Link> ·{" "}
          <Link href="/operasyon">Teknik operasyon</Link> ·{" "}
          <Link href="/strateji">Hedef kitle ve konu stratejisi</Link>
        </details>
      </footer>
    </div>
  );
}
