# Konsepthane ContentOS - Editorial Workflow

## Governing pipeline

Discovery
→ Research
→ Normalize
→ Duplicate Detection
→ Idea Scoring
→ Evidence Pack
→ SEO / Search Intent
→ Content Brief
→ Writer
→ Editor
→ QA
→ Human Review
→ Schedule
→ Konsepthane Publishing API
→ Pinterest Distribution
→ Analytics Feedback

Workflow state is durable and auditable. A queue job may perform work for a
state, but queue completion alone must never advance the editorial record.

## Canonical state machine

| State | Entry requirement | Allowed next state(s) |
| --- | --- | --- |
| `DISCOVERED` | Candidate recorded from an enabled source or authorized human input | `RESEARCHING`, `REJECTED` |
| `RESEARCHING` | Research task accepted | `NORMALIZED`, `BLOCKED`, `REJECTED` |
| `NORMALIZED` | Source observations normalized with provenance intact | `DUPLICATE_CHECK` |
| `DUPLICATE_CHECK` | Candidate ready for inventory comparison | `DUPLICATE`, `IDEA_SCORING`, `BLOCKED` |
| `DUPLICATE` | Material overlap is documented | `REJECTED`, `RESEARCHING` if a distinct angle is proposed |
| `IDEA_SCORING` | Candidate is not an unresolved duplicate | `EVIDENCE_BUILDING`, `REJECTED`, `BLOCKED` |
| `EVIDENCE_BUILDING` | Opportunity meets the commissioning threshold | `SEO_RESEARCH`, `BLOCKED`, `REJECTED` |
| `SEO_RESEARCH` | Evidence pack meets minimum sourcing requirements | `BRIEFING`, `BLOCKED` |
| `BRIEFING` | Intent and cannibalization assessment completed | `DRAFTING`, `CHANGES_REQUESTED` |
| `DRAFTING` | Brief version accepted for production | `EDITING`, `BLOCKED` |
| `EDITING` | Draft version exists | `QA_REVIEW`, `CHANGES_REQUESTED`, `REJECTED` |
| `QA_REVIEW` | Edited version and eligible media set exist | `AWAITING_HUMAN_REVIEW`, `CHANGES_REQUESTED`, `BLOCKED` |
| `AWAITING_HUMAN_REVIEW` | QA passes all hard publication gates | `APPROVED`, `CHANGES_REQUESTED`, `REJECTED` |
| `APPROVED` | Authorized human approves exact content/evidence/media versions | `SCHEDULED`, `CHANGES_REQUESTED` |
| `SCHEDULED` | Approved item has a valid publication time and target | `PUBLISHING`, `APPROVAL_EXPIRED`, `BLOCKED` |
| `PUBLISHING` | Approval remains valid and an idempotent API request is active | `PUBLISHED`, `BLOCKED` |
| `PUBLISHED` | Konsepthane API confirms a public content identity/version | `PINTEREST_PENDING`, `MEASURING` |
| `PINTEREST_PENDING` | Published content has eligible media and distribution settings | `DISTRIBUTED`, `BLOCKED`, `MEASURING` |
| `DISTRIBUTED` | Pinterest result is recorded | `MEASURING` |
| `MEASURING` | Published identity is available for analytics matching | `REFRESH_CANDIDATE`, `ARCHIVED`, `MEASURING` |
| `REFRESH_CANDIDATE` | Performance/evidence change justifies reassessment | `RESEARCHING`, `ARCHIVED` |
| `CHANGES_REQUESTED` | Reviewer or gate records actionable reasons | Return to the named responsible state |
| `BLOCKED` | Required input, policy decision, budget, or integration is unavailable | Resume prior state after an explicit resolution event, or `REJECTED` |
| `APPROVAL_EXPIRED` | Approved package changed or approval validity ended | `QA_REVIEW`, `AWAITING_HUMAN_REVIEW` |
| `REJECTED` | A reason and actor are recorded | Terminal, or explicitly reopened to `RESEARCHING` |
| `ARCHIVED` | No active editorial action remains | Terminal, or explicitly reopened to `RESEARCHING` |

## Mandatory transition rules

- Every transition records actor, timestamp, reason, from/to state, relevant
  artifact versions, and correlation ID.
- Only the backend workflow service may apply state transitions.
- Duplicate, evidence, QA, media-rights, budget, approval, and publishing gates
  produce explicit decisions; absence of a result is not a pass.
- `APPROVED` requires a named authorized human at launch. AI or worker identity
  cannot satisfy this gate.
- Any substantive change to approved text, factual claims, links, evidence, or
  media invalidates approval and moves the item to `APPROVAL_EXPIRED`.
- Scheduling does not imply approval, and job success does not imply publication.
- Publishing is complete only after the Publishing API returns a durable public
  identity/version or an equivalent confirmed status.
- Pinterest distribution cannot precede confirmed Konsepthane publication.
- Retry attempts retain one logical operation ID and create separate attempt records.

## Stage gates

### Research and evidence

- Multiple relevant sources are synthesized for substantive topics.
- Each factual claim is linked to eligible evidence or explicitly marked as
  opinion, instruction, or editorial judgment.
- Conflicting sources and uncertainty remain visible in the evidence pack.
- A single competitor article cannot become the outline or factual basis of a draft.

### Brief, writing, and editing

- The brief defines audience, search intent, original angle, claim/evidence map,
  media need, exclusions, and acceptance criteria.
- The writer may use only approved brief/evidence inputs and must surface gaps.
- The editor checks usefulness and originality as well as language and structure.

### QA and human review

- QA checks evidence coverage, unsupported claims, source diversity, similarity,
  internal consistency, links, SEO requirements, media provenance, and policy blocks.
- A human reviewer sees the draft, brief, evidence/claim map, QA results, media
  rights, and material AI/provider metadata before deciding.
- Review outcomes are approve, request changes, or reject; silent timeout is not approval.

### Publication and feedback

- The scheduler submits only a still-valid approved package.
- The Publishing Engine validates the package again before the API call.
- Analytics observations cannot rewrite the historical approval or publication
  record; they create new feedback and possible refresh work.

## Exceptions and recovery

Operators may retry idempotent work, resolve a documented block, or reopen a
terminal item with an explicit reason. They may not skip mandatory states or
manually mark an item published without a confirmed Publishing API result.
Emergency production corrections occur through the Konsepthane-owned process;
ContentOS records the external change when reconciliation becomes available.
