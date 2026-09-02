import Link from "next/link";

import {
  OPPORTUNITY_DISPOSITIONS,
  QUEUE_FILTER_STATES,
  fetchWorkQueue,
  type WorkQueueRow,
} from "@/lib/editorial-api";
import { formatUtcTimestamp } from "@/lib/format";
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
    "Promotion queued. The work item appears here once the worker records it.",
  "duplicate-reopened":
    "Duplicate reopened as an operator work item. Scoring is a separate explicit action.",
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
        Workflow state
        <select name="state" defaultValue={filters.state ?? ""}>
          <option value="">Any</option>
          {QUEUE_FILTER_STATES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <label>
        Disposition
        <select name="disposition" defaultValue={filters.disposition ?? ""}>
          <option value="">Any</option>
          {OPPORTUNITY_DISPOSITIONS.map((value) => (
            <option key={value} value={value}>
              {value}
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
          placeholder="title or topic fragment"
        />
      </label>
      <button type="submit">Apply</button>
    </form>
  );
}

function ScoreCell({ row }: { row: WorkQueueRow }) {
  if (row.score_id === null) {
    return <span className="muted">Not evaluated</span>;
  }
  return (
    <span>
      <span
        className="badge"
        data-tone={scoreEligibilityTone(row.score_eligibility)}
      >
        {row.score_band} / {row.score_eligibility}
      </span>
      {row.score_missing_signals.length > 0 && (
        <span className="muted cell-secondary">
          {row.score_missing_signals.length} missing signals
        </span>
      )}
    </span>
  );
}

function IdeaCell({ row }: { row: WorkQueueRow }) {
  if (row.selected_idea_id === null) {
    return <span className="muted">No selection</span>;
  }
  return (
    <span>
      {row.selected_idea_title}
      <span className="muted cell-secondary">
        originality: {row.selected_idea_originality ?? "unknown"}
      </span>
    </span>
  );
}

function PackCell({ row }: { row: WorkQueueRow }) {
  if (row.latest_pack_id === null) {
    return <span className="muted">No pack</span>;
  }
  return (
    <span
      className="badge"
      data-tone={packSufficiencyTone(row.latest_pack_sufficiency)}
    >
      v{row.latest_pack_version} {row.latest_pack_sufficiency}
    </span>
  );
}

function BriefCell({ row }: { row: WorkQueueRow }) {
  if (row.latest_brief_id === null) {
    return <span className="muted">No brief</span>;
  }
  return (
    <span
      className="badge"
      data-tone={briefStatusTone(row.latest_brief_status)}
    >
      v{row.latest_brief_version} {row.latest_brief_status}
    </span>
  );
}

function ResearchIntakeForms() {
  return (
    <section aria-labelledby="editorial-intake">
      <h2 id="editorial-intake">Research intake</h2>
      <div className="control-stack">
        <form action={promoteResearchAction} className="control-form">
          <input
            type="text"
            name="normalized_document_id"
            required
            maxLength={36}
            placeholder="normalized document id"
            aria-label="Normalized document id to promote"
          />
          <button type="submit">Promote research</button>
          <span className="muted">
            Queues promotion of an eligible normalized document; the worker
            applies the duplicate gates.
          </span>
        </form>
        <form action={reopenDuplicateAction} className="control-form">
          <input
            type="text"
            name="normalized_document_id"
            required
            maxLength={36}
            placeholder="normalized document id"
            aria-label="Duplicate document id to reopen"
          />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="reason"
            aria-label="Reopen reason"
          />
          <input
            type="text"
            name="distinct_angle"
            required
            maxLength={1000}
            placeholder="demonstrably distinct angle"
            aria-label="Distinct angle"
          />
          <button type="submit">Reopen duplicate</button>
          <span className="muted">
            Operator override for an effective DUPLICATE decision; the decision
            itself is never altered.
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
      <h1 id="editorial-title">Editorial Work Queue</h1>
      <p className="muted">
        Phase-3 editorial pipeline: research promotion through accepted brief.
        Every state and artifact comes from durable records; nothing here
        publishes content.
      </p>
      <ControlNotice
        notice={firstParam(rawParams.notice)}
        error={firstParam(rawParams.error)}
        noticeMessages={QUEUE_NOTICES}
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
          No editorial work items match the current view.
        </p>
      )}
      {result.kind === "ok" && result.data.items.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Work item</th>
                  <th scope="col">State</th>
                  <th scope="col">Disposition</th>
                  <th scope="col">Score</th>
                  <th scope="col">Selected idea</th>
                  <th scope="col">Evidence pack</th>
                  <th scope="col">Brief</th>
                  <th scope="col">Entered state</th>
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
                        {row.current_state}
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
                    <td>{row.disposition ?? "—"}</td>
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
          <nav className="pagination" aria-label="Editorial queue pagination">
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
      <ResearchIntakeForms />
    </section>
  );
}
