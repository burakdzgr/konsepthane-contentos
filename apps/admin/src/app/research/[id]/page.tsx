import Link from "next/link";
import { notFound } from "next/navigation";

import {
  CONFIDENCE_LABELS,
  MISSION_STAGE_LABELS,
  MISSION_STATUS_LABELS,
  RECOMMENDATION_LABELS,
  SURFACE_LABELS,
  fetchMission,
  stateLabel,
  type MissionCandidate,
} from "@/lib/missions-api";

import { rerunMissionAction } from "../actions";
import styles from "../research.module.css";

export const dynamic = "force-dynamic";

const STAGE_ORDER = [
  "planning",
  "keywords",
  "searching",
  "extracting",
  "clustering",
  "evaluating",
  "grounding",
  "promoting",
  "completed",
];

const FACTOR_LABELS: Record<string, string> = {
  novelty: "Özgünlük",
  usefulness: "Fayda",
  specificity: "Somutluk",
  visual_potential: "Görsel güç",
  shareability: "Paylaşılabilirlik",
  emotional_impact: "Duygusal etki",
  audience_fit: "Kitle uyumu",
  turkey_applicability: "Türkiye uygulanabilirliği",
};

function demandText(entry: Record<string, unknown>): string {
  const demand = (entry.demand ?? {}) as Record<string, unknown>;
  if (demand.state === "observed") {
    return `${Number(demand.clicks ?? 0)} tık / ${Number(demand.impressions ?? 0)} gösterim`;
  }
  if (demand.state === "not_observed") return "Sitede görülmedi";
  return "Bilinmiyor";
}

