"""The research-driven idea engine.

A ResearchMission starts from a goal, never from a source. The engine:

1. PLANNING     — understands intent and plans queries (model, else deterministic)
2. KEYWORDS     — expands keywords; demand/trend from configured providers, else UNKNOWN
3. SEARCHING    — registered sources, open web, visual inspiration, community, trend
4. EXTRACTING   — idea primitives + candidates (extracted and synthesized)
5. CLUSTERING   — merges near-duplicates deterministically
6. EVALUATING   — idea quality, cliché filter, strategy fit, recommendations
7. GROUNDING    — fetches the pages behind promotable ideas through the normal
                  intake chain (so factual evidence rules stay intact)
8. PROMOTING    — strong, grounded ideas become EditorialOpportunities

Two confidences stay separate on purpose: IDEA quality (creative, judged
here) and FACTUAL evidence (judged only by the evidence pipeline). Signals
collected here are inspiration provenance and never ResearchEvidence.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.repository import DuplicateDecisionRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.integrations.enums import ProviderName
from contentos.integrations.google_search_console import GoogleSearchConsoleProvider
from contentos.integrations.observations import recent_trend_term_rows
from contentos.integrations.registry import IntegrationRegistry
from contentos.integrations.sessions import bind_session
from contentos.missions.enums import (
    CandidateKind,
    CandidateRecommendation,
    FactualEvidenceConfidence,
    IdeaConfidence,
    MissionStage,
    MissionStatus,
    SurfaceKind,
)
from contentos.missions.models import MissionIdeaCandidate, MissionSignal, ResearchMission
from contentos.missions.schemas import (
    IDEA_SYNTHESIS_SCHEMA_NAME,
    IDEA_SYNTHESIS_SCHEMA_VERSION,
    IDEA_SYNTHESIS_TEMPLATE_NAME,
    IDEA_SYNTHESIS_TEMPLATE_VERSION,
    MAX_SYNTHESIS_CANDIDATES,
    MAX_WEB_SIGNALS,
    MISSION_PLAN_SCHEMA_NAME,
    MISSION_PLAN_SCHEMA_VERSION,
    MISSION_PLAN_TEMPLATE_NAME,
    MISSION_PLAN_TEMPLATE_VERSION,
    RESEARCH_SIGNALS_SCHEMA_NAME,
    RESEARCH_SIGNALS_SCHEMA_VERSION,
    WEB_RESEARCH_TEMPLATE_NAME,
    WEB_RESEARCH_TEMPLATE_VERSION,
    IdeaSynthesisV1,
    MissionPlanV1,
    PlannedQueryV1,
    ResearchSignalsV1,
)
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
)
from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.sources.enums import (
    DiscoveryStrategy,
    SourceCapability,
    SourceKind,
    SourceLifecycleState,
    SourceRole,
    TrustTier,
)
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService
from contentos.strategy.service import StrategyService, normalize_phrase
from contentos.workflow.enums import WorkflowActorOrigin, WorkItemOrigin
from contentos.workflow.service import WorkflowService

_logger = structlog.get_logger(__name__)

ENGINE_NAME = "research-mission-engine"
ENGINE_VERSION = "1"

MAX_REGISTERED_SIGNALS = 40
MAX_TREND_SIGNALS = 12
MAX_SYNTHESIS_SIGNALS = 60
MAX_PROMOTIONS = 5
# Model factor scores run generous; only the strongest few are "strong".
MAX_PROMOTE_RECOMMENDED = 8
MAX_GROUNDING_FETCHES = 8
MAX_SUPPORTING_INPUTS = 4
GROUNDING_WAIT = timedelta(minutes=15)
PROMOTE_THRESHOLD = 65
CONTINUE_THRESHOLD = 50
MERGE_JACCARD = 0.6
# One shared token this long is specific enough on its own ("cinderella");
# "evlilik" (7) alone would drag every marriage page into a proposal mission.
STRONG_TOKEN_LENGTH = 9
MAX_OUTPUT_TOKENS = 6000
DEMAND_WINDOW_DAYS = 90
TREND_WINDOW_DAYS = 30
STRATEGIC_FIT_BONUS = 5

# Creative quality weights; none of them is a demand or a fact measure.
QUALITY_WEIGHTS: dict[str, float] = {
    "novelty": 0.20,
    "usefulness": 0.20,
    "specificity": 0.10,
    "visual_potential": 0.15,
    "shareability": 0.10,
    "emotional_impact": 0.10,
    "audience_fit": 0.10,
    "turkey_applicability": 0.05,
}

_GENERIC_TOKENS = frozenset(
    {
        "fikir",
        "fikirleri",
        "fikri",
        "ideas",
        "idea",
        "icin",
        "ile",
        "ve",
        "bir",
        "the",
        "and",
        "for",
        "with",
        "nasil",
        "yapilir",
        "en",
        "iyi",
        "best",
        "top",
        "2024",
        "2025",
        "2026",
    }
)

_PLAN_TEMPLATE = """\
Sen Konsepthane için çalışan bir ARAŞTIRMA PLANLAYICISISIN. Konsepthane,
Türkiye'de kutlama ve etkinlik konseptleri (doğum günü, evlilik teklifi,
baby shower, düğün öncesi vb.) için özgün, uygulanabilir ve görsel olarak
güçlü fikirler yayımlar. Sana bir araştırma görevi (konu, amaç, hedef
kitle) verilir. Görevin araştırmayı planlamak:
1. intent_summary: okurun gerçek niyeti ve ne bulmak istediği (Türkçe).
2. audience_notes: hedef kitlenin uygulanabilirlik/bütçe/ortam beklentileri.
3. keywords: Türkçe arama niyetini kapsayan 6-20 anahtar ifade (eş anlam,
   niyet varyantları: "yaratıcı", "farklı", "sürpriz", "romantik" vb.).
4. queries: 6-16 arama sorgusu; Türkçe ve İngilizce karışık. surface
   alanı: open_web (genel web), visual_inspiration (site:pinterest.com ile
   görsel/tema keşfi), community_need (forum/soru-cevap ihtiyaçları).
5. cliche_patterns: bu konuda herkesin yazdığı sıradan fikirler (örn.
   "sahilde teklif", "restoranda teklif"); 5-20 adet.
6. primitive_hints: fikirlerin altındaki mekanikler (yükseklik, sürpriz
   zamanlaması, gizli mesaj, rota, QR, ortak hatıra, reveal...).
