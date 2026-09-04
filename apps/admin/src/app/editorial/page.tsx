import Link from "next/link";

import {
  OPPORTUNITY_DISPOSITIONS,
  QUEUE_FILTER_STATES,
  fetchWorkQueue,
  type WorkQueueRow,
} from "@/lib/editorial-api";
import { formatUtcTimestamp } from "@/lib/format";
import { trLabel } from "@/lib/tr-labels";
import {
  briefStatusTone,
  packSufficiencyTone,
  scoreEligibilityTone,
  workflowStateTone,
} from "@/lib/editorial-display";
import {
  buildPageQuery,
  firstParam,
  parseOffset,
  parseSearchText,
  pickEnum,
  type RawSearchParams,
} from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { promoteResearchAction, reopenDuplicateAction } from "./actions";

const QUEUE_NOTICES: Record<string, string> = {
  "promotion-queued":
    "Yükseltme kuyruğa alındı. İş öğesi, worker kaydettiğinde burada görünür.",
  "duplicate-reopened":
    "Kopya, operatör iş öğesi olarak yeniden açıldı. Puanlama ayrı ve açık bir eylemdir.",
};

// The Phase-3 editorial work queue from durable PostgreSQL state at request
// time. Every projected artifact carries its truthful status; absent
// artifacts render as absent, never as progress.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type QueueFilterState = {
  state?: (typeof QUEUE_FILTER_STATES)[number];
  disposition?: (typeof OPPORTUNITY_DISPOSITIONS)[number];
  q?: string;
  offset: number;
};

function parseFilters(params: RawSearchParams): QueueFilterState {
  return {
    state: pickEnum(params.state, QUEUE_FILTER_STATES),
    disposition: pickEnum(params.disposition, OPPORTUNITY_DISPOSITIONS),
    q: parseSearchText(params.q),
    offset: parseOffset(params.offset),
  };
}

function pageHref(filters: QueueFilterState, offset: number): string {
  return `/editorial${buildPageQuery({
    state: filters.state,
    disposition: filters.disposition,
    q: filters.q,
    offset: offset > 0 ? offset : undefined,
  })}`;
}

