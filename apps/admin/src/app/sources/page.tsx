import Link from "next/link";

import {
  DISCOVERY_STRATEGIES,
  SOURCE_KINDS,
  SOURCE_LIFECYCLE_STATES,
  fetchResearchSources,
  type SourceListItem,
} from "@/lib/research-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  allowedLifecycleTargets,
  isDiscoveryEligible,
} from "@/lib/source-controls";
import {
  buildPageQuery,
  firstParam,
  parseOffset,
  parseSearchText,
  pickEnum,
  type RawSearchParams,
} from "@/lib/search-params";
import { ControlNotice } from "../notices";
import {
  runSourceDiscoveryAction,
  transitionSourceLifecycleAction,
} from "./actions";

const SOURCE_NOTICES: Record<string, string> = {
  "source-registered":
    "Source registered. Registering a source does not automatically crawl it.",
  "source-existing":
    "An identical source already existed; nothing was changed.",
  "lifecycle-updated": "Source lifecycle updated.",
  "discovery-queued": "Discovery queued.",
};

// Operational registry data must reflect the moment of the request.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type SourceFilterState = {
  state?: (typeof SOURCE_LIFECYCLE_STATES)[number];
  kind?: (typeof SOURCE_KINDS)[number];
  strategy?: (typeof DISCOVERY_STRATEGIES)[number];
  q?: string;
  offset: number;
};

function parseFilters(params: RawSearchParams): SourceFilterState {
  return {
    state: pickEnum(params.state, SOURCE_LIFECYCLE_STATES),
    kind: pickEnum(params.kind, SOURCE_KINDS),
    strategy: pickEnum(params.strategy, DISCOVERY_STRATEGIES),
    q: parseSearchText(params.q),
    offset: parseOffset(params.offset),
  };
}

function pageHref(filters: SourceFilterState, offset: number): string {
  return `/sources${buildPageQuery({
    state: filters.state,
    kind: filters.kind,
    strategy: filters.strategy,
    q: filters.q,
    offset: offset > 0 ? offset : undefined,
  })}`;
}

function itemCounts(source: SourceListItem): string {
  const parts: string[] = [];
  if (source.discovered_count > 0) parts.push(`${source.discovered_count} new`);
  if (source.accepted_count > 0)
    parts.push(`${source.accepted_count} accepted`);
  if (source.fetched_count > 0) parts.push(`${source.fetched_count} fetched`);
  if (source.fetch_failed_count > 0) {
    parts.push(`${source.fetch_failed_count} failed`);
  }
  if (source.rejected_count > 0)
    parts.push(`${source.rejected_count} rejected`);
  return parts.join(" · ");
}

function FilterForm({ filters }: { filters: SourceFilterState }) {
  return (
    <form className="filter-form" method="get" action="/sources">
      <label>
        State
        <select name="state" defaultValue={filters.state ?? ""}>
          <option value="">Any</option>
          {SOURCE_LIFECYCLE_STATES.map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>
      </label>
      <label>
        Kind
        <select name="kind" defaultValue={filters.kind ?? ""}>
          <option value="">Any</option>
          {SOURCE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {kind}
            </option>
          ))}
        </select>
      </label>
      <label>
        Strategy
        <select name="strategy" defaultValue={filters.strategy ?? ""}>
          <option value="">Any</option>
          {DISCOVERY_STRATEGIES.map((strategy) => (
            <option key={strategy} value={strategy}>
              {strategy}
            </option>
          ))}
        </select>
      </label>
      <label>
        Search
        <input
          type="text"
          name="q"
          defaultValue={filters.q ?? ""}
          maxLength={100}
          placeholder="slug or name"
        />
      </label>
      <button type="submit">Apply</button>
    </form>
  );
}

