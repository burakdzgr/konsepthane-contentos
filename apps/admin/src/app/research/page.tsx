import Link from "next/link";

import {
  MISSION_STAGE_LABELS,
  MISSION_STATUS_LABELS,
  fetchMissions,
  stateLabel,
} from "@/lib/missions-api";
import { fetchStrategyOverview } from "@/lib/strategy-api";

import { createMissionAction } from "./actions";
import styles from "./research.module.css";

export const dynamic = "force-dynamic";

const FLOW = [
  "Konu ve okur niyeti",
  "Anahtar kelimeler ve arama sinyalleri",
  "Kayıtlı kaynaklar, açık web, görsel ilham, topluluk",
  "Fikir mekanikleri ve adaylar",
  "Klişe eleme ve gruplama",
  "Fikir kalitesi ve strateji uyumu",
  "Sayfa temellendirme ve içerik fırsatı",
];

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ResearchMissionsPage({
  searchParams,
}: {
  searchParams?: SearchParams;
}) {
  const params = searchParams ? await searchParams : {};
  const error = typeof params.error === "string" ? params.error : null;
  const [missions, strategy] = await Promise.all([fetchMissions(), fetchStrategyOverview()]);
  const items = missions.kind === "ok" ? missions.data : [];
  const clusters = strategy.kind === "ok" ? strategy.data.clusters : [];

  return (
    <main className={styles.page}>
      <header className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>FİKİR KEŞİF MERKEZİ</span>
          <h1>Araştırmalar</h1>
          <p>
            Kaynak seçmek zorunda değilsin. Ne aradığını söyle; ContentOS konuyu anlar,
            anahtar kelimeleri genişletir, kayıtlı kaynakları ve açık webi tarar, klişeleri
            eler ve yalnızca güçlü, uygulanabilir fikirleri içerik fırsatına dönüştürür.
          </p>
        </div>
        <div className={styles.truth}>
          <b>İki ayrı güven ölçüsü</b>
          <span>
            Fikir güveni yaratıcı kaliteyi anlatır; kanıt güveni yalnızca doğrulanabilir
            iddiaları. Arama hacmi veya trend verisi yoksa &ldquo;Bilinmiyor&rdquo; kalır.
          </span>
        </div>
      </header>

      {error === "create" ? (
        <p role="alert" className={styles.alert}>
          Araştırma oluşturulamadı. Konu, amaç ve hedef kitle zorunludur.
        </p>
      ) : null}

      <section className={styles.grid}>
        <form action={createMissionAction} className={styles.composer}>
          <div className={styles.title}>
            <span>✦</span>
            <div>
              <h2>Yeni araştırma başlat</h2>
              <p>Dört kısa bilgi yeterli. Kaynak, sorgu ve agent seçimlerini sistem yapar.</p>
            </div>
          </div>
          <label>
            <span>Ne araştırmak istiyorsun?</span>
            <input
              name="topic"
              required
              maxLength={300}
              placeholder="Örn. İlginç evlilik teklifleri"
            />
          </label>
          <label>
            <span>Bu araştırmadan beklediğin sonuç</span>
            <textarea
              name="goal"
              required
              maxLength={2000}
              rows={3}
              placeholder="Türkiye için gerçekten yaratıcı ve uygulanabilir 20 fikir bul"
            />
          </label>
          <div className={styles.two}>
            <label>
              <span>Hedef kitle</span>
              <input name="audience" required maxLength={300} placeholder="20–35 yaş çiftler" />
            </label>
            <label>
              <span>
                Odak kelime <small>isteğe bağlı</small>
              </span>
              <input name="seed_keyword" maxLength={240} placeholder="ilginç evlilik teklifleri" />
            </label>
          </div>
          <label>
            <span>
              Konu kümesi <small>isteğe bağlı</small>
            </span>
            <select name="topic_cluster_id" defaultValue="">
              <option value="">Sistem eşleştirsin</option>
              {clusters.map((cluster) => (
                <option value={cluster.id} key={cluster.id}>
                  {cluster.name}
                </option>
              ))}
            </select>
          </label>
          <button className={styles.primary} type="submit">
            <span>▶</span> Araştırmayı başlat
          </button>
          <p className={styles.help}>
            Araştırma kuyruğa alınır ve sayfada canlı ilerler; sen fırsatları ve fikirleri
            görürsün, mekanik adımları değil.
          </p>
        </form>

        <section className={styles.flow}>
          <h2>Bu görev nasıl ilerler?</h2>
          {FLOW.map((step, index) => (
            <div className={styles.step} key={step}>
              <b>{index + 1}</b>
              <span>{step}</span>
            </div>
          ))}
          <div className={styles.separation}>
            <b>Kaynak sayısı ölçüt değil</b>
            <p>
              Özgün bir fikir başka sitelerde bulunmayabilir. Fırsatın gücü fikrin kalitesi,
              okur ihtiyacı, strateji uyumu ve uygulanabilirlikle ölçülür; olgusal iddialar
              için kanıt kuralları aynen sürer.
            </p>
          </div>
          <p className={styles.help}>
            Mekanik hattı (keşif, getirme, normalizasyon) görmek için{" "}
            <Link href="/research/hat">Araştırma hattı (gelişmiş)</Link>.
          </p>
        </section>
      </section>

      <section className={styles.list}>
        <div className={styles.listHead}>
          <div>
            <h2>Son araştırmalar</h2>
            <p>{items.length} kalıcı görev</p>
          </div>
        </div>
        {missions.kind !== "ok" ? (
          <div className={styles.empty}>Araştırma listesi şu an okunamıyor.</div>
        ) : items.length === 0 ? (
          <div className={styles.empty}>Henüz araştırma görevi yok. İlk konunu yukarıdan başlat.</div>
        ) : (
          items.map((mission) => (
            <Link className={styles.mission} href={`/research/${mission.id}`} key={mission.id}>
              <div className={styles.missionIcon}>⌕</div>
              <div className={styles.missionBody}>
                <h3>{mission.topic}</h3>
                <p>
                  {mission.audience} · {mission.goal}
                </p>
                <span>
                  {stateLabel(MISSION_STATUS_LABELS, mission.status)} ·{" "}
                  {stateLabel(MISSION_STAGE_LABELS, mission.stage)}
                </span>
              </div>
              <div className={styles.stats}>
                <b>{Number(mission.result_summary.ideas ?? 0)}</b>
                <span>fikir</span>
              </div>
              <div className={styles.stats}>
                <b>{Number(mission.result_summary.promotable ?? 0)}</b>
                <span>güçlü aday</span>
              </div>
              <div className={styles.stats}>
                <b>{Number(mission.result_summary.promoted ?? 0)}</b>
                <span>fırsat</span>
              </div>
              <span className={styles.arrow}>→</span>
            </Link>
          ))
        )}
      </section>
    </main>
  );
}
