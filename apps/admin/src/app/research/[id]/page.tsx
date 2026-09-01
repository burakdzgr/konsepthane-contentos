import Link from "next/link";
import { notFound } from "next/navigation";

import {
  DISCOVERY_REJECTION_REASONS,
  fetchPipelineDetail,
  type PipelineDetail,
} from "@/lib/research-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  discoveryStateTone,
  duplicateOutcomeTone,
  fetchOutcomeTone,
  normalizationStatusTone,
} from "@/lib/pipeline-display";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import {
  acceptDiscoveryItemAction,
  rejectDiscoveryItemAction,
  requeueDiscoveryItemAction,
  startDiscoveryItemFetchAction,
} from "./actions";

// One DiscoveryItem's full pipeline history from durable state, at request
// time, plus the explicit operator decisions valid for its current state.
// No payload access, no article body, no pipeline-stage bypass.
export const dynamic = "force-dynamic";

const DETAIL_NOTICES: Record<string, string> = {
  accepted: "Item accepted. Starting the fetch is a separate action.",
  rejected: "Item rejected. Rejection is terminal.",
  requeued:
    "Item requeued as accepted. Starting the fetch is a separate action.",
  "fetch-queued":
    "Fetch queued. The pipeline continues automatically after a successful fetch.",
};

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function TruncationNote({
  shown,
  total,
  noun,
}: {
  shown: number;
  total: number;
  noun: string;
}) {
  if (total <= shown) {
    return null;
  }
  return (
    <p className="muted" role="note">
      Showing the latest {shown} of {total} {noun}.
    </p>
  );
}

function DiscoverySection({ detail }: { detail: PipelineDetail }) {
  const item = detail.discovery_item;
  return (
    <section aria-labelledby="detail-discovery">
      <h2 id="detail-discovery">Discovery</h2>
      <dl className="status-list">
        <Row name="State">
          <span
            className="badge"
            data-tone={discoveryStateTone(item.lifecycle_state)}
          >
            {item.lifecycle_state}
          </span>
        </Row>
        <Row name="Source">
          {detail.source.name}{" "}
          <span className="mono muted">({detail.source.slug})</span>
        </Row>
        <Row name="Canonical URL">
          <span className="cell-url" title={item.canonical_url}>
            {item.canonical_url}
          </span>
        </Row>
        {item.discovered_url !== item.canonical_url && (
          <Row name="Discovered URL">
            <span className="cell-url" title={item.discovered_url}>
              {item.discovered_url}
            </span>
          </Row>
        )}
        <Row name="Method">{item.discovery_method}</Row>
        {item.title_hint !== null && (
          <Row name="Title hint (untrusted)">{item.title_hint}</Row>
        )}
        {item.rejection_reason !== null && (
          <Row name="Rejection">
            {item.rejection_reason}
            {item.rejection_note !== null ? ` — ${item.rejection_note}` : ""}
          </Row>
        )}
        <Row name="Discovered at">{formatUtcTimestamp(item.discovered_at)}</Row>
        <Row name="Last seen">{formatUtcTimestamp(item.last_seen_at)}</Row>
        {item.external_published_at !== null && (
          <Row name="Source-claimed publish date">
            {formatUtcTimestamp(item.external_published_at)}
          </Row>
        )}
        <Row name="Item ID">
          <span className="mono muted">{item.id}</span>
        </Row>
      </dl>
    </section>
  );
}

function FetchSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-fetch">
      <h2 id="detail-fetch">Fetch history</h2>
      {detail.fetch_attempts.length === 0 && (
        <p className="empty-note">No fetch attempts recorded.</p>
      )}
      {detail.fetch_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Fetched</th>
                <th scope="col">Outcome</th>
                <th scope="col">Status</th>
                <th scope="col">Type</th>
                <th scope="col">Size</th>
                <th scope="col">Robots</th>
                <th scope="col">Retry</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {detail.fetch_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{formatUtcTimestamp(attempt.fetched_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={fetchOutcomeTone(attempt.fetch_outcome)}
                    >
                      {attempt.fetch_outcome}
                    </span>
                  </td>
                  <td>{attempt.status_code ?? "—"}</td>
                  <td>{attempt.content_type ?? "—"}</td>
                  <td>
                    {attempt.body_size_bytes !== null
                      ? `${attempt.body_size_bytes} B`
                      : "—"}
                  </td>
                  <td>{attempt.robots_decision}</td>
                  <td>{attempt.retry_classification}</td>
                  <td>{attempt.failure_detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.fetch_attempts.length}
        total={detail.total_fetch_attempts}
        noun="fetch attempts"
      />
    </section>
  );
}

function NormalizationSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-normalization">
      <h2 id="detail-normalization">Normalization history</h2>
      {detail.normalization_attempts.length === 0 && (
        <p className="empty-note">No normalization attempts recorded.</p>
      )}
      {detail.normalization_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Normalized</th>
                <th scope="col">Status</th>
                <th scope="col">Extractor</th>
                <th scope="col">Title</th>
                <th scope="col">Author</th>
                <th scope="col">Published</th>
                <th scope="col">Failure</th>
              </tr>
            </thead>
            <tbody>
              {detail.normalization_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{formatUtcTimestamp(attempt.normalized_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={normalizationStatusTone(
                        attempt.normalization_status,
                      )}
                    >
                      {attempt.normalization_status}
                    </span>
                  </td>
                  <td className="mono">
                    {attempt.extractor_name}/{attempt.extractor_version}
                  </td>
                  <td>{attempt.title ?? "—"}</td>
                  <td>{attempt.author_name ?? "—"}</td>
                  <td>{formatUtcTimestamp(attempt.external_published_at)}</td>
                  <td>
                    {attempt.failure_code ?? "—"}
                    {attempt.failure_detail !== null
                      ? ` — ${attempt.failure_detail}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.normalization_attempts.length}
        total={detail.total_normalization_attempts}
        noun="normalization attempts"
      />
    </section>
  );
}

function DuplicateSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-duplicates">
      <h2 id="detail-duplicates">Duplicate decisions</h2>
      {detail.duplicate_decisions.length === 0 && (
        <p className="empty-note">No duplicate decisions recorded.</p>
      )}
      {detail.duplicate_decisions.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Evaluated</th>
                <th scope="col">Decision</th>
                <th scope="col">Engine</th>
                <th scope="col">Rationale</th>
                <th scope="col">Matches</th>
                <th scope="col">Document</th>
              </tr>
            </thead>
            <tbody>
              {detail.duplicate_decisions.map((decision) => (
                <tr key={decision.id}>
                  <td>{formatUtcTimestamp(decision.evaluated_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={duplicateOutcomeTone(decision.decision)}
                    >
                      {decision.decision}
                    </span>
                  </td>
                  <td className="mono">
                    {decision.engine_name}/{decision.engine_version}
                  </td>
                  <td>
                    {decision.rationale_codes.length > 0
                      ? decision.rationale_codes.join(", ")
                      : "—"}
                  </td>
                  <td>{decision.match_count}</td>
                  <td className="mono muted">
                    {decision.normalized_document_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.duplicate_decisions.length}
        total={detail.total_duplicate_decisions}
        noun="duplicate decisions"
      />
    </section>
  );
}

function EvidenceSection({ detail }: { detail: PipelineDetail }) {
  const evidence = detail.evidence;
  return (
    <section aria-labelledby="detail-evidence">
      <h2 id="detail-evidence">Evidence summary</h2>
      <p className="muted">
        Counts only: evidence statements and excerpts are not shown here.
      </p>
      <dl className="status-list">
        <Row name="Total evidence">{evidence.total}</Row>
        <Row name="By verification status">
          {Object.entries(evidence.by_verification_status)
            .map(([status, count]) => `${status}: ${count}`)
            .join(" · ") || "—"}
        </Row>
        <Row name="By evidence type">
          {Object.entries(evidence.by_evidence_type)
            .map(([type, count]) => `${type}: ${count}`)
            .join(" · ") || "—"}
        </Row>
        <Row name="Newest evidence">
          {formatUtcTimestamp(evidence.latest_extracted_at)}
        </Row>
      </dl>
    </section>
  );
}

function ActionPanel({ detail }: { detail: PipelineDetail }) {
  const item = detail.discovery_item;
  const state = item.lifecycle_state;
  return (
    <section aria-labelledby="detail-actions">
      <h2 id="detail-actions">Operator actions</h2>
      {state === "discovered" && (
        <div className="control-stack">
          <form action={acceptDiscoveryItemAction} className="control-form">
            <input type="hidden" name="discovery_item_id" value={item.id} />
            <button type="submit">Accept</button>
            <span className="muted">
              Accept admits the item for fetching; fetch stays a separate
              action.
            </span>
          </form>
          <form action={rejectDiscoveryItemAction} className="control-form">
            <input type="hidden" name="discovery_item_id" value={item.id} />
            <select
              name="reason"
              required
              defaultValue=""
              aria-label="Rejection reason"
            >
              <option value="" disabled>
                Rejection reason…
              </option>
              {DISCOVERY_REJECTION_REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {reason}
                </option>
              ))}
            </select>
            <input
              type="text"
              name="note"
              maxLength={2000}
              placeholder="optional note"
              aria-label="Rejection note"
            />
            <button type="submit">Reject</button>
          </form>
        </div>
      )}
      {state === "accepted" && (
        <form action={startDiscoveryItemFetchAction} className="control-form">
          <input type="hidden" name="discovery_item_id" value={item.id} />
          <button type="submit">Start fetch</button>
          <span className="muted">
            After a successful fetch the pipeline continues automatically:
            normalize → duplicate check → evidence.
          </span>
        </form>
      )}
      {state === "fetch_failed" && (
        <form action={requeueDiscoveryItemAction} className="control-form">
          <input type="hidden" name="discovery_item_id" value={item.id} />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="reason for requeueing"
            aria-label="Requeue reason"
          />
          <button type="submit">Requeue</button>
          <span className="muted">
            Requeue returns the item to accepted; it does not start the fetch.
          </span>
        </form>
      )}
      {state === "fetched" && (
        <p className="muted">
          This item is fetched; the pipeline ran from its snapshot. No actions
          are available here.
        </p>
      )}
      {state === "rejected" && (
        <p className="muted">
          This item is rejected. Rejection is terminal; no actions are
          available.
        </p>
      )}
    </section>
  );
}

export default async function ResearchDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<RawSearchParams>;
}) {
  const { id } = await params;
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchPipelineDetail(id);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="detail-title">
        <h1 id="detail-title">Discovery item</h1>
        <p role="status">The backend API cannot be reached right now.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="detail-title">
        <h1 id="detail-title">Discovery item</h1>
        <p role="status">The backend API returned unexpected data.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="detail-title">
      <h1 id="detail-title">Discovery item</h1>
      <p className="muted">
        <Link href="/research">← Back to Research Pipeline</Link>
      </p>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={DETAIL_NOTICES}
      />
      <DiscoverySection detail={detail} />
      <ActionPanel detail={detail} />
      <FetchSection detail={detail} />
      <NormalizationSection detail={detail} />
      <DuplicateSection detail={detail} />
      <EvidenceSection detail={detail} />
    </section>
  );
}
