import Link from "next/link";
import { notFound } from "next/navigation";

import {
  fetchDraftDetail,
  type DraftClaimUsageView,
  type DraftDetail,
} from "@/lib/editorial-api";
import {
  draftStatusTone,
  generationStatusTone,
  verdictLabel,
  verdictTone,
} from "@/lib/editorial-display";
import { formatUtcTimestamp } from "@/lib/format";

// One durable draft version in full: the validated body, the claim ->
// evidence provenance chain, policy verdicts exactly as persisted (UNKNOWN
// stays UNKNOWN), the supersession audit trail, and safe attempt metadata.
// Read-only: every command lives on the work-item page.
export const dynamic = "force-dynamic";

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function SummarySection({ detail }: { detail: DraftDetail }) {
  const draft = detail.draft;
  return (
    <section aria-labelledby="draft-summary">
      <h2 id="draft-summary">Draft version</h2>
      <dl className="status-list">
        <Row name="Version">v{draft.version}</Row>
        <Row name="Origin">
          {draft.origin === "operator" ? "operator" : "writer engine"} (
          <span className="mono">
            {draft.engine_name}/{draft.engine_version}
          </span>
          )
        </Row>
        <Row name="Status">
          <span className="badge" data-tone={draftStatusTone(draft.status)}>
            {draft.status}
          </span>
          {draft.superseded_by_draft_id !== null && (
            <>
              {" "}
              <Link
                href={`/editorial/${draft.work_item_id}/drafts/${draft.superseded_by_draft_id}`}
              >
                superseded by newer version
              </Link>
            </>
          )}
        </Row>
        <Row name="Title proposal">{draft.title_proposal ?? "—"}</Row>
        <Row name="Uncertainty coverage">
          <span
            className="badge"
            data-tone={verdictTone(draft.uncertainty_coverage_status)}
          >
            {verdictLabel(draft.uncertainty_coverage_status)}
          </span>
        </Row>
        <Row name="Originality">
          <span
            className="badge"
            data-tone={verdictTone(draft.originality_outcome)}
          >
            {verdictLabel(draft.originality_outcome)}
          </span>
        </Row>
        <Row name="Body schema">
          <span className="mono">{draft.body_schema_version}</span>
        </Row>
        <Row name="Content hash">
          <span className="mono">{draft.content_hash}</span>
        </Row>
        <Row name="Brief">
          <span className="mono">{draft.content_brief_id}</span>
        </Row>
        <Row name="Created">{formatUtcTimestamp(draft.created_at)}</Row>
      </dl>
    </section>
  );
}

function BodySection({ detail }: { detail: DraftDetail }) {
  return (
    <section aria-labelledby="draft-body">
      <h2 id="draft-body">Body</h2>
      {detail.body.sections.map((section) => (
        <article key={section.key} className="card">
          <h3>
            {section.heading}{" "}
            <span className="mono muted">({section.key})</span>
          </h3>
          {section.blocks.map((block) => (
            <div key={block.block_id} className="status-row">
              <dt>
                <span className="mono">{block.block_id}</span>
                <br />
                <span className="badge" data-tone="neutral">
                  {block.kind}
                </span>
              </dt>
              <dd>
                <p>{block.text}</p>
                {block.claim_refs.length > 0 && (
                  <p className="mono muted">
                    claims: {block.claim_refs.join(", ")}
                  </p>
                )}
                {block.uncertainty_refs.length > 0 && (
                  <p className="mono muted">
                    uncertainty: {block.uncertainty_refs.join(", ")}
                  </p>
                )}
                {block.link_need_ref !== undefined && (
                  <p className="mono muted">
                    internal link need #{block.link_need_ref} (from the brief)
                  </p>
                )}
                {block.media_need_ref !== undefined && (
                  <p className="mono muted">
                    media need #{block.media_need_ref} (from the brief)
                  </p>
                )}
              </dd>
            </div>
          ))}
        </article>
      ))}
    </section>
  );
}