function trendText(entry: Record<string, unknown>): string {
  const trend = (entry.trend ?? {}) as Record<string, unknown>;
  if (trend.state === "observed") {
    return `${String(trend.term)} (${String(trend.trend_type ?? "")}${
      trend.rank != null ? ` #${String(trend.rank)}` : ""
    })`;
  }
  if (trend.state === "not_observed") return "Listede yok";
  return "Bilinmiyor";
}

function stageState(
  stage: string,
  currentStage: string,
  status: string,
  log: Record<string, unknown>[],
): "done" | "active" | "todo" | "failed" {
  const entries = log.filter((entry) => entry.stage === stage);
  if (entries.some((entry) => entry.status === "failed")) return "failed";
  if (entries.some((entry) => entry.status === "done")) return "done";
  if (stage === currentStage && (status === "running" || status === "grounding")) return "active";
  if (stage === currentStage && status === "completed") return "done";
  const currentIndex = STAGE_ORDER.indexOf(currentStage);
  return STAGE_ORDER.indexOf(stage) < currentIndex ? "done" : "todo";
}

function CandidateCard({ candidate }: { candidate: MissionCandidate }) {
  const factors = candidate.quality_factors as Record<string, unknown>;
  return (
    <article className={styles.candidate} data-recommendation={candidate.recommendation}>
      <div className={styles.candidateHead}>
        <div>
          <h3>{candidate.title}</h3>
          <p>{candidate.angle}</p>
        </div>
        <div className={styles.stats}>
          <b>{candidate.idea_quality}</b>
          <span>fikir kalitesi</span>
        </div>
      </div>
      <div className={styles.pills}>
        <span className={styles.pill}>
          {stateLabel(RECOMMENDATION_LABELS, candidate.recommendation)}
        </span>
        <span className={styles.pill}>
          {candidate.candidate_kind === "synthesized" ? "Sentezlenmiş" : "Sinyalden çıkarılmış"}
        </span>
        <span className={styles.pill}>
          Fikir güveni: {stateLabel(CONFIDENCE_LABELS, candidate.idea_confidence)}
        </span>
        <span className={styles.pill}>
          Kanıt güveni: {stateLabel(CONFIDENCE_LABELS, candidate.factual_evidence_confidence)}
        </span>
        {candidate.work_item_id ? (
          <Link className={styles.pillLink} href={`/editorial/${candidate.work_item_id}`}>
            İçerik fırsatını aç →
          </Link>
        ) : candidate.opportunity_id ? (
          <span className={styles.pill}>İçerik fırsatı açıldı</span>
        ) : null}
      </div>
      {candidate.is_cliche && candidate.cliche_reason ? (
        <p className={styles.note}>Klişe: {candidate.cliche_reason}</p>
      ) : null}
      {candidate.primitives.length > 0 ? (
        <p className={styles.note}>
          Mekanikler:{" "}
          {candidate.primitives
            .map((primitive) => String(primitive.label ?? primitive.key ?? ""))
            .filter(Boolean)
            .join(" + ")}
        </p>
      ) : null}
      {candidate.implementation_steps.length > 0 ? (
        <ol className={styles.steps}>
          {candidate.implementation_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ) : null}
      {candidate.factual_claims_needed.length > 0 ? (
        <p className={styles.note}>
          Kanıt gerektiren iddialar: {candidate.factual_claims_needed.join("; ")}
        </p>
      ) : null}
      <div className={styles.factors}>
        {Object.entries(FACTOR_LABELS).map(([key, label]) => (
          <span key={key}>
            {label} <b>{Number(factors[key] ?? 0)}</b>
          </span>
        ))}
      </div>
      <p className={styles.rationale}>{candidate.rationale}</p>
    </article>
  );
}

export default async function MissionDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = searchParams ? await searchParams : {};
  const error = typeof query.error === "string" ? query.error : null;
  const result = await fetchMission(id);
  if (result.kind !== "ok") notFound();
  const { mission, signals, candidates } = result.data;
  const summary = mission.result_summary;
  const elimination = mission.elimination_summary;
  const counts = (mission.surface_summary.counts ?? {}) as Record<string, number>;
  const unavailable = (mission.surface_summary.unavailable ?? []) as string[];
  const promoted = candidates.filter((candidate) => candidate.opportunity_id);
  const strong = candidates.filter(
    (candidate) => candidate.recommendation === "promote" && !candidate.opportunity_id,
  );
  const continued = candidates.filter((candidate) => candidate.recommendation === "continue_research");
  const eliminated = candidates.filter(
    (candidate) => candidate.recommendation === "eliminate" || candidate.recommendation === "merged",
  );
  const busy = mission.status === "queued" || mission.status === "running" || mission.status === "grounding";

  return (
    <main className={styles.page}>
      <header className={styles.hero}>
        <div>
          <Link href="/research">← Araştırmalar</Link>
          <h1>{mission.topic}</h1>
          <p>{mission.goal}</p>
          <span className={styles.status} data-status={mission.status}>
            {stateLabel(MISSION_STATUS_LABELS, mission.status)} ·{" "}
            {stateLabel(MISSION_STAGE_LABELS, mission.stage)}
          </span>
        </div>
        <form action={rerunMissionAction}>
          <input type="hidden" name="id" value={mission.id} />
          <button className={styles.primary} disabled={busy}>
            {busy ? "Araştırma sürüyor…" : "Araştırmayı yeniden çalıştır"}
          </button>
        </form>
      </header>

      {error === "run" ? (
        <p role="alert" className={styles.alert}>
          Araştırma yeniden kuyruğa alınamadı.
        </p>
      ) : null}
      {error === "queue" ? (
        <p role="alert" className={styles.alert}>
          Araştırma kaydedildi ama kuyruğa alınamadı; worker ve kuyruğu kontrol et.
        </p>
      ) : null}
      {mission.failure_reason ? (
        <p role="alert" className={styles.alert}>
          Araştırma başarısız oldu: {mission.failure_reason}
        </p>
      ) : null}

      <section className={styles.progress} aria-label="Araştırma ilerlemesi">
        {STAGE_ORDER.map((stage) => {
          const state = stageState(stage, mission.stage, mission.status, mission.progress_log);
          const last = [...mission.progress_log].reverse().find((entry) => entry.stage === stage);
          return (
            <div className={styles.progressStep} data-state={state} key={stage}>
              <b>{stateLabel(MISSION_STAGE_LABELS, stage)}</b>
              <span>{last ? String(last.note ?? "") : "Bekliyor"}</span>
            </div>
          );
        })}
      </section>

      <section className="stats-grid">
        <article>
          <span>Bulunan fikir</span>
          <strong>{Number(elimination.found ?? summary.ideas ?? 0)}</strong>
        </article>
        <article>
          <span>Klişe elendi</span>
          <strong>{Number(elimination.generic_eliminated ?? 0)}</strong>
        </article>
        <article>
          <span>Birleştirildi</span>
          <strong>{Number(elimination.merged ?? 0)}</strong>
        </article>
        <article>
          <span>Güçlü aday</span>
          <strong>{Number(elimination.promotable ?? summary.promotable ?? 0)}</strong>
        </article>
        <article>
          <span>İçerik fırsatı</span>
          <strong>{Number(summary.promoted ?? 0)}</strong>
        </article>
        <article>
          <span>Arama verisi</span>
          <strong>{summary.search_demand === "observed" ? "Var" : summary.search_demand === "not_observed" ? "Görülmedi" : "Bilinmiyor"}</strong>
        </article>
      </section>

      <section className={styles.grid}>
        <section className={styles.list}>
          <div className={styles.listHead}>
            <div>
              <h2>Fikir adayları</h2>
              <p>Kaynak sayısı değil, fikrin kendi niteliği değerlendirilir.</p>
            </div>
          </div>
          {candidates.length === 0 ? (
            <div className={styles.empty}>
              {busy ? "Fikirler henüz çıkarılmadı; araştırma sürüyor." : "Bu turda fikir bulunamadı."}
            </div>
          ) : null}
          {promoted.length > 0 ? <h3 className={styles.group}>İçerik fırsatına dönüşenler</h3> : null}
          {promoted.map((candidate) => (
            <CandidateCard candidate={candidate} key={candidate.id} />
          ))}
          {strong.length > 0 ? <h3 className={styles.group}>Güçlü adaylar</h3> : null}
          {strong.map((candidate) => (
            <CandidateCard candidate={candidate} key={candidate.id} />
          ))}
          {continued.length > 0 ? <h3 className={styles.group}>Araştırmaya devam</h3> : null}
          {continued.map((candidate) => (
            <CandidateCard candidate={candidate} key={candidate.id} />
          ))}
          {eliminated.length > 0 ? (
            <details className={styles.details}>
              <summary>Elenen ve birleştirilen adaylar ({eliminated.length})</summary>
              {eliminated.map((candidate) => (
                <CandidateCard candidate={candidate} key={candidate.id} />
              ))}
            </details>
          ) : null}
        </section>

        <aside className={styles.flow}>
          <h2>Araştırma kapsamı</h2>
          <p>
            Hedef kitle: <b>{mission.audience}</b>
          </p>
          <p>
            Odak kelime: <b>{mission.seed_keyword ?? "Sistem eşleştirdi"}</b>
          </p>
          {typeof mission.plan.intent_summary === "string" ? (
            <p>
              Okur niyeti: <b>{mission.plan.intent_summary}</b>
            </p>
          ) : null}
          <p>
            Faktüel kanıt:{" "}
            <b>
              {summary.factual_evidence === "not_evaluated"
                ? "Fikir aşamasında değerlendirilmez"
                : String(summary.factual_evidence ?? "Bilinmiyor")}
            </b>
          </p>

          <h2>Bulunan yüzeyler</h2>
          {Object.entries(counts).map(([key, value]) => (
            <div className={styles.step} key={key}>
              <b>{value}</b>
              <span>{stateLabel(SURFACE_LABELS, key)}</span>
            </div>
          ))}
          {unavailable.map((note) => (
            <p className={styles.note} key={note}>
              {note}
            </p>
          ))}

          <h2>Anahtar kelimeler</h2>
          {mission.keyword_plan.length === 0 ? (
            <p className={styles.note}>Henüz genişletilmedi.</p>
          ) : (
            <table className={styles.keywords}>
              <thead>
                <tr>
                  <th>Kelime</th>
                  <th>Arama verisi</th>
                  <th>Trend</th>
                </tr>
              </thead>
              <tbody>
                {mission.keyword_plan.map((entry) => (
                  <tr key={String(entry.keyword)}>
                    <td>{String(entry.keyword)}</td>
                    <td>{demandText(entry)}</td>
                    <td>{trendText(entry)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {Array.isArray(mission.plan.cliche_patterns) && mission.plan.cliche_patterns.length > 0 ? (
            <>
              <h2>Klişe kalıpları</h2>
              <p className={styles.note}>{(mission.plan.cliche_patterns as string[]).join(" · ")}</p>
            </>
          ) : null}
        </aside>
      </section>

      <section className={styles.list}>
        <div className={styles.listHead}>
          <div>
            <h2>İlham izi</h2>
            <p>Bunlar ilham sinyalidir; hiçbiri olgu kanıtı değildir.</p>
          </div>
        </div>
        {signals.length === 0 ? <div className={styles.empty}>Henüz sinyal toplanmadı.</div> : null}
        {signals.slice(0, 40).map((signal) => (
          <div className={styles.mission} key={signal.id}>
            <div className={styles.missionIcon}>↗</div>
            <div className={styles.missionBody}>
              <h3>{signal.title}</h3>
              <p>{signal.snippet ?? ""}</p>
              <span>
                {stateLabel(SURFACE_LABELS, signal.surface_kind)} ·{" "}
                {String(signal.provenance.source_name ?? signal.provenance.method ?? "Kaynak")}
                {signal.normalized_document_id ? " · belge getirildi" : ""}
              </span>
            </div>
            {signal.reference_url ? (
              <a href={signal.reference_url} target="_blank" rel="noreferrer">
                Aç
              </a>
            ) : null}
          </div>
        ))}
      </section>
    </main>
  );
}
