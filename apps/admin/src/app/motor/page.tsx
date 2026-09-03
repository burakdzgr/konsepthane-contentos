import Link from "next/link";

import { fetchCurrentUser } from "@/lib/auth-api";
import {
  fetchWorkItemDetail,
  fetchWorkItemDrafts,
  fetchWorkItemMedia,
  fetchWorkItemPublication,
  fetchWorkItemQaReports,
  fetchWorkItemReviews,
  fetchWorkQueue,
  type WorkItemDetail,
  type WorkQueueRow,
} from "@/lib/editorial-api";
import {
  fetchPipelineItems,
  fetchResearchSources,
  isUuid,
  type PipelineListItem,
  type SourceListItem,
} from "@/lib/research-api";
import { isDiscoveryEligible } from "@/lib/source-controls";
import {
  MOTOR_STAGES,
  STATE_LABELS_TR,
  deriveNextSteps,
  stageIndexForState,
  stageStatusForState,
  type MotorContext,
  type MotorStepId,
} from "@/lib/motor-plan";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import {
  motorAcceptBriefAction,
  motorAcceptDiscoveryAction,
  motorAcceptReviewAction,
  motorAnalyzeIntentAction,
  motorApproveAction,
  motorAssemblePackageAction,
  motorComposeBriefAction,
  motorEvaluateAction,
  motorFetchDiscoveryAction,
  motorGenerateDraftAction,
  motorGenerateIdeasAction,
  motorGenerateReviewAction,
  motorPromoteAction,
  motorPublishNowAction,
  motorRequestChangesAction,
  motorResolveApprovalExpiredAction,
  motorResolveBlockAction,
  motorResolveChangesRequestedAction,
  motorRunDiscoveryAction,
  motorRunQaAction,
  motorSchedulePublicationAction,
  motorSelectIdeaAction,
  motorWaiveQaGateAction,
} from "./actions";

// The Motor: the whole editorial engine on ONE page. Intake (source →
// discovery → promote) at the top, the active work items in the middle,
// and for the selected item a stage stepper plus exactly the explicit
// next step(s) its durable state admits. Complex interactions deep-link
// to the detail page; nothing here bypasses a backend rule.
export const dynamic = "force-dynamic";

const MOTOR_NOTICES: Record<string, string> = {
  "kesif-kuyrukta": "Keşif kuyruğa alındı. Yeni öğeler worker bitince görünür.",
  "kesif-kabul": "Keşif öğesi kabul edildi. Sıradaki adım: Getir.",
  "getirme-kuyrukta":
    "Getirme kuyruğa alındı. Normalleştirme sonucu worker bitince görünür.",
  "yukseltme-kuyrukta":
    "Yükseltme kuyruğa alındı. İş öğesi worker bitince listede belirir.",
  "puanlama-kuyrukta": "Puanlama kuyruğa alındı. Yenileyerek sonucu görün.",
  "fikirler-kuyrukta":
    "Fikir üretimi kuyruğa alındı. Adaylar worker bitince görünür.",
  "fikir-secildi": "Fikir seçildi.",
  "analiz-kuyrukta": "Arama niyeti analizi kuyruğa alındı.",
  "brief-kuyrukta":
    "Brief oluşturma kuyruğa alındı. Sonuç TASLAK durumundadır.",
  "brief-kabul": "Brief taslak yazımı için kabul edildi.",
  "taslak-kuyrukta":
    "Yazar taslağı üretimi kuyruğa alındı. Taslak worker bitince görünür.",
  "inceleme-kuyrukta":
    "Editör değerlendirmesi kuyruğa alındı. Karar worker bitince görünür.",
  "inceleme-kabul": "Değerlendirme kabul edildi; iş QA incelemesine geçti.",
  "qa-kuyrukta": "QA kapı çalıştırması kuyruğa alındı.",
  "qa-kapisi-atlandi":
    "Muafiyet kaydedildi ve denetlendi. Kapılar yeniden ÇALIŞTIRILMADI — QA'i açıkça çalıştırın.",
  "paket-onaylandi": "Paket onaylandı ve kayda geçti.",
  "degisiklik-istendi":
    "Değişiklik talebi kaydedildi ve sorumlu aşamaya yönlendirildi.",
  "paket-birlestirildi": "Yayın paketi onaylı artefaktlardan birleştirildi.",
  "yayin-zamanlandi":
    "Yayın zamanlandı. Yönetimli gönderim çalışana kadar hiçbir şey yayınlanmaz.",
  "yayin-kuyrukta":
    "Yayın gönderimi kuyruğa alındı; worker önce onayı yeniden doğrular.",
  "blok-cozuldu": "Blok çözüldü; iş önceki durumuna döndü.",
  "degisiklik-cozuldu":
    "Değişiklik talebi çözülerek sorumlu duruma yönlendirildi.",
  "onay-suresi-cozuldu":
    "Süresi dolan onay çözülerek türetilen hedefe yönlendirildi.",
};

