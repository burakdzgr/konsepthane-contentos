"""Transport-neutral intelligence-signal extraction, lookup and banding.

``signal_bands_for_opportunity(session, opportunity_id)`` is the contract
opportunity intelligence consumes: one honest ``Band`` per ``SignalFamily``.
Families with no durable signal are ``UNKNOWN`` — never zero, never
inferred. Families owned elsewhere (``inspiration`` in
``contentos.inspiration``; ``search``/``trend`` provider observations in
``contentos.signals``) are UNKNOWN here unless a producer mirrors them into
``intelligence_signals``; consumers combine the stores themselves.
"""

import hashlib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.intelligence.enums import Band, SignalFamily
from contentos.intelligence.extractors import (
    PROVIDER_FOR_FAMILY,
    DocumentContext,
    SignalDraft,
    extract_drafts,
)
from contentos.intelligence.models import IntelligenceSignal
from contentos.intelligence.repository import IntelligenceSignalRepository
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.sources.models import Source
from contentos.strategy.service import StrategyService, normalize_phrase

# Band thresholds (documented contract). ``occurrences`` is the sum of
# occurrence_count over the opportunity's matching rows of one family;
# ``sources`` is the number of distinct source ids behind them.
STRONG_MIN_OCCURRENCES = 6
STRONG_MIN_SOURCES = 2
MODERATE_MIN_OCCURRENCES = 3
MODERATE_MIN_SOURCES = 2

MAX_OPPORTUNITY_SIGNALS = 200
MAX_CONCEPT_CANDIDATES = 500
MAX_TOPIC_TOKENS = 12
MIN_TOPIC_TOKEN_LENGTH = 4
DISTINCTIVE_TOKEN_LENGTH = 6


class IntelligenceSignalError(Exception):
    """Base class for intelligence-signal failures."""


class DocumentNotFoundError(IntelligenceSignalError):
    """The normalized document does not exist."""


class OpportunityNotFoundError(IntelligenceSignalError):
    """The opportunity does not exist."""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    created: int
    updated: int
    families: tuple[SignalFamily, ...]
    skipped_reason: str | None = None


