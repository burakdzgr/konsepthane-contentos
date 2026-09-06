"""Cross-source research inputs for one opportunity.

An evidence pack needs at least two independent sources, and idea
originality is judged against the distinct sources behind the admitted
research inputs. Intake promotes ONE document per opportunity, so unless
something links related documents from *other* sources, every opportunity
stays single-sourced forever. This module does that linking
deterministically and conservatively:

- candidates are SUCCEEDED normalized documents from sources whose role
  yields opportunities (inspiration, Turkish editorial) and that permit
  research evidence — never community sources;
- relatedness is distinctive-token overlap between the opportunity topic
  and the candidate title after normalization and stop-word removal
  ("unicorn" ties "Unicorn Birthday Party" to "Sparkle + Shine Unicorn
  Party"; "birthday party" alone ties nothing to anything);
- a candidate needs an effective duplicate decision (the research-input
  row pins it), a bounded scan, a bounded number of links, and each link
  is recorded as a SUPPORTING input added by the system with a note that
  names the shared terms.

Linking never removes inputs, never touches the root document, and never
raises into the caller's pipeline: an opportunity that has no related
documents simply stays as it is.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.repository import DuplicateDecisionRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import OpportunityActor, ResearchInputRole
from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.sources.enums import OPPORTUNITY_ROLES
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService
from contentos.strategy.service import normalize_phrase

MAX_LINKED_INPUTS = 4
CANDIDATE_SCAN_LIMIT = 600
MIN_TOKEN_LENGTH = 3
# Tokens that describe the whole domain rather than a topic. Shared alone
# they tie everything to everything; they never count as evidence of
# relatedness.
GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        "party",
        "parti",
        "partisi",
        "birthday",
        "dogum",
        "gunu",
        "ideas",
        "idea",
        "fikir",
        "fikirleri",
        "fikri",
        "the",
        "and",
        "for",
        "with",
        "your",
        "ile",
        "icin",
        "nasil",
        "yapilir",
        "kara",
        "karas",
        "pretty",
        "catch",
        "my",
        "com",
        "blog",
        "makaleler",
        "yazilari",
        "dugun",
        "partiavm",
        "2024",
        "2025",
        "2026",
        "diy",
        "themed",
        "theme",
        "temali",
        "tema",
        "en",
        "iyi",
        "best",
        "top",
        "guide",
        "rehberi",
        "rehber",
        "how",
        "to",
        "from",
        "that",
        "this",
        "bir",
        "ve",
    }
)


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    linked_document_ids: tuple[uuid.UUID, ...] = ()
    shared_terms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    candidates_scanned: int = 0
    skipped_without_decision: int = 0
    topic_tokens: tuple[str, ...] = ()

    @property
    def linked(self) -> int:
        return len(self.linked_document_ids)


def distinctive_tokens(text: str) -> tuple[str, ...]:
    """Normalized tokens of a title/topic minus generic domain words, in
    first-seen order."""
    stripped = text.split("|")[0] if "|" in text else text
    seen: list[str] = []
    for token in normalize_phrase(stripped).split():
        if len(token) < MIN_TOKEN_LENGTH or token in GENERIC_TOKENS or token.isdigit():
            continue
        if token not in seen:
            seen.append(token)
    return tuple(seen)


def link_related_research_inputs(
    session: Session,
    opportunity_id: uuid.UUID,
    *,
    limit: int = MAX_LINKED_INPUTS,
    now: datetime | None = None,
) -> LinkOutcome:
    opportunities = OpportunityRepository(session)
    opportunity = opportunities.get_by_id(opportunity_id)
    if opportunity is None:
        return LinkOutcome()
    topic_tokens = distinctive_tokens(opportunity.topic_summary)
    if not topic_tokens:
        return LinkOutcome(topic_tokens=())
    required = min(2, len(topic_tokens))

    inputs = opportunities.list_research_inputs(opportunity.id)
    input_document_ids = {row.normalized_document_id for row in inputs}
    root_source_id = _source_id_for(session, opportunity.promotion_root_document_id)
    linked_source_ids = {
        sid
        for sid in (_source_id_for(session, doc_id) for doc_id in input_document_ids)
        if sid is not None
    }

    rows = session.execute(
        select(NormalizedDocument, Source)
        .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
        .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
        .join(Source, Source.id == DiscoveryItem.source_id)
        .where(
            NormalizedDocument.normalization_status == NormalizationStatus.SUCCEEDED,
            NormalizedDocument.title.is_not(None),
            Source.primary_role.in_(tuple(OPPORTUNITY_ROLES)),
        )
        .order_by(NormalizedDocument.created_at.desc(), NormalizedDocument.id.desc())
        .limit(CANDIDATE_SCAN_LIMIT)
    ).all()

    scored: list[tuple[int, int, uuid.UUID, uuid.UUID, tuple[str, ...]]] = []
    topic_set = set(topic_tokens)
    for position, (document, source) in enumerate(rows):
        if (
            document.id in input_document_ids
            or document.id == opportunity.promotion_root_document_id
        ):
            continue
        if not SourceRegistryService.evidence_allowed(source):
            continue
        shared = tuple(
            token for token in distinctive_tokens(document.title or "") if token in topic_set
        )
        if len(shared) < required:
            continue
        # Documents from a source not yet represented come first: they are
        # what makes the pack multi-sourced.
        other_source = (
            0 if source.id not in linked_source_ids and source.id != root_source_id else 1
        )
        scored.append((other_source, -len(shared), position, document.id, shared, source.id))  # type: ignore[arg-type]

    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    decisions = DuplicateDecisionRepository(session)
    moment = now if now is not None else datetime.now(UTC)
    linked: list[uuid.UUID] = []
    shared_terms: dict[str, tuple[str, ...]] = {}
    skipped = 0
    for entry in scored:
        if len(linked) >= limit:
            break
        document_id = entry[3]
        shared = entry[4]
        decision = decisions.get_effective_for_document(document_id)
        if decision is None:
            skipped += 1
            continue
        opportunities.insert_research_input(
            OpportunityResearchInput(
                opportunity_id=opportunity.id,
                normalized_document_id=document_id,
                duplicate_decision_id=decision.id,
                role=ResearchInputRole.SUPPORTING,
                added_by=OpportunityActor.SYSTEM,
                note=f"ilişkili konu: {', '.join(shared)}",
                added_at=moment,
            )
        )
        linked.append(document_id)
        shared_terms[str(document_id)] = shared
    session.flush()
    return LinkOutcome(
        linked_document_ids=tuple(linked),
        shared_terms=shared_terms,
        candidates_scanned=len(rows),
        skipped_without_decision=skipped,
        topic_tokens=topic_tokens,
    )


def _source_id_for(session: Session, document_id: uuid.UUID) -> uuid.UUID | None:
    row = session.execute(
        select(DiscoveryItem.source_id)
        .join(FetchSnapshot, FetchSnapshot.discovery_item_id == DiscoveryItem.id)
        .join(NormalizedDocument, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
        .where(NormalizedDocument.id == document_id)
    ).scalar_one_or_none()
    return row


def distinct_source_count(session: Session, opportunity: EditorialOpportunity) -> int:
    inputs = OpportunityRepository(session).list_research_inputs(opportunity.id)
    sources = {
        sid
        for sid in (_source_id_for(session, row.normalized_document_id) for row in inputs)
        if sid is not None
    }
    return len(sources)
