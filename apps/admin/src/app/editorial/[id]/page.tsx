import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchCurrentUser } from "@/lib/auth-api";
import {
  RESOLVED_CONTRADICTION_STATUSES,
  fetchEligibleEvidence,
  fetchWorkItemDetail,
  fetchWorkItemDecisions,
  fetchWorkItemDrafts,
  fetchWorkItemMedia,
  fetchWorkItemPublication,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
  type AiAttemptView,
  type BriefView,
  type ContradictionView,
  type DecisionListPage,
  type DraftListPage,
  type MediaCoveragePage,
  type MediaSatisfactionView,
  type PublicationPage,
  type QaReportListPage,
  type ReviewListPage,
  type EligibleEvidenceItem,
  type IdeaView,
  type IntentAnalysisView,
  type PackView,
  type ScoreView,
  type WorkItemDetail,
} from "@/lib/editorial-api";
import {
  briefStatusTone,
  cannibalizationLabel,
  contradictionResolutionTone,
  draftStatusTone,
  generationStatusTone,
  originalityTone,
  packSufficiencyTone,
  reviewVerdictTone,
  scoreEligibilityTone,
  verdictLabel,
  verdictTone,
  workflowStateTone,
} from "@/lib/editorial-display";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import {
  acceptBriefAction,
  acceptReviewAction,
  analyzeSearchIntentAction,
  approvePackageAction,
  assemblePublicationPackageAction,
  bindMediaAssetAction,
  publishWorkItemAction,
  resolveApprovalExpiredAction,
  schedulePublicationAction,
  generateMediaImageAction,
  unbindMediaAction,
  uploadAndBindMediaAction,
  buildEvidencePackAction,
  commissionOpportunityAction,
  composeBriefAction,
  deselectIdeaAction,
  evaluateOpportunityAction,
  generateDraftAction,
  generateEditorReviewAction,
  generateIdeasAction,
  reassemblePackAction,
  rejectBlockedAction,
  rejectOpportunityAction,
  rejectPackageAction,
  requestChangesDecisionAction,
  requestReworkAction,
  revokeApprovalAction,
  resolveBlockAction,
  resolveChangesRequestedAction,
  resolveContradictionAction,
  runQaAction,
  selectIdeaAction,
  submitDraftAction,
  waiveQaGateAction,
} from "./actions";

// One editorial work item's full explainability projection from durable
// state, plus exactly the explicit operator commands its current state
// admits. The backend fail-closes every rule; this page never bypasses one.
export const dynamic = "force-dynamic";