def observation_hash(
    family: SignalFamily,
    concept_key: str,
    provider: str,
    source_id: uuid.UUID | None,
    normalized_document_id: uuid.UUID | None,
) -> str:
    material = "|".join(
        (
            family.value,
            concept_key,
            provider,
            str(source_id) if source_id else "",
            str(normalized_document_id) if normalized_document_id else "",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def band_for(occurrences: int, distinct_sources: int) -> Band:
    """Pure banding rule; see the threshold constants above."""
    if occurrences <= 0:
        return Band.UNKNOWN
    if occurrences >= STRONG_MIN_OCCURRENCES and distinct_sources >= STRONG_MIN_SOURCES:
        return Band.STRONG
    if occurrences >= MODERATE_MIN_OCCURRENCES or distinct_sources >= MODERATE_MIN_SOURCES:
        return Band.MODERATE
    return Band.WEAK


def bands_from_signals(signals: Iterable[IntelligenceSignal]) -> dict[SignalFamily, Band]:
    occurrences: dict[SignalFamily, int] = {}
    sources: dict[SignalFamily, set[uuid.UUID]] = {}
    for row in signals:
        occurrences[row.family] = occurrences.get(row.family, 0) + row.occurrence_count
        if row.source_id is not None:
            sources.setdefault(row.family, set()).add(row.source_id)
    return {
        family: band_for(occurrences.get(family, 0), len(sources.get(family, ())))
        for family in SignalFamily
    }


class IntelligenceSignalService:
    def __init__(self, session: Session, *, now: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._repository = IntelligenceSignalRepository(session)
        self._opportunities = OpportunityRepository(session)
        self._now = now or (lambda: datetime.now(UTC))

    # --- extraction -------------------------------------------------------

    def extract_for_document(
        self, document_id: uuid.UUID, *, capabilities: Iterable[str] | None = None
    ) -> ExtractionResult:
        """Idempotent role-aware extraction for one normalized document.

        ``capabilities`` overrides the source's registry capabilities (tests
        and operator re-runs); by default the source decides.
        """
        document = self._session.get(NormalizedDocument, document_id)
        if document is None:
            raise DocumentNotFoundError(f"no normalized document with id {document_id}")
        if document.normalization_status is not NormalizationStatus.SUCCEEDED:
            return ExtractionResult(0, 0, (), skipped_reason="normalization_not_succeeded")
        source, url_host = self._resolve_source(document)
        if source is None:
            return ExtractionResult(0, 0, (), skipped_reason="source_unresolved")
        drafts = extract_drafts(
            DocumentContext(document=document, source=source, url_host=url_host),
            strategy=StrategyService(self._session),
            capabilities=capabilities,
        )
        created = updated = 0
        families: list[SignalFamily] = []
        observed_at = self._now()
        for draft in drafts:
            if self._record(draft, source, document, observed_at):
                created += 1
            else:
                updated += 1
            if draft.family not in families:
                families.append(draft.family)
        return ExtractionResult(created, updated, tuple(families))

    def _record(
        self,
        draft: SignalDraft,
        source: Source,
        document: NormalizedDocument,
        observed_at: datetime,
    ) -> bool:
        provider = PROVIDER_FOR_FAMILY[draft.family]
        digest = observation_hash(draft.family, draft.concept_key, provider, source.id, document.id)
        existing = self._repository.get_by_hash(digest)
        if existing is not None:
            existing.occurrence_count += 1
            existing.last_observed_at = observed_at
            existing.value = draft.value
            existing.subject = draft.subject
            self._session.flush()
            return False
        self._repository.add(
            IntelligenceSignal(
                family=draft.family,
                subject=draft.subject,
                concept_key=draft.concept_key,
                locale=source.locale,
                market=source.market,
                source_id=source.id,
                normalized_document_id=document.id,
                opportunity_id=None,
                provider=provider,
                value=draft.value,
                occurrence_count=1,
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                observation_hash=digest,
            )
        )
        return True

    def _resolve_source(self, document: NormalizedDocument) -> tuple[Source | None, str | None]:
        snapshot = self._session.get(FetchSnapshot, document.fetch_snapshot_id)
        if snapshot is None:
            return None, None
        item = self._session.get(DiscoveryItem, snapshot.discovery_item_id)
        if item is None:
            return None, None
        source = self._session.get(Source, item.source_id)
        url = snapshot.final_url or snapshot.requested_url
        host = urlsplit(url).hostname if url else None
        return source, host

    # --- opportunity lookups ---------------------------------------------

    def signals_for_opportunity(self, opportunity_id: uuid.UUID) -> list[IntelligenceSignal]:
        """Rows linked to the opportunity's research documents, pinned to the
        opportunity, or whose concept key overlaps its topic summary."""
        opportunity = self._session.get(EditorialOpportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        document_ids = {opportunity.promotion_root_document_id}
        document_ids.update(
            row.normalized_document_id
            for row in self._opportunities.list_research_inputs(opportunity.id)
        )
        rows = self._repository.list_signals(
            limit=MAX_OPPORTUNITY_SIGNALS,
            document_ids=document_ids,
            opportunity_id=opportunity.id,
        )
        seen = {row.id for row in rows}
        topic_tokens = _topic_tokens(opportunity.topic_summary)
        normalized_topic = normalize_phrase(opportunity.topic_summary)
        for candidate in self._repository.list_by_concept_tokens(
            topic_tokens, limit=MAX_CONCEPT_CANDIDATES
        ):
            if candidate.id in seen or len(rows) >= MAX_OPPORTUNITY_SIGNALS:
                continue
            if _concept_matches(candidate.concept_key, normalized_topic, topic_tokens):
                seen.add(candidate.id)
                rows.append(candidate)
        rows.sort(key=lambda row: (row.last_observed_at, row.id), reverse=True)
        return rows

    def bands_for_opportunity(self, opportunity_id: uuid.UUID) -> dict[SignalFamily, Band]:
        return bands_from_signals(self.signals_for_opportunity(opportunity_id))


def signal_bands_for_opportunity(
    session: Session, opportunity_id: uuid.UUID
) -> dict[SignalFamily, Band]:
    """Contract for opportunity intelligence: one Band per family, UNKNOWN
    when no durable signal exists."""
    return IntelligenceSignalService(session).bands_for_opportunity(opportunity_id)


def _topic_tokens(topic_summary: str) -> list[str]:
    tokens: list[str] = []
    for token in normalize_phrase(topic_summary).split():
        if len(token) >= MIN_TOPIC_TOKEN_LENGTH and token not in tokens:
            tokens.append(token)
        if len(tokens) >= MAX_TOPIC_TOKENS:
            break
    return tokens


def _concept_matches(concept_key: str, normalized_topic: str, topic_tokens: list[str]) -> bool:
    if not concept_key:
        return False
    if concept_key in normalized_topic:
        return True
    concept_tokens = set(concept_key.split())
    overlap = concept_tokens & set(topic_tokens)
    if len(overlap) >= min(2, len(concept_tokens)):
        return True
    return any(len(token) >= DISTINCTIVE_TOKEN_LENGTH for token in overlap)
