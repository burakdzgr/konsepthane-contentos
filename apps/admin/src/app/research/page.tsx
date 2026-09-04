import Link from "next/link";

import { trLabel } from "@/lib/tr-labels";

import {
  DISCOVERY_LIFECYCLE_STATES,
  DISCOVERY_METHODS,
  DUPLICATE_OUTCOMES,
  FETCH_OUTCOMES,
  NORMALIZATION_STATUSES,
  fetchPipelineItems,
  isUuid,
  type PipelineListItem,
} from "@/lib/research-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  discoveryStateTone,
  duplicateOutcomeTone,
  evidenceCountTone,
  fetchOutcomeTone,
  normalizationStatusTone,
} from "@/lib/pipeline-display";
import {
  buildPageQuery,
  firstParam,
  parseBooleanParam,
  parseOffset,
  parseUrlSearchText,
  pickEnum,
  type RawSearchParams,
} from "@/lib/search-params";

// The operational pipeline view must reflect durable PostgreSQL state at
// request time; queue state never appears here.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type PipelineFilterState = {
  source?: string;
  state?: (typeof DISCOVERY_LIFECYCLE_STATES)[number];
  method?: (typeof DISCOVERY_METHODS)[number];
  fetch?: (typeof FETCH_OUTCOMES)[number];
  normalize?: (typeof NORMALIZATION_STATUSES)[number];
  duplicate?: (typeof DUPLICATE_OUTCOMES)[number];
  evidence?: boolean;
  q?: string;
  offset: number;
};

function parseFilters(params: RawSearchParams): PipelineFilterState {
  const source = firstParam(params.source);
  return {
    source: source !== undefined && isUuid(source) ? source : undefined,
    state: pickEnum(params.state, DISCOVERY_LIFECYCLE_STATES),
    method: pickEnum(params.method, DISCOVERY_METHODS),
    fetch: pickEnum(params.fetch, FETCH_OUTCOMES),
    normalize: pickEnum(params.normalize, NORMALIZATION_STATUSES),
    duplicate: pickEnum(params.duplicate, DUPLICATE_OUTCOMES),
    evidence: parseBooleanParam(params.evidence),
    q: parseUrlSearchText(params.q),
    offset: parseOffset(params.offset),
  };
}

function pageHref(filters: PipelineFilterState, offset: number): string {
  return `/research${buildPageQuery({
    source: filters.source,
    state: filters.state,
    method: filters.method,
    fetch: filters.fetch,
    normalize: filters.normalize,
    duplicate: filters.duplicate,
    evidence: filters.evidence,
    q: filters.q,
    offset: offset > 0 ? offset : undefined,
  })}`;
}

function EnumSelect({
  label,
  name,
  values,
  selected,
}: {
  label: string;
  name: string;
  values: readonly string[];
  selected: string | undefined;
}) {
  return (
    <label>
      {label}
      <select name={name} defaultValue={selected ?? ""}>
        <option value="">Tümü</option>
        {values.map((value) => (
          <option key={value} value={value}>
            {trLabel(value)}
          </option>
        ))}
      </select>
    </label>
  );
}

function FilterForm({ filters }: { filters: PipelineFilterState }) {
  return (
    <form className="filter-form" method="get" action="/research">
      {filters.source !== undefined && (
        <input type="hidden" name="source" value={filters.source} />
      )}
      <EnumSelect
        label="Keşif"
        name="state"
        values={DISCOVERY_LIFECYCLE_STATES}
        selected={filters.state}
      />
      <EnumSelect
        label="Yöntem"
        name="method"
        values={DISCOVERY_METHODS}
        selected={filters.method}
      />
      <EnumSelect
        label="Getirme"
        name="fetch"
        values={FETCH_OUTCOMES}
        selected={filters.fetch}
      />
      <EnumSelect
        label="Normalleştirme"
        name="normalize"
        values={NORMALIZATION_STATUSES}
        selected={filters.normalize}
      />
      <EnumSelect
        label="Kopya"
        name="duplicate"
        values={DUPLICATE_OUTCOMES}
        selected={filters.duplicate}
      />
      <label>
        Kanıt
        <select
          name="evidence"
          defaultValue={
            filters.evidence === undefined ? "" : String(filters.evidence)
          }
        >
          <option value="">Tümü</option>
          <option value="true">kanıt var</option>
          <option value="false">kanıt yok</option>
        </select>
      </label>
      <label>
        URL içerir
        <input
          type="text"
          name="q"
          defaultValue={filters.q ?? ""}
          maxLength={200}
          placeholder="kanonik URL parçası"
        />
      </label>
      <button type="submit">Uygula</button>
    </form>
  );
}

