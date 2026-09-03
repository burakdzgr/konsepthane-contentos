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

const BAND_LABELS: Record<string, string> = {
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
  unknown: "Bilinmiyor",
  strong: "Güçlü",
  moderate: "Orta",
  weak: "Zayıf",
};

function OpportunityCard({ row }: { row: WorkQueueRow }) {
  const recommendation =
    row.recommendation !== null
      ? (RECOMMENDATION[row.recommendation] ?? null)
      : null;
  const clusters = Array.isArray(row.strategy_context.clusters)
    ? row.strategy_context.clusters
        .map((entry) =>
          typeof entry === "object" && entry !== null && "name" in entry
            ? String(entry.name)
            : null,
        )
        .filter((entry): entry is string => entry !== null)
    : [];
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
          <span className="badge">DEĞERLENDİRİLİYOR</span>
        )}
      </header>
      {row.topic_summary !== null && <p>{row.topic_summary}</p>}
      <dl className="agent-facts">
        <div>
          <dt>İlham Değeri</dt>
          <dd title="Bir fikrin ne kadar özgün, uygulanabilir ve paylaşılabilir olduğunu değerlendirir.">
            {row.inspiration_band === null
              ? "Bilinmiyor"
              : BAND_LABELS[row.inspiration_band]}
          </dd>
        </div>
        <div>
          <dt>Arama fırsatı</dt>
          <dd>
            {row.search_opportunity === null
              ? "Bilinmiyor"
              : BAND_LABELS[row.search_opportunity]}
          </dd>
        </div>
        <div>
          <dt>Stratejik alan</dt>
          <dd title="Bu içeriğin Konsepthane'nin büyümek istediği konu alanlarıyla ilişkisini gösterir.">
            {clusters.join(", ") || "Eşleşme yok"}
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
      <p className="muted">
        Araştırma: {row.inspiration_signal_count} kaynak sinyali ·{" "}
        {row.inspiration_concept_count} gruplanmış fikir · Trend:{" "}
        {row.trend_state === "known" ? "Var" : "Bilinmiyor"}
      </p>
      {row.score_risk_flags.length > 0 && (
        <p className="muted">
          Risk işaretleri: {row.score_risk_flags.join(", ")}
        </p>
      )}
      {recommendation !== null && (
        <p className="muted">{recommendation.hint}</p>
      )}
      {row.inspiration_rationale !== null && <p>{row.inspiration_rationale}</p>}
      <div className="opportunity-actions">
        <Link href={`/editorial/${row.work_item_id}`}>İncele</Link>
        {row.opportunity_id !== null &&
          row.recommendation !== "continue_research" && (
            <>
              <form
                action={commissionOpportunityAction}
                className="control-form"
              >
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
      ? result.data.items.filter(
          (row) =>
            row.inspiration_evaluation_id !== null &&
            row.recommendation !== "continue_research",
        )
      : null;
  const pendingScore =
    result.kind === "ok"
      ? result.data.items.filter(
          (row) => row.inspiration_evaluation_id === null,
        ).length
      : 0;
  const continuedResearch =
    result.kind === "ok"
      ? result.data.items.filter(
          (row) => row.recommendation === "continue_research",
        ).length
      : 0;
  return (
    <section className="panel panel-wide" aria-labelledby="firsatlar-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Gerçek editoryal kararlar</p>
          <h1 id="firsatlar-title">Benden Bekleyenler</h1>
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
          {pendingScore} fırsatı ContentOS değerlendiriyor; karar gerektirirse
          burada belirir.
        </p>
      )}
      {rows !== null && continuedResearch > 0 && (
        <p className="muted">
          {continuedResearch} fırsat için sistem otomatik olarak araştırmayı
          sürdürüyor; sizden karar beklenmiyor.
        </p>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="empty-note">
          ContentOS çalışıyor, şu anda sizden karar bekleyen bir iş yok. Süreci
          <Link href="/calisma"> Çalışmalar</Link> alanından izleyebilirsiniz.
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