function FilterForm({ filters }: { filters: QueueFilterState }) {
  return (
    <form className="filter-form" method="get" action="/editorial">
      <label>
        İş akışı durumu
        <select name="state" defaultValue={filters.state ?? ""}>
          <option value="">Tümü</option>
          {QUEUE_FILTER_STATES.map((value) => (
            <option key={value} value={value}>
              {trLabel(value)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Fırsat durumu
        <select name="disposition" defaultValue={filters.disposition ?? ""}>
          <option value="">Tümü</option>
          {OPPORTUNITY_DISPOSITIONS.map((value) => (
            <option key={value} value={value}>
              {trLabel(value)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Arama
        <input
          type="text"
          name="q"
          defaultValue={filters.q ?? ""}
          maxLength={100}
          placeholder="başlık veya konu parçası"
        />
      </label>
      <button type="submit">Uygula</button>
    </form>
  );
}

function ScoreCell({ row }: { row: WorkQueueRow }) {
  if (row.score_id === null) {
    return <span className="muted">Değerlendirilmedi</span>;
  }
  return (
    <span>
      <span
        className="badge"
        data-tone={scoreEligibilityTone(row.score_eligibility)}
      >
        {trLabel(row.score_band)} / {trLabel(row.score_eligibility)}
      </span>
      {row.score_missing_signals.length > 0 && (
        <span className="muted cell-secondary">
          {row.score_missing_signals.length} eksik sinyal
        </span>
      )}
    </span>
  );
}

function IdeaCell({ row }: { row: WorkQueueRow }) {
  if (row.selected_idea_id === null) {
    return <span className="muted">Seçim yok</span>;
  }
  return (
    <span>
      {row.selected_idea_title}
      <span className="muted cell-secondary">
        özgünlük: {trLabel(row.selected_idea_originality)}
      </span>
    </span>
  );
}

function PackCell({ row }: { row: WorkQueueRow }) {
  if (row.latest_pack_id === null) {
    return <span className="muted">Paket yok</span>;
  }
  return (
    <span
      className="badge"
      data-tone={packSufficiencyTone(row.latest_pack_sufficiency)}
    >
      v{row.latest_pack_version} {trLabel(row.latest_pack_sufficiency)}
    </span>
  );
}

function BriefCell({ row }: { row: WorkQueueRow }) {
  if (row.latest_brief_id === null) {
    return <span className="muted">Brief yok</span>;
  }
  return (
    <span
      className="badge"
      data-tone={briefStatusTone(row.latest_brief_status)}
    >
      v{row.latest_brief_version} {trLabel(row.latest_brief_status)}
    </span>
  );
}

function ResearchIntakeForms() {
  return (
    <section aria-labelledby="editorial-intake">
      <h2 id="editorial-intake">Araştırma girişi</h2>
      <div className="control-stack">
        <form action={promoteResearchAction} className="control-form">
          <input
            type="text"
            name="normalized_document_id"
            required
            maxLength={36}
            placeholder="normalize edilmiş doküman kimliği"
            aria-label="Yükseltilecek normalize edilmiş doküman kimliği"
          />
          <button type="submit">Araştırmayı yükselt</button>
          <span className="muted">
            Uygun bir normalize edilmiş dokümanın yükseltilmesini kuyruğa alır;
            kopya kapılarını worker uygular.
          </span>
        </form>
        <form action={reopenDuplicateAction} className="control-form">
          <input
            type="text"
            name="normalized_document_id"
            required
            maxLength={36}
            placeholder="normalize edilmiş doküman kimliği"
            aria-label="Yeniden açılacak kopya doküman kimliği"
          />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="gerekçe"
            aria-label="Yeniden açma gerekçesi"
          />
          <input
            type="text"
            name="distinct_angle"
            required
            maxLength={1000}
            placeholder="kanıtlanabilir şekilde farklı bir açı"
            aria-label="Farklı açı"
          />
          <button type="submit">Kopyayı yeniden aç</button>
          <span className="muted">
            Geçerli bir DUPLICATE kararı için operatör müdahalesi; kararın
            kendisi asla değiştirilmez.
          </span>
        </form>
      </div>
    </section>
  );
}

export default async function EditorialPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const rawParams = await searchParams;
  const filters = parseFilters(rawParams);
  const result = await fetchWorkQueue({
    workflowState: filters.state,
    opportunityDisposition: filters.disposition,
    search: filters.q,
    limit: PAGE_SIZE,
    offset: filters.offset,
  });

  return (
    <section className="panel panel-wide" aria-labelledby="editorial-title">
      <h1 id="editorial-title">Editoryal İş Kuyruğu</h1>
      <p className="muted">
        Faz-3 editoryal hattı: araştırma yükseltmesinden kabul edilmiş
        brief&apos;e kadar. Her durum ve artefakt kalıcı kayıtlardan gelir;
        buradaki hiçbir şey içerik yayınlamaz.
      </p>
      <ControlNotice
        notice={firstParam(rawParams.notice)}
        error={firstParam(rawParams.error)}
        noticeMessages={QUEUE_NOTICES}
      />
      <FilterForm filters={filters} />
      {result.kind === "unreachable" && (
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      )}
      {result.kind === "malformed" && (
        <p role="status">Arka uç API&apos;si beklenmedik veri döndürdü.</p>
      )}
      {result.kind === "ok" && result.data.items.length === 0 && (
        <p className="empty-note" role="status">
          Geçerli görünümle eşleşen editoryal iş öğesi yok.
        </p>
      )}
      {result.kind === "ok" && result.data.items.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">İş öğesi</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Fırsat durumu</th>
                  <th scope="col">Skor</th>
                  <th scope="col">Seçili fikir</th>
                  <th scope="col">Kanıt paketi</th>
                  <th scope="col">Brief</th>
                  <th scope="col">Duruma giriş</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((row) => (
                  <tr key={row.work_item_id}>
                    <td title={row.topic_summary ?? undefined}>
                      <Link href={`/editorial/${row.work_item_id}`}>
                        {row.title_working_label}
                      </Link>
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-tone={workflowStateTone(row.current_state)}
                      >
                        {trLabel(row.current_state)}
                      </span>
                      {row.blocked_reason !== null && (
                        <span className="muted cell-secondary">
                          {row.blocked_reason}
                        </span>
                      )}
                      {row.rejected_reason !== null && (
                        <span className="muted cell-secondary">
                          {row.rejected_reason}
                        </span>
                      )}
                    </td>
                    <td>{trLabel(row.disposition)}</td>
                    <td>
                      <ScoreCell row={row} />
                    </td>
                    <td>
                      <IdeaCell row={row} />
                    </td>
                    <td>
                      <PackCell row={row} />
                    </td>
                    <td>
                      <BriefCell row={row} />
                    </td>
                    <td>{formatUtcTimestamp(row.current_state_entered_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pagination" aria-label="Editoryal kuyruk sayfalaması">
            <span className="muted">
              {filters.offset + 1}–{filters.offset + result.data.items.length} /{" "}
              {result.data.total} gösteriliyor
            </span>
            {filters.offset > 0 && (
              <Link
                href={pageHref(
                  filters,
                  Math.max(filters.offset - PAGE_SIZE, 0),
                )}
              >
                Önceki
              </Link>
            )}
            {filters.offset + result.data.items.length < result.data.total && (
              <Link href={pageHref(filters, filters.offset + PAGE_SIZE)}>
                Sonraki
              </Link>
            )}
          </nav>
        </>
      )}
      <ResearchIntakeForms />
    </section>
  );
}