function FetchCell({ item }: { item: PipelineListItem }) {
  if (item.fetch_outcome === null) {
    return <span className="muted">—</span>;
  }
  return (
    <span className="badge" data-tone={fetchOutcomeTone(item.fetch_outcome)}>
      {trLabel(item.fetch_outcome)}
      {item.status_code !== null ? ` ${item.status_code}` : ""}
    </span>
  );
}

function NormalizeCell({ item }: { item: PipelineListItem }) {
  if (item.normalization_status === null) {
    return <span className="muted">—</span>;
  }
  return (
    <span
      className="badge"
      data-tone={normalizationStatusTone(item.normalization_status)}
    >
      {trLabel(item.normalization_status)}
      {item.normalization_failure_code !== null
        ? ` (${trLabel(item.normalization_failure_code)})`
        : ""}
    </span>
  );
}

function DuplicateCell({ item }: { item: PipelineListItem }) {
  if (item.duplicate_outcome === null) {
    return <span className="muted">—</span>;
  }
  return (
    <span
      className="badge"
      data-tone={duplicateOutcomeTone(item.duplicate_outcome)}
    >
      {trLabel(item.duplicate_outcome)}
    </span>
  );
}

export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const filters = parseFilters(await searchParams);
  const result = await fetchPipelineItems({
    sourceId: filters.source,
    lifecycleState: filters.state,
    discoveryMethod: filters.method,
    fetchOutcome: filters.fetch,
    normalizationStatus: filters.normalize,
    duplicateOutcome: filters.duplicate,
    hasEvidence: filters.evidence,
    urlContains: filters.q,
    limit: PAGE_SIZE,
    offset: filters.offset,
  });

  return (
    <section className="panel panel-wide" aria-labelledby="research-title">
      <h1 id="research-title">Araştırma Hattı</h1>
      <p className="muted">
        Keşfedilen her URL&apos;ye aşama aşama ne olduğu, kalıcı durumdan. Salt
        okunur.
      </p>
      <FilterForm filters={filters} />
      {result.kind === "unreachable" && (
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      )}
      {result.kind === "malformed" && (
        <p role="status">Arka uç API&apos;si beklenmeyen veri döndürdü.</p>
      )}
      {result.kind === "ok" && result.data.items.length === 0 && (
        <p className="empty-note" role="status">
          Geçerli görünümle eşleşen keşif öğesi yok.
        </p>
      )}
      {result.kind === "ok" && result.data.items.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Keşfedildi</th>
                  <th scope="col">Kaynak</th>
                  <th scope="col">URL</th>
                  <th scope="col">Keşif</th>
                  <th scope="col">Getirme</th>
                  <th scope="col">Normalleştirme</th>
                  <th scope="col">Kopya</th>
                  <th scope="col">Kanıt</th>
                  <th scope="col">Son görülme</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatUtcTimestamp(item.discovered_at)}</td>
                    <td title={item.source_name}>{item.source_slug}</td>
                    <td className="cell-url" title={item.canonical_url}>
                      <Link href={`/research/${item.id}`}>
                        {item.canonical_url}
                      </Link>
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-tone={discoveryStateTone(item.lifecycle_state)}
                      >
                        {trLabel(item.lifecycle_state)}
                      </span>
                      {item.rejection_reason !== null && (
                        <span className="muted cell-secondary">
                          {item.rejection_reason}
                        </span>
                      )}
                    </td>
                    <td>
                      <FetchCell item={item} />
                    </td>
                    <td>
                      <NormalizeCell item={item} />
                    </td>
                    <td>
                      <DuplicateCell item={item} />
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-tone={evidenceCountTone(item.evidence_count)}
                      >
                        {item.evidence_count}
                      </span>
                    </td>
                    <td>{formatUtcTimestamp(item.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pagination" aria-label="Hat sayfalaması">
            <span className="muted">
              {result.data.total} kayıttan {filters.offset + 1}–
              {filters.offset + result.data.items.length} gösteriliyor
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
    </section>
  );
}