function latestByCreatedAt<T extends { created_at: string }>(
  items: readonly T[],
): T | null {
  let latest: T | null = null;
  for (const item of items) {
    if (latest === null || item.created_at > latest.created_at) {
      latest = item;
    }
  }
  return latest;
}

function Stepper({ detail }: { detail: WorkItemDetail }) {
  const state = detail.work_item.current_state;
  const activeIndex = stageIndexForState(state);
  const status = stageStatusForState(state);
  const isDone = state === "published" || activeIndex > 5;
  return (
    <ol className="motor-steps" aria-label="Aşamalar">
      {MOTOR_STAGES.map((stage, index) => {
        let tone: "done" | "current" | "pending" = "pending";
        if (index < activeIndex || (index === activeIndex && isDone)) {
          tone = "done";
        } else if (index === activeIndex) {
          tone = "current";
        }
        return (
          <li key={stage.key} className="motor-step" data-tone={tone}>
            <span className="motor-step-index">{index + 1}</span>
            <span className="motor-step-label">{stage.label}</span>
          </li>
        );
      })}
      {status === "exception" && (
        <li className="motor-step" data-tone="exception">
          <span className="motor-step-label">{STATE_LABELS_TR[state]}</span>
        </li>
      )}
    </ol>
  );
}

function ReasonInput({ label }: { label?: string }) {
  return (
    <input
      type="text"
      name="reason"
      required
      placeholder={label ?? "gerekçe"}
      aria-label={label ?? "Gerekçe"}
    />
  );
}

function StepCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="motor-action-card">
      <h4>{title}</h4>
      {description !== undefined && <p className="muted">{description}</p>}
      {children}
    </div>
  );
}