Olgu, istatistik veya trend UYDURMA; bu bir plandır.
"""

_WEB_RESEARCH_TEMPLATE = """\
Sen Konsepthane için AÇIK WEB ARAŞTIRMASI yapan bir asistansın. Web'de
arama yapabiliyorsan verilen sorguları GERÇEKTEN ara ve gördüğün sayfaları
raporla. Her sinyal: gerçek bir sayfa başlığı, kısa özet (kendi
cümlelerinle), kesin URL (uyduramazsan null), yüzey türü ve neden ilgili
olduğu. Pinterest sonuçları GÖRSEL/YARATICI İLHAM sinyalidir; olgu değildir.
Topluluk yüzeyi (forum, soru-cevap, yorum) kullanıcı ihtiyacını gösterir.
KURALLAR:
- URL uydurma; emin değilsen url alanını null bırak.
- Sayfa içeriğini kopyalama; snippet kendi özetin olsun (en fazla 2 cümle).
- Fiyat, istatistik, tarih gibi olgusal iddiaları sinyal olarak yazma.
- Toplam en fazla 40 sinyal; çeşitlilik (farklı siteler, diller) önemli.
- Arama yapamıyorsan signals listesini boş bırak ve search_notes'ta belirt.
"""

RECALL_RESEARCH_TEMPLATE_NAME = "web-research-recall"

_RECALL_RESEARCH_TEMPLATE = """\
Sen Konsepthane için araştırma yapan bir asistansın. Bu turda web'de ARAMA
YAPMA ve tarayıcı/araç kullanma; yalnızca kendi bilginle yanıt ver. Verilen
konu ve sorgular için kamuya açık yayınlarda, blog ve forumlarda yaygın
olarak görülen fikir kalıplarını ve okur ihtiyaçlarını sinyal olarak listele.
Her sinyal: fikri anlatan bir başlık, kendi cümlelerinle 1-2 cümle özet,
yüzey türü (open_web / visual_inspiration / community_need), dil ve neden
ilgili olduğu. url alanını DAİMA null bırak; sayfa adresi uydurma.
Olgu, istatistik, fiyat, tarih veya "en popüler" iddiası yazma.
En fazla 40 sinyal; çeşitlilik (mekanik, mekân, bütçe, dil) önemli.
"""

_SYNTHESIS_TEMPLATE = """\
Sen Konsepthane için FİKİR SENTEZİ yapan bir editörsün. Sana bir araştırma
görevi ve toplanan ilham sinyalleri (id'li) verilir. Görevin:
1. primitives: sinyallerde görülen fikirlerin altındaki mekanikleri çıkar
   (örn. yükseklik, sürpriz zamanlaması, fotoğraf anı, gizli mesaj, rota,
   QR, ortak hatıra, reveal). key alanı kısa slug (a-z, 0-9, -).
2. candidates: 12-30 fikir adayı. İki tür:
   - extracted: sinyallerde doğrudan görülen bir fikir (signal_ids zorunlu).
   - synthesized: mekaniklerin YENİ ve uygulanabilir birleşimi (primitive_keys
     zorunlu; ilham aldığı signal_ids varsa ver).
3. Her aday: somut başlık (Türkçe, klişe değil), angle (neden farklı, kime
   iyi gelir), cluster_key (benzer adaylar aynı anahtarı paylaşır),
   is_cliche + cliche_reason (sahil/restoran/çiçek gibi sıradan fikirler
   klişedir), factors (0-100: novelty, usefulness, specificity,
   visual_potential, shareability, emotional_impact, audience_fit,
   turkey_applicability — Türkiye'de bütçe, mekân ve kültür açısından
   uygulanabilirlik), implementation_steps (3-6 adım),
   factual_claims_needed (fikri anlatırken doğrulanması gereken olgular;
   fikrin kendisi olgu DEĞİLDİR), rationale.
KURALLAR:
- Sinyal başlıklarını kopyalama; her aday kendi cümlelerinle.
- Anlamsız birleşim üretme: her synthesized aday gerçek bir çift için
  uygulanabilir olmalı.
- İstatistik, trend veya "en popüler" iddiası yazma.
- signal_ids yalnızca verilen id'lerden olsun.
"""


@dataclass(frozen=True, slots=True)
class StageOutcome:
    stage: MissionStage
    note: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FinalizeOutcome:
    done: bool
    promoted: tuple[uuid.UUID, ...] = ()
    # Opportunities created by THIS call; the caller evaluates them after
    # its commit (a task dispatched before the commit finds no row).
    newly_promoted: tuple[uuid.UUID, ...] = ()
    pending_fetches: int = 0
    note: str = ""


def _tokens(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for token in normalize_phrase(text).split():
        if len(token) < 3 or token in _GENERIC_TOKENS or token.isdigit():
            continue
        if token not in seen:
            seen.append(token)
    return tuple(seen)


def _related(query_tokens: set[str], text: str) -> tuple[str, ...]:
    shared = tuple(token for token in _tokens(text) if token in query_tokens)
    if len(shared) >= 2 or any(len(token) >= STRONG_TOKEN_LENGTH for token in shared):
        return shared
    return ()


def _jaccard(a: str, b: str) -> float:
    left, right = set(_tokens(a)), set(_tokens(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _absolute_url(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return None
    if len(candidate) > 2000 or any(c.isspace() for c in candidate):
        return None
    return candidate


def _url_words(url: str | None) -> str:
    """Slug words of a URL path ("/evlilik-teklifi-fikirleri" -> "evlilik
    teklifi fikirleri"): sitemap discoveries usually carry no title hint."""
    if not url:
        return ""
    path = urlsplit(url).path
    return " ".join(part for part in re.split(r"[^0-9A-Za-zÇçĞğİıÖöŞşÜü]+", path) if len(part) > 2)


def _slug_title(url: str) -> str:
    """A readable title from the last path segment when the sitemap gave no
    title hint ("/unutulmaz-evlilik-teklifleri-153" -> "unutulmaz evlilik
    teklifleri")."""
    segments = [part for part in urlsplit(url).path.split("/") if part]
    last = segments[-1] if segments else ""
    words = [w for w in re.split(r"[^0-9A-Za-zÇçĞğİıÖöŞşÜü]+", last) if w and not w.isdigit()]
    return " ".join(words) if words else url


def _domain(url: str) -> str | None:
    host = urlsplit(url).hostname
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def quality_score(factors: dict[str, int], *, strategic_fit: bool) -> int:
    weighted = sum(QUALITY_WEIGHTS[key] * int(factors.get(key, 0)) for key in QUALITY_WEIGHTS)
    total = weighted / sum(QUALITY_WEIGHTS.values())
    if strategic_fit:
        total += STRATEGIC_FIT_BONUS
    return max(0, min(100, round(total)))


def confidence_for(quality: int) -> IdeaConfidence:
    if quality >= 75:
        return IdeaConfidence.HIGH
    if quality >= 55:
        return IdeaConfidence.MEDIUM
    return IdeaConfidence.LOW


def matches_cliche(title: str, angle: str, patterns: list[str]) -> str | None:
    """A candidate is a cliché when every distinctive token of a known
    cliché pattern appears in its title (the angle never rescues it)."""
    title_tokens = set(_tokens(title))
    for pattern in patterns:
        pattern_tokens = set(_tokens(pattern))
        if pattern_tokens and pattern_tokens <= title_tokens:
            return pattern
    del angle
    return None


class MissionEngine:
    """Stateful orchestration over one session; the caller commits at the
    checkpoints the engine announces (so the operator sees live progress)."""

    def __init__(
        self,
        session: Session,
        *,
        provider: StructuredGenerationProvider | None = None,
        registry: IntegrationRegistry | None = None,
        dispatch_fetch: Callable[[str], None] | None = None,
        checkpoint: Callable[[], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._registry = registry
        self._dispatch_fetch = dispatch_fetch
        self._checkpoint = checkpoint or (lambda: None)
        self._now = now or (lambda: datetime.now(UTC))
        self._generation = StructuredGenerationService(session)

    # --- public --------------------------------------------------------------------

    def run(self, mission_id: uuid.UUID) -> ResearchMission:
        mission = self._session.get(ResearchMission, mission_id)
        if mission is None:
            raise LookupError("araştırma görevi bulunamadı")
        mission.status = MissionStatus.RUNNING
        mission.failure_reason = None
        self._reset(mission)
        try:
            plan = self._plan(mission)
            self._keywords(mission, plan)
            signals = self._search(mission, plan)
            candidates = self._extract(mission, plan, signals)
            candidates = self._cluster(mission, candidates)
            self._evaluate(mission, plan, candidates, signals)
            self._ground(mission, candidates, signals)
        except Exception as error:
            mission.status = MissionStatus.FAILED
            mission.failure_reason = f"{type(error).__name__}: {error}"[:2000]
            self._log(mission, mission.stage, "failed", mission.failure_reason)
            self._session.flush()
            self._checkpoint()
            raise
        return mission

    def finalize(self, mission_id: uuid.UUID) -> FinalizeOutcome:
        """Promote grounded promotable candidates; report whether fetches
        are still pending (the task re-checks later)."""
        mission = self._session.get(ResearchMission, mission_id)
        if mission is None:
            raise LookupError("araştırma görevi bulunamadı")
        if mission.status not in (MissionStatus.GROUNDING, MissionStatus.RUNNING):
            return FinalizeOutcome(done=True, note="görev zaten sonuçlandı")
        candidates = self._promotable(mission)
        signals = {str(row.id): row for row in self._signals(mission)}
        promoted: list[uuid.UUID] = []
        newly: list[uuid.UUID] = []
        pending = 0
        for candidate in candidates:
            if candidate.opportunity_id is not None:
                promoted.append(candidate.opportunity_id)
                continue
            documents = self._grounded_documents(candidate, signals)
            if documents:
                opportunity = self._promote(mission, candidate, documents)
                if opportunity is not None:
                    promoted.append(opportunity.id)
                    newly.append(opportunity.id)
                continue
            if self._fetch_pending(candidate, signals):
                pending += 1
        if pending and self._now() - self._grounding_started(mission) < GROUNDING_WAIT:
            self._session.flush()
            self._checkpoint()
            return FinalizeOutcome(
                done=False,
                promoted=tuple(promoted),
                newly_promoted=tuple(newly),
                pending_fetches=pending,
            )
        self._complete(mission, promoted, pending)
        return FinalizeOutcome(
            done=True,
            promoted=tuple(promoted),
            newly_promoted=tuple(newly),
            pending_fetches=pending,
        )

    # --- stages ---------------------------------------------------------------------

    def _plan(self, mission: ResearchMission) -> MissionPlanV1:
        self._stage(mission, MissionStage.PLANNING, "Konu ve okur niyeti analiz ediliyor")
        strategy = self._strategy_projection(mission)
        surfaces = [
            {
                "name": source.name,
                "role": source.primary_role.value,
                "capabilities": list(source.capabilities or []),
            }
            for source in self._active_sources()
        ]
        plan: MissionPlanV1 | None = None
        plan_source = "deterministic"
        if self._provider is not None:
            request = GenerationRequest(
                purpose=GenerationPurpose.MISSION_PLANNING,
                schema_name=MISSION_PLAN_SCHEMA_NAME,
                schema_version=MISSION_PLAN_SCHEMA_VERSION,
                template_name=MISSION_PLAN_TEMPLATE_NAME,
                template_version=MISSION_PLAN_TEMPLATE_VERSION,
                input_refs={
                    "schema": "mission-plan-input/1",
                    "mission_id": str(mission.id),
                    "engine_name": ENGINE_NAME,
                    "engine_version": ENGINE_VERSION,
                },
                input_projection={
                    "topic": mission.topic,
                    "goal": mission.goal,
                    "audience": mission.audience,
                    "seed_keyword": mission.seed_keyword,
                    "locale": mission.locale,
                    "market": mission.market,
                    "strategy": strategy,
                    "registered_surfaces": surfaces[:20],
                },
                generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
                retry_number=self._retry(mission, "planning"),
                instructions=_PLAN_TEMPLATE,
            )
            spec: StructuredOutputSpec[MissionPlanV1] = StructuredOutputSpec(
                schema_name=MISSION_PLAN_SCHEMA_NAME,
                schema_version=MISSION_PLAN_SCHEMA_VERSION,
                model_type=MissionPlanV1,
                domain_validator=_plan_validator,
            )
            execution = self._generation.execute(request, spec, self._provider)
            if execution.status is GenerationStatus.SUCCEEDED and execution.payload is not None:
                plan = execution.payload
                plan_source = "model"
            else:
                self._log(
                    mission,
                    MissionStage.PLANNING,
                    "note",
                    f"model planı alınamadı ({execution.status.value}); deterministik plan",
                )
        if plan is None:
            plan = _deterministic_plan(mission)
        mission.plan = {
            "source": plan_source,
            "intent_summary": plan.intent_summary,
            "audience_notes": plan.audience_notes,
            "cliche_patterns": list(plan.cliche_patterns),
            "primitive_hints": list(plan.primitive_hints),
            "strategy": strategy,
        }
        mission.query_plan = [
            {
                "query": q.query,
                "language": q.language,
                "purpose": q.purpose,
                "surface": q.surface,
                "status": "planned",
            }
            for q in plan.queries
        ]
        self._log(
            mission,
            MissionStage.PLANNING,
            "done",
            f"{len(plan.keywords)} anahtar ifade, {len(plan.queries)} sorgu ({plan_source})",
        )
        self._session.flush()
        self._checkpoint()
        return plan

    def _keywords(self, mission: ResearchMission, plan: MissionPlanV1) -> None:
        self._stage(mission, MissionStage.KEYWORDS, "Anahtar kelimeler ve arama sinyalleri")
        keywords: list[str] = []
        for raw in [mission.seed_keyword or "", *plan.keywords]:
            cleaned = " ".join(raw.split())
            if cleaned and cleaned.casefold() not in {k.casefold() for k in keywords}:
                keywords.append(cleaned[:240])
        demand_rows, demand_state = self._search_console_rows()
        trend_rows = self._trend_rows(mission)
        entries: list[dict[str, Any]] = []
        for keyword in keywords[:20]:
            tokens = set(_tokens(keyword))
            demand: dict[str, Any] = {"state": demand_state}
            if demand_rows and tokens:
                clicks = impressions = 0
                matched = 0
                for query, row_clicks, row_impressions in demand_rows:
                    if tokens <= set(_tokens(query)):
                        matched += 1
                        clicks += row_clicks
                        impressions += row_impressions
                if matched:
                    demand = {
                        "state": "observed",
                        "provider": ProviderName.GOOGLE_SEARCH_CONSOLE.value,
                        "window_days": DEMAND_WINDOW_DAYS,
                        "matched_queries": matched,
                        "clicks": clicks,
                        "impressions": impressions,
                    }
                else:
                    demand = {"state": "not_observed", "note": "site trafiğinde bu sorgu görülmedi"}
            trend: dict[str, Any] = {"state": "unknown"}
            for term, payload in trend_rows:
                if tokens and tokens <= set(_tokens(term)):
                    trend = {
                        "state": "observed",
                        "provider": ProviderName.GOOGLE_TRENDS_BIGQUERY.value,
                        "term": term,
                        "trend_type": payload.get("trend_type"),
                        "rank": payload.get("rank"),
                    }
                    break
            if trend["state"] == "unknown" and trend_rows:
                trend = {"state": "not_observed", "note": "TR top/rising listelerinde görülmedi"}
            entries.append({"keyword": keyword, "demand": demand, "trend": trend})
        mission.keyword_plan = entries
        observed = sum(1 for e in entries if e["demand"].get("state") == "observed")
        trending = sum(1 for e in entries if e["trend"].get("state") == "observed")
        self._log(
            mission,
            MissionStage.KEYWORDS,
            "done",
            f"{len(entries)} anahtar kelime; arama verisi {observed}, trend eşleşmesi {trending}",
        )
        self._session.flush()
        self._checkpoint()

    def _search(self, mission: ResearchMission, plan: MissionPlanV1) -> list[MissionSignal]:
        self._stage(mission, MissionStage.SEARCHING, "Kayıtlı kaynaklar ve açık web taranıyor")
        query_tokens: set[str] = set()
        for entry in mission.keyword_plan:
            query_tokens.update(_tokens(str(entry["keyword"])))
        query_tokens.update(_tokens(mission.topic))
        signals: list[MissionSignal] = []
        counts: dict[str, int] = {}
        unavailable: list[str] = []

        def add(signal: MissionSignal) -> None:
            self._session.add(signal)
            signals.append(signal)
            counts[signal.surface_kind.value] = counts.get(signal.surface_kind.value, 0) + 1

        for signal in self._registered_signals(mission, query_tokens):
            add(signal)
        for signal in self._trend_signals(mission):
            add(signal)
        web_note = self._web_research(mission, plan, add)
        if web_note:
            unavailable.append(web_note)
        self._session.flush()
        for kind in SurfaceKind:
            if kind.value not in counts:
                counts.setdefault(kind.value, 0)
        mission.surface_summary = {
            "counts": counts,
            "surfaces_used": sorted(k for k, v in counts.items() if v),
            "unavailable": unavailable,
            "note": "Sinyaller ilham izidir; hiçbiri olgu kanıtı değildir.",
        }
        self._log(
            mission,
            MissionStage.SEARCHING,
            "done",
            f"{len(signals)} sinyal: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v),
        )
        self._checkpoint()
        return signals

    def _extract(
        self, mission: ResearchMission, plan: MissionPlanV1, signals: list[MissionSignal]
    ) -> list[MissionIdeaCandidate]:
        self._stage(mission, MissionStage.EXTRACTING, "Fikir parçaları ve adaylar çıkarılıyor")
        synthesis: IdeaSynthesisV1 | None = None
        synthesis_source = "deterministic"
        known_ids = {str(row.id) for row in signals}
        if self._provider is not None and signals:
            request = GenerationRequest(
                purpose=GenerationPurpose.IDEA_SYNTHESIS,
                schema_name=IDEA_SYNTHESIS_SCHEMA_NAME,
                schema_version=IDEA_SYNTHESIS_SCHEMA_VERSION,
                template_name=IDEA_SYNTHESIS_TEMPLATE_NAME,
                template_version=IDEA_SYNTHESIS_TEMPLATE_VERSION,
                input_refs={
                    "schema": "idea-synthesis-input/1",
                    "mission_id": str(mission.id),
                    "signal_ids": sorted(known_ids)[:MAX_SYNTHESIS_SIGNALS],
                    "engine_name": ENGINE_NAME,
                    "engine_version": ENGINE_VERSION,
                },
                input_projection={
                    "topic": mission.topic,
                    "goal": mission.goal,
                    "audience": mission.audience,
                    "intent_summary": plan.intent_summary,
                    "audience_notes": plan.audience_notes,
                    "cliche_patterns": list(plan.cliche_patterns),
                    "primitive_hints": list(plan.primitive_hints),
                    "strategy": mission.plan.get("strategy", {}),
                    "signals": [
                        {
                            "id": str(row.id),
                            "surface": row.surface_kind.value,
                            "title": row.title[:200],
                            "snippet": (row.snippet or "")[:300],
                            "domain": _domain(row.reference_url) if row.reference_url else None,
                        }
                        for row in signals[:MAX_SYNTHESIS_SIGNALS]
                    ],
                    "limits": {"max_candidates": MAX_SYNTHESIS_CANDIDATES},
                },
                generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
                retry_number=self._retry(mission, "synthesis"),
                instructions=_SYNTHESIS_TEMPLATE,
            )
            spec: StructuredOutputSpec[IdeaSynthesisV1] = StructuredOutputSpec(
                schema_name=IDEA_SYNTHESIS_SCHEMA_NAME,
                schema_version=IDEA_SYNTHESIS_SCHEMA_VERSION,
                model_type=IdeaSynthesisV1,
                domain_validator=_synthesis_validator(known_ids),
            )
            execution = self._generation.execute(request, spec, self._provider)
            if execution.status is GenerationStatus.SUCCEEDED and execution.payload is not None:
                synthesis = execution.payload
                synthesis_source = "model"
            else:
                self._log(
                    mission,
                    MissionStage.EXTRACTING,
                    "note",
                    f"model sentezi alınamadı ({execution.status.value}); deterministik çıkarım",
                )
        candidates: list[MissionIdeaCandidate] = []
        primitives_by_key: dict[str, dict[str, str]] = {}
        if synthesis is not None:
            primitives_by_key = {
                p.key: {"key": p.key, "label": p.label, "description": p.description}
                for p in synthesis.primitives
            }
            for item in synthesis.candidates:
                candidates.append(
                    MissionIdeaCandidate(
                        mission_id=mission.id,
                        title=item.title[:300],
                        angle=item.angle,
                        candidate_kind=CandidateKind(item.kind),
                        cluster_key=item.cluster_key[:240],
                        primitives=[
                            primitives_by_key.get(key, {"key": key, "label": key})
                            for key in item.primitive_keys
                        ],
                        implementation_steps=list(item.implementation_steps),
                        factual_claims_needed=list(item.factual_claims_needed),
                        signal_ids=[sid for sid in item.signal_ids if sid in known_ids],
                        is_cliche=item.is_cliche,
                        cliche_reason=item.cliche_reason,
                        idea_quality=0,
                        quality_factors=item.factors.model_dump(),
                        idea_confidence=IdeaConfidence.LOW,
                        factual_evidence_confidence=FactualEvidenceConfidence.UNKNOWN,
                        recommendation=CandidateRecommendation.CONTINUE_RESEARCH,
                        rationale=item.rationale,
                    )
                )
        else:
            candidates = _deterministic_candidates(mission, signals)
        for candidate in candidates:
            self._session.add(candidate)
        self._session.flush()
        mission.result_summary = {
            **mission.result_summary,
            "synthesis_source": synthesis_source,
            "primitives": list(primitives_by_key.values()),
        }
        self._log(
            mission,
            MissionStage.EXTRACTING,
            "done",
            f"{len(candidates)} aday, {len(primitives_by_key)} mekanik ({synthesis_source})",
        )
        self._checkpoint()
        return candidates

    def _cluster(
        self, mission: ResearchMission, candidates: list[MissionIdeaCandidate]
    ) -> list[MissionIdeaCandidate]:
        self._stage(mission, MissionStage.CLUSTERING, "Benzer fikirler gruplanıyor")
        strategy = StrategyService(self._session)
        for candidate in candidates:
            candidate.idea_quality = quality_score(
                candidate.quality_factors, strategic_fit=self._strategic_fit(strategy, candidate)
            )
        ordered = sorted(candidates, key=lambda c: (-c.idea_quality, c.title))
        kept: list[MissionIdeaCandidate] = []
        merged = 0
        for candidate in ordered:
            twin = next(
                (
                    other
                    for other in kept
                    if other.cluster_key == candidate.cluster_key
                    or _jaccard(other.title, candidate.title) >= MERGE_JACCARD
                ),
                None,
            )
            if twin is None:
                kept.append(candidate)
                continue
            candidate.merged_into_id = twin.id
            candidate.recommendation = CandidateRecommendation.MERGED
            candidate.rationale = f"'{twin.title}' ile aynı fikir kümesi; birleştirildi."
            twin.signal_ids = sorted(set(twin.signal_ids) | set(candidate.signal_ids))
            merged += 1
        self._session.flush()
        mission.elimination_summary = {**mission.elimination_summary, "merged": merged}
        self._log(mission, MissionStage.CLUSTERING, "done", f"{merged} benzer aday birleştirildi")
        self._checkpoint()
        return kept

    def _evaluate(
        self,
        mission: ResearchMission,
        plan: MissionPlanV1,
        candidates: list[MissionIdeaCandidate],
        signals: list[MissionSignal],
    ) -> None:
        self._stage(
            mission, MissionStage.EVALUATING, "Fikir kalitesi ve klişeler değerlendiriliyor"
        )
        signal_titles = [normalize_phrase(row.title) for row in signals]
        generic = weak = promote = 0
        for candidate in candidates:
            # A title that is a signal title verbatim is extraction, never synthesis.
            normalized = normalize_phrase(candidate.title)
            if normalized and normalized in signal_titles:
                candidate.candidate_kind = CandidateKind.EXTRACTED
                candidate.quality_factors = {
                    **candidate.quality_factors,
                    "novelty": min(int(candidate.quality_factors.get("novelty", 0)), 40),
                }
                candidate.idea_quality = quality_score(
                    candidate.quality_factors, strategic_fit=candidate.idea_quality > 0
                )
            pattern = matches_cliche(candidate.title, candidate.angle, list(plan.cliche_patterns))
            factors = candidate.quality_factors
            if pattern is not None and not candidate.is_cliche:
                candidate.is_cliche = True
                candidate.cliche_reason = f"Bilinen klişe kalıbı: {pattern}"
            if (
                not candidate.is_cliche
                and int(factors.get("novelty", 0)) < 35
                and int(factors.get("specificity", 0)) < 40
            ):
                candidate.is_cliche = True
                candidate.cliche_reason = "Özgünlük ve somutluk çok düşük."
            candidate.idea_confidence = confidence_for(candidate.idea_quality)
            candidate.factual_evidence_confidence = (
                FactualEvidenceConfidence.NOT_REQUIRED
                if not candidate.factual_claims_needed
                else FactualEvidenceConfidence.UNKNOWN
            )
            if candidate.is_cliche:
                candidate.recommendation = CandidateRecommendation.ELIMINATE
                generic += 1
            elif candidate.idea_quality >= PROMOTE_THRESHOLD:
                candidate.recommendation = CandidateRecommendation.PROMOTE
                promote += 1
            elif candidate.idea_quality >= CONTINUE_THRESHOLD:
                candidate.recommendation = CandidateRecommendation.CONTINUE_RESEARCH
            else:
                candidate.recommendation = CandidateRecommendation.ELIMINATE
                weak += 1
        strong = sorted(
            (c for c in candidates if c.recommendation is CandidateRecommendation.PROMOTE),
            key=lambda c: (-c.idea_quality, c.title),
        )
        for candidate in strong[MAX_PROMOTE_RECOMMENDED:]:
            candidate.recommendation = CandidateRecommendation.CONTINUE_RESEARCH
            candidate.rationale = (
                candidate.rationale + " | Güçlü aday sınırı: daha yüksek puanlı adaylar öncelikli."
            )
            promote -= 1
        self._session.flush()
        found = len(candidates) + int(mission.elimination_summary.get("merged", 0))
        mission.elimination_summary = {
            "found": found,
            "generic_eliminated": generic,
            "merged": int(mission.elimination_summary.get("merged", 0)),
            "weak_eliminated": weak,
            "retained": len(candidates) - generic - weak,
            "promotable": promote,
        }
        mission.result_summary = {
            **mission.result_summary,
            "signals": len(signals),
            "ideas": found,
            "promotable": promote,
            "search_demand": self._demand_summary(mission),
            "trend": self._trend_summary(mission),
            "factual_evidence": "not_evaluated",
        }
        self._log(
            mission,
            MissionStage.EVALUATING,
            "done",
            f"{found} fikir: {generic} klişe elendi, "
            f"{mission.elimination_summary['merged']} birleştirildi, "
            f"{weak} zayıf elendi, {promote} güçlü aday",
        )
        self._checkpoint()

    def _ground(
        self,
        mission: ResearchMission,
        candidates: list[MissionIdeaCandidate],
        signals: list[MissionSignal],
    ) -> None:
        self._stage(mission, MissionStage.GROUNDING, "Güçlü fikirlerin sayfaları getiriliyor")
        by_id = {str(row.id): row for row in signals}
        promotable = sorted(
            (c for c in candidates if c.recommendation is CandidateRecommendation.PROMOTE),
            key=lambda c: (-c.idea_quality, c.title),
        )[:MAX_PROMOTIONS]
        dispatched = 0
        ready = 0
        context_links = 0
        groundable = [
            row
            for row in signals
            if row.discovery_item_id is not None or row.reference_url is not None
        ]
        for candidate in promotable:
            rows = [by_id[sid] for sid in candidate.signal_ids if sid in by_id]
            if not any(row.discovery_item_id or row.reference_url for row in rows):
                # A synthesized idea often cites only URL-less recall/visual
                # signals. Ground it with the topic pages that share the most
                # with it (registered sources first): context inputs, never
                # "the source of the idea".
                for row in _context_signals(candidate, mission, groundable):
                    if str(row.id) not in candidate.signal_ids:
                        candidate.signal_ids = [*candidate.signal_ids, str(row.id)]
                        rows.append(row)
                        context_links += 1
            if any(row.normalized_document_id is not None for row in rows):
                ready += 1
                continue
            for row in rows:
                if dispatched >= MAX_GROUNDING_FETCHES:
                    break
                if row.discovery_item_id is not None:
                    # A registered-source page that was discovered but never
                    # fetched: pull it through the intake chain now.
                    if self._fetch_registered(row):
                        dispatched += 1
                    continue
                if row.reference_url is None:
                    continue
                item = self._discover_open_web(mission, row)
                if item is None:
                    continue
                row.discovery_item_id = item.id
                if self._dispatch_fetch is not None:
                    self._dispatch_fetch(str(item.id))
                    dispatched += 1
        self._session.flush()
        mission.status = MissionStatus.GROUNDING
        mission.result_summary = {
            **mission.result_summary,
            "grounding": {
                "promotable": len(promotable),
                "ready": ready,
                "dispatched_fetches": dispatched,
                "context_links": context_links,
                "started_at": self._now().isoformat(),
            },
        }
        self._log(
            mission,
            MissionStage.GROUNDING,
            "done",
            f"{len(promotable)} güçlü aday; {ready} hazır belge, {dispatched} sayfa getiriliyor",
        )
        self._checkpoint()

    # --- promotion --------------------------------------------------------------------

    def _promote(
        self,
        mission: ResearchMission,
        candidate: MissionIdeaCandidate,
        documents: list[NormalizedDocument],
    ) -> EditorialOpportunity | None:
        opportunities = OpportunityRepository(self._session)
        decisions = DuplicateDecisionRepository(self._session)
        root: NormalizedDocument | None = None
        supporting: list[NormalizedDocument] = []
        for document in documents:
            if decisions.get_effective_for_document(document.id) is None:
                continue
            if root is None and opportunities.get_by_promotion_root(document.id) is None:
                root = document
            else:
                supporting.append(document)
        if root is None:
            candidate.recommendation = CandidateRecommendation.CONTINUE_RESEARCH
            candidate.rationale = (
                candidate.rationale
                + " | Fırsat açılamadı: destek belgeleri zaten başka bir fırsata bağlı."
            )
            return None
        workflow = WorkflowService(self._session)
        work_item = workflow.create_work_item(
            origin=WorkItemOrigin.RESEARCH_MISSION,
            title_working_label=candidate.title[:200],
            reason=f"araştırma görevi '{mission.topic}' güçlü fikir üretti (kalite {candidate.idea_quality})",
            actor_origin=WorkflowActorOrigin.SYSTEM,
            locale=mission.locale,
            market=mission.market,
            artifact_refs={
                "promotion": "research_mission",
                "mission_id": str(mission.id),
                "mission_candidate_id": str(candidate.id),
                "normalized_document_id": str(root.id),
                "idea_quality": candidate.idea_quality,
            },
        )
        opportunity = opportunities.insert_opportunity(
            EditorialOpportunity(
                work_item_id=work_item.id,
                promotion_root_document_id=root.id,
                topic_summary=candidate.title[:300],
                mission_candidate_id=candidate.id,
                disposition=OpportunityDisposition.OPEN,
            )
        )
        moment = self._now()
        for index, document in enumerate([root, *supporting[:MAX_SUPPORTING_INPUTS]]):
            decision = decisions.get_effective_for_document(document.id)
            assert decision is not None
            opportunities.insert_research_input(
                OpportunityResearchInput(
                    opportunity_id=opportunity.id,
                    normalized_document_id=document.id,
                    duplicate_decision_id=decision.id,
                    role=ResearchInputRole.PRIMARY_SIGNAL
                    if index == 0
                    else ResearchInputRole.SUPPORTING,
                    added_by=OpportunityActor.SYSTEM,
                    note=f"araştırma görevi: {mission.topic}",
                    added_at=moment,
                )
            )
        candidate.opportunity_id = opportunity.id
        self._session.flush()
        self._log(
            mission,
            MissionStage.PROMOTING,
            "done",
            f"'{candidate.title}' içerik fırsatına dönüştü",
        )
        return opportunity

    def _complete(self, mission: ResearchMission, promoted: list[uuid.UUID], pending: int) -> None:
        mission.stage = MissionStage.COMPLETED
        mission.status = MissionStatus.COMPLETED if promoted else MissionStatus.NEEDS_MORE_RESEARCH
        mission.result_summary = {
            **mission.result_summary,
            "promoted_opportunity_ids": [str(value) for value in promoted],
            "promoted": len(promoted),
            "grounding_pending_at_close": pending,
        }
        self._log(
            mission,
            MissionStage.COMPLETED,
            "done",
            f"{len(promoted)} fırsat açıldı"
            + (f"; {pending} sayfa getirilemedi" if pending else ""),
        )
        self._session.flush()
        self._checkpoint()

    # --- surfaces -----------------------------------------------------------------------

    def _registered_signals(
        self, mission: ResearchMission, query_tokens: set[str]
    ) -> list[MissionSignal]:
        rows = self._session.execute(
            select(DiscoveryItem, Source)
            .join(Source, Source.id == DiscoveryItem.source_id)
            .where(
                Source.lifecycle_state == SourceLifecycleState.ACTIVE,
                DiscoveryItem.lifecycle_state != DiscoveryLifecycleState.REJECTED,
            )
            .order_by(DiscoveryItem.discovered_at.desc(), DiscoveryItem.id.desc())
            .limit(3000)
        ).all()
        ranked: list[tuple[int, DiscoveryItem, Source, tuple[str, ...]]] = []
        for item, source in rows:
            haystack = " ".join(
                filter(None, [item.title_hint, item.snippet_hint, _url_words(item.canonical_url)])
            )
            shared = _related(query_tokens, haystack)
            if shared:
                ranked.append((len(shared), item, source, shared))
        ranked.sort(key=lambda value: (-value[0], value[1].discovered_at), reverse=False)
        signals: list[MissionSignal] = []
        for _, item, source, shared in ranked[:MAX_REGISTERED_SIGNALS]:
            document_id = self._session.execute(
                select(NormalizedDocument.id)
                .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
                .where(
                    FetchSnapshot.discovery_item_id == item.id,
                    NormalizedDocument.normalization_status == NormalizationStatus.SUCCEEDED,
                )
                .order_by(NormalizedDocument.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            signals.append(
                MissionSignal(
                    mission_id=mission.id,
                    source_id=source.id,
                    discovery_item_id=item.id,
                    normalized_document_id=document_id,
                    surface_kind=_surface_for(source),
                    title=(item.title_hint or _slug_title(item.canonical_url))[:500],
                    snippet=item.snippet_hint,
                    reference_url=item.canonical_url,
                    query=", ".join(shared)[:300],
                    signal_role=source.primary_role.value,
                    provenance={
                        "source_name": source.name,
                        "discovery_method": item.discovery_method.value,
                        "shared_terms": list(shared),
                        "is_factual_evidence": False,
                        "has_document": document_id is not None,
                    },
                )
            )
        return signals

    def _trend_signals(self, mission: ResearchMission) -> list[MissionSignal]:
        signals: list[MissionSignal] = []
        for entry in mission.keyword_plan:
            trend = entry.get("trend") or {}
            if trend.get("state") != "observed" or len(signals) >= MAX_TREND_SIGNALS:
                continue
            signals.append(
                MissionSignal(
                    mission_id=mission.id,
                    surface_kind=SurfaceKind.TREND_MARKET,
                    title=f"Google Trends TR: {trend.get('term')}",
                    snippet=(
                        f"{trend.get('trend_type')} listesi, sıra {trend.get('rank')}"
                        if trend.get("rank") is not None
                        else str(trend.get("trend_type"))
                    ),
                    reference_url=None,
                    query=str(entry.get("keyword"))[:300],
                    signal_role=SourceRole.TREND.value,
                    provenance={
                        "provider": trend.get("provider"),
                        "is_factual_evidence": False,
                    },
                )
            )
        return signals

    def _web_research(
        self,
        mission: ResearchMission,
        plan: MissionPlanV1,
        add: Callable[[MissionSignal], None],
    ) -> str | None:
        if self._provider is None:
            return "open_web: metin sağlayıcısı yapılandırılmamış"
        queries = [
            {"query": q.query, "language": q.language, "purpose": q.purpose, "surface": q.surface}
            for q in plan.queries
        ]
        request = GenerationRequest(
            purpose=GenerationPurpose.WEB_RESEARCH,
            schema_name=RESEARCH_SIGNALS_SCHEMA_NAME,
            schema_version=RESEARCH_SIGNALS_SCHEMA_VERSION,
            template_name=WEB_RESEARCH_TEMPLATE_NAME,
            template_version=WEB_RESEARCH_TEMPLATE_VERSION,
            input_refs={
                "schema": "web-research-input/1",
                "mission_id": str(mission.id),
                "engine_name": ENGINE_NAME,
                "engine_version": ENGINE_VERSION,
            },
            input_projection={
                "topic": mission.topic,
                "goal": mission.goal,
                "audience": mission.audience,
                "market": mission.market,
                "queries": queries,
                "limits": {"max_signals": MAX_WEB_SIGNALS},
            },
            generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
            retry_number=self._retry(mission, "web"),
            instructions=_WEB_RESEARCH_TEMPLATE,
        )
        spec: StructuredOutputSpec[ResearchSignalsV1] = StructuredOutputSpec(
            schema_name=RESEARCH_SIGNALS_SCHEMA_NAME,
            schema_version=RESEARCH_SIGNALS_SCHEMA_VERSION,
            model_type=ResearchSignalsV1,
        )
        execution = self._generation.execute(request, spec, self._provider)
        mode = "live"
        note: str | None = None
        if execution.status is not GenerationStatus.SUCCEEDED or execution.payload is None:
            # Live browsing failed (the browser gateway is the usual reason):
            # fall back to the model's own recall, labelled as such — no URLs,
            # no "we searched the web" pretence; grounding needs real pages.
            note = (
                "open_web: canlı web araştırması başarısız "
                f"({execution.status.value}); model hatırlaması kullanıldı"
            )
            mode = "recall"
            request = GenerationRequest(
                purpose=GenerationPurpose.WEB_RESEARCH,
                schema_name=RESEARCH_SIGNALS_SCHEMA_NAME,
                schema_version=RESEARCH_SIGNALS_SCHEMA_VERSION,
                template_name=RECALL_RESEARCH_TEMPLATE_NAME,
                template_version=WEB_RESEARCH_TEMPLATE_VERSION,
                input_refs={
                    "schema": "web-research-input/1",
                    "mission_id": str(mission.id),
                    "mode": "recall",
                    "engine_name": ENGINE_NAME,
                    "engine_version": ENGINE_VERSION,
                },
                input_projection={
                    "topic": mission.topic,
                    "goal": mission.goal,
                    "audience": mission.audience,
                    "market": mission.market,
                    "queries": queries,
                    "limits": {"max_signals": MAX_WEB_SIGNALS},
                },
                generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
                retry_number=self._retry(mission, "recall"),
                instructions=_RECALL_RESEARCH_TEMPLATE,
            )
            execution = self._generation.execute(request, spec, self._provider)
            if execution.status is not GenerationStatus.SUCCEEDED or execution.payload is None:
                return f"open_web: model araştırması başarısız ({execution.status.value})"
        seen: set[tuple[str, str | None]] = set()
        for item in execution.payload.signals:
            url = _absolute_url(item.url) if mode == "live" else None
            key = (normalize_phrase(item.title), url)
            if key in seen:
                continue
            seen.add(key)
            add(
                MissionSignal(
                    mission_id=mission.id,
                    surface_kind=SurfaceKind(item.surface),
                    title=item.title[:500],
                    snippet=item.snippet,
                    reference_url=url,
                    query=(item.query or "")[:300] or None,
                    signal_role="model_web_research",
                    provenance={
                        "method": "model_web_research" if mode == "live" else "model_recall",
                        "provider": self._provider.identity.provider,
                        "model": self._provider.identity.model_name,
                        "language": item.language,
                        "why_relevant": item.why_relevant,
                        "url_verified": False,
                        "is_factual_evidence": False,
                    },
                )
            )
        if execution.payload.search_notes and not execution.payload.signals:
            return f"open_web: {execution.payload.search_notes[:200]}"
        return note

    # --- grounding helpers --------------------------------------------------------------

    def _discover_open_web(
        self, mission: ResearchMission, signal: MissionSignal
    ) -> DiscoveryItem | None:
        url = signal.reference_url
        if url is None:
            return None
        domain = _domain(url)
        if domain is None:
            return None
        source = self._open_web_source(domain)
        if source is None:
            return None
        try:
            item = DiscoveryService(self._session).discover_manual(
                source.id,
                url,
                title_hint=signal.title[:500],
                snippet_hint=(signal.snippet or "")[:2000] or None,
                locale=mission.locale,
                metadata={"mission_id": str(mission.id), "signal_id": str(signal.id)},
            )
        except Exception as error:  # noqa: BLE001 - grounding is best effort
            _logger.info("mission_grounding_skipped", domain=domain, error=type(error).__name__)
            return None
        signal.source_id = source.id
        return item

    def _fetch_registered(self, signal: MissionSignal) -> bool:
        if signal.normalized_document_id is not None or signal.discovery_item_id is None:
            return False
        item = self._session.get(DiscoveryItem, signal.discovery_item_id)
        if item is None or self._dispatch_fetch is None:
            return False
        if item.lifecycle_state is DiscoveryLifecycleState.DISCOVERED:
            try:
                DiscoveryService(self._session).accept_item(item.id)
            except Exception as error:  # noqa: BLE001 - grounding is best effort
                _logger.info("mission_accept_failed", error=type(error).__name__)
                return False
        elif item.lifecycle_state is not DiscoveryLifecycleState.ACCEPTED:
            return False
        self._session.flush()
        self._dispatch_fetch(str(item.id))
        return True

    def _open_web_source(self, domain: str) -> Source | None:
        """One SEARCH-role source per open-web domain: it may ground evidence
        but never promotes opportunities of its own (role gate)."""
        slug = ("web-" + re.sub(r"[^a-z0-9]+", "-", domain))[:80].strip("-")
        existing = self._session.scalar(select(Source).where(Source.slug == slug))
        if existing is not None:
            return existing if existing.lifecycle_state is SourceLifecycleState.ACTIVE else None
        registry = SourceRegistryService(self._session)
        try:
            source = registry.register_source(
                slug=slug,
                name=f"Açık web: {domain}",
                kind=SourceKind.EDITORIAL_SITE,
                base_url=f"https://{domain}",
                trust_tier=TrustTier.GENERAL,
                discovery_strategy=DiscoveryStrategy.MANUAL,
                primary_role=SourceRole.SEARCH,
                capabilities=[SourceCapability.SEARCH, SourceCapability.INSPIRATION],
                metadata={"open_web_grounding": True},
            )
            if source.lifecycle_state is not SourceLifecycleState.ACTIVE:
                source = registry.transition_source_state(
                    source.id,
                    SourceLifecycleState.ACTIVE,
                    reason="araştırma görevi açık web temellendirmesi",
                )
        except Exception as error:  # noqa: BLE001 - grounding is best effort
            _logger.info(
                "mission_open_web_source_failed", domain=domain, error=type(error).__name__
            )
            return None
        return source

    def _grounded_documents(
        self, candidate: MissionIdeaCandidate, signals: dict[str, MissionSignal]
    ) -> list[NormalizedDocument]:
        documents: list[NormalizedDocument] = []
        for sid in candidate.signal_ids:
            signal = signals.get(sid)
            if signal is None:
                continue
            document_id = signal.normalized_document_id
            if document_id is None and signal.discovery_item_id is not None:
                document_id = self._session.execute(
                    select(NormalizedDocument.id)
                    .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
                    .where(
                        FetchSnapshot.discovery_item_id == signal.discovery_item_id,
                        NormalizedDocument.normalization_status == NormalizationStatus.SUCCEEDED,
                    )
                    .order_by(NormalizedDocument.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if document_id is not None:
                    signal.normalized_document_id = document_id
            if document_id is None:
                continue
            document = self._session.get(NormalizedDocument, document_id)
            if document is not None and document not in documents:
                documents.append(document)
        return documents

    def _fetch_pending(
        self, candidate: MissionIdeaCandidate, signals: dict[str, MissionSignal]
    ) -> bool:
        for sid in candidate.signal_ids:
            signal = signals.get(sid)
            if signal is None or signal.discovery_item_id is None:
                continue
            item = self._session.get(DiscoveryItem, signal.discovery_item_id)
            if item is not None and item.lifecycle_state in (
                DiscoveryLifecycleState.DISCOVERED,
                DiscoveryLifecycleState.ACCEPTED,
                DiscoveryLifecycleState.FETCHED,
            ):
                return True
        return False

    def _grounding_started(self, mission: ResearchMission) -> datetime:
        raw = (mission.result_summary.get("grounding") or {}).get("started_at")
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
        return self._now()

    def _promotable(self, mission: ResearchMission) -> list[MissionIdeaCandidate]:
        rows = self._session.scalars(
            select(MissionIdeaCandidate)
            .where(
                MissionIdeaCandidate.mission_id == mission.id,
                MissionIdeaCandidate.recommendation == CandidateRecommendation.PROMOTE,
            )
            .order_by(MissionIdeaCandidate.idea_quality.desc(), MissionIdeaCandidate.title)
        ).all()
        return list(rows)[:MAX_PROMOTIONS]

    def _signals(self, mission: ResearchMission) -> list[MissionSignal]:
        return list(
            self._session.scalars(
                select(MissionSignal).where(MissionSignal.mission_id == mission.id)
            )
        )

    # --- providers --------------------------------------------------------------------

    def _search_console_rows(self) -> tuple[list[tuple[str, int, int]], str]:
        if self._registry is None:
            return [], "unknown"
        provider = self._registry.get(ProviderName.GOOGLE_SEARCH_CONSOLE)
        if not isinstance(provider, GoogleSearchConsoleProvider) or not provider.configured():
            return [], "unknown"
        end = self._now().date() - timedelta(days=3)
        start = end - timedelta(days=DEMAND_WINDOW_DAYS)
        try:
            with bind_session(self._session):
                payload = provider.search_analytics(start, end, ["query"], row_limit=1000)
        except Exception as error:  # noqa: BLE001 - UNKNOWN, never a guess
            _logger.info("mission_search_console_failed", error=type(error).__name__)
            return [], "unknown"
        rows: list[tuple[str, int, int]] = []
        raw_rows = payload.get("rows") if isinstance(payload, dict) else payload
        for row in raw_rows or []:
            keys = getattr(row, "keys", None)
            if keys is None and isinstance(row, dict):
                keys = row.get("keys")
            query = keys[0] if isinstance(keys, (list, tuple)) and keys else None
            if not isinstance(query, str):
                query = getattr(row, "query", None)
            if not isinstance(query, str):
                continue
            clicks = getattr(row, "clicks", None)
            impressions = getattr(row, "impressions", None)
            if isinstance(row, dict):
                clicks = row.get("clicks", 0)
                impressions = row.get("impressions", 0)
            rows.append((query, int(clicks or 0), int(impressions or 0)))
        return rows, "observed" if rows else "no_data"

    def _trend_rows(self, mission: ResearchMission) -> list[tuple[str, dict[str, Any]]]:
        try:
            rows = recent_trend_term_rows(
                self._session,
                mission.market,
                since=self._now() - timedelta(days=TREND_WINDOW_DAYS),
                limit=2000,
            )
        except Exception as error:  # noqa: BLE001
            _logger.info("mission_trend_rows_failed", error=type(error).__name__)
            return []
        return [(row.subject, dict(row.value or {})) for row in rows]

    def _strategy_projection(self, mission: ResearchMission) -> dict[str, Any]:
        try:
            context = StrategyService(self._session).context_for_text(
                f"{mission.topic} {mission.goal} {mission.audience}",
                locale=mission.locale,
                market=mission.market,
            )
        except Exception:  # noqa: BLE001 - strategy never blocks research
            return {}
        return context.projection()

    @staticmethod
    def _strategic_fit(strategy: StrategyService, candidate: MissionIdeaCandidate) -> bool:
        try:
            context = strategy.context_for_text(f"{candidate.title} {candidate.angle}")
        except Exception:  # noqa: BLE001
            return False
        return bool(context.keywords or context.clusters)

    def _active_sources(self) -> list[Source]:
        return list(
            self._session.scalars(
                select(Source)
                .where(Source.lifecycle_state == SourceLifecycleState.ACTIVE)
                .order_by(Source.name)
            )
        )

    # --- bookkeeping ------------------------------------------------------------------

    def _reset(self, mission: ResearchMission) -> None:
        for candidate in self._session.scalars(
            select(MissionIdeaCandidate).where(MissionIdeaCandidate.mission_id == mission.id)
        ).all():
            if candidate.opportunity_id is None:
                self._session.delete(candidate)
        for signal in self._signals(mission):
            self._session.delete(signal)
        mission.progress_log = []
        mission.elimination_summary = {}
        mission.surface_summary = {}
        # The run number survives a reset: every rerun must be a fresh set of
        # model calls (attempt identity includes the retry number).
        mission.result_summary = {
            "run_number": int(mission.result_summary.get("run_number", 0)) + 1,
            "run_started_at": self._now().isoformat(),
        }
        self._session.flush()

    def _stage(self, mission: ResearchMission, stage: MissionStage, note: str) -> None:
        mission.stage = stage
        self._log(mission, stage, "started", note)
        self._session.flush()
        self._checkpoint()

    def _log(self, mission: ResearchMission, stage: MissionStage, status: str, note: str) -> None:
        mission.progress_log = [
            *mission.progress_log,
            {
                "stage": stage.value,
                "status": status,
                "note": note[:500],
                "at": self._now().isoformat(),
            },
        ]

    def _retry(self, mission: ResearchMission, step: str) -> int:
        """Every run of a mission is a fresh set of model calls."""
        runs = int(mission.result_summary.get("run_number", 0))
        return runs * 10 + {"planning": 0, "web": 1, "synthesis": 2, "recall": 3}[step]

    @staticmethod
    def _demand_summary(mission: ResearchMission) -> str:
        states = {str((e.get("demand") or {}).get("state")) for e in mission.keyword_plan}
        if "observed" in states:
            return "observed"
        if "not_observed" in states:
            return "not_observed"
        return "unknown"

    @staticmethod
    def _trend_summary(mission: ResearchMission) -> str:
        states = {str((e.get("trend") or {}).get("state")) for e in mission.keyword_plan}
        if "observed" in states:
            return "observed"
        if "not_observed" in states:
            return "not_observed"
        return "unknown"


# --- deterministic fallbacks and validators -------------------------------------------


def _deterministic_plan(mission: ResearchMission) -> MissionPlanV1:
    root = (mission.seed_keyword or mission.topic).strip()
    variants = [
        root,
        f"yaratıcı {root}",
        f"farklı {root}",
        f"{root} fikirleri",
        f"{root} nasıl yapılır",
    ]
    return MissionPlanV1(
        intent_summary=f"{mission.audience} için '{mission.topic}' konusunda uygulanabilir fikir arayışı.",
        audience_notes=mission.audience,
        keywords=[v[:300] for v in variants],
        queries=[
            PlannedQueryV1(query=variants[0], language="tr", purpose="intent", surface="open_web"),
            PlannedQueryV1(
                query=variants[1], language="tr", purpose="inspiration", surface="open_web"
            ),
            PlannedQueryV1(
                query=f"site:pinterest.com {root}",
                language="tr",
                purpose="visual",
                surface="visual_inspiration",
            ),
            PlannedQueryV1(
                query=f"{root} forum", language="tr", purpose="community", surface="community_need"
            ),
        ],
        cliche_patterns=[],
        primitive_hints=[],
    )


def _deterministic_candidates(
    mission: ResearchMission, signals: list[MissionSignal]
) -> list[MissionIdeaCandidate]:
    """No model: extracted candidates from signal titles with explainable
    heuristic factors (and no synthesized ideas — that needs a model)."""
    candidates: list[MissionIdeaCandidate] = []
    seen: set[str] = set()
    for signal in signals:
        title = re.sub(r"\s*[|–-]\s*[^|–-]+$", "", signal.title).strip()
        key = " ".join(sorted(_tokens(title)))[:240]
        if not key or key in seen:
            continue
        seen.add(key)
        words = len(normalize_phrase(title).split())
        factors = {
            "novelty": 45,
            "usefulness": 45,
            "specificity": min(100, 30 + words * 6),
            "visual_potential": 45,
            "shareability": 40,
            "emotional_impact": 40,
            "audience_fit": 50,
            "turkey_applicability": 50,
        }
        candidates.append(
            MissionIdeaCandidate(
                mission_id=mission.id,
                title=title[:300],
                angle=f"{mission.audience} için '{title}' fikrini uygulanabilir adımlara dönüştür.",
                candidate_kind=CandidateKind.EXTRACTED,
                cluster_key=key[:240] or "genel",
                primitives=[],
                implementation_steps=[],
                factual_claims_needed=[],
                signal_ids=[str(signal.id)],
                is_cliche=False,
                cliche_reason=None,
                idea_quality=0,
                quality_factors=factors,
                idea_confidence=IdeaConfidence.LOW,
                factual_evidence_confidence=FactualEvidenceConfidence.UNKNOWN,
                recommendation=CandidateRecommendation.CONTINUE_RESEARCH,
                rationale="Model sentezi yok; sinyal başlığından çıkarılan aday.",
            )
        )
    return candidates


MAX_CONTEXT_SIGNALS = 2


def _context_signals(
    candidate: MissionIdeaCandidate, mission: ResearchMission, groundable: list[MissionSignal]
) -> list[MissionSignal]:
    """Groundable signals that share the most distinctive tokens with the
    candidate (falling back to the mission topic), registered sources first."""
    wanted = set(_tokens(f"{candidate.title} {candidate.angle}")) | set(_tokens(mission.topic))
    ranked: list[tuple[int, int, str, MissionSignal]] = []
    for row in groundable:
        shared = len(wanted & set(_tokens(f"{row.title} {row.snippet or ''} {row.query or ''}")))
        if not shared:
            continue
        registered = 0 if row.surface_kind is SurfaceKind.REGISTERED_SOURCE else 1
        ranked.append((registered, -shared, row.title, row))
    ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    return [entry[3] for entry in ranked[:MAX_CONTEXT_SIGNALS]]


def _surface_for(source: Source) -> SurfaceKind:
    capabilities = set(source.capabilities or [])
    if (
        source.primary_role is SourceRole.COMMUNITY_INTENT
        or SourceCapability.COMMUNITY_NEED.value in capabilities
    ):
        return SurfaceKind.COMMUNITY_NEED
    if source.primary_role is SourceRole.TREND or SourceCapability.TREND.value in capabilities:
        return SurfaceKind.TREND_MARKET
    if source.primary_role is SourceRole.SEARCH:
        return SurfaceKind.OPEN_WEB
    return SurfaceKind.REGISTERED_SOURCE


def _plan_validator(plan: MissionPlanV1) -> str | None:
    if not any(q.language == "tr" for q in plan.queries):
        return "no_turkish_query"
    return None


def _synthesis_validator(known_ids: set[str]) -> Callable[[IdeaSynthesisV1], str | None]:
    def validate(payload: IdeaSynthesisV1) -> str | None:
        keys = {p.key for p in payload.primitives}
        for candidate in payload.candidates:
            if candidate.kind == "extracted" and not candidate.signal_ids:
                return "extracted_without_signal"
            if candidate.kind == "synthesized" and not candidate.primitive_keys:
                return "synthesized_without_primitives"
            if any(key not in keys for key in candidate.primitive_keys):
                return "unknown_primitive_key"
            if any(sid not in known_ids for sid in candidate.signal_ids):
                return "unknown_signal_id"
        return None

    return validate