const DETAIL_NOTICES: Record<string, string> = {
  "evaluation-queued": "Scoring queued. Reload to see the new evaluation.",
  commissioned: "Opportunity commissioned. Idea work can begin.",
  "opportunity-rejected": "Opportunity rejected with your reason.",
  "ideas-queued":
    "Idea generation queued. Candidates appear when the worker finishes.",
  "idea-selected": "Idea version selected.",
  "idea-deselected": "Selection cleared. Nothing is selected now.",
  "pack-queued": "Evidence pack assembly queued with your explicit selections.",
  "contradiction-resolved":
    "Contradiction resolved. The old pack keeps its sufficiency; reassemble to reflect the resolution.",
  "pack-reassembled":
    "New pack version created. Continuing with it is the next explicit step.",
  "block-resolved": "Block resolved back to the prior state.",
  "blocked-rejected": "Blocked work item rejected.",
  "analysis-queued": "Search-intent analysis queued with your exact pins.",
  "compose-queued": "Brief composition queued. The result is a DRAFT.",
  "brief-accepted":
    "Brief accepted for drafting. This does not publish content.",
  "duplicate-reopened": "Duplicate reopened as this operator work item.",
  "draft-queued":
    "Writer draft generation queued. The draft appears when the worker finishes.",
  "draft-submitted":
    "Operator draft stored through the full gates; the item moved to editing.",
  "rework-requested":
    "Rework recorded: changes requested with the writer stage responsible.",
  "changes-request-resolved":
    "Routed out of changes-requested to the recorded responsible state.",
  "review-queued":
    "Editor review queued. The verdict appears when the worker finishes.",
  "review-accepted":
    "Review accepted; the item moved to QA review. This does not publish content.",
  "qa-queued": "QA gate run queued. Re-runs are idempotent.",
  "qa-gate-waived":
    "Waiver recorded and audited. Gates were NOT re-run — run QA explicitly.",
  "package-approved":
    "Package approved by you, on the record. Scheduling belongs to a later phase.",
  "decision-changes-requested":
    "Change request recorded and routed to the responsible stage.",
  "package-rejected": "Package rejected, on the record.",
  "approval-revoked":
    "Approval revoked (the original record stays) and routed for rework.",
  "media-bound":
    "Media need bound to the asset. Gates were NOT re-run — run QA explicitly.",
  "media-unbound": "Binding withdrawn; the need is honestly unsatisfied again.",
  "media-image-queued":
    "Image generation queued. Generation satisfies nothing by itself — bind the asset explicitly.",
  "publication-package-assembled":
    "Publication package assembled from the exact approved artifacts.",
  "publication-scheduled":
    "Publication scheduled. Nothing is published until the governed dispatch runs.",
  "publish-queued":
    "Publication dispatch queued; the worker re-checks the approval first.",
  "approval-expiry-resolved":
    "Routed out of the expired approval to the derived target.",
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

function ReasonForm({
  action,
  workItemId,
  hidden,
  label,
  placeholder,
  helper,
}: {
  action: (formData: FormData) => Promise<void>;
  workItemId: string;
  hidden: Record<string, string>;
  label: string;
  placeholder: string;
  helper?: string;
}) {
  return (
    <form action={action} className="control-form">
      <input type="hidden" name="work_item_id" value={workItemId} />
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <input
        type="text"
        name="reason"
        required
        maxLength={1000}
        placeholder={placeholder}
        aria-label={`${label} reason`}
      />
      <button type="submit">{label}</button>
      {helper !== undefined && <span className="muted">{helper}</span>}
    </form>
  );
}

function WorkflowSection({ detail }: { detail: WorkItemDetail }) {
  const item = detail.work_item;
  return (
    <section aria-labelledby="detail-workflow">
      <h2 id="detail-workflow">Workflow</h2>
      <dl className="status-list">
        <Row name="State">
          <span
            className="badge"
            data-tone={workflowStateTone(item.current_state)}
          >
            {item.current_state}
          </span>{" "}
          <span className="muted">
            since {formatUtcTimestamp(item.current_state_entered_at)}
          </span>
        </Row>
        <Row name="Working title">{item.title_working_label}</Row>
        <Row name="Origin">{item.origin}</Row>
        <Row name="Locale / market">
          {item.locale} / {item.market}
        </Row>
        {item.blocked_reason !== null && (
          <Row name="Blocked reason">{item.blocked_reason}</Row>
        )}
        {item.current_state === "blocked" && (
          <Row name="Legal resume target">
            {item.blocked_resume_state ?? "No prior resumable state recorded"}
          </Row>
        )}
        {item.rejected_reason !== null && (
          <Row name="Rejected reason">{item.rejected_reason}</Row>
        )}
        <Row name="Work item ID">
          <span className="mono muted">{item.id}</span>
        </Row>
      </dl>
      {item.current_state === "blocked" && (
        <div className="control-stack">
          <ReasonForm
            action={resolveBlockAction}
            workItemId={item.id}
            hidden={{}}
            label="Resolve block"
            placeholder="what changed to unblock this"
            helper={`Resumes the history-derived prior state${
              item.blocked_resume_state !== null
                ? ` (${item.blocked_resume_state})`
                : ""
            }; no target can be chosen here.`}
          />
          <ReasonForm
            action={rejectBlockedAction}
            workItemId={item.id}
            hidden={{}}
            label="Reject blocked item"
            placeholder="why this work item is abandoned"
          />
        </div>
      )}
    </section>
  );
}

function ScoreCard({ score }: { score: ScoreView }) {
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Result">
          <span
            className="badge"
            data-tone={scoreEligibilityTone(score.eligibility)}
          >
            {score.overall_band} / {score.eligibility}
          </span>{" "}
          {score.effective && <strong>(effective)</strong>}
        </Row>
        <Row name="Overall value">
          {score.overall_value !== null ? score.overall_value : "Unknown"}
        </Row>
        <Row name="Engine">
          <span className="mono">
            {score.engine_name}/{score.engine_version}
          </span>
        </Row>
        <Row name="Missing signals">
          {score.missing_signals.length > 0
            ? score.missing_signals.join(", ")
            : "None recorded"}
        </Row>
        <Row name="Risk flags">
          {score.risk_flags.length > 0
            ? score.risk_flags.join(", ")
            : "None recorded"}
        </Row>
        <Row name="Evaluated">{formatUtcTimestamp(score.evaluated_at)}</Row>
      </dl>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Component</th>
              <th scope="col">Availability</th>
              <th scope="col">Value</th>
              <th scope="col">Provider</th>
              <th scope="col">Observed</th>
            </tr>
          </thead>
          <tbody>
            {score.components.map((component) => (
              <tr key={component.component}>
                <td>{component.component}</td>
                <td>
                  {component.availability === "unknown" ? (
                    <span className="badge" data-tone="neutral">
                      Unknown
                    </span>
                  ) : (
                    component.availability
                  )}
                </td>
                <td>
                  {component.availability === "known" &&
                  component.value !== null
                    ? component.value
                    : "Not observed"}
                </td>
                <td>{component.provider ?? "—"}</td>
                <td>{formatUtcTimestamp(component.observed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OpportunitySection({ detail }: { detail: WorkItemDetail }) {
  const opportunity = detail.opportunity;
  if (opportunity === null) {
    return (
      <section aria-labelledby="detail-opportunity">
        <h2 id="detail-opportunity">Opportunity & score</h2>
        <p className="empty-note">
          No opportunity is linked to this work item.
        </p>
      </section>
    );
  }
  const effective = detail.scores.find((score) => score.effective);
  const workItemId = detail.work_item.id;
  const canDecide =
    opportunity.disposition === "open" &&
    detail.work_item.current_state === "idea_scoring";
  return (
    <section aria-labelledby="detail-opportunity">
      <h2 id="detail-opportunity">Opportunity & score</h2>
      <dl className="status-list">
        <Row name="Disposition">
          {opportunity.disposition}
          {opportunity.disposition_reason !== null &&
            ` — ${opportunity.disposition_reason}`}
        </Row>
        <Row name="Topic">{opportunity.topic_summary}</Row>
        {opportunity.update_of_reference !== null && (
          <Row name="Update reference">{opportunity.update_of_reference}</Row>
        )}
        <Row name="Promotion root document">
          <span className="mono muted">
            {opportunity.promotion_root_document_id}
          </span>
        </Row>
      </dl>
      {detail.scores.length === 0 && (
        <p className="empty-note">
          Not evaluated yet. Scoring is an explicit action.
        </p>
      )}
      {detail.scores.map((score) => (
        <ScoreCard key={score.id} score={score} />
      ))}
      <TruncationNote
        shown={detail.scores.length}
        total={detail.total_scores}
        noun="score evaluations"
      />
      <div className="control-stack">
        <form action={evaluateOpportunityAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="opportunity_id" value={opportunity.id} />
          <button type="submit">Queue (re-)evaluation</button>
          <span className="muted">
            Scoring records a new evaluation; it never commissions by itself.
          </span>
        </form>
        {canDecide && (
          <>
            <ReasonForm
              action={commissionOpportunityAction}
              workItemId={workItemId}
              hidden={{ opportunity_id: opportunity.id }}
              label="Commission"
              placeholder="why this opportunity is worth pursuing"
              helper={
                effective !== undefined
                  ? `Effective score: ${effective.overall_band} / ${effective.eligibility}` +
                    (effective.missing_signals.length > 0
                      ? `; missing: ${effective.missing_signals.join(", ")}`
                      : "")
                  : "No durable score exists yet — the backend will refuse."
              }
            />
            <ReasonForm
              action={rejectOpportunityAction}
              workItemId={workItemId}
              hidden={{ opportunity_id: opportunity.id }}
              label="Reject opportunity"
              placeholder="why this opportunity is not pursued"
            />
          </>
        )}
      </div>
    </section>
  );
}

function ResearchInputsSection({ detail }: { detail: WorkItemDetail }) {
  return (
    <section aria-labelledby="detail-inputs">
      <h2 id="detail-inputs">Research inputs</h2>
      {detail.research_inputs.length === 0 && (
        <p className="empty-note">No research inputs recorded.</p>
      )}
      {detail.research_inputs.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Role</th>
                <th scope="col">Duplicate</th>
                <th scope="col">Source</th>
                <th scope="col">Trust</th>
                <th scope="col">Published</th>
                <th scope="col">Fetched</th>
                <th scope="col">Added by</th>
              </tr>
            </thead>
            <tbody>
              {detail.research_inputs.map((input) => (
                <tr key={input.id}>
                  <td title={input.normalized_document_id}>
                    {input.document_title ?? "Untitled"}
                  </td>
                  <td>{input.role}</td>
                  <td>{input.duplicate_outcome ?? "Unknown"}</td>
                  <td>{input.source_slug ?? "Unknown"}</td>
                  <td>{input.trust_tier ?? "Unknown"}</td>
                  <td>{formatUtcTimestamp(input.external_published_at)}</td>
                  <td>{formatUtcTimestamp(input.fetched_at)}</td>
                  <td>{input.added_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function IdeaCard({
  idea,
  workItemId,
  canOperate,
}: {
  idea: IdeaView;
  workItemId: string;
  canOperate: boolean;
}) {
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Working title">
          {idea.working_title} <span className="muted">v{idea.version}</span>{" "}
          {idea.effective_selected && <strong>(selected)</strong>}
        </Row>
        <Row name="Angle">{idea.angle}</Row>
        <Row name="Rationale">{idea.rationale}</Row>
        <Row name="Audience">{idea.audience}</Row>
        <Row name="Value">{idea.value_proposition}</Row>
        <Row name="Type / origin">
          {idea.content_type} · {idea.origin}
        </Row>
        <Row name="Originality">
          <span
            className="badge"
            data-tone={originalityTone(idea.originality_status)}
          >
            {idea.originality_status}
          </span>
        </Row>
        {idea.exclusions.length > 0 && (
          <Row name="Exclusions">{idea.exclusions.join("; ")}</Row>
        )}
        {idea.generation_attempt_id !== null && (
          <Row name="Generation attempt">
            <span className="mono muted">{idea.generation_attempt_id}</span>
          </Row>
        )}
        <Row name="Idea ID">
          <span className="mono muted">{idea.id}</span>
        </Row>
      </dl>
      {canOperate && !idea.effective_selected && (
        <ReasonForm
          action={selectIdeaAction}
          workItemId={workItemId}
          hidden={{ idea_id: idea.id }}
          label="Select this version"
          placeholder="why this exact version"
        />
      )}
      {canOperate && idea.effective_selected && (
        <ReasonForm
          action={deselectIdeaAction}
          workItemId={workItemId}
          hidden={{ idea_id: idea.id }}
          label="Deselect"
          placeholder="why the selection is cleared"
          helper="Deselecting never restores an older selection."
        />
      )}
    </div>
  );
}

function IdeasSection({ detail }: { detail: WorkItemDetail }) {
  const workItemId = detail.work_item.id;
  const opportunity = detail.opportunity;
  const canGenerate =
    opportunity !== null &&
    opportunity.disposition === "commissioned" &&
    detail.work_item.current_state === "evidence_building";
  return (
    <section aria-labelledby="detail-ideas">
      <h2 id="detail-ideas">Ideas</h2>
      {detail.ideas.length === 0 && (
        <p className="empty-note">No idea versions exist yet.</p>
      )}
      {detail.ideas.map((idea) => (
        <IdeaCard
          key={idea.id}
          idea={idea}
          workItemId={workItemId}
          canOperate={canGenerate}
        />
      ))}
      <TruncationNote
        shown={detail.ideas.length}
        total={detail.total_ideas}
        noun="idea versions"
      />
      {canGenerate && opportunity !== null && (
        <form action={generateIdeasAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="opportunity_id" value={opportunity.id} />
          <label>
            Candidates
            <select name="candidate_count" defaultValue="3">
              {["1", "2", "3", "4", "5"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Generate idea candidates</button>
          <span className="muted">
            Model-assisted candidates only; nothing is auto-selected.
          </span>
        </form>
      )}
      {detail.selection_events.length > 0 && (
        <>
          <h3>Selection history</h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Idea</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {detail.selection_events.map((event) => (
                  <tr key={event.id}>
                    <td>{formatUtcTimestamp(event.occurred_at)}</td>
                    <td>{event.action}</td>
                    <td className="mono muted">{event.idea_id}</td>
                    <td>{event.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TruncationNote
            shown={detail.selection_events.length}
            total={detail.total_selection_events}
            noun="selection events"
          />
        </>
      )}
    </section>
  );
}

function ContradictionCard({
  contradiction,
  workItemId,
}: {
  contradiction: ContradictionView;
  workItemId: string;
}) {
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Claim">{contradiction.claim_key}</Row>
        <Row name="Nature">{contradiction.nature}</Row>
        <Row name="Severity">{contradiction.severity}</Row>
        <Row name="Sides">
          A: {contradiction.evidence_side_a.join(", ")} · B:{" "}
          {contradiction.evidence_side_b.join(", ")}
        </Row>
        <Row name="Resolution">
          <span
            className="badge"
            data-tone={contradictionResolutionTone(
              contradiction.resolution_status,
            )}
          >
            {contradiction.resolution_status}
          </span>
          {contradiction.resolution_reason !== null &&
            ` — ${contradiction.resolution_reason}`}
        </Row>
        {contradiction.handling_recommendation !== null && (
          <Row name="Handling">{contradiction.handling_recommendation}</Row>
        )}
        {contradiction.resolved_at !== null && (
          <Row name="Resolved">
            {contradiction.resolved_by} ·{" "}
            {formatUtcTimestamp(contradiction.resolved_at)}
          </Row>
        )}
      </dl>
      {contradiction.resolution_status === "unresolved" && (
        <form action={resolveContradictionAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input
            type="hidden"
            name="contradiction_id"
            value={contradiction.id}
          />
          <select
            name="resolution_status"
            required
            defaultValue=""
            aria-label="Resolution status"
          >
            <option value="" disabled>
              Resolution…
            </option>
            {RESOLVED_CONTRADICTION_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="resolution reason"
            aria-label="Resolution reason"
          />
          <button type="submit">Resolve</button>
          <span className="muted">
            Resolving never changes this pack&apos;s stored sufficiency;
            reassemble a new version afterwards.
          </span>
        </form>
      )}
    </div>
  );
}

function PackCard({
  pack,
  workItemId,
}: {
  pack: PackView;
  workItemId: string;
}) {
  const detailEntries = Object.entries(pack.sufficiency_detail).filter(
    ([, value]) => Array.isArray(value) && value.length > 0,
  );
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Pack">
          <span className="mono muted">{pack.id}</span>{" "}
          <span className="muted">v{pack.version}</span>
        </Row>
        <Row name="Sufficiency">
          <span
            className="badge"
            data-tone={packSufficiencyTone(pack.sufficiency)}
          >
            {pack.sufficiency}
          </span>
        </Row>
        {detailEntries.length > 0 && (
          <Row name="Why">
            {detailEntries
              .map(
                ([key, value]) => `${key}: ${(value as unknown[]).join("; ")}`,
              )
              .join(" · ")}
          </Row>
        )}
        <Row name="Assembler">
          <span className="mono">
            {pack.assembler_name}/{pack.assembler_version}
          </span>
        </Row>
        <Row name="Pinned idea">
          {pack.idea_id !== null ? (
            <span className="mono muted">{pack.idea_id}</span>
          ) : (
            "Not pinned"
          )}
        </Row>
        <Row name="Assembled">{formatUtcTimestamp(pack.created_at)}</Row>
      </dl>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Cluster</th>
              <th scope="col">Statement</th>
              <th scope="col">Type</th>
              <th scope="col">Verification</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {pack.items.map((item) => (
              <tr key={item.id}>
                <td>{item.role}</td>
                <td>{item.claim_cluster}</td>
                <td title={item.research_evidence_id}>
                  {item.statement ?? "—"}
                </td>
                <td>{item.evidence_type ?? "Unknown"}</td>
                <td>{item.verification_status ?? "Unknown"}</td>
                <td>
                  {item.source_slug ?? "Unknown"}
                  {item.trust_tier !== null ? ` (${item.trust_tier})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pack.contradictions.map((contradiction) => (
        <ContradictionCard
          key={contradiction.id}
          contradiction={contradiction}
          workItemId={workItemId}
        />
      ))}
      <form action={reassemblePackAction} className="control-form">
        <input type="hidden" name="work_item_id" value={workItemId} />
        <input type="hidden" name="pack_id" value={pack.id} />
        <button type="submit">Reassemble as new version</button>
        <span className="muted">
          Produces a new immutable version reflecting current contradiction
          resolutions; this version stays untouched and workflow does not
          advance by itself.
        </span>
      </form>
    </div>
  );
}

function PackBuilder({
  detail,
  evidence,
}: {
  detail: WorkItemDetail;
  evidence: EligibleEvidenceItem[];
}) {
  const opportunity = detail.opportunity;
  const selectedIdeaId = detail.effective_selected_idea_id;
  if (
    opportunity === null ||
    detail.work_item.current_state !== "evidence_building"
  ) {
    return null;
  }
  if (selectedIdeaId === null) {
    return (
      <p className="muted">
        Building a pack requires an effective selected idea first.
      </p>
    );
  }
  if (evidence.length === 0) {
    return (
      <p className="muted">
        No eligible research evidence exists for this opportunity yet.
      </p>
    );
  }
  return (
    <form
      action={buildEvidencePackAction}
      className="control-form pack-builder"
    >
      <input type="hidden" name="work_item_id" value={detail.work_item.id} />
      <input type="hidden" name="opportunity_id" value={opportunity.id} />
      <input type="hidden" name="idea_id" value={selectedIdeaId} />
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Use</th>
              <th scope="col">Statement</th>
              <th scope="col">Verification</th>
              <th scope="col">Source</th>
              <th scope="col">Role</th>
              <th scope="col">Claim cluster</th>
              <th scope="col">Note</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((item) => (
              <tr key={item.id}>
                <td>
                  <input
                    type="checkbox"
                    name={`select-${item.id}`}
                    aria-label={`Select evidence ${item.id}`}
                  />
                </td>
                <td title={item.id}>{item.statement}</td>
                <td>{item.verification_status}</td>
                <td>
                  {item.source_slug ?? "Unknown"}
                  {item.trust_tier !== null ? ` (${item.trust_tier})` : ""}
                </td>
                <td>
                  <select name={`role-${item.id}`} defaultValue="supporting">
                    {[
                      "key_fact",
                      "supporting",
                      "contradicting",
                      "context",
                      "caution",
                    ].map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="text"
                    name={`cluster-${item.id}`}
                    maxLength={100}
                    placeholder="cluster"
                    aria-label={`Claim cluster for ${item.id}`}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    name={`note-${item.id}`}
                    maxLength={1000}
                    placeholder="optional"
                    aria-label={`Display note for ${item.id}`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="submit">Build evidence pack from selection</button>
      <span className="muted">
        You select the evidence explicitly; nothing is chosen for you. The
        worker assembles and evaluates sufficiency.
      </span>
    </form>
  );
}

function EvidenceSection({
  detail,
  evidence,
}: {
  detail: WorkItemDetail;
  evidence: EligibleEvidenceItem[];
}) {
  return (
    <section aria-labelledby="detail-evidence">
      <h2 id="detail-evidence">Evidence packs</h2>
      {detail.evidence_packs.length === 0 && (
        <p className="empty-note">No evidence pack versions exist yet.</p>
      )}
      {detail.evidence_packs.map((pack) => (
        <PackCard key={pack.id} pack={pack} workItemId={detail.work_item.id} />
      ))}
      <TruncationNote
        shown={detail.evidence_packs.length}
        total={detail.total_evidence_packs}
        noun="pack versions"
      />
      <PackBuilder detail={detail} evidence={evidence} />
    </section>
  );
}

function IntentCard({ analysis }: { analysis: IntentAnalysisView }) {
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Analysis">
          <span className="mono muted">{analysis.id}</span>{" "}
          <span className="muted">v{analysis.version}</span>
        </Row>
        <Row name="Primary intent">{analysis.primary_intent}</Row>
        <Row name="Page purpose">{analysis.page_purpose}</Row>
        <Row name="Likely format">{analysis.likely_format}</Row>
        <Row name="Query concepts">
          {analysis.query_concepts.join(", ") || "None recorded"}
        </Row>
        <Row name="Known signals">
          {analysis.known_signals.length === 0 && "None consumed"}
          {analysis.known_signals.map((signal) => (
            <span key={signal.id} className="cell-secondary">
              {signal.signal_type} · {signal.provider} · observed{" "}
              {formatUtcTimestamp(signal.observed_at)}
              {signal.as_of !== null
                ? ` (as of ${formatUtcTimestamp(signal.as_of)})`
                : ""}
            </span>
          ))}
        </Row>
        <Row name="Missing signals">
          {analysis.missing_signals.length > 0
            ? analysis.missing_signals.join(", ")
            : "None"}
        </Row>
        <Row name="Cannibalization">
          {cannibalizationLabel(analysis.cannibalization_status)}
        </Row>
        <Row name="Engine">
          <span className="mono">
            {analysis.engine_name}/{analysis.engine_version}
          </span>
        </Row>
        <Row name="Created">{formatUtcTimestamp(analysis.created_at)}</Row>
      </dl>
    </div>
  );
}

function SearchIntentSection({ detail }: { detail: WorkItemDetail }) {
  const opportunity = detail.opportunity;
  const readyPack = detail.evidence_packs.find(
    (pack) => pack.sufficiency === "ready",
  );
  const canAnalyze =
    opportunity !== null &&
    detail.work_item.current_state === "seo_research" &&
    detail.effective_selected_idea_id !== null &&
    readyPack !== undefined;
  return (
    <section aria-labelledby="detail-intent">
      <h2 id="detail-intent">Search intent</h2>
      {detail.intent_analyses.length === 0 && (
        <p className="empty-note">No search-intent analysis exists yet.</p>
      )}
      {detail.intent_analyses.map((analysis) => (
        <IntentCard key={analysis.id} analysis={analysis} />
      ))}
      <TruncationNote
        shown={detail.intent_analyses.length}
        total={detail.total_intent_analyses}
        noun="analysis versions"
      />
      {canAnalyze && opportunity !== null && readyPack !== undefined && (
        <form action={analyzeSearchIntentAction} className="control-form">
          <input
            type="hidden"
            name="work_item_id"
            value={detail.work_item.id}
          />
          <input type="hidden" name="opportunity_id" value={opportunity.id} />
          <input
            type="hidden"
            name="idea_id"
            value={detail.effective_selected_idea_id ?? ""}
          />
          <input type="hidden" name="evidence_pack_id" value={readyPack.id} />
          <input
            type="text"
            name="signal_id"
            maxLength={36}
            placeholder="search signal id (optional)"
            aria-label="Exact search signal id"
          />
          <input
            type="text"
            name="signal_id"
            maxLength={36}
            placeholder="second signal id (optional)"
            aria-label="Second exact search signal id"
          />
          <button type="submit">Queue search-intent analysis</button>
          <span className="muted">
            Pins the selected idea, the READY pack v{readyPack.version}, and
            ONLY the exact signal observations you list — never an implicit
            latest.
          </span>
        </form>
      )}
    </section>
  );
}

function BriefCard({
  brief,
  workItemId,
  canAccept,
}: {
  brief: BriefView;
  workItemId: string;
  canAccept: boolean;
}) {
  const guardOutcome = brief.structure_guard_result["outcome"];
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Brief">
          <span className="mono muted">{brief.id}</span>{" "}
          <span className="muted">v{brief.version}</span>{" "}
          <span className="badge" data-tone={briefStatusTone(brief.status)}>
            {brief.status}
          </span>
        </Row>
        <Row name="Objective">{brief.content_objective}</Row>
        <Row name="Intent summary">{brief.intent_summary}</Row>
        <Row name="Original angle">{brief.original_angle}</Row>
        <Row name="Required sections">
          {brief.required_sections
            .map((section) => String(section["key"] ?? ""))
            .filter(Boolean)
            .join(", ")}
        </Row>
        <Row name="Exclusions">
          {brief.exclusions.length > 0 ? brief.exclusions.join("; ") : "None"}
        </Row>
        <Row name="Uncertainty notes">
          {brief.uncertainty_notes.length > 0 ? (
            <ul className="plain-list">
              {brief.uncertainty_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : (
            "None"
          )}
        </Row>
        <Row name="Structure guard">
          {typeof guardOutcome === "string" ? guardOutcome : "Not reported"}
        </Row>
        <Row name="Pins">
          idea <span className="mono muted">{brief.idea_id}</span> · pack{" "}
          <span className="mono muted">{brief.evidence_pack_id}</span> · intent{" "}
          <span className="mono muted">{brief.search_intent_analysis_id}</span>
        </Row>
        <Row name="Engine">
          <span className="mono">
            {brief.engine_name}/{brief.engine_version}
          </span>
        </Row>
      </dl>
      {brief.claims.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Claim</th>
                <th scope="col">Kind</th>
                <th scope="col">Text</th>
                <th scope="col">Evidence links</th>
              </tr>
            </thead>
            <tbody>
              {brief.claims.map((claim) => (
                <tr key={claim.id}>
                  <td>{claim.claim_key}</td>
                  <td>{claim.claim_kind}</td>
                  <td>{claim.claim_text}</td>
                  <td className="mono muted">
                    {claim.evidence_ids.length > 0
                      ? claim.evidence_ids.join(", ")
                      : "No evidence (non-factual kind)"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {brief.status_events.length > 0 && (
        <ul className="plain-list">
          {brief.status_events.map((event) => (
            <li key={event.id}>
              {formatUtcTimestamp(event.occurred_at)}: {event.from_status} →{" "}
              {event.to_status} ({event.actor_origin}) — {event.reason}
            </li>
          ))}
        </ul>
      )}
      {canAccept && brief.status === "draft" && (
        <ReasonForm
          action={acceptBriefAction}
          workItemId={workItemId}
          hidden={{ brief_id: brief.id }}
          label="Accept for drafting"
          placeholder="why the writing contract is complete"
          helper='"Accept for drafting" releases the brief to the Phase-4 Writer. It does NOT publish content and is not publication approval.'
        />
      )}
    </div>
  );
}

function BriefsSection({ detail }: { detail: WorkItemDetail }) {
  const inBriefing = detail.work_item.current_state === "briefing";
  const readyPack = detail.evidence_packs.find(
    (pack) => pack.sufficiency === "ready",
  );
  const latestAnalysis = detail.intent_analyses[0];
  const canCompose =
    inBriefing &&
    detail.effective_selected_idea_id !== null &&
    readyPack !== undefined &&
    latestAnalysis !== undefined;
  return (
    <section aria-labelledby="detail-briefs">
      <h2 id="detail-briefs">Briefs & claims</h2>
      {detail.briefs.length === 0 && (
        <p className="empty-note">No brief versions exist yet.</p>
      )}
      {detail.briefs.map((brief) => (
        <BriefCard
          key={brief.id}
          brief={brief}
          workItemId={detail.work_item.id}
          canAccept={inBriefing}
        />
      ))}
      <TruncationNote
        shown={detail.briefs.length}
        total={detail.total_briefs}
        noun="brief versions"
      />
      {canCompose &&
        readyPack !== undefined &&
        latestAnalysis !== undefined && (
          <form action={composeBriefAction} className="control-form">
            <input
              type="hidden"
              name="work_item_id"
              value={detail.work_item.id}
            />
            <input
              type="hidden"
              name="idea_id"
              value={detail.effective_selected_idea_id ?? ""}
            />
            <input type="hidden" name="evidence_pack_id" value={readyPack.id} />
            <input
              type="hidden"
              name="search_intent_analysis_id"
              value={latestAnalysis.id}
            />
            {detail.briefs.length > 0 && (
              <input
                type="text"
                name="supersede_reason"
                maxLength={1000}
                placeholder="supersede reason (existing draft)"
                aria-label="Supersede reason"
              />
            )}
            <button type="submit">Compose draft brief</button>
            <span className="muted">
              Produces a DRAFT from the pinned idea, READY pack v
              {readyPack.version}, and analysis v{latestAnalysis.version}.
              Accepting it for drafting is a separate decision.
            </span>
          </form>
        )}
    </section>
  );
}

function DraftsSection({
  detail,
  drafts,
}: {
  detail: WorkItemDetail;
  drafts: DraftListPage | null;
}) {
  const workItemId = detail.work_item.id;
  const state = detail.work_item.current_state;
  const acceptedBrief = detail.briefs.find(
    (brief) => brief.status === "accepted_for_drafting",
  );
  const rows = drafts?.drafts ?? [];
  const hasActiveDraft = rows.some((row) => row.status === "active");
  const canProduce = state === "drafting" && acceptedBrief !== undefined;
  return (
    <section aria-labelledby="detail-drafts">
      <h2 id="detail-drafts">Writer drafts</h2>
      {drafts === null && (
        <p className="muted" role="note">
          Draft versions could not be loaded right now.
        </p>
      )}
      {drafts !== null && rows.length === 0 && (
        <p className="empty-note">No draft versions exist yet.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Origin</th>
                <th scope="col">Status</th>
                <th scope="col">Title proposal</th>
                <th scope="col">Coverage</th>
                <th scope="col">Originality</th>
                <th scope="col">Created</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>v{row.version}</td>
                  <td>
                    {row.origin === "operator" ? "operator" : "writer engine"}
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td>{row.title_proposal ?? "—"}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={verdictTone(row.uncertainty_coverage_status)}
                    >
                      {verdictLabel(row.uncertainty_coverage_status)}
                    </span>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={verdictTone(row.originality_outcome)}
                    >
                      {verdictLabel(row.originality_outcome)}
                    </span>
                  </td>
                  <td>{formatUtcTimestamp(row.created_at)}</td>
                  <td>
                    <Link href={`/editorial/${workItemId}/drafts/${row.id}`}>
                      Open draft
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canProduce && acceptedBrief !== undefined && (
        <form action={generateDraftAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="brief_id" value={acceptedBrief.id} />
          <input
            type="number"
            name="retry_number"
            min={0}
            max={50}
            defaultValue={0}
            aria-label="Retry number"
          />
          {hasActiveDraft && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="supersede reason (active draft exists)"
              aria-label="Draft supersede reason"
            />
          )}
          <button type="submit">Generate writer draft</button>
          <span className="muted">
            Queues generation from accepted brief v{acceptedBrief.version}.
            Regeneration is the same command with the next retry number and a
            reason.
          </span>
        </form>
      )}
      {canProduce && acceptedBrief !== undefined && (
        <form action={submitDraftAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="brief_id" value={acceptedBrief.id} />
          <input
            type="text"
            name="title_proposal"
            maxLength={200}
            placeholder="title proposal (optional)"
            aria-label="Draft title proposal"
          />
          <textarea
            name="sections_json"
            required
            rows={6}
            placeholder='writer-draft-body/1 sections as JSON, e.g. [{"key":"giris","heading":"...","blocks":[...]}]'
            aria-label="Draft sections JSON"
          />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="submission reason"
            aria-label="Draft submission reason"
          />
          {hasActiveDraft && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="supersede reason (active draft exists)"
              aria-label="Manual draft supersede reason"
            />
          )}
          <button type="submit">Submit operator draft</button>
          <span className="muted">
            Human-authored draft through the SAME gates as the writer engine; a
            valid draft moves the item to editing.
          </span>
        </form>
      )}
      {state === "editing" && (
        <ReasonForm
          action={requestReworkAction}
          workItemId={workItemId}
          hidden={{}}
          label="Request rework"
          placeholder="what must the writer stage change?"
          helper="Records changes-requested with the writer stage responsible; the active draft is pinned."
        />
      )}
      {state === "changes_requested" && (
        <ReasonForm
          action={resolveChangesRequestedAction}
          workItemId={workItemId}
          hidden={{}}
          label="Route rework"
          placeholder="route to the recorded responsible state"
          helper="Routes to the durable recorded responsible state — no target can be chosen here."
        />
      )}
    </section>
  );
}

function ReviewsSection({
  detail,
  reviews,
}: {
  detail: WorkItemDetail;
  reviews: ReviewListPage | null;
}) {
  const workItemId = detail.work_item.id;
  const state = detail.work_item.current_state;
  const rows = reviews?.reviews ?? [];
  const activeReview = rows.find((row) => row.status === "active");
  return (
    <section aria-labelledby="detail-reviews">
      <h2 id="detail-reviews">Editor reviews</h2>
      <p className="muted">
        Findings are policy signals, never evidence. The verdict is computed
        deterministically; a human advances the workflow.
      </p>
      {reviews === null && (
        <p className="muted" role="note">
          Review versions could not be loaded right now.
        </p>
      )}
      {reviews !== null && rows.length === 0 && (
        <p className="empty-note">No editor review versions exist yet.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Verdict</th>
                <th scope="col">Status</th>
                <th scope="col">Findings (blocking / major / minor)</th>
                <th scope="col">Envelope recheck</th>
                <th scope="col">Created</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>v{row.version}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={reviewVerdictTone(row.verdict)}
                    >
                      {row.verdict}
                    </span>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td>
                    {row.finding_counts.blocking ?? 0} /{" "}
                    {row.finding_counts.major ?? 0} /{" "}
                    {row.finding_counts.minor ?? 0}
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={
                        row.writer_envelope_recomputed === null
                          ? "neutral"
                          : "ok"
                      }
                    >
                      {row.writer_envelope_recomputed === null
                        ? "UNKNOWN"
                        : row.writer_envelope_recomputed
                          ? "recomputed"
                          : "not recomputed"}
                    </span>
                  </td>
                  <td>{formatUtcTimestamp(row.created_at)}</td>
                  <td>
                    <Link href={`/editorial/${workItemId}/reviews/${row.id}`}>
                      Open review
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {state === "editing" && (
        <form action={generateEditorReviewAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input
            type="number"
            name="retry_number"
            min={0}
            max={50}
            defaultValue={0}
            aria-label="Review retry number"
          />
          {activeReview !== undefined && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="supersede reason (active review exists)"
              aria-label="Review supersede reason"
            />
          )}
          <button type="submit">Generate editor review</button>
          <span className="muted">
            Queues the model-assisted review; the verdict is computed by the
            deterministic policy, never by the model.
          </span>
        </form>
      )}
      {state === "editing" && activeReview !== undefined && (
        <ReasonForm
          action={acceptReviewAction}
          workItemId={workItemId}
          hidden={{}}
          label="Accept review"
          placeholder="why this draft may proceed to QA"
          helper={
            activeReview.verdict === "pass"
              ? "Advances to QA review with the pass review pinned. Not a publication decision."
              : "The active review verdict is 'revise'; the backend will refuse until a pass review covers the active draft."
          }
        />
      )}
    </section>
  );
}

const QA_GATE_ORDER = [
  "package_integrity",
  "provenance_chain",
  "writer_envelope",
  "content_safety",
  "editorial_review_currency",
  "media_needs",
  "internal_link_needs",
] as const;

function qaGateTone(
  result: string,
): "ok" | "warn" | "bad" | "neutral" | "info" {
  if (result === "pass" || result === "not_applicable" || result === "none") {
    return "ok";
  }
  if (result === "waived_by_human" || result === "pending") {
    return "info";
  }
  if (result === "unsatisfied") {
    return "warn";
  }
  if (result === "fail") {
    return "bad";
  }
  return "neutral"; // UNKNOWN and anything unexpected: never a pass.
}

function QaSection({
  detail,
  qaReports,
}: {
  detail: WorkItemDetail;
  qaReports: QaReportListPage | null;
}) {
  const workItemId = detail.work_item.id;
  const state = detail.work_item.current_state;
  const rows = qaReports?.reports ?? [];
  const waivers = qaReports?.waivers ?? [];
  return (
    <section aria-labelledby="detail-qa">
      <h2 id="detail-qa">QA reports</h2>
      <p className="muted">
        Deterministic hard gates over the exact pinned package. The absence of a
        result is never a pass; a ready report advances the item to the human
        decision automatically.
      </p>
      {qaReports === null && (
        <p className="muted" role="note">
          QA reports could not be loaded right now.
        </p>
      )}
      {qaReports !== null && rows.length === 0 && (
        <p className="empty-note">No QA report versions exist yet.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Outcome</th>
                <th scope="col">Status</th>
                <th scope="col">Gates</th>
                <th scope="col">Created</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>v{row.version}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={
                        row.outcome === "ready_for_human_review" ? "ok" : "warn"
                      }
                    >
                      {row.outcome}
                    </span>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td>
                    {QA_GATE_ORDER.map((gate) => {
                      const result = row.gate_summary[gate] ?? "UNKNOWN";
                      return (
                        <span
                          key={gate}
                          className="badge"
                          data-tone={qaGateTone(result)}
                          title={gate}
                        >
                          {gate}: {result}
                        </span>
                      );
                    })}
                  </td>
                  <td>{formatUtcTimestamp(row.created_at)}</td>
                  <td>
                    <Link
                      href={`/editorial/${workItemId}/qa-reports/${row.id}`}
                    >
                      Open report
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {waivers.length > 0 && (
        <p className="muted" role="note">
          Audited waivers:{" "}
          {waivers
            .map((waiver) => `${waiver.gate_key} — ${waiver.reason}`)
            .join(" · ")}
        </p>
      )}
      {state === "qa_review" && (
        <div className="control-stack">
          <form action={runQaAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <button type="submit">Run QA gates</button>
            <span className="muted">
              Deterministic re-run; identical results reuse the report.
            </span>
          </form>
          <form action={waiveQaGateAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <input type="hidden" name="gate_key" value="media_needs" />
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="why the media requirement is deliberately deferred"
              aria-label="Waive media gate reason"
            />
            <button type="submit">Waive media gate</button>
            <span className="muted">
              WARNING: an audited human waiver — the media needs stay visible
              and gates are NOT re-run automatically.
            </span>
          </form>
          <form action={requestReworkAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <select
              name="responsible_state"
              defaultValue="drafting"
              aria-label="Responsible state"
            >
              <option value="drafting">writer stage (drafting)</option>
              <option value="editing">editor stage (editing)</option>
            </select>
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="what must change and who is responsible"
              aria-label="QA rework reason"
            />
            <button type="submit">Request rework</button>
            <span className="muted">
              Routes via the recorded responsible state; the choice is bounded,
              never arbitrary.
            </span>
          </form>
        </div>
      )}
      {state === "awaiting_human_review" && (
        <p role="note">
          <strong>Human decision pending.</strong> The full package (draft,
          editor review, QA report) is pinned in the workflow history. The
          decision itself is recorded in the Human decisions section below by an
          authenticated reviewer.
        </p>
      )}
    </section>
  );
}

const MEDIA_COMMAND_STATES = new Set([
  "drafting",
  "editing",
  "qa_review",
  "changes_requested",
]);

function MediaSatisfactionCell({
  satisfaction,
}: {
  satisfaction: MediaSatisfactionView;
}) {
  const asset = satisfaction.asset;
  return (
    <div>
      {/* Bytes go through the admin's authenticated proxy, never the backend. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/editorial/media-assets/${asset.id}/content`}
        alt={asset.alt_text}
        width={120}
        loading="lazy"
      />
      <p>
        <span className="badge" data-tone="neutral">
          {asset.origin}
        </span>{" "}
        {asset.media_type} · {asset.byte_size} bytes
      </p>
      <p className="muted">Alt: {asset.alt_text}</p>
      <p className="muted">License: {asset.license_note}</p>
      {asset.source_attribution !== null && (
        <p className="muted">Attribution: {asset.source_attribution}</p>
      )}
      <p className="muted">
        Bound by {satisfaction.satisfied_by.display_name} —{" "}
        {satisfaction.reason}
      </p>
    </div>
  );
}

function MediaSection({
  detail,
  media,
}: {
  detail: WorkItemDetail;
  media: MediaCoveragePage | null;
}) {
  const workItemId = detail.work_item.id;
  const commandsOpen = MEDIA_COMMAND_STATES.has(detail.work_item.current_state);
  return (
    <section aria-labelledby="detail-media">
      <h2 id="detail-media">Media</h2>
      <p className="muted">
        A need is satisfied ONLY by an explicit human binding of one durable
        asset. Generation and upload alone satisfy nothing.
      </p>
      {media === null && (
        <p className="empty-note">The media coverage cannot be loaded.</p>
      )}
      {media !== null && media.total_needs === 0 && (
        <p className="empty-note">
          The accepted brief defines no media needs (or no accepted brief exists
          yet).
        </p>
      )}
      {media !== null && media.total_needs > 0 && (
        <>
          <p>
            Coverage: {media.satisfied_needs} / {media.total_needs} needs
            satisfied.
          </p>
          {!commandsOpen && (
            <p role="note">
              Media commands are closed in{" "}
              <strong>{detail.work_item.current_state}</strong>: the package is
              frozen while under terminal review.
            </p>
          )}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Need</th>
                  <th scope="col">Coverage</th>
                </tr>
              </thead>
              <tbody>
                {media.needs.map((need) => (
                  <tr key={need.need_index}>
                    <td>{need.need_index}</td>
                    <td>
                      <strong>{need.role}</strong>
                      <p className="muted">{need.purpose}</p>
                      {need.constraints !== null && (
                        <p className="muted">Constraints: {need.constraints}</p>
                      )}
                    </td>
                    <td>
                      {need.satisfaction !== null ? (
                        <MediaSatisfactionCell
                          satisfaction={need.satisfaction}
                        />
                      ) : (
                        <span className="badge" data-tone="warning">
                          Unsatisfied
                        </span>
                      )}
                      {commandsOpen && need.satisfaction === null && (
                        <div className="control-stack">
                          <form
                            action={uploadAndBindMediaAction}
                            className="control-form"
                          >
                            <input
                              type="hidden"
                              name="work_item_id"
                              value={workItemId}
                            />
                            <input
                              type="hidden"
                              name="need_index"
                              value={need.need_index}
                            />
                            <input
                              type="file"
                              name="file"
                              required
                              accept="image/png,image/jpeg,image/webp"
                              aria-label={`Upload file for need ${need.need_index}`}
                            />
                            <input
                              type="text"
                              name="alt_text"
                              required
                              maxLength={1000}
                              placeholder="alt text (required)"
                              aria-label={`Alt text for need ${need.need_index}`}
                            />
                            <input
                              type="text"
                              name="license_note"
                              required
                              maxLength={1000}
                              placeholder="license note (required)"
                              aria-label={`License note for need ${need.need_index}`}
                            />
                            <input
                              type="text"
                              name="reason"
                              required
                              maxLength={1000}
                              placeholder="why this asset satisfies the need"
                              aria-label={`Binding reason for need ${need.need_index}`}
                            />
                            <button type="submit">Upload & bind</button>
                          </form>
                          <form
                            action={bindMediaAssetAction}
                            className="control-form"
                          >
                            <input
                              type="hidden"
                              name="work_item_id"
                              value={workItemId}
                            />
                            <input
                              type="hidden"
                              name="need_index"
                              value={need.need_index}
                            />
                            <input
                              type="text"
                              name="media_asset_id"
                              required
                              className="mono"
                              placeholder="existing media asset id"
                              aria-label={`Asset id for need ${need.need_index}`}
                            />
                            <input
                              type="text"
                              name="reason"
                              required
                              maxLength={1000}
                              placeholder="why this asset satisfies the need"
                              aria-label={`Bind reason for need ${need.need_index}`}
                            />
                            <button type="submit">Bind existing asset</button>
                          </form>
                          <form
                            action={generateMediaImageAction}
                            className="control-form"
                          >
                            <input
                              type="hidden"
                              name="work_item_id"
                              value={workItemId}
                            />
                            <input
                              type="hidden"
                              name="need_index"
                              value={need.need_index}
                            />
                            <button type="submit">Generate image</button>
                            <span className="muted">
                              Produces a candidate asset with AI provenance; you
                              still bind it explicitly.
                            </span>
                          </form>
                        </div>
                      )}
                      {commandsOpen && need.satisfaction !== null && (
                        <form
                          action={unbindMediaAction}
                          className="control-form"
                        >
                          <input
                            type="hidden"
                            name="work_item_id"
                            value={workItemId}
                          />
                          <input
                            type="hidden"
                            name="need_index"
                            value={need.need_index}
                          />
                          <input
                            type="text"
                            name="reason"
                            required
                            maxLength={1000}
                            placeholder="why the binding no longer stands"
                            aria-label={`Unbind reason for need ${need.need_index}`}
                          />
                          <button type="submit">Unbind</button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {media !== null && media.history.length > media.satisfied_needs && (
        <p className="muted" role="note">
          Binding history:{" "}
          {media.history
            .map(
              (row) =>
                `#${row.need_index} ${row.status} — ${row.satisfied_by.display_name}: ${row.reason}`,
            )
            .join(" · ")}
        </p>
      )}
    </section>
  );
}

function PublicationSection({
  detail,
  publication,
}: {
  detail: WorkItemDetail;
  publication: PublicationPage | null;
}) {
  const workItemId = detail.work_item.id;
  const state = detail.work_item.current_state;
  return (
    <section aria-labelledby="detail-publication">
      <h2 id="detail-publication">Publication</h2>
      <p className="muted">
        ContentOS publishes exactly what was approved, or nothing: immutable
        hashed packages behind the current-approval guard, dispatched only
        through the governed Publishing API transport.
      </p>
      {publication === null && (
        <p className="empty-note">The publication state cannot be loaded.</p>
      )}
      {publication !== null && (
        <>
          {publication.packages.length === 0 && (
            <p className="empty-note">No publication package exists yet.</p>
          )}
          {publication.latest_package_approval_current === false && (
            <p role="note">
              <strong>
                The latest package no longer matches a current approval.
              </strong>{" "}
              Re-assembly (and possibly re-approval) is required before
              publication can proceed.
            </p>
          )}
          {publication.packages.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">Package</th>
                    <th scope="col">Assembled by</th>
                    <th scope="col">Attempts</th>
                  </tr>
                </thead>
                <tbody>
                  {publication.packages.map((row) => (
                    <tr key={row.id}>
                      <td>v{row.version}</td>
                      <td>
                        <span className="mono">{row.id}</span>
                        <p className="muted">
                          {row.section_count} sections · {row.manifest_needs}{" "}
                          media bindings
                          {row.waived_unmet_indexes.length > 0
                            ? ` · waived unmet needs: ${row.waived_unmet_indexes.join(", ")}`
                            : ""}
                        </p>
                        <p className="mono muted">
                          hash={row.package_hash.slice(0, 12)}… content=
                          {row.content_hash.slice(0, 12)}…
                        </p>
                      </td>
                      <td>{row.assembled_by.display_name}</td>
                      <td>
                        {row.attempts.length === 0 && (
                          <span className="muted">No dispatches yet.</span>
                        )}
                        {row.attempts.map((attempt) => (
                          <p key={attempt.id}>
                            #{attempt.attempt_number}{" "}
                            <span
                              className="badge"
                              data-tone={
                                attempt.status === "succeeded"
                                  ? "positive"
                                  : "negative"
                              }
                            >
                              {attempt.status}
                            </span>{" "}
                            {attempt.remote_publication_ref !== null
                              ? `ref=${attempt.remote_publication_ref}`
                              : (attempt.error_class ?? "")}
                          </p>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {state === "approved" && (
        <div className="control-stack">
          <form
            action={assemblePublicationPackageAction}
            className="control-form"
          >
            <input type="hidden" name="work_item_id" value={workItemId} />
            <button type="submit">Assemble publication package</button>
            <span className="muted">
              Deterministic projection of the approved artifacts; identical
              content converges on the existing package.
            </span>
          </form>
          {publication !== null && publication.packages.length > 0 && (
            <form action={schedulePublicationAction} className="control-form">
              <input type="hidden" name="work_item_id" value={workItemId} />
              <input
                type="hidden"
                name="publication_package_id"
                value={publication.packages[0]!.id}
              />
              <input
                type="text"
                name="reason"
                required
                maxLength={1000}
                placeholder="why this package goes to the publication plan"
                aria-label="Scheduling reason"
              />
              <button type="submit">Schedule publication</button>
              <span className="muted">
                Schedules package v{publication.packages[0]!.version}; nothing
                is published until the governed dispatch runs.
              </span>
            </form>
          )}
        </div>
      )}
      {(state === "scheduled" || state === "publishing") && (
        <form action={publishWorkItemAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <button type="submit">Publish now</button>
          <span className="muted">
            Queues the governed dispatch; the worker re-checks the approval and
            a stale one expires instead of publishing.
          </span>
        </form>
      )}
      {state === "approval_expired" && (
        <form action={resolveApprovalExpiredAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="route the expired approval back for review"
            aria-label="Expiry resolution reason"
          />
          <button type="submit">Resolve expired approval</button>
          <span className="muted">
            The target is DERIVED: back to human review while the QA report
            still covers the draft, else back to QA.
          </span>
        </form>
      )}
    </section>
  );
}

function DecisionsSection({
  detail,
  decisions,
  isReviewer,
}: {
  detail: WorkItemDetail;
  decisions: DecisionListPage | null;
  isReviewer: boolean;
}) {
  const workItemId = detail.work_item.id;
  const state = detail.work_item.current_state;
  const status = decisions?.approval_status ?? null;
  return (
    <section aria-labelledby="detail-decisions">
      <h2 id="detail-decisions">Human decisions</h2>
      <p className="muted">
        Append-only record of named human decisions. Every decision pins the
        exact package (draft, editor review, QA report) by id and content hash.
      </p>
      {decisions === null && (
        <p className="empty-note">The decision record cannot be loaded.</p>
      )}
      {decisions !== null && (
        <>
          {status !== null && status.approved && (
            <p role="note">
              <strong>Approval on record</strong>
              {": "}
              <span
                className="badge"
                data-tone={status.current ? "positive" : "warning"}
              >
                {status.current ? "current" : "stale"}
              </span>{" "}
              {status.current
                ? "The active draft still carries the approved content hash."
                : "The active draft no longer matches the approved content hash — the approval does not cover the current content."}
            </p>
          )}
          {decisions.decisions.length === 0 && (
            <p className="empty-note">No human decisions are recorded.</p>
          )}
          {decisions.decisions.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Decision</th>
                    <th scope="col">Reviewer</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Pinned package</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.decisions.map((decision) => (
                    <tr key={decision.id}>
                      <td>{formatUtcTimestamp(decision.created_at)}</td>
                      <td>
                        <span
                          className="badge"
                          data-tone={
                            decision.decision === "approved"
                              ? "positive"
                              : decision.decision === "changes_requested"
                                ? "warning"
                                : "negative"
                          }
                        >
                          {decision.decision}
                        </span>
                      </td>
                      <td>{decision.reviewer.display_name}</td>
                      <td>{decision.reason}</td>
                      <td className="mono muted">
                        draft={decision.content_draft_id} hash=
                        {decision.content_hash.slice(0, 12)}…
                        {decision.revokes_decision_id !== null
                          ? ` revokes=${decision.revokes_decision_id}`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {(state === "awaiting_human_review" || state === "approved") &&
        !isReviewer && (
          <p role="note">
            You are signed in without the reviewer role. Decisions can only be
            recorded by an authorized reviewer.
          </p>
        )}
      {state === "awaiting_human_review" && isReviewer && (
        <div className="control-stack">
          <form action={approvePackageAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="why this package is approved"
              aria-label="Approval reason"
            />
            <button type="submit">Approve package</button>
            <span className="muted">
              Recorded under your name and bound to the active content hash.
            </span>
          </form>
          <form action={requestChangesDecisionAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <select
              name="responsible_state"
              defaultValue="drafting"
              aria-label="Decision responsible state"
            >
              <option value="drafting">writer stage (drafting)</option>
              <option value="editing">editor stage (editing)</option>
              <option value="qa_review">qa stage (qa_review)</option>
            </select>
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="what must change and who is responsible"
              aria-label="Requested changes reason"
            />
            <button type="submit">Request changes</button>
            <span className="muted">
              Routes via the recorded responsible state; the choice is bounded,
              never arbitrary.
            </span>
          </form>
          <form action={rejectPackageAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="why the package is rejected outright"
              aria-label="Rejection reason"
            />
            <button type="submit">Reject package</button>
            <span className="muted">
              WARNING: an editorial rejection of the package, on the record.
            </span>
          </form>
        </div>
      )}
      {state === "approved" && isReviewer && (
        <form action={revokeApprovalAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <select
            name="responsible_state"
            defaultValue="drafting"
            aria-label="Revocation responsible state"
          >
            <option value="drafting">writer stage (drafting)</option>
            <option value="editing">editor stage (editing)</option>
            <option value="qa_review">qa stage (qa_review)</option>
          </select>
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="why the approval no longer stands"
            aria-label="Revocation reason"
          />
          <button type="submit">Revoke approval</button>
          <span className="muted">
            WARNING: the approval record stays; a revocation event is appended
            and the item routes back for rework.
          </span>
        </form>
      )}
    </section>
  );
}

function AiAttemptsSection({ attempts }: { attempts: AiAttemptView[] }) {
  return (
    <section aria-labelledby="detail-attempts">
      <h2 id="detail-attempts">AI attempts</h2>
      <p className="muted">
        Safe persisted metadata only. Prompts and raw model output are never
        stored and never shown.
      </p>
      {attempts.length === 0 && (
        <p className="empty-note">No AI attempts are linked to this item.</p>
      )}
      {attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Purpose</th>
                <th scope="col">Provider / model</th>
                <th scope="col">Schema</th>
                <th scope="col">Template</th>
                <th scope="col">Status</th>
                <th scope="col">Retry</th>
                <th scope="col">Usage</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{attempt.purpose}</td>
                  <td className="mono">
                    {attempt.provider}/{attempt.model_name}
                  </td>
                  <td className="mono">
                    {attempt.schema_name}/{attempt.schema_version}
                  </td>
                  <td className="mono">
                    {attempt.template_name}/{attempt.template_version}
                  </td>
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
                  <td>
                    {Object.keys(attempt.usage).length > 0
                      ? Object.entries(attempt.usage)
                          .map(([key, value]) => `${key}: ${String(value)}`)
                          .join(" · ")
                      : "Not reported"}
                  </td>
                  <td>{formatUtcTimestamp(attempt.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function WorkflowHistorySection({ detail }: { detail: WorkItemDetail }) {
  return (
    <section aria-labelledby="detail-history">
      <h2 id="detail-history">Workflow history</h2>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Transition</th>
              <th scope="col">Actor</th>
              <th scope="col">Reason</th>
              <th scope="col">Artifacts</th>
            </tr>
          </thead>
          <tbody>
            {detail.workflow_events.map((event) => (
              <tr key={event.id}>
                <td>{formatUtcTimestamp(event.occurred_at)}</td>
                <td>
                  {event.from_state ?? "created"} → {event.to_state}
                </td>
                <td>
                  {event.actor_display_name !== null
                    ? `${event.actor_origin} · ${event.actor_display_name}`
                    : event.actor_origin === "operator"
                      ? "operator · UNKNOWN"
                      : event.actor_origin}
                </td>
                <td>{event.reason}</td>
                <td className="mono muted">
                  {Object.entries(event.artifact_refs)
                    .map(([key, value]) => `${key}=${String(value)}`)
                    .join(" ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TruncationNote
        shown={detail.workflow_events.length}
        total={detail.total_workflow_events}
        noun="workflow events"
      />
    </section>
  );
}

export default async function EditorialDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<RawSearchParams>;
}) {
  const { id } = await params;
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchWorkItemDetail(id);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="editorial-detail-title">
        <h1 id="editorial-detail-title">Editorial work item</h1>
        <p role="status">The backend API cannot be reached right now.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="editorial-detail-title">
        <h1 id="editorial-detail-title">Editorial work item</h1>
        <p role="status">The backend API returned unexpected data.</p>
      </section>
    );
  }

  const detail = result.data;
  const draftsResult = await fetchWorkItemDrafts(detail.work_item.id);
  const drafts = draftsResult.kind === "ok" ? draftsResult.data : null;
  const reviewsResult = await fetchWorkItemReviews(detail.work_item.id);
  const reviews = reviewsResult.kind === "ok" ? reviewsResult.data : null;
  const qaResult = await fetchWorkItemQaReports(detail.work_item.id);
  const qaReports = qaResult.kind === "ok" ? qaResult.data : null;
  const decisionsResult = await fetchWorkItemDecisions(detail.work_item.id);
  const decisions = decisionsResult.kind === "ok" ? decisionsResult.data : null;
  const mediaResult = await fetchWorkItemMedia(detail.work_item.id);
  const media = mediaResult.kind === "ok" ? mediaResult.data : null;
  const publicationResult = await fetchWorkItemPublication(detail.work_item.id);
  const publication =
    publicationResult.kind === "ok" ? publicationResult.data : null;
  const currentUserResult = await fetchCurrentUser();
  const isReviewer =
    currentUserResult.kind === "ok" &&
    currentUserResult.data.roles.includes("reviewer");
  // The pack builder needs the eligible evidence only while packs are built.
  let eligibleEvidence: EligibleEvidenceItem[] = [];
  if (
    detail.opportunity !== null &&
    detail.work_item.current_state === "evidence_building" &&
    detail.effective_selected_idea_id !== null
  ) {
    const evidenceResult = await fetchEligibleEvidence(detail.opportunity.id, {
      limit: 100,
    });
    if (evidenceResult.kind === "ok") {
      eligibleEvidence = evidenceResult.data.items;
    }
  }

  return (
    <section
      className="panel panel-wide"
      aria-labelledby="editorial-detail-title"
    >
      <h1 id="editorial-detail-title">Editorial work item</h1>
      <p className="muted">
        <Link href="/editorial">← Back to Editorial Work Queue</Link>
      </p>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={DETAIL_NOTICES}
      />
      <WorkflowSection detail={detail} />
      <OpportunitySection detail={detail} />
      <ResearchInputsSection detail={detail} />
      <IdeasSection detail={detail} />
      <EvidenceSection detail={detail} evidence={eligibleEvidence} />
      <SearchIntentSection detail={detail} />
      <BriefsSection detail={detail} />
      <DraftsSection detail={detail} drafts={drafts} />
      <ReviewsSection detail={detail} reviews={reviews} />
      <QaSection detail={detail} qaReports={qaReports} />
      <MediaSection detail={detail} media={media} />
      <DecisionsSection
        detail={detail}
        decisions={decisions}
        isReviewer={isReviewer}
      />
      <PublicationSection detail={detail} publication={publication} />
      <AiAttemptsSection attempts={detail.ai_attempts} />
      <WorkflowHistorySection detail={detail} />
    </section>
  );
}