function SourceControls({ source }: { source: SourceListItem }) {
  return (
    <div className="control-stack">
      <form action={transitionSourceLifecycleAction} className="control-form">
        <input type="hidden" name="source_id" value={source.id} />
        <select
          name="new_state"
          required
          defaultValue=""
          aria-label={`New lifecycle state for ${source.slug}`}
        >
          <option value="" disabled>
            New state…
          </option>
          {allowedLifecycleTargets(source.lifecycle_state).map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>
        <input
          type="text"
          name="reason"
          required
          maxLength={1000}
          placeholder="reason"
          aria-label={`Reason for changing ${source.slug}`}
        />
        <button type="submit">Apply state</button>
      </form>
      {isDiscoveryEligible(source) && (
        <form action={runSourceDiscoveryAction} className="control-form">
          <input type="hidden" name="source_id" value={source.id} />
          <button type="submit">Run discovery</button>
        </form>
      )}
    </div>
  );
}

export default async function SourcesPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const params = await searchParams;
  const filters = parseFilters(params);
  const result = await fetchResearchSources({
    lifecycleState: filters.state,
    kind: filters.kind,
    discoveryStrategy: filters.strategy,
    search: filters.q,
    limit: PAGE_SIZE,
    offset: filters.offset,
  });

  return (
    <section className="panel" aria-labelledby="sources-title">
      <h1 id="sources-title">Sources</h1>
      <p className="muted">
        Governed research origins and their discovery-item counts.{" "}
        <Link href="/sources/new">Register source</Link>
      </p>
      <ControlNotice
        notice={firstParam(params.notice)}
        error={firstParam(params.error)}
        noticeMessages={SOURCE_NOTICES}
      />
      <FilterForm filters={filters} />
      {result.kind === "unreachable" && (
        <p role="status">The backend API cannot be reached right now.</p>
      )}
      {result.kind === "malformed" && (
        <p role="status">The backend API returned unexpected data.</p>
      )}
      {result.kind === "ok" && result.data.items.length === 0 && (
        <p className="empty-note" role="status">
          No sources match the current view.
        </p>
      )}
      {result.kind === "ok" && result.data.items.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Kind / Strategy</th>
                  <th scope="col">State</th>
                  <th scope="col">Trust</th>
                  <th scope="col">Locale</th>
                  <th scope="col">Discovery items</th>
                  <th scope="col">Base URL</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Controls</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <span className="cell-primary">{source.name}</span>
                      <span className="mono muted cell-secondary">
                        {source.slug}
                      </span>
                    </td>
                    <td>
                      {source.kind} / {source.discovery_strategy}
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-tone={
                          source.lifecycle_state === "active"
                            ? "ok"
                            : source.lifecycle_state === "blocked"
                              ? "bad"
                              : "warn"
                        }
                      >
                        {source.lifecycle_state}
                      </span>
                    </td>
                    <td>{source.trust_tier}</td>
                    <td>
                      {source.locale} / {source.market}
                    </td>
                    <td>
                      <Link href={`/research?source=${source.id}`}>
                        {source.total_discovery_items} items
                      </Link>
                      {source.total_discovery_items > 0 && (
                        <span className="muted cell-secondary">
                          {itemCounts(source)}
                        </span>
                      )}
                    </td>
                    <td className="cell-url" title={source.base_url}>
                      {source.base_url}
                    </td>
                    <td>{formatUtcTimestamp(source.updated_at)}</td>
                    <td>
                      <SourceControls source={source} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pagination" aria-label="Sources pagination">
            <span className="muted">
              Showing {filters.offset + 1}–
              {filters.offset + result.data.items.length} of {result.data.total}
            </span>
            {filters.offset > 0 && (
              <Link
                href={pageHref(
                  filters,
                  Math.max(filters.offset - PAGE_SIZE, 0),
                )}
              >
                Previous
              </Link>
            )}
            {filters.offset + result.data.items.length < result.data.total && (
              <Link href={pageHref(filters, filters.offset + PAGE_SIZE)}>
                Next
              </Link>
            )}
          </nav>
        </>
      )}
    </section>
  );
}