function StepForms({
  steps,
  detail,
  context,
}: {
  steps: MotorStepId[];
  detail: WorkItemDetail;
  context: MotorContext;
}) {
  const workItemId = detail.work_item.id;
  const opportunityId = detail.opportunity?.id ?? "";
  const detailHref = `/editorial/${workItemId}`;
  const hidden = <input type="hidden" name="work_item_id" value={workItemId} />;
  const rendered = steps.map((step) => {
    switch (step) {
      case "evaluate":
        return (
          <StepCard
            key={step}
            title="Fırsatı puanla"
            description="Puanlama worker'da çalışır; sonuç geldiğinde fikir üretimi açılır."
          >
            <form action={motorEvaluateAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="opportunity_id"
                value={opportunityId}
              />
              <button type="submit">Değerlendir</button>
            </form>
          </StepCard>
        );
      case "generate-ideas":
        return (
          <StepCard
            key={step}
            title="Fikir üret"
            description="Model destekli fikir adayları üretir. Seçim her zaman size aittir."
          >
            <form action={motorGenerateIdeasAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="opportunity_id"
                value={opportunityId}
              />
              <button type="submit">Fikir üret</button>
            </form>
          </StepCard>
        );
      case "select-idea":
        return (
          <StepCard
            key={step}
            title="Fikir seç"
            description="Bir adayı gerekçesiyle seçin; kanıt aşaması seçimle açılır."
          >
            <ul className="plain-list">
              {detail.ideas.map((idea) => (
                <li key={idea.id}>
                  <form action={motorSelectIdeaAction} className="control-form">
                    {hidden}
                    <input type="hidden" name="idea_id" value={idea.id} />
                    <span className="motor-idea-title">
                      {idea.working_title}
                    </span>
                    <ReasonInput label="seçim gerekçesi" />
                    <button type="submit">Seç</button>
                  </form>
                </li>
              ))}
            </ul>
          </StepCard>
        );
      case "build-evidence-link":
        return (
          <StepCard
            key={step}
            title="Kanıt paketi"
            description="Kanıt seçimi satır satır açık karar ister; detay sayfasında yapılır."
          >
            <p>
              <Link href={detailHref}>Kanıt seçimine git →</Link>
            </p>
          </StepCard>
        );
      case "analyze-intent":
        return (
          <StepCard
            key={step}
            title="Arama niyetini analiz et"
            description="Seçili fikir ve en yeni kanıt paketiyle çalışır."
          >
            <form action={motorAnalyzeIntentAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="opportunity_id"
                value={opportunityId}
              />
              <input
                type="hidden"
                name="idea_id"
                value={context.selectedIdeaId ?? ""}
              />
              <input
                type="hidden"
                name="evidence_pack_id"
                value={context.latestPackId ?? ""}
              />
              <button type="submit">Analizi başlat</button>
            </form>
          </StepCard>
        );
      case "compose-brief":
        return (
          <StepCard
            key={step}
            title="Brief oluştur"
            description="Seçili fikir, en yeni kanıt paketi ve niyet analiziyle kuyruklanır."
          >
            <form action={motorComposeBriefAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="idea_id"
                value={context.selectedIdeaId ?? ""}
              />
              <input
                type="hidden"
                name="evidence_pack_id"
                value={context.latestPackId ?? ""}
              />
              <input
                type="hidden"
                name="search_intent_analysis_id"
                value={context.latestAnalysisId ?? ""}
              />
              <button type="submit">Brief oluştur</button>
            </form>
          </StepCard>
        );
      case "accept-brief":
        return (
          <StepCard
            key={step}
            title="Brief'i kabul et"
            description="Kabul, taslak yazımını açar; hiçbir şey yayınlamaz."
          >
            <form action={motorAcceptBriefAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="brief_id"
                value={context.latestBriefId ?? ""}
              />
              <ReasonInput label="kabul gerekçesi" />
              <button type="submit">Kabul et</button>
            </form>
          </StepCard>
        );
      case "generate-draft":
        return (
          <StepCard
            key={step}
            title="Taslak üret"
            description="Yazar motoru kabul edilen brief'ten taslağı üretir."
          >
            <form action={motorGenerateDraftAction} className="control-form">
              {hidden}
              <input
                type="hidden"
                name="brief_id"
                value={context.latestBriefId ?? ""}
              />
              <button type="submit">Taslak üret</button>
            </form>
          </StepCard>
        );
      case "submit-draft-link":
        return (
          <StepCard
            key={step}
            title="Elle taslak gönder"
            description="Bölümleri kendiniz yazacaksanız detay sayfasındaki formu kullanın."
          >
            <p>
              <Link href={detailHref}>Taslak formuna git →</Link>
            </p>
          </StepCard>
        );
      case "generate-editor-review":
        return (
          <StepCard
            key={step}
            title="Editör değerlendirmesi üret"
            description="Editör motoru aktif taslağı değerlendirir."
          >
            <form action={motorGenerateReviewAction} className="control-form">
              {hidden}
              <button type="submit">Değerlendirme üret</button>
            </form>
          </StepCard>
        );
      case "accept-review":
        return (
          <StepCard
            key={step}
            title="Değerlendirmeyi kabul et"
            description="Kabul, işi QA incelemesine taşır."
          >
            <form action={motorAcceptReviewAction} className="control-form">
              {hidden}
              <ReasonInput label="kabul gerekçesi" />
              <button type="submit">Kabul et</button>
            </form>
          </StepCard>
        );
      case "run-qa":
        return (
          <StepCard
            key={step}
            title="QA çalıştır"
            description="Kapı çalıştırmaları idempotenttir; tekrar çalıştırmak güvenlidir."
          >
            <form action={motorRunQaAction} className="control-form">
              {hidden}
              <button type="submit">QA çalıştır</button>
            </form>
          </StepCard>
        );
      case "waive-qa-gate":
        return (
          <StepCard
            key={step}
            title="Medya kapısını muaf tut"
            description={`Karşılanmamış ${context.unsatisfiedMediaNeeds} medya ihtiyacı var. Muafiyet denetlenir ve QA'i yeniden çalıştırmanız gerekir.`}
          >
            <form action={motorWaiveQaGateAction} className="control-form">
              {hidden}
              <ReasonInput label="muafiyet gerekçesi" />
              <button type="submit">Muaf tut</button>
            </form>
          </StepCard>
        );
      case "media-link":
        return (
          <StepCard
            key={step}
            title="Medya ihtiyaçlarını bağla"
            description="Yükleme, üretim ve bağlama detay sayfasında yapılır."
          >
            <p>
              <Link href={detailHref}>Medya bölümüne git →</Link>
            </p>
          </StepCard>
        );
      case "approve":
        return (
          <StepCard
            key={step}
            title="Paketi onayla"
            description="Onay kayda geçer; yayına almak ayrı bir adımdır."
          >
            <form action={motorApproveAction} className="control-form">
              {hidden}
              <ReasonInput label="onay gerekçesi" />
              <button type="submit">Onayla</button>
            </form>
          </StepCard>
        );
      case "request-changes":
        return (
          <StepCard
            key={step}
            title="Değişiklik iste"
            description="Talep, sorumlu aşamaya gerekçesiyle yönlendirilir."
          >
            <form action={motorRequestChangesAction} className="control-form">
              {hidden}
              <select name="responsible_state" aria-label="Sorumlu aşama">
                <option value="drafting">Taslak yazımı</option>
                <option value="editing">Editör incelemesi</option>
                <option value="qa_review">QA incelemesi</option>
              </select>
              <ReasonInput label="talep gerekçesi" />
              <button type="submit">Değişiklik iste</button>
            </form>
          </StepCard>
        );
      case "reviewer-required":
        return (
          <StepCard
            key={step}
            title="Onay bekleniyor"
            description="Karar yalnızca reviewer rolüne sahip bir kullanıcı tarafından verilebilir. Bu hesapta reviewer rolü yok."
          />
        );
      case "assemble-package":
        return (
          <StepCard
            key={step}
            title="Yayın paketini birleştir"
            description="Paket, onaylanan artefaktların birebir kopyasından oluşur."
          >
            <form action={motorAssemblePackageAction} className="control-form">
              {hidden}
              <button type="submit">Paketi birleştir</button>
            </form>
          </StepCard>
        );
      case "schedule-publication":
        return (
          <StepCard
            key={step}
            title="Yayını zamanla"
            description="Zamanlama kayda geçer; gönderim yönetimli görevle çalışır."
          >
            <form
              action={motorSchedulePublicationAction}
              className="control-form"
            >
              {hidden}
              <input
                type="hidden"
                name="publication_package_id"
                value={context.latestPackageId ?? ""}
              />
              <ReasonInput label="zamanlama gerekçesi" />
              <button type="submit">Zamanla</button>
            </form>
          </StepCard>
        );
      case "publish-now":
        return (
          <StepCard
            key={step}
            title="Yayınla"
            description="Gönderim kuyruklanır; worker önce onayın güncelliğini doğrular."
          >
            <form action={motorPublishNowAction} className="control-form">
              {hidden}
              <button type="submit">Yayınla</button>
            </form>
          </StepCard>
        );
      case "published-info":
        return (
          <StepCard
            key={step}
            title="Yayında"
            description="Bu iş yayınlandı. Deneme ve paket kayıtları detay sayfasındadır."
          >
            <p>
              <Link href={detailHref}>Yayın kayıtlarına git →</Link>
            </p>
          </StepCard>
        );
      case "resolve-block":
        return (
          <StepCard
            key={step}
            title="Bloku çöz"
            description={
              detail.work_item.blocked_reason === null
                ? "İş engellendi."
                : `Engel gerekçesi: ${detail.work_item.blocked_reason}`
            }
          >
            <form action={motorResolveBlockAction} className="control-form">
              {hidden}
              <ReasonInput label="çözüm gerekçesi" />
              <button type="submit">Bloku çöz</button>
            </form>
          </StepCard>
        );
      case "resolve-changes-requested":
        return (
          <StepCard
            key={step}
            title="Değişiklik talebini çöz"
            description="İş, kayıtlı sorumlu duruma geri yönlendirilir."
          >
            <form
              action={motorResolveChangesRequestedAction}
              className="control-form"
            >
              {hidden}
              <ReasonInput label="çözüm gerekçesi" />
              <button type="submit">Çöz</button>
            </form>
          </StepCard>
        );
      case "resolve-approval-expired":
        return (
          <StepCard
            key={step}
            title="Süresi dolan onayı çöz"
            description="İş, türetilen hedef duruma yönlendirilir; yeni onay gerekir."
          >
            <form
              action={motorResolveApprovalExpiredAction}
              className="control-form"
            >
              {hidden}
              <ReasonInput label="çözüm gerekçesi" />
              <button type="submit">Çöz</button>
            </form>
          </StepCard>
        );
      case "duplicate-link":
        return (
          <StepCard
            key={step}
            title="Kopya"
            description="Bu doküman kopya olarak işaretlendi. Ayrı bir açıyla yeniden açmak Editoryal sayfasından yapılır."
          >
            <p>
              <Link href="/editorial">Editoryal kuyruğuna git →</Link>
            </p>
          </StepCard>
        );
      case "terminal-info":
        return (
          <StepCard
            key={step}
            title="Kapalı"
            description={
              detail.work_item.rejected_reason === null
                ? "Bu iş kapatıldı."
                : `Kapanış gerekçesi: ${detail.work_item.rejected_reason}`
            }
          />
        );
      case "worker-wait":
        return (
          <StepCard
            key={step}
            title="Worker çalışıyor"
            description="Sıradaki artefakt kuyruktaki görev bitince görünür. Sayfayı yenileyin."
          />
        );
      case "detail-link-only":
      default:
        return (
          <StepCard
            key={step}
            title="Detay sayfası"
            description="Bu adımın kontrolleri detay sayfasındadır."
          >
            <p>
              <Link href={detailHref}>Detaya git →</Link>
            </p>
          </StepCard>
        );
    }
  });
  return <div className="motor-actions">{rendered}</div>;
}

function IntakeSection({
  sources,
  pipeline,
}: {
  sources: SourceListItem[] | null;
  pipeline: PipelineListItem[] | null;
}) {
  const discoverable = (sources ?? []).filter((source) =>
    isDiscoveryEligible(source),
  );
  const toAccept = (pipeline ?? []).filter(
    (item) => item.lifecycle_state === "discovered",
  );
  const toFetch = (pipeline ?? []).filter(
    (item) =>
      item.lifecycle_state === "accepted" ||
      item.lifecycle_state === "fetch_failed",
  );
  const toPromote = (pipeline ?? []).filter(
    (item) =>
      item.normalization_status === "succeeded" &&
      item.normalized_document_id !== null,
  );
  return (
    <details className="motor-intake">
      <summary>
        Giriş hattı — keşfet ({toAccept.length}), getir ({toFetch.length}),
        yükselt ({toPromote.length})
      </summary>
      <div className="motor-columns">
        <div className="motor-column">
          <h3>1 · Kaynaktan keşfet</h3>
          {discoverable.length === 0 && (
            <p className="empty-note">
              Keşfedilebilir aktif kaynak yok. Feed veya sitemap türünde bir{" "}
              <Link href="/sources/new">kaynak kaydedin</Link>.
            </p>
          )}
          <ul className="plain-list">
            {discoverable.map((source) => (
              <li key={source.id}>
                <form action={motorRunDiscoveryAction} className="control-form">
                  <input type="hidden" name="source_id" value={source.id} />
                  <span>{source.name}</span>
                  <button type="submit">Keşfi başlat</button>
                </form>
              </li>
            ))}
          </ul>
        </div>
        <div className="motor-column">
          <h3>2 · Kabul et &amp; getir</h3>
          {toAccept.length === 0 && toFetch.length === 0 && (
            <p className="empty-note">Bekleyen keşif öğesi yok.</p>
          )}
          <ul className="plain-list">
            {toAccept.slice(0, 10).map((item) => (
              <li key={item.id}>
                <form
                  action={motorAcceptDiscoveryAction}
                  className="control-form"
                >
                  <input
                    type="hidden"
                    name="discovery_item_id"
                    value={item.id}
                  />
                  <span className="cell-url">{item.canonical_url}</span>
                  <button type="submit">Kabul et</button>
                </form>
              </li>
            ))}
            {toFetch.slice(0, 10).map((item) => (
              <li key={item.id}>
                <form
                  action={motorFetchDiscoveryAction}
                  className="control-form"
                >
                  <input
                    type="hidden"
                    name="discovery_item_id"
                    value={item.id}
                  />
                  <span className="cell-url">{item.canonical_url}</span>
                  <button type="submit">Getir</button>
                </form>
              </li>
            ))}
          </ul>
        </div>
        <div className="motor-column">
          <h3>3 · İşe yükselt</h3>
          {toPromote.length === 0 && (
            <p className="empty-note">Yükseltmeye hazır doküman yok.</p>
          )}
          <ul className="plain-list">
            {toPromote.slice(0, 10).map((item) => (
              <li key={item.id}>
                <form action={motorPromoteAction} className="control-form">
                  <input
                    type="hidden"
                    name="normalized_document_id"
                    value={item.normalized_document_id ?? ""}
                  />
                  <span className="cell-url">{item.canonical_url}</span>
                  {item.duplicate_outcome !== null && (
                    <span className="badge">{item.duplicate_outcome}</span>
                  )}
                  <button type="submit">Yükselt</button>
                </form>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  );
}

function WorkItemList({
  rows,
  selectedId,
}: {
  rows: WorkQueueRow[];
  selectedId: string | null;
}) {
  if (rows.length === 0) {
    return (
      <p className="empty-note">
        Henüz iş öğesi yok. Giriş hattından bir doküman yükseltin.
      </p>
    );
  }
  return (
    <ul className="motor-item-list">
      {rows.map((row) => (
        <li
          key={row.work_item_id}
          data-selected={row.work_item_id === selectedId ? "true" : undefined}
        >
          <Link href={`/motor?item=${row.work_item_id}`}>
            <span className="motor-item-title">{row.title_working_label}</span>
            <span
              className="badge"
              data-state={row.current_state}
              title={row.current_state}
            >
              {STATE_LABELS_TR[row.current_state]}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function contextFromArtifacts(
  detail: WorkItemDetail,
  extras: {
    hasActiveDraft: boolean;
    activeReviewVerdict: "pass" | "revise" | null;
    activeQaOutcome: "ready_for_human_review" | "not_ready" | null;
    unsatisfiedMediaNeeds: number;
    latestPackageId: string | null;
    isReviewer: boolean;
  },
): MotorContext {
  const latestPack = latestByCreatedAt(detail.evidence_packs);
  const latestAnalysis = latestByCreatedAt(detail.intent_analyses);
  const latestBrief = latestByCreatedAt(detail.briefs);
  return {
    state: detail.work_item.current_state,
    hasScore: detail.scores.length > 0,
    hasIdeas: detail.ideas.length > 0,
    selectedIdeaId: detail.effective_selected_idea_id,
    latestPackId: latestPack?.id ?? null,
    latestAnalysisId: latestAnalysis?.id ?? null,
    latestBriefId: latestBrief?.id ?? null,
    latestBriefStatus: latestBrief?.status ?? null,
    ...extras,
  };
}

export default async function MotorPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const selectedParam = firstParam(query.item);
  const selectedId =
    selectedParam !== undefined && isUuid(selectedParam) ? selectedParam : null;

  const [sourcesResult, pipelineResult, queueResult, currentUserResult] =
    await Promise.all([
      fetchResearchSources({ limit: 50 }),
      fetchPipelineItems({ limit: 100 }),
      fetchWorkQueue({ limit: 20 }),
      fetchCurrentUser(),
    ]);

  const sources = sourcesResult.kind === "ok" ? sourcesResult.data.items : null;
  const pipeline =
    pipelineResult.kind === "ok" ? pipelineResult.data.items : null;
  const queueRows = queueResult.kind === "ok" ? queueResult.data.items : [];
  const isReviewer =
    currentUserResult.kind === "ok" &&
    currentUserResult.data.roles.includes("reviewer");

  const backendDown =
    sourcesResult.kind === "unreachable" &&
    pipelineResult.kind === "unreachable" &&
    queueResult.kind === "unreachable";

  const focusId = selectedId ?? queueRows[0]?.work_item_id ?? null;

  let detail: WorkItemDetail | null = null;
  let extras = {
    hasActiveDraft: false,
    activeReviewVerdict: null as "pass" | "revise" | null,
    activeQaOutcome: null as "ready_for_human_review" | "not_ready" | null,
    unsatisfiedMediaNeeds: 0,
    latestPackageId: null as string | null,
    isReviewer,
  };
  if (focusId !== null) {
    const detailResult = await fetchWorkItemDetail(focusId);
    if (detailResult.kind === "ok") {
      detail = detailResult.data;
      const [drafts, reviews, qaReports, media, publication] =
        await Promise.all([
          fetchWorkItemDrafts(focusId),
          fetchWorkItemReviews(focusId),
          fetchWorkItemQaReports(focusId),
          fetchWorkItemMedia(focusId),
          fetchWorkItemPublication(focusId),
        ]);
      extras = {
        hasActiveDraft:
          drafts.kind === "ok" &&
          drafts.data.drafts.some((draft) => draft.status === "active"),
        activeReviewVerdict:
          reviews.kind === "ok"
            ? (reviews.data.reviews.find((review) => review.status === "active")
                ?.verdict ?? null)
            : null,
        activeQaOutcome:
          qaReports.kind === "ok"
            ? (qaReports.data.reports.find(
                (report) => report.status === "active",
              )?.outcome ?? null)
            : null,
        unsatisfiedMediaNeeds:
          media.kind === "ok"
            ? media.data.needs.filter((need) => need.satisfaction === null)
                .length
            : 0,
        latestPackageId:
          publication.kind === "ok"
            ? (latestByCreatedAt(publication.data.packages)?.id ?? null)
            : null,
        isReviewer,
      };
    }
  }

  return (
    <section className="panel panel-wide" aria-labelledby="motor-title">
      <h1 id="motor-title">Üretim Motoru</h1>
      <p className="muted">
        Tüm hat tek sayfada: keşiften yayına her adım sırayla burada ilerler.
        Karmaşık seçimler ilgili detay sayfasına bağlanır.
      </p>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={MOTOR_NOTICES}
      />
      {backendDown && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      <IntakeSection sources={sources} pipeline={pipeline} />
      <div className="motor-layout">
        <aside className="motor-queue">
          <h2>Aktif işler</h2>
          <WorkItemList rows={queueRows} selectedId={focusId} />
        </aside>
        <div className="motor-focus">
          {detail === null ? (
            <p className="empty-note">
              Seçili iş yok. Soldan bir iş seçin veya giriş hattından yeni bir
              doküman yükseltin.
            </p>
          ) : (
            <>
              <h2>{detail.work_item.title_working_label}</h2>
              <p className="muted">
                Durum:{" "}
                <span className="badge">
                  {STATE_LABELS_TR[detail.work_item.current_state]}
                </span>{" "}
                · Girildi:{" "}
                {formatUtcTimestamp(detail.work_item.current_state_entered_at)}{" "}
                · <Link href={`/editorial/${detail.work_item.id}`}>Detay</Link>{" "}
                ·{" "}
                <Link href={`/motor?item=${detail.work_item.id}`}>Yenile</Link>
              </p>
              <Stepper detail={detail} />
              <StepForms
                steps={deriveNextSteps(contextFromArtifacts(detail, extras))}
                detail={detail}
                context={contextFromArtifacts(detail, extras)}
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
