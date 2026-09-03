import Link from "next/link";

import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";
import {
  commissionOpportunityAction,
  rejectOpportunityAction,
} from "../editorial/[id]/actions";

// The reviewed-opportunity queue: the FIRST genuine human decision of
// the pipeline — "should Konsepthane produce content on this topic?" —
// asked only after the machine finished discovery, prefilter, fetch,
// normalization, deduplication and explainable scoring.
export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {};

const RECOMMENDATION: Record<
  string,
  { label: string; tone: string; hint: string }
> = {
  commissionable: {
    label: "ÜRET",
    tone: "ok",
    hint: "Skor motoru üretilebilir buldu; komisyon kapısı açık.",
  },
  needs_operator_review: {
    label: "İNCELE",
    tone: "warn",
    hint: "Sinyaller eksik; karar tamamen size ait.",
  },
  not_commissionable: {
    label: "ATLA",
    tone: "bad",
    hint: "Skor motoru üretime uygun bulmadı; reddetmek tek tıklık.",
  },
};

function OpportunityCard({ row }: { row: WorkQueueRow }) {
  const recommendation =
    row.score_eligibility !== null
      ? (RECOMMENDATION[row.score_eligibility] ?? null)
      : null;
  return (
    <article className="opportunity-card">
      <header className="agent-card-header">
        <h3>
          <Link href={`/editorial/${row.work_item_id}`}>
            {row.title_working_label}
          </Link>
        </h3>
        {recommendation !== null ? (
          <span className="badge" data-tone={recommendation.tone}>
            {recommendation.label}
          </span>
        ) : (
          <span className="badge">SKOR BEKLENİYOR</span>
        )}
      </header>
      {row.topic_summary !== null && <p>{row.topic_summary}</p>}
      <dl className="agent-facts">
        <div>
          <dt>Skor bandı</dt>
          <dd>{row.score_band ?? "yok"}</dd>
        </div>
        <div>
          <dt>Skor</dt>
          <dd>
            {row.score_overall_value !== null
              ? row.score_overall_value.toFixed(2)
              : "yok"}
          </dd>
        </div>
        <div>
          <dt>Pazar</dt>
          <dd>
            {row.locale} / {row.market}
          </dd>
        </div>
        <div>
          <dt>Değerlendirildi</dt>
          <dd>
            {row.score_evaluated_at !== null
              ? formatUtcTimestamp(row.score_evaluated_at)
              : "henüz değil"}
          </dd>
        </div>
      </dl>
      {row.score_missing_signals.length > 0 && (
        <p className="muted">
          Eksik sinyaller: {row.score_missing_signals.join(", ")}
        </p>
      )}
      {row.score_risk_flags.length > 0 && (
        <p className="muted">
          Risk işaretleri: {row.score_risk_flags.join(", ")}
        </p>
      )}
      {recommendation !== null && (
        <p className="muted">{recommendation.hint}</p>
      )}
      <div className="opportunity-actions">
        <Link href={`/editorial/${row.work_item_id}`}>İncele</Link>
        {row.opportunity_id !== null && (
          <>
            <form action={commissionOpportunityAction} className="control-form">
              <input
                type="hidden"
                name="work_item_id"
                value={row.work_item_id}
              />
              <input
                type="hidden"
                name="opportunity_id"
                value={row.opportunity_id}
              />
              <input
                type="text"
                name="reason"
                required
                placeholder="üretim gerekçesi"
                aria-label={`${row.title_working_label} üretim gerekçesi`}
              />
              <button type="submit">İçerik üretimini onayla</button>
            </form>
            <form action={rejectOpportunityAction} className="control-form">
              <input
                type="hidden"
                name="work_item_id"
                value={row.work_item_id}
              />
              <input
                type="hidden"
                name="opportunity_id"
                value={row.opportunity_id}
              />
              <input
                type="text"
                name="reason"
                required
                placeholder="ret gerekçesi"
                aria-label={`${row.title_working_label} ret gerekçesi`}
              />
              <button type="submit">Reddet</button>
            </form>
          </>
        )}
      </div>
    </article>
  );
}

export default async function OpportunityReviewPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchWorkQueue({
    workflowState: "idea_scoring",
    opportunityDisposition: "open",
    limit: 50,
  });
  const rows =
    result.kind === "ok"
      ? result.data.items.filter((row) => row.score_id !== null)
      : null;
  const pendingScore =
    result.kind === "ok"
      ? result.data.items.filter((row) => row.score_id === null).length
      : 0;
  return (
    <section className="panel panel-wide" aria-labelledby="firsatlar-title">
      <div className="kontrol-header">
        <div>
          <h1 id="firsatlar-title">Fırsat İncelemesi</h1>
          <p className="muted">
            Bu konuda Konsepthane için içerik üretelim mi? Makine keşfetti,
            filtreledi, getirdi ve skorladı — karar sizin. Karar gerekçesiyle
            kayda geçer.
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
      {rows !== null && pendingScore > 0 && (
        <p className="muted">
          {pendingScore} fırsat henüz skorlanıyor; skorlanınca burada belirir.
        </p>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="empty-note">
          İncelenecek skorlanmış fırsat yok. Otonom alım yeni fırsat ürettikçe
          burada listelenir (<Link href="/calisma">Çalışmalar</Link>).
        </p>
      )}
      {rows !== null && rows.length > 0 && (
        <div className="opportunity-grid">
          {rows.map((row) => (
            <OpportunityCard key={row.work_item_id} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}
