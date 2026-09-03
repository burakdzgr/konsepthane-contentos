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
      <h2 id="draft-summary">Taslak sürümü</h2>
      <dl className="status-list">
        <Row name="Sürüm">v{draft.version}</Row>
        <Row name="Köken">
          {draft.origin === "operator" ? "operatör" : "yazar motoru"} (
          <span className="mono">
            {draft.engine_name}/{draft.engine_version}
          </span>
          )
        </Row>
        <Row name="Durum">
          <span className="badge" data-tone={draftStatusTone(draft.status)}>
            {draft.status}
          </span>
          {draft.superseded_by_draft_id !== null && (
            <>
              {" "}
              <Link
                href={`/editorial/${draft.work_item_id}/drafts/${draft.superseded_by_draft_id}`}
              >
                daha yeni sürümle geçersiz kılındı
              </Link>
            </>
          )}
        </Row>
        <Row name="Başlık önerisi">{draft.title_proposal ?? "—"}</Row>
        <Row name="Belirsizlik kapsamı">
          <span
            className="badge"
            data-tone={verdictTone(draft.uncertainty_coverage_status)}
          >
            {verdictLabel(draft.uncertainty_coverage_status)}
          </span>
        </Row>
        <Row name="Özgünlük">
          <span
            className="badge"
            data-tone={verdictTone(draft.originality_outcome)}
          >
            {verdictLabel(draft.originality_outcome)}
          </span>
        </Row>
        <Row name="Gövde şeması">
          <span className="mono">{draft.body_schema_version}</span>
        </Row>
        <Row name="İçerik hash'i">
          <span className="mono">{draft.content_hash}</span>
        </Row>
        <Row name="Brief">
          <span className="mono">{draft.content_brief_id}</span>
        </Row>
        <Row name="Oluşturuldu">{formatUtcTimestamp(draft.created_at)}</Row>
      </dl>
    </section>
  );
}

function BodySection({ detail }: { detail: DraftDetail }) {
  return (
    <section aria-labelledby="draft-body">
      <h2 id="draft-body">Gövde</h2>
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
                    iddialar: {block.claim_refs.join(", ")}
                  </p>
                )}
                {block.uncertainty_refs.length > 0 && (
                  <p className="mono muted">
                    belirsizlik: {block.uncertainty_refs.join(", ")}
                  </p>
                )}
                {block.link_need_ref !== undefined && (
                  <p className="mono muted">
                    iç bağlantı ihtiyacı #{block.link_need_ref} (brief&apos;ten)
                  </p>
                )}
                {block.media_need_ref !== undefined && (
                  <p className="mono muted">
                    medya ihtiyacı #{block.media_need_ref} (brief&apos;ten)
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
      <h2 id="draft-claims">İddia → kanıt zinciri</h2>
      <p className="muted">
        Gövdede kullanılan her iddia, brief&apos;teki iddiasına ve arkasındaki
        tam ResearchEvidence kimliklerine bağlıdır.
      </p>
      {usages.length === 0 && (
        <p className="empty-note">Bu taslak hiçbir iddia bağlamıyor.</p>
      )}
      {usages.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Blok</th>
                <th scope="col">İddia</th>
                <th scope="col">Tür</th>
                <th scope="col">Ele alış</th>
                <th scope="col">Kanıt kimlikleri</th>
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
                      : "kayıt yok"}
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
      <h2 id="draft-audit">Geçersiz kılma denetimi</h2>
      {detail.status_events.length === 0 && (
        <p className="empty-note">Kayıtlı durum değişikliği yok.</p>
      )}
      {detail.status_events.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Ne zaman</th>
                <th scope="col">Değişiklik</th>
                <th scope="col">Aktör</th>
                <th scope="col">Gerekçe</th>
                <th scope="col">Yerine geçen</th>
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
      <h2 id="draft-attempts">Yazar üretim denemeleri</h2>
      <p className="muted">
        Yalnızca güvenli, kalıcı üstveriler — başarısız denemeler görünür kalır;
        istemler ve ham model çıktısı asla saklanmaz ve asla gösterilmez.
      </p>
      {detail.generation_attempts.length === 0 && (
        <p className="empty-note">Bu brief için yazar üretim denemesi yok.</p>
      )}
      {detail.generation_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Durum</th>
                <th scope="col">Yeniden deneme</th>
                <th scope="col">Sağlayıcı / model</th>
                <th scope="col">Şema</th>
                <th scope="col">Ne zaman</th>
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
          Gösterilenlerin ötesinde daha eski denemeler var.
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
        <h1 id="draft-detail-title">Yazar taslağı</h1>
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="draft-detail-title">
        <h1 id="draft-detail-title">Yazar taslağı</h1>
        <p role="status">Arka uç API&apos;si beklenmedik veri döndürdü.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="draft-detail-title">
      <h1 id="draft-detail-title">Yazar taslağı</h1>
      <p className="muted">
        <Link href={`/editorial/${id}`}>← İş öğesine dön</Link>
      </p>
      <SummarySection detail={detail} />
      <BodySection detail={detail} />
      <ClaimChainSection usages={detail.claim_usages} />
      <AuditSection detail={detail} />
      <AttemptsSection detail={detail} />
    </section>
  );
}
