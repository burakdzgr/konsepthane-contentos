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
import { trLabel, trList } from "@/lib/tr-labels";
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
  "evaluation-queued":
    "Puanlama kuyruğa alındı. Yeni değerlendirmeyi görmek için sayfayı yenileyin.",
  commissioned: "Fırsat görevlendirildi. Fikir çalışması başlayabilir.",
  "commissioned-override":
    "Fırsat, kaynak tabanı kapısı gerekçeyle aşılarak görevlendirildi; aşım karar geçmişine kaydedildi.",
  "opportunity-rejected": "Fırsat, gerekçenizle birlikte reddedildi.",
  "ideas-queued":
    "Fikir üretimi kuyruğa alındı. Adaylar worker tamamladığında görünür.",
  "idea-selected": "Fikir sürümü seçildi.",
  "idea-deselected": "Seçim kaldırıldı. Şu anda hiçbir şey seçili değil.",
  "pack-queued":
    "Kanıt paketi birleştirme, açık seçimlerinizle kuyruğa alındı.",
  "contradiction-resolved":
    "Çelişki çözüldü. Eski paket yeterliliğini korur; çözümü yansıtmak için yeniden birleştirin.",
  "pack-reassembled":
    "Yeni paket sürümü oluşturuldu. Onunla devam etmek bir sonraki açık adımdır.",
  "block-resolved": "Engel çözüldü; önceki duruma dönüldü.",
  "blocked-rejected": "Engellenen iş öğesi reddedildi.",
  "analysis-queued":
    "Arama niyeti analizi, tam sabitlemelerinizle kuyruğa alındı.",
  "compose-queued": "Brief oluşturma kuyruğa alındı. Sonuç bir TASLAK'tır.",
  "brief-accepted":
    "Brief, taslak yazımı için kabul edildi. Bu, içerik yayınlamaz.",
  "duplicate-reopened": "Kopya, bu operatör iş öğesi olarak yeniden açıldı.",
  "draft-queued":
    "Yazar taslağı üretimi kuyruğa alındı. Taslak, worker tamamladığında görünür.",
  "draft-submitted":
    "Operatör taslağı tüm kapılardan geçirilerek kaydedildi; öğe düzenleme aşamasına geçti.",
  "rework-requested":
    "Yeniden çalışma kaydedildi: yazar aşaması sorumlu olacak şekilde değişiklik istendi.",
  "changes-request-resolved":
    "Değişiklik istendi durumundan, kayıtlı sorumlu duruma yönlendirildi.",
  "review-queued":
    "Editör değerlendirmesi kuyruğa alındı. Hüküm, worker tamamladığında görünür.",
  "review-accepted":
    "Değerlendirme kabul edildi; öğe QA incelemesine geçti. Bu, içerik yayınlamaz.",
  "qa-queued":
    "QA kapısı çalıştırması kuyruğa alındı. Tekrarlanan çalıştırmalar idempotenttir.",
  "qa-gate-waived":
    "Vazgeçme kaydedildi ve denetlendi. Kapılar yeniden ÇALIŞTIRILMADI — QA'yı açıkça çalıştırın.",
  "package-approved":
    "Paket, kayıt altında sizin tarafınızdan onaylandı. Zamanlama daha sonraki bir faza aittir.",
  "decision-changes-requested":
    "Değişiklik isteği kaydedildi ve sorumlu aşamaya yönlendirildi.",
  "package-rejected": "Paket, kayıt altında reddedildi.",
  "approval-revoked":
    "Onay geri çekildi (orijinal kayıt korunur) ve yeniden çalışma için yönlendirildi.",
  "media-bound":
    "Medya ihtiyacı varlığa bağlandı. Kapılar yeniden ÇALIŞTIRILMADI — QA'yı açıkça çalıştırın.",
  "media-unbound":
    "Bağlama geri çekildi; ihtiyaç yeniden dürüstçe karşılanmamış durumda.",
  "media-image-queued":
    "Görsel üretimi kuyruğa alındı. Üretim tek başına hiçbir ihtiyacı karşılamaz — varlığı açıkça bağlayın.",
  "publication-package-assembled":
    "Yayın paketi, tam olarak onaylanan artefaktlardan birleştirildi.",
  "publication-scheduled":
    "Yayın zamanlandı. Yönetimli gönderim çalışana kadar hiçbir şey yayınlanmaz.",
  "publish-queued":
    "Yayın gönderimi kuyruğa alındı; worker önce onayı yeniden kontrol eder.",
  "approval-expiry-resolved":
    "Süresi dolan onaydan türetilen hedefe yönlendirildi.",
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
      {total} {noun} içinden en son {shown} tanesi gösteriliyor.
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
        aria-label={`${label} gerekçesi`}
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
      <h2 id="detail-workflow">İş akışı</h2>
      <dl className="status-list">
        <Row name="Durum">
          <span
            className="badge"
            data-tone={workflowStateTone(item.current_state)}
          >
            {trLabel(item.current_state)}
          </span>{" "}
          <span className="muted">
            {formatUtcTimestamp(item.current_state_entered_at)} tarihinden beri
          </span>
        </Row>
        <Row name="Çalışma başlığı">{item.title_working_label}</Row>
        <Row name="Köken">{trLabel(item.origin)}</Row>
        <Row name="Yerel ayar / pazar">
          {item.locale} / {item.market}
        </Row>
        {item.blocked_reason !== null && (
          <Row name="Engellenme gerekçesi">{item.blocked_reason}</Row>
        )}
        {item.current_state === "blocked" && (
          <Row name="Geçerli devam hedefi">
            {item.blocked_resume_state ??
              "Devam edilebilir önceki durum kaydı yok"}
          </Row>
        )}
        {item.rejected_reason !== null && (
          <Row name="Reddedilme gerekçesi">{item.rejected_reason}</Row>
        )}
        <Row name="İş öğesi kimliği">
          <span className="mono muted">{item.id}</span>
        </Row>
      </dl>
      {item.current_state === "blocked" && (
        <div className="control-stack">
          <ReasonForm
            action={resolveBlockAction}
            workItemId={item.id}
            hidden={{}}
            label="Engeli çöz"
            placeholder="engeli kaldırmak için ne değişti"
            helper={`Geçmişten türetilen önceki durumu${
              item.blocked_resume_state !== null
                ? ` (${item.blocked_resume_state})`
                : ""
            } sürdürür; burada hedef seçilemez.`}
          />
          <ReasonForm
            action={rejectBlockedAction}
            workItemId={item.id}
            hidden={{}}
            label="Engellenen öğeyi reddet"
            placeholder="bu iş öğesi neden terk ediliyor"
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
        <Row name="Sonuç">
          <span
            className="badge"
            data-tone={scoreEligibilityTone(score.eligibility)}
          >
            {trLabel(score.overall_band)} / {trLabel(score.eligibility)}
          </span>{" "}
          {score.effective && (
            <strong title="Görevlendirme kapısının baktığı, en son kaydedilmiş skor">
              (yürürlükteki skor)
            </strong>
          )}
        </Row>
        <Row name="Ne ölçüyor">
          <span className="muted">
            Kaynak tabanının kalitesi: güncellik, kaynak sayısı, kaynak güveni,
            kanıt miktarı ve kopya örtüşmesi. Konunun değerini değil; arama
            talebi, rekabet ve hedef kitle uyumu henüz ölçülmüyor.
          </span>
        </Row>
        <Row name="Genel değer">
          {score.overall_value !== null ? score.overall_value : "Bilinmiyor"}
        </Row>
        <Row name="Motor">
          <span className="mono">
            {score.engine_name}/{score.engine_version}
          </span>
        </Row>
        <Row name="Eksik sinyaller">{trList(score.missing_signals)}</Row>
        <Row name="Risk bayrakları">{trList(score.risk_flags)}</Row>
        <Row name="Değerlendirildi">
          {formatUtcTimestamp(score.evaluated_at)}
        </Row>
      </dl>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Bileşen</th>
              <th scope="col">Mevcudiyet</th>
              <th scope="col">Değer</th>
              <th scope="col">Sağlayıcı</th>
              <th scope="col">Gözlemlendi</th>
            </tr>
          </thead>
          <tbody>
            {score.components.map((component) => (
              <tr key={component.component}>
                <td>{trLabel(component.component)}</td>
                <td>
                  {component.availability === "unknown" ? (
                    <span className="badge" data-tone="neutral">
                      Bilinmiyor
                    </span>
                  ) : (
                    trLabel(component.availability)
                  )}
                </td>
                <td>
                  {component.availability === "known" &&
                  component.value !== null
                    ? component.value
                    : "Gözlemlenmedi"}
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
        <h2 id="detail-opportunity">Fırsat ve skor</h2>
        <p className="empty-note">Bu iş öğesine bağlı fırsat yok.</p>
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
      <h2 id="detail-opportunity">Fırsat ve skor</h2>
      <dl className="status-list">
        <Row name="Fırsat durumu">
          {trLabel(opportunity.disposition)}
          {opportunity.disposition_reason !== null &&
            ` — ${opportunity.disposition_reason}`}
        </Row>
        <Row name="Konu">{opportunity.topic_summary}</Row>
        {opportunity.update_of_reference !== null && (
          <Row name="Güncelleme referansı">
            {opportunity.update_of_reference}
          </Row>
        )}
        <Row name="Yükseltme kök dokümanı">
          <span className="mono muted">
            {opportunity.promotion_root_document_id}
          </span>
        </Row>
      </dl>
      {detail.scores.length === 0 && (
        <p className="empty-note">
          Henüz değerlendirilmedi. Puanlama açık bir eylemdir.
        </p>
      )}
      {detail.scores.map((score) => (
        <ScoreCard key={score.id} score={score} />
      ))}
      <TruncationNote
        shown={detail.scores.length}
        total={detail.total_scores}
        noun="skor değerlendirmesi"
      />
      <div className="control-stack">
        <form action={evaluateOpportunityAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="opportunity_id" value={opportunity.id} />
          <button type="submit">(Yeniden) değerlendirmeyi kuyruğa al</button>
          <span className="muted">
            Puanlama yeni bir değerlendirme kaydeder; asla kendi başına
            görevlendirmez.
          </span>
        </form>
        {canDecide && (
          <>
            {opportunity.commission_eligible ? (
              <ReasonForm
                action={commissionOpportunityAction}
                workItemId={workItemId}
                hidden={{ opportunity_id: opportunity.id }}
                label="Görevlendir"
                placeholder="bu fırsat neden değerlendirmeye değer"
                helper={
                  effective !== undefined
                    ? `Yürürlükteki skor: ${trLabel(effective.overall_band)} / ${trLabel(effective.eligibility)}` +
                      (effective.missing_signals.length > 0
                        ? `; eksik: ${trList(effective.missing_signals)}`
                        : "")
                    : "Yürürlükteki skor görevlendirilebilir."
                }
              />
            ) : (
              // Same rule as the backend gate (commission_eligible): never
              // offer a command the domain will refuse with 409.
              <p className="muted" role="note">
                {effective !== undefined
                  ? `Görevlendirme kapalı: yürürlükteki skor ${trLabel(effective.overall_band)} / ${trLabel(effective.eligibility)}` +
                    (effective.missing_signals.length > 0
                      ? `; eksik: ${trList(effective.missing_signals)}`
                      : "") +
                    ". Bu skor kaynak tabanını ölçer, konunun değerini değil; aşağıdaki gerekçeli aşımla yine de görevlendirebilirsiniz."
                  : "Görevlendirme kapalı: henüz kalıcı bir skor yok. Skor olmadan görevlendirme yapılamaz."}
              </p>
            )}
            {!opportunity.commission_eligible &&
              opportunity.commission_override_possible && (
                <ReasonForm
                  action={commissionOpportunityAction}
                  workItemId={workItemId}
                  hidden={{
                    opportunity_id: opportunity.id,
                    override_gate: "true",
                  }}
                  label="Yine de görevlendir"
                  placeholder="konu neden buna değer (kapı aşımı gerekçesi)"
                  helper="Kaynak tabanı kapısını gerekçeyle aşar (ADR 0010); aşım ve aşılan skor karar geçmişine kaydedilir."
                />
              )}
            <ReasonForm
              action={rejectOpportunityAction}
              workItemId={workItemId}
              hidden={{ opportunity_id: opportunity.id }}
              label="Fırsatı reddet"
              placeholder="bu fırsat neden sürdürülmüyor"
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
      <h2 id="detail-inputs">Araştırma girdileri</h2>
      {detail.research_inputs.length === 0 && (
        <p className="empty-note">Kayıtlı araştırma girdisi yok.</p>
      )}
      {detail.research_inputs.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Doküman</th>
                <th scope="col">Rol</th>
                <th scope="col">Kopya</th>
                <th scope="col">Kaynak</th>
                <th scope="col">Güven</th>
                <th scope="col">Yayınlandı</th>
                <th scope="col">Getirildi</th>
                <th scope="col">Ekleyen</th>
              </tr>
            </thead>
            <tbody>
              {detail.research_inputs.map((input) => (
                <tr key={input.id}>
                  <td title={input.normalized_document_id}>
                    {input.document_title ?? "Başlıksız"}
                  </td>
                  <td>{trLabel(input.role)}</td>
                  <td>{trLabel(input.duplicate_outcome)}</td>
                  <td>{input.source_slug ?? "Bilinmiyor"}</td>
                  <td>{trLabel(input.trust_tier)}</td>
                  <td>{formatUtcTimestamp(input.external_published_at)}</td>
                  <td>{formatUtcTimestamp(input.fetched_at)}</td>
                  <td>{trLabel(input.added_by)}</td>
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
        <Row name="Çalışma başlığı">
          {idea.working_title} <span className="muted">v{idea.version}</span>{" "}
          {idea.effective_selected && <strong>(seçili)</strong>}
        </Row>
        <Row name="Açı">{idea.angle}</Row>
        <Row name="Dayanak">{idea.rationale}</Row>
        <Row name="Hedef kitle">{idea.audience}</Row>
        <Row name="Değer">{idea.value_proposition}</Row>
        <Row name="Tür / köken">
          {trLabel(idea.content_type)} · {trLabel(idea.origin)}
        </Row>
        <Row name="Özgünlük">
          <span
            className="badge"
            data-tone={originalityTone(idea.originality_status)}
          >
            {trLabel(idea.originality_status)}
          </span>
        </Row>
        {idea.exclusions.length > 0 && (
          <Row name="Hariç tutulanlar">{idea.exclusions.join("; ")}</Row>
        )}
        {idea.generation_attempt_id !== null && (
          <Row name="Üretim denemesi">
            <span className="mono muted">{idea.generation_attempt_id}</span>
          </Row>
        )}
        <Row name="Fikir kimliği">
          <span className="mono muted">{idea.id}</span>
        </Row>
      </dl>
      {canOperate && !idea.effective_selected && (
        <ReasonForm
          action={selectIdeaAction}
          workItemId={workItemId}
          hidden={{ idea_id: idea.id }}
          label="Bu sürümü seç"
          placeholder="neden tam olarak bu sürüm"
        />
      )}
      {canOperate && idea.effective_selected && (
        <ReasonForm
          action={deselectIdeaAction}
          workItemId={workItemId}
          hidden={{ idea_id: idea.id }}
          label="Seçimi kaldır"
          placeholder="seçim neden kaldırılıyor"
          helper="Seçimi kaldırmak asla eski bir seçimi geri getirmez."
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
      <h2 id="detail-ideas">Fikirler</h2>
      {detail.ideas.length === 0 && (
        <p className="empty-note">Henüz fikir sürümü yok.</p>
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
        noun="fikir sürümü"
      />
      {canGenerate && opportunity !== null && (
        <form action={generateIdeasAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <input type="hidden" name="opportunity_id" value={opportunity.id} />
          <label>
            Aday sayısı
            <select name="candidate_count" defaultValue="3">
              {["1", "2", "3", "4", "5"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Fikir adayları üret</button>
          <span className="muted">
            Yalnızca model destekli adaylar; hiçbir şey otomatik seçilmez.
          </span>
        </form>
      )}
      {detail.selection_events.length > 0 && (
        <>
          <h3>Seçim geçmişi</h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Ne zaman</th>
                  <th scope="col">Eylem</th>
                  <th scope="col">Fikir</th>
                  <th scope="col">Gerekçe</th>
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
            noun="seçim olayı"
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
        <Row name="İddia">{contradiction.claim_key}</Row>
        <Row name="Nitelik">{contradiction.nature}</Row>
        <Row name="Önem">{trLabel(contradiction.severity)}</Row>
        <Row name="Taraflar">
          A: {contradiction.evidence_side_a.join(", ")} · B:{" "}
          {contradiction.evidence_side_b.join(", ")}
        </Row>
        <Row name="Çözüm">
          <span
            className="badge"
            data-tone={contradictionResolutionTone(
              contradiction.resolution_status,
            )}
          >
            {trLabel(contradiction.resolution_status)}
          </span>
          {contradiction.resolution_reason !== null &&
            ` — ${contradiction.resolution_reason}`}
        </Row>
        {contradiction.handling_recommendation !== null && (
          <Row name="Ele alış">{contradiction.handling_recommendation}</Row>
        )}
        {contradiction.resolved_at !== null && (
          <Row name="Çözüldü">
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
            aria-label="Çözüm durumu"
          >
            <option value="" disabled>
              Çözüm…
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
            placeholder="çözüm gerekçesi"
            aria-label="Çözüm gerekçesi"
          />
          <button type="submit">Çöz</button>
          <span className="muted">
            Çözmek bu paketin kayıtlı yeterliliğini asla değiştirmez; ardından
            yeni bir sürüm olarak yeniden birleştirin.
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
        <Row name="Paket">
          <span className="mono muted">{pack.id}</span>{" "}
          <span className="muted">v{pack.version}</span>
        </Row>
        <Row name="Yeterlilik">
          <span
            className="badge"
            data-tone={packSufficiencyTone(pack.sufficiency)}
          >
            {trLabel(pack.sufficiency)}
          </span>
        </Row>
        {detailEntries.length > 0 && (
          <Row name="Neden">
            {detailEntries
              .map(
                ([key, value]) => `${key}: ${(value as unknown[]).join("; ")}`,
              )
              .join(" · ")}
          </Row>
        )}
        <Row name="Birleştirici">
          <span className="mono">
            {pack.assembler_name}/{pack.assembler_version}
          </span>
        </Row>
        <Row name="Sabitlenmiş fikir">
          {pack.idea_id !== null ? (
            <span className="mono muted">{pack.idea_id}</span>
          ) : (
            "Sabitlenmemiş"
          )}
        </Row>
        <Row name="Birleştirildi">{formatUtcTimestamp(pack.created_at)}</Row>
      </dl>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Rol</th>
              <th scope="col">Küme</th>
              <th scope="col">İfade</th>
              <th scope="col">Tür</th>
              <th scope="col">Doğrulama</th>
              <th scope="col">Kaynak</th>
            </tr>
          </thead>
          <tbody>
            {pack.items.map((item) => (
              <tr key={item.id}>
                <td>{trLabel(item.role)}</td>
                <td>{item.claim_cluster}</td>
                <td title={item.research_evidence_id}>
                  {item.statement ?? "—"}
                </td>
                <td>{item.evidence_type ?? "Bilinmiyor"}</td>
                <td>{item.verification_status ?? "Bilinmiyor"}</td>
                <td>
                  {item.source_slug ?? "Bilinmiyor"}
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
        <button type="submit">Yeni sürüm olarak yeniden birleştir</button>
        <span className="muted">
          Güncel çelişki çözümlerini yansıtan yeni ve değişmez bir sürüm üretir;
          bu sürüm olduğu gibi kalır ve iş akışı kendi başına ilerlemez.
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
        Paket oluşturmak için önce geçerli bir seçili fikir gerekir.
      </p>
    );
  }
  if (evidence.length === 0) {
    return (
      <p className="muted">Bu fırsat için henüz uygun araştırma kanıtı yok.</p>
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
              <th scope="col">Kullan</th>
              <th scope="col">İfade</th>
              <th scope="col">Doğrulama</th>
              <th scope="col">Kaynak</th>
              <th scope="col">Rol</th>
              <th scope="col">İddia kümesi</th>
              <th scope="col">Not</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((item) => (
              <tr key={item.id}>
                <td>
                  <input
                    type="checkbox"
                    name={`select-${item.id}`}
                    aria-label={`${item.id} kanıtını seç`}
                  />
                </td>
                <td title={item.id}>{item.statement}</td>
                <td>{trLabel(item.verification_status)}</td>
                <td>
                  {item.source_slug ?? "Bilinmiyor"}
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
                    placeholder="küme"
                    aria-label={`${item.id} için iddia kümesi`}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    name={`note-${item.id}`}
                    maxLength={1000}
                    placeholder="isteğe bağlı"
                    aria-label={`${item.id} için görüntüleme notu`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="submit">Seçimden kanıt paketi oluştur</button>
      <span className="muted">
        Kanıtı açıkça siz seçersiniz; sizin yerinize hiçbir şey seçilmez. Paketi
        worker birleştirir ve yeterliliği değerlendirir.
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
      <h2 id="detail-evidence">Kanıt paketleri</h2>
      {detail.evidence_packs.length === 0 && (
        <p className="empty-note">Henüz kanıt paketi sürümü yok.</p>
      )}
      {detail.evidence_packs.map((pack) => (
        <PackCard key={pack.id} pack={pack} workItemId={detail.work_item.id} />
      ))}
      <TruncationNote
        shown={detail.evidence_packs.length}
        total={detail.total_evidence_packs}
        noun="paket sürümü"
      />
      <PackBuilder detail={detail} evidence={evidence} />
    </section>
  );
}

function IntentCard({ analysis }: { analysis: IntentAnalysisView }) {
  return (
    <div className="detail-card">
      <dl className="status-list">
        <Row name="Analiz">
          <span className="mono muted">{analysis.id}</span>{" "}
          <span className="muted">v{analysis.version}</span>
        </Row>
        <Row name="Birincil niyet">{analysis.primary_intent}</Row>
        <Row name="Sayfa amacı">{analysis.page_purpose}</Row>
        <Row name="Olası format">{analysis.likely_format}</Row>
        <Row name="Sorgu kavramları">
          {analysis.query_concepts.join(", ") || "Kayıt yok"}
        </Row>
        <Row name="Bilinen sinyaller">
          {analysis.known_signals.length === 0 && "Hiçbiri kullanılmadı"}
          {analysis.known_signals.map((signal) => (
            <span key={signal.id} className="cell-secondary">
              {trLabel(signal.signal_type)} · {signal.provider} · gözlemlendi:{" "}
              {formatUtcTimestamp(signal.observed_at)}
              {signal.as_of !== null
                ? ` (${formatUtcTimestamp(signal.as_of)} itibarıyla)`
                : ""}
            </span>
          ))}
        </Row>
        <Row name="Eksik sinyaller">
          {analysis.missing_signals.length > 0
            ? analysis.missing_signals.join(", ")
            : "Yok"}
        </Row>
        <Row name="Kanibalizasyon">
          {cannibalizationLabel(analysis.cannibalization_status)}
        </Row>
        <Row name="Motor">
          <span className="mono">
            {analysis.engine_name}/{analysis.engine_version}
          </span>
        </Row>
        <Row name="Oluşturuldu">{formatUtcTimestamp(analysis.created_at)}</Row>
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
      <h2 id="detail-intent">Arama niyeti</h2>
      {detail.intent_analyses.length === 0 && (
        <p className="empty-note">Henüz arama niyeti analizi yok.</p>
      )}
      {detail.intent_analyses.map((analysis) => (
        <IntentCard key={analysis.id} analysis={analysis} />
      ))}
      <TruncationNote
        shown={detail.intent_analyses.length}
        total={detail.total_intent_analyses}
        noun="analiz sürümü"
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
            placeholder="arama sinyali kimliği (isteğe bağlı)"
            aria-label="Tam arama sinyali kimliği"
          />
          <input
            type="text"
            name="signal_id"
            maxLength={36}
            placeholder="ikinci sinyal kimliği (isteğe bağlı)"
            aria-label="İkinci tam arama sinyali kimliği"
          />
          <button type="submit">Arama niyeti analizini kuyruğa al</button>
          <span className="muted">
            Seçili fikri, READY (hazır) paket v{readyPack.version} sürümünü ve
            YALNIZCA listelediğiniz tam sinyal gözlemlerini sabitler — asla
            örtük bir &quot;en son&quot; kullanılmaz.
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
            {trLabel(brief.status)}
          </span>
        </Row>
        <Row name="Hedef">{brief.content_objective}</Row>
        <Row name="Niyet özeti">{brief.intent_summary}</Row>
        <Row name="Özgün açı">{brief.original_angle}</Row>
        <Row name="Zorunlu bölümler">
          {brief.required_sections
            .map((section) => String(section["key"] ?? ""))
            .filter(Boolean)
            .join(", ")}
        </Row>
        <Row name="Hariç tutulanlar">
          {brief.exclusions.length > 0 ? brief.exclusions.join("; ") : "Yok"}
        </Row>
        <Row name="Belirsizlik notları">
          {brief.uncertainty_notes.length > 0 ? (
            <ul className="plain-list">
              {brief.uncertainty_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : (
            "Yok"
          )}
        </Row>
        <Row name="Yapı koruması">
          {typeof guardOutcome === "string" ? guardOutcome : "Raporlanmadı"}
        </Row>
        <Row name="Sabitlemeler">
          fikir <span className="mono muted">{brief.idea_id}</span> · paket{" "}
          <span className="mono muted">{brief.evidence_pack_id}</span> · niyet{" "}
          <span className="mono muted">{brief.search_intent_analysis_id}</span>
        </Row>
        <Row name="Motor">
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
                <th scope="col">İddia</th>
                <th scope="col">Tür</th>
                <th scope="col">Metin</th>
                <th scope="col">Kanıt bağlantıları</th>
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
                      : "Kanıt yok (olgusal olmayan tür)"}
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
              {formatUtcTimestamp(event.occurred_at)}:{" "}
              {trLabel(event.from_status)} → {trLabel(event.to_status)} (
              {trLabel(event.actor_origin)}) — {event.reason}
            </li>
          ))}
        </ul>
      )}
      {canAccept && brief.status === "draft" && (
        <ReasonForm
          action={acceptBriefAction}
          workItemId={workItemId}
          hidden={{ brief_id: brief.id }}
          label="Taslak için kabul et"
          placeholder="yazım sözleşmesi neden eksiksiz"
          helper="&quot;Taslak için kabul et&quot;, brief'i Faz-4 Yazar'a bırakır. İçerik YAYINLAMAZ ve yayın onayı değildir."
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
      <h2 id="detail-briefs">Brief&apos;ler ve iddialar</h2>
      {detail.briefs.length === 0 && (
        <p className="empty-note">Henüz brief sürümü yok.</p>
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
        noun="brief sürümü"
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
                placeholder="geçersiz kılma gerekçesi (mevcut taslak)"
                aria-label="Geçersiz kılma gerekçesi"
              />
            )}
            <button type="submit">Taslak brief oluştur</button>
            <span className="muted">
              Sabitlenmiş fikirden, READY (hazır) paket v{readyPack.version} ve
              analiz v{latestAnalysis.version} sürümlerinden bir TASLAK üretir.
              Taslak için kabul etmek ayrı bir karardır.
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
      <h2 id="detail-drafts">Yazar taslakları</h2>
      {drafts === null && (
        <p className="muted" role="note">
          Taslak sürümleri şu anda yüklenemedi.
        </p>
      )}
      {drafts !== null && rows.length === 0 && (
        <p className="empty-note">Henüz taslak sürümü yok.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Sürüm</th>
                <th scope="col">Köken</th>
                <th scope="col">Durum</th>
                <th scope="col">Başlık önerisi</th>
                <th scope="col">Kapsam</th>
                <th scope="col">Özgünlük</th>
                <th scope="col">Oluşturuldu</th>
                <th scope="col">Detay</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>v{row.version}</td>
                  <td>
                    {row.origin === "operator" ? "operatör" : "yazar motoru"}
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {trLabel(row.status)}
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
                      Taslağı aç
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
            aria-label="Yeniden deneme numarası"
          />
          {hasActiveDraft && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="geçersiz kılma gerekçesi (etkin taslak var)"
              aria-label="Taslak geçersiz kılma gerekçesi"
            />
          )}
          <button type="submit">Yazar taslağı üret</button>
          <span className="muted">
            Kabul edilmiş brief v{acceptedBrief.version} sürümünden üretimi
            kuyruğa alır. Yeniden üretim, bir sonraki yeniden deneme numarası ve
            bir gerekçeyle aynı komuttur.
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
            placeholder="başlık önerisi (isteğe bağlı)"
            aria-label="Taslak başlık önerisi"
          />
          <textarea
            name="sections_json"
            required
            rows={6}
            placeholder='writer-draft-body/1 bölümleri JSON olarak, örn. [{"key":"giris","heading":"...","blocks":[...]}]'
            aria-label="Taslak bölümleri JSON"
          />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="gönderim gerekçesi"
            aria-label="Taslak gönderim gerekçesi"
          />
          {hasActiveDraft && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="geçersiz kılma gerekçesi (etkin taslak var)"
              aria-label="Manuel taslak geçersiz kılma gerekçesi"
            />
          )}
          <button type="submit">Operatör taslağını gönder</button>
          <span className="muted">
            İnsan yazımı taslak, yazar motoruyla AYNI kapılardan geçer; geçerli
            bir taslak öğeyi düzenleme aşamasına taşır.
          </span>
        </form>
      )}
      {state === "editing" && (
        <ReasonForm
          action={requestReworkAction}
          workItemId={workItemId}
          hidden={{}}
          label="Yeniden çalışma iste"
          placeholder="yazar aşaması neyi değiştirmeli?"
          helper="Yazar aşaması sorumlu olacak şekilde değişiklik isteğini kaydeder; etkin taslak sabitlenir."
        />
      )}
      {state === "changes_requested" && (
        <ReasonForm
          action={resolveChangesRequestedAction}
          workItemId={workItemId}
          hidden={{}}
          label="Yeniden çalışmayı yönlendir"
          placeholder="kayıtlı sorumlu duruma yönlendir"
          helper="Kalıcı olarak kaydedilmiş sorumlu duruma yönlendirir — burada hedef seçilemez."
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
      <h2 id="detail-reviews">Editör değerlendirmeleri</h2>
      <p className="muted">
        Bulgular politika sinyalidir, asla kanıt değildir. Hüküm deterministik
        olarak hesaplanır; iş akışını bir insan ilerletir.
      </p>
      {reviews === null && (
        <p className="muted" role="note">
          Değerlendirme sürümleri şu anda yüklenemedi.
        </p>
      )}
      {reviews !== null && rows.length === 0 && (
        <p className="empty-note">Henüz editör değerlendirmesi sürümü yok.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Sürüm</th>
                <th scope="col">Hüküm</th>
                <th scope="col">Durum</th>
                <th scope="col">Bulgular (engelleyici / büyük / küçük)</th>
                <th scope="col">Zarf yeniden kontrolü</th>
                <th scope="col">Oluşturuldu</th>
                <th scope="col">Detay</th>
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
                      {trLabel(row.verdict)}
                    </span>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {trLabel(row.status)}
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
                        ? "BİLİNMİYOR"
                        : row.writer_envelope_recomputed
                          ? "yeniden hesaplandı"
                          : "yeniden hesaplanmadı"}
                    </span>
                  </td>
                  <td>{formatUtcTimestamp(row.created_at)}</td>
                  <td>
                    <Link href={`/editorial/${workItemId}/reviews/${row.id}`}>
                      Değerlendirmeyi aç
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
            aria-label="Değerlendirme yeniden deneme numarası"
          />
          {activeReview !== undefined && (
            <input
              type="text"
              name="supersede_reason"
              maxLength={1000}
              placeholder="geçersiz kılma gerekçesi (etkin değerlendirme var)"
              aria-label="Değerlendirme geçersiz kılma gerekçesi"
            />
          )}
          <button type="submit">Editör değerlendirmesi üret</button>
          <span className="muted">
            Model destekli değerlendirmeyi kuyruğa alır; hüküm deterministik
            politika tarafından hesaplanır, asla model tarafından değil.
          </span>
        </form>
      )}
      {state === "editing" && activeReview !== undefined && (
        <ReasonForm
          action={acceptReviewAction}
          workItemId={workItemId}
          hidden={{}}
          label="Değerlendirmeyi kabul et"
          placeholder="bu taslak neden QA'ya ilerleyebilir"
          helper={
            activeReview.verdict === "pass"
              ? "Geçen değerlendirme sabitlenerek QA incelemesine ilerletir. Bir yayın kararı değildir."
              : "Etkin değerlendirmenin hükmü 'revise'; etkin taslağı kapsayan bir 'pass' değerlendirme olana kadar arka uç reddedecektir."
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
      <h2 id="detail-qa">QA raporları</h2>
      <p className="muted">
        Tam sabitlenmiş paket üzerinde deterministik katı kapılar. Sonucun
        yokluğu asla geçer sayılmaz; hazır bir rapor öğeyi otomatik olarak insan
        kararına ilerletir.
      </p>
      {qaReports === null && (
        <p className="muted" role="note">
          QA raporları şu anda yüklenemedi.
        </p>
      )}
      {qaReports !== null && rows.length === 0 && (
        <p className="empty-note">Henüz QA raporu sürümü yok.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Sürüm</th>
                <th scope="col">Sonuç</th>
                <th scope="col">Durum</th>
                <th scope="col">Kapılar</th>
                <th scope="col">Oluşturuldu</th>
                <th scope="col">Detay</th>
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
                      {trLabel(row.outcome)}
                    </span>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={draftStatusTone(row.status)}
                    >
                      {trLabel(row.status)}
                    </span>
                  </td>
                  <td>
                    {QA_GATE_ORDER.map((gate) => {
                      const result = row.gate_summary[gate] ?? "BİLİNMİYOR";
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
                      Raporu aç
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
          Denetlenen vazgeçmeler:{" "}
          {waivers
            .map((waiver) => `${waiver.gate_key} — ${waiver.reason}`)
            .join(" · ")}
        </p>
      )}
      {state === "qa_review" && (
        <div className="control-stack">
          <form action={runQaAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <button type="submit">QA kapılarını çalıştır</button>
            <span className="muted">
              Deterministik yeniden çalıştırma; özdeş sonuçlar mevcut raporu
              yeniden kullanır.
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
              placeholder="medya gereksinimi neden bilinçli olarak erteleniyor"
              aria-label="Medya kapısından vazgeçme gerekçesi"
            />
            <button type="submit">Medya kapısını atla</button>
            <span className="muted">
              UYARI: denetlenen bir insan vazgeçmesi — medya ihtiyaçları görünür
              kalır ve kapılar otomatik olarak yeniden ÇALIŞTIRILMAZ.
            </span>
          </form>
          <form action={requestReworkAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <select
              name="responsible_state"
              defaultValue="drafting"
              aria-label="Sorumlu durum"
            >
              <option value="drafting">yazar aşaması (drafting)</option>
              <option value="editing">editör aşaması (editing)</option>
            </select>
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="ne değişmeli ve kim sorumlu"
              aria-label="QA yeniden çalışma gerekçesi"
            />
            <button type="submit">Yeniden çalışma iste</button>
            <span className="muted">
              Kayıtlı sorumlu durum üzerinden yönlendirir; seçim sınırlıdır,
              asla keyfi değildir.
            </span>
          </form>
        </div>
      )}
      {state === "awaiting_human_review" && (
        <p role="note">
          <strong>İnsan kararı bekleniyor.</strong> Paketin tamamı (taslak,
          editör değerlendirmesi, QA raporu) iş akışı geçmişinde sabitlenmiştir.
          Kararın kendisi, aşağıdaki İnsan kararları bölümünde kimliği
          doğrulanmış bir değerlendirici tarafından kaydedilir.
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
          {trLabel(asset.origin)}
        </span>{" "}
        {asset.media_type} · {asset.byte_size} bytes
      </p>
      <p className="muted">Alt metin: {asset.alt_text}</p>
      <p className="muted">Lisans: {asset.license_note}</p>
      {asset.source_attribution !== null && (
        <p className="muted">Atıf: {asset.source_attribution}</p>
      )}
      <p className="muted">
        Bağlayan: {satisfaction.satisfied_by.display_name} —{" "}
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
      <h2 id="detail-media">Medya</h2>
      <p className="muted">
        Bir ihtiyaç YALNIZCA bir kalıcı varlığın açık bir insan bağlamasıyla
        karşılanır. Üretim ve yükleme tek başına hiçbir şeyi karşılamaz.
      </p>
      {media === null && (
        <p className="empty-note">Medya kapsamı yüklenemiyor.</p>
      )}
      {media !== null && media.total_needs === 0 && (
        <p className="empty-note">
          Kabul edilmiş brief hiçbir medya ihtiyacı tanımlamıyor (ya da henüz
          kabul edilmiş brief yok).
        </p>
      )}
      {media !== null && media.total_needs > 0 && (
        <>
          <p>
            Kapsam: {media.satisfied_needs} / {media.total_needs} ihtiyaç
            karşılandı.
          </p>
          {!commandsOpen && (
            <p role="note">
              Medya komutları <strong>{detail.work_item.current_state}</strong>{" "}
              durumunda kapalıdır: paket, nihai inceleme sürecinde
              dondurulmuştur.
            </p>
          )}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">İhtiyaç</th>
                  <th scope="col">Kapsam</th>
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
                        <p className="muted">Kısıtlar: {need.constraints}</p>
                      )}
                    </td>
                    <td>
                      {need.satisfaction !== null ? (
                        <MediaSatisfactionCell
                          satisfaction={need.satisfaction}
                        />
                      ) : (
                        <span className="badge" data-tone="warning">
                          Karşılanmadı
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
                              aria-label={`İhtiyaç ${need.need_index} için dosya yükle`}
                            />
                            <input
                              type="text"
                              name="alt_text"
                              required
                              maxLength={1000}
                              placeholder="alt metin (zorunlu)"
                              aria-label={`İhtiyaç ${need.need_index} için alt metin`}
                            />
                            <input
                              type="text"
                              name="license_note"
                              required
                              maxLength={1000}
                              placeholder="lisans notu (zorunlu)"
                              aria-label={`İhtiyaç ${need.need_index} için lisans notu`}
                            />
                            <input
                              type="text"
                              name="reason"
                              required
                              maxLength={1000}
                              placeholder="bu varlık ihtiyacı neden karşılıyor"
                              aria-label={`İhtiyaç ${need.need_index} bağlaması için gerekçe`}
                            />
                            <button type="submit">Yükle ve bağla</button>
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
                              placeholder="mevcut medya varlığı kimliği"
                              aria-label={`İhtiyaç ${need.need_index} için varlık kimliği`}
                            />
                            <input
                              type="text"
                              name="reason"
                              required
                              maxLength={1000}
                              placeholder="bu varlık ihtiyacı neden karşılıyor"
                              aria-label={`İhtiyaç ${need.need_index} için bağlama gerekçesi`}
                            />
                            <button type="submit">Mevcut varlığı bağla</button>
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
                            <button type="submit">Görsel üret</button>
                            <span className="muted">
                              Yapay zeka kökenli bir aday varlık üretir;
                              bağlamayı yine açıkça siz yaparsınız.
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
                            placeholder="bağlama neden artık geçerli değil"
                            aria-label={`İhtiyaç ${need.need_index} için bağlamayı kaldırma gerekçesi`}
                          />
                          <button type="submit">Bağlamayı kaldır</button>
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
          Bağlama geçmişi:{" "}
          {media.history
            .map(
              (row) =>
                `#${row.need_index} ${trLabel(row.status)} — ${row.satisfied_by.display_name}: ${row.reason}`,
            )
            .join(" · ")}
          {media.history_truncated &&
            ` · … daha eski bağlamalar gösterilmiyor (toplam ${media.total_history})`}
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
      <h2 id="detail-publication">Yayın</h2>
      <p className="muted">
        ContentOS tam olarak onaylananı yayınlar, yoksa hiçbir şey yayınlamaz:
        güncel onay korumasının arkasındaki değişmez, hash&apos;lenmiş paketler
        yalnızca yönetimli Publishing API taşıması üzerinden gönderilir.
      </p>
      {publication === null && (
        <p className="empty-note">Yayın durumu yüklenemiyor.</p>
      )}
      {publication !== null && (
        <>
          {publication.packages.length === 0 && (
            <p className="empty-note">Henüz yayın paketi yok.</p>
          )}
          {publication.latest_package_approval_current === false && (
            <p role="note">
              <strong>En son paket artık güncel bir onayla eşleşmiyor.</strong>{" "}
              Yayın ilerleyebilmeden önce yeniden birleştirme (ve muhtemelen
              yeniden onay) gerekir.
            </p>
          )}
          {publication.packages.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Sürüm</th>
                    <th scope="col">Paket</th>
                    <th scope="col">Birleştiren</th>
                    <th scope="col">Denemeler</th>
                  </tr>
                </thead>
                <tbody>
                  {publication.packages.map((row) => (
                    <tr key={row.id}>
                      <td>v{row.version}</td>
                      <td>
                        <span className="mono">{row.id}</span>
                        <p className="muted">
                          {row.section_count} bölüm · {row.manifest_needs} medya
                          bağlaması
                          {row.waived_unmet_indexes.length > 0
                            ? ` · vazgeçilen karşılanmamış ihtiyaçlar: ${row.waived_unmet_indexes.join(", ")}`
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
                          <span className="muted">Henüz gönderim yok.</span>
                        )}
                        {row.attempts_truncated && (
                          <p className="muted">
                            {row.total_attempts} denemeden {row.attempts.length}{" "}
                            tanesi gösteriliyor.
                          </p>
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
                              {trLabel(attempt.status)}
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
          {publication.packages.length > 0 && (
            <TruncationNote
              shown={publication.packages.length}
              total={publication.total_packages}
              noun="yayın paketi"
            />
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
            <button type="submit">Yayın paketini birleştir</button>
            <span className="muted">
              Onaylanan artefaktların deterministik projeksiyonu; özdeş içerik
              mevcut pakette birleşir.
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
                placeholder="bu paket yayın planına neden giriyor"
                aria-label="Zamanlama gerekçesi"
              />
              <button type="submit">Yayını zamanla</button>
              <span className="muted">
                Paket v{publication.packages[0]!.version} sürümünü zamanlar;
                yönetimli gönderim çalışana kadar hiçbir şey yayınlanmaz.
              </span>
            </form>
          )}
        </div>
      )}
      {(state === "scheduled" || state === "publishing") && (
        <form action={publishWorkItemAction} className="control-form">
          <input type="hidden" name="work_item_id" value={workItemId} />
          <button type="submit">Şimdi yayınla</button>
          <span className="muted">
            Yönetimli gönderimi kuyruğa alır; worker onayı yeniden kontrol eder
            ve bayat bir onay yayınlanmak yerine süresi dolmuş sayılır.
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
            placeholder="süresi dolan onayı incelemeye geri yönlendir"
            aria-label="Süre dolumu çözüm gerekçesi"
          />
          <button type="submit">Süresi dolan onayı çöz</button>
          <span className="muted">
            Hedef TÜRETİLİR: QA raporu taslağı hâlâ kapsıyorsa insan
            incelemesine, aksi halde QA&apos;ya geri döner.
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
      <h2 id="detail-decisions">İnsan kararları</h2>
      <p className="muted">
        İsimlendirilmiş insan kararlarının yalnızca-ekleme kaydı. Her karar, tam
        paketi (taslak, editör değerlendirmesi, QA raporu) kimlik ve içerik
        hash&apos;i ile sabitler.
      </p>
      {decisions === null && (
        <p className="empty-note">Karar kaydı yüklenemiyor.</p>
      )}
      {decisions !== null && (
        <>
          {status !== null && status.approved && (
            <p role="note">
              <strong>Kayıtlı onay</strong>
              {": "}
              <span
                className="badge"
                data-tone={status.current ? "positive" : "warning"}
              >
                {status.current ? "güncel" : "bayat"}
              </span>{" "}
              {status.current
                ? "Etkin taslak, onaylanan içerik hash'ini hâlâ taşıyor."
                : "Etkin taslak, onaylanan içerik hash'iyle artık eşleşmiyor — onay mevcut içeriği kapsamıyor."}
            </p>
          )}
          {decisions.decisions.length === 0 && (
            <p className="empty-note">Kayıtlı insan kararı yok.</p>
          )}
          {decisions.decisions.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Ne zaman</th>
                    <th scope="col">Karar</th>
                    <th scope="col">Değerlendirici</th>
                    <th scope="col">Gerekçe</th>
                    <th scope="col">Sabitlenmiş paket</th>
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
                          {trLabel(decision.decision)}
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
          <TruncationNote
            shown={decisions.decisions.length}
            total={decisions.total}
            noun="karar"
          />
        </>
      )}
      {(state === "awaiting_human_review" || state === "approved") &&
        !isReviewer && (
          <p role="note">
            Değerlendirici rolü olmadan oturum açtınız. Kararlar yalnızca
            yetkili bir değerlendirici tarafından kaydedilebilir.
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
              placeholder="bu paket neden onaylanıyor"
              aria-label="Onay gerekçesi"
            />
            <button type="submit">Paketi onayla</button>
            <span className="muted">
              Sizin adınıza kaydedilir ve etkin içerik hash&apos;ine bağlanır.
            </span>
          </form>
          <form action={requestChangesDecisionAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <select
              name="responsible_state"
              defaultValue="drafting"
              aria-label="Karar sorumlu durumu"
            >
              <option value="drafting">yazar aşaması (drafting)</option>
              <option value="editing">editör aşaması (editing)</option>
              <option value="qa_review">QA aşaması (qa_review)</option>
            </select>
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="ne değişmeli ve kim sorumlu"
              aria-label="İstenen değişiklikler gerekçesi"
            />
            <button type="submit">Değişiklik iste</button>
            <span className="muted">
              Kayıtlı sorumlu durum üzerinden yönlendirir; seçim sınırlıdır,
              asla keyfi değildir.
            </span>
          </form>
          <form action={rejectPackageAction} className="control-form">
            <input type="hidden" name="work_item_id" value={workItemId} />
            <input
              type="text"
              name="reason"
              required
              maxLength={1000}
              placeholder="paket neden doğrudan reddediliyor"
              aria-label="Ret gerekçesi"
            />
            <button type="submit">Paketi reddet</button>
            <span className="muted">
              UYARI: paketin kayıt altına alınan editoryal reddi.
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
            aria-label="Geri çekme sorumlu durumu"
          >
            <option value="drafting">yazar aşaması (drafting)</option>
            <option value="editing">editör aşaması (editing)</option>
            <option value="qa_review">QA aşaması (qa_review)</option>
          </select>
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="onay neden artık geçerli değil"
            aria-label="Geri çekme gerekçesi"
          />
          <button type="submit">Onayı geri çek</button>
          <span className="muted">
            UYARI: onay kaydı korunur; bir geri çekme olayı eklenir ve öğe
            yeniden çalışma için geri yönlendirilir.
          </span>
        </form>
      )}
    </section>
  );
}

function AiAttemptsSection({ attempts }: { attempts: AiAttemptView[] }) {
  return (
    <section aria-labelledby="detail-attempts">
      <h2 id="detail-attempts">Yapay zeka denemeleri</h2>
      <p className="muted">
        Yalnızca güvenli, kalıcı üstveriler. İstemler ve ham model çıktısı asla
        saklanmaz ve asla gösterilmez.
      </p>
      {attempts.length === 0 && (
        <p className="empty-note">Bu öğeye bağlı yapay zeka denemesi yok.</p>
      )}
      {attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Amaç</th>
                <th scope="col">Sağlayıcı / model</th>
                <th scope="col">Şema</th>
                <th scope="col">Şablon</th>
                <th scope="col">Durum</th>
                <th scope="col">Yeniden deneme</th>
                <th scope="col">Kullanım</th>
                <th scope="col">Ne zaman</th>
              </tr>
            </thead>
            <tbody>
              {attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{trLabel(attempt.purpose)}</td>
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
                      {trLabel(attempt.status)}
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
                      : "Raporlanmadı"}
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
      <h2 id="detail-history">İş akışı geçmişi</h2>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Ne zaman</th>
              <th scope="col">Geçiş</th>
              <th scope="col">Aktör</th>
              <th scope="col">Gerekçe</th>
              <th scope="col">Artefaktlar</th>
            </tr>
          </thead>
          <tbody>
            {detail.workflow_events.map((event) => (
              <tr key={event.id}>
                <td>{formatUtcTimestamp(event.occurred_at)}</td>
                <td>
                  {event.from_state === null
                    ? "oluşturuldu"
                    : trLabel(event.from_state)}{" "}
                  → {trLabel(event.to_state)}
                </td>
                <td>
                  {event.actor_display_name !== null
                    ? `${trLabel(event.actor_origin)} · ${event.actor_display_name}`
                    : event.actor_origin === "operator"
                      ? "operator · BİLİNMİYOR"
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
        noun="iş akışı olayı"
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
        <h1 id="editorial-detail-title">Editoryal iş öğesi</h1>
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="editorial-detail-title">
        <h1 id="editorial-detail-title">Editoryal iş öğesi</h1>
        <p role="status">Arka uç API&apos;si beklenmedik veri döndürdü.</p>
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
      <h1 id="editorial-detail-title">Editoryal iş öğesi</h1>
      <p className="muted">
        <Link href="/editorial">← Editoryal İş Kuyruğu&apos;na dön</Link>
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