function ClaimChainSection({ usages }: { usages: DraftClaimUsageView[] }) {
  return (
    <section aria-labelledby="draft-claims">
      <h2 id="draft-claims">Claim → evidence chain</h2>
      <p className="muted">
        Every claim used in the body, bound to its brief claim and the exact
        ResearchEvidence identities behind it.
      </p>
      {usages.length === 0 && (
        <p className="empty-note">This draft binds no claims.</p>
      )}
      {usages.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Block</th>
                <th scope="col">Claim</th>
                <th scope="col">Kind</th>
                <th scope="col">Handling</th>
                <th scope="col">Evidence IDs</th>
              </tr>
            </thead>
            <tbody>
              {usages.map((usage) => (
                <tr key={usage.id}>
                  <td className="mono">
                    {usage.section_key}/{usage.block_id}
                  </td>
                  <td>
                    <span className="mono">{usage.claim_key}</span>
                    <br />
                    {usage.claim_text}
                  </td>
                  <td>{usage.claim_kind}</td>
                  <td>{usage.handling ?? "—"}</td>
                  <td className="mono">
                    {usage.research_evidence_ids.length > 0
                      ? usage.research_evidence_ids.join(", ")
                      : "none recorded"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AuditSection({ detail }: { detail: DraftDetail }) {
  return (
    <section aria-labelledby="draft-audit">
      <h2 id="draft-audit">Supersession audit</h2>
      {detail.status_events.length === 0 && (
        <p className="empty-note">No status changes recorded.</p>
      )}
      {detail.status_events.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Change</th>
                <th scope="col">Actor</th>
                <th scope="col">Reason</th>
                <th scope="col">Replacement</th>
              </tr>
            </thead>
            <tbody>
              {detail.status_events.map((event) => (
                <tr key={event.id}>
                  <td>{formatUtcTimestamp(event.occurred_at)}</td>
                  <td>
                    {event.from_status} → {event.to_status}
                  </td>
                  <td>{event.actor_origin}</td>
                  <td>{event.reason}</td>
                  <td className="mono">{event.replacement_draft_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AttemptsSection({ detail }: { detail: DraftDetail }) {
  return (
    <section aria-labelledby="draft-attempts">
      <h2 id="draft-attempts">Writer generation attempts</h2>
      <p className="muted">
        Safe persisted metadata only — failed attempts stay visible; prompts and
        raw model output are never stored and never shown.
      </p>
      {detail.generation_attempts.length === 0 && (
        <p className="empty-note">
          No writer generation attempts exist for this brief.
        </p>
      )}
      {detail.generation_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Retry</th>
                <th scope="col">Provider / model</th>
                <th scope="col">Schema</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {detail.generation_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>
                    <span
                      className="badge"
                      data-tone={generationStatusTone(attempt.status)}
                    >
                      {attempt.status}
                    </span>
                    {attempt.error_class !== null
                      ? ` (${attempt.error_class})`
                      : ""}
                  </td>
                  <td>{attempt.retry_number}</td>
                  <td className="mono">
                    {attempt.provider}/{attempt.model_name}
                  </td>
                  <td className="mono">
                    {attempt.schema_name}/{attempt.schema_version}
                  </td>
                  <td>{formatUtcTimestamp(attempt.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail.generation_attempts_truncated && (
        <p className="muted" role="note">
          Older attempts exist beyond the ones shown.
        </p>
      )}
    </section>
  );
}

export default async function DraftDetailPage({
  params,
}: {
  params: Promise<{ id: string; draftId: string }>;
}) {
  const { id, draftId } = await params;
  const result = await fetchDraftDetail(draftId);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="draft-detail-title">
        <h1 id="draft-detail-title">Writer draft</h1>
        <p role="status">The backend API cannot be reached right now.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="draft-detail-title">
        <h1 id="draft-detail-title">Writer draft</h1>
        <p role="status">The backend API returned unexpected data.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="draft-detail-title">
      <h1 id="draft-detail-title">Writer draft</h1>
      <p className="muted">
        <Link href={`/editorial/${id}`}>← Back to the work item</Link>
      </p>
      <SummarySection detail={detail} />
      <BodySection detail={detail} />
      <ClaimChainSection usages={detail.claim_usages} />
      <AuditSection detail={detail} />
      <AttemptsSection detail={detail} />
    </section>
  );
}
