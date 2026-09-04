"""Strategy portfolio and inspiration recommendation acceptance tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from contentos.db.base import Base
from contentos.inspiration.enums import (
    InspirationBand,
    OpportunityRecommendation,
    SearchOpportunityBand,
)
from contentos.inspiration.service import recommendation_for
from contentos.strategy.enums import StrategyStatus
from contentos.strategy.models import AudienceStrategy, StrategicKeyword, TopicCluster
from contentos.strategy.service import MAX_STRATEGY_MATCHES, StrategyService


def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            AudienceStrategy.__table__,
            TopicCluster.__table__,
            StrategicKeyword.__table__,
        ],
    )
    return Session(engine)


def test_create_edit_keyword_and_assign_topic_cluster() -> None:
    with session() as db:
        service = StrategyService(db)
        cluster = service.create_cluster(name="Evlilik Teklifi", priority=90)
        keyword = service.create_keyword(
            phrase="ilginç evlilik teklifleri",
            priority=85,
            topic_cluster_id=cluster.id,
        )
        updated = service.update_keyword(
            keyword.id,
            phrase="klişe olmayan evlilik teklifleri",
            priority=95,
            status=StrategyStatus.ACTIVE,
            topic_cluster_id=cluster.id,
            notes="Özgün ve uygulanabilir fikirler",
        )

        assert updated.priority == 95
        assert updated.topic_cluster_id == cluster.id
        assert updated.normalized_phrase == "klise olmayan evlilik teklifleri"


def test_strategy_priority_orders_but_does_not_filter_unexpected_idea() -> None:
    with session() as db:
        service = StrategyService(db)
        cluster = service.create_cluster(name="1 Yaş Doğum Günü", priority=100)
        service.create_keyword(
            phrase="1 yaş doğum günü",
            priority=100,
            topic_cluster_id=cluster.id,
        )

        assert service.priority_for_text("1 yaş doğum günü masa süsleme") == 100
        # Zero means "no priority boost", never rejection/censorship.
        assert service.priority_for_text("beklenmedik yaratıcı bahçe fikri") == 0


def test_writer_context_is_bounded_to_relevant_portfolio_slice() -> None:
    with session() as db:
        service = StrategyService(db)
        cluster = service.create_cluster(name="Çocuk Doğum Günü", priority=100)
        for index in range(MAX_STRATEGY_MATCHES + 4):
            service.create_keyword(
                phrase=f"çocuk doğum günü konsepti {index}",
                priority=100 - index,
                topic_cluster_id=cluster.id,
            )
        service.create_keyword(phrase="nişan masası", priority=99)

        context = service.context_for_text(
            "çocuk doğum günü konsepti için uygulanabilir fikirler"
        ).projection()
        assert len(context["keywords"]) == MAX_STRATEGY_MATCHES
        assert all("nişan" not in row["phrase"] for row in context["keywords"])
        assert context["bounded"] is True


def test_high_search_low_inspiration_continues_research() -> None:
    result = recommendation_for(
        search=SearchOpportunityBand.STRONG,
        inspiration=InspirationBand.LOW,
        has_evidence=True,
        has_strategy_match=True,
        commissionable=True,
    )
    assert result is OpportunityRecommendation.CONTINUE_RESEARCH


def test_high_quality_with_evidence_and_strategy_is_ready_for_human_decision() -> None:
    result = recommendation_for(
        search=SearchOpportunityBand.UNKNOWN,
        inspiration=InspirationBand.HIGH,
        has_evidence=True,
        has_strategy_match=True,
        commissionable=True,
    )
    assert result is OpportunityRecommendation.PRODUCE


def test_unknown_search_is_not_coerced_to_weak() -> None:
    result = recommendation_for(
        search=SearchOpportunityBand.UNKNOWN,
        inspiration=InspirationBand.MEDIUM,
        has_evidence=True,
        has_strategy_match=False,
        commissionable=True,
    )
    assert result is OpportunityRecommendation.HUMAN_REVIEW


def test_produce_is_never_recommended_for_a_score_the_gate_would_refuse() -> None:
    """The inbox verdict and the commissioning gate share one rule: a
    NOT_COMMISSIONABLE / NEEDS_OPERATOR_REVIEW base score can never carry
    an "İÇERİK ÜRET" verdict, because the backend would refuse it with 409."""
    result = recommendation_for(
        search=SearchOpportunityBand.UNKNOWN,
        inspiration=InspirationBand.HIGH,
        has_evidence=True,
        has_strategy_match=True,
        commissionable=False,
    )
    assert result is OpportunityRecommendation.HUMAN_REVIEW
