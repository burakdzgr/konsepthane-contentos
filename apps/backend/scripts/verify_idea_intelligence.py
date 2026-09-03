"""Verify idea intelligence against an existing real source in local PostgreSQL.

The script never invents source, search, or trend data. It adds a small,
idempotent operator strategy only when missing, evaluates opportunities already
derived from the requested source, and proves every extracted signal still
resolves to that source through the durable research chain.
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from contentos.core.config import Settings
from contentos.db.session import create_database_engine, create_session_factory
from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.inspiration.models import InspirationSignal
from contentos.inspiration.service import InspirationIntelligenceService
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput
from contentos.sources.models import Source
from contentos.strategy.models import AudienceStrategy, StrategicKeyword, TopicCluster
from contentos.strategy.service import StrategyService, normalize_phrase


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="kara", help="Source name/slug fragment")
    parser.add_argument("--limit", type=int, default=50, help="Opportunity cap (1-200)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be between 1 and 200")
    return args


def ensure_strategy(session: Session) -> None:
    service = StrategyService(session)
    cluster = session.scalar(select(TopicCluster).where(TopicCluster.slug == "cocuk-dogum-gunu"))
    if cluster is None:
        cluster = service.create_cluster(name="Çocuk Doğum Günü", priority=95)
    if (
        session.scalar(select(AudienceStrategy).where(AudienceStrategy.name == "Çocuklu anneler"))
        is None
    ):
        service.create_audience(name="Çocuklu anneler", priority=100)
    phrases = (
        ("çocuk doğum günü konseptleri", 100),
        ("frozen doğum günü", 95),
        ("1 yaş doğum günü", 100),
    )
    for phrase, priority in phrases:
        if (
            session.scalar(
                select(StrategicKeyword).where(
                    StrategicKeyword.normalized_phrase == normalize_phrase(phrase)
                )
            )
            is None
        ):
            service.create_keyword(
                phrase=phrase,
                priority=priority,
                topic_cluster_id=cluster.id,
                notes="Gerçek yerel kabul senaryosu için operatör stratejisi.",
            )


def main() -> None:
    args = parse_args()
    settings = Settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        needle = f"%{args.source.casefold()}%"
        sources = list(
            session.scalars(
                select(Source).where(
                    or_(func.lower(Source.name).like(needle), func.lower(Source.slug).like(needle))
                )
            )
        )
        assert sources, f"No existing source matched {args.source!r}"
        source_ids = [row.id for row in sources]
        discovered_count = int(
            session.scalar(
                select(func.count())
                .select_from(DiscoveryItem)
                .where(DiscoveryItem.source_id.in_(source_ids))
            )
            or 0
        )
        normalized_count = int(
            session.scalar(
                select(func.count())
                .select_from(NormalizedDocument)
                .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
                .join(DiscoveryItem, FetchSnapshot.discovery_item_id == DiscoveryItem.id)
                .where(DiscoveryItem.source_id.in_(source_ids))
            )
            or 0
        )
        opportunity_ids = list(
            session.scalars(
                select(OpportunityResearchInput.opportunity_id)
                .join(
                    NormalizedDocument,
                    OpportunityResearchInput.normalized_document_id == NormalizedDocument.id,
                )
                .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
                .join(DiscoveryItem, FetchSnapshot.discovery_item_id == DiscoveryItem.id)
                .where(DiscoveryItem.source_id.in_(source_ids))
                .distinct()
                .limit(args.limit)
            )
        )
        assert opportunity_ids, "The source has no promoted opportunities to evaluate"
        ensure_strategy(session)
        session.commit()

        service = InspirationIntelligenceService(session)
        recommendations: Counter[str] = Counter()
        inspiration_bands: Counter[str] = Counter()
        search_bands: Counter[str] = Counter()
        signals_created = 0
        for opportunity_id in opportunity_ids:
            assert session.get(EditorialOpportunity, opportunity_id) is not None
            result = service.evaluate(opportunity_id)
            signals_created += result.signals_created
            recommendations[result.evaluation.recommendation.value] += 1
            inspiration_bands[result.evaluation.inspiration_band.value] += 1
            search_bands[result.evaluation.search_opportunity.value] += 1
        session.commit()

        provenance_count = int(
            session.scalar(
                select(func.count())
                .select_from(InspirationSignal)
                .join(
                    NormalizedDocument,
                    InspirationSignal.normalized_document_id == NormalizedDocument.id,
                )
                .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
                .join(DiscoveryItem, FetchSnapshot.discovery_item_id == DiscoveryItem.id)
                .where(
                    InspirationSignal.opportunity_id.in_(opportunity_ids),
                    DiscoveryItem.source_id.in_(source_ids),
                )
            )
            or 0
        )
        total_signals = int(
            session.scalar(
                select(func.count())
                .select_from(InspirationSignal)
                .where(InspirationSignal.opportunity_id.in_(opportunity_ids))
            )
            or 0
        )
        assert provenance_count == total_signals

        print(f"source={','.join(row.name for row in sources)}")
        print(f"discovered_urls={discovered_count}")
        print(f"normalized_documents={normalized_count}")
        print(f"evaluated_opportunities={len(opportunity_ids)}")
        print(f"signals={total_signals} newly_created={signals_created}")
        print(f"inspiration={dict(inspiration_bands)}")
        print(f"search_opportunity={dict(search_bands)}")
        print(f"recommendations={dict(recommendations)}")
        print(f"provenance_resolved={provenance_count}/{total_signals}")


if __name__ == "__main__":
    main()
