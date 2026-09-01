import type {
  PipelineDetail,
  PipelineListItem,
  PipelineListPage,
  SourceListItem,
  SourceListPage,
} from "@/lib/research-api";

export const ITEM_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0";
export const SOURCE_ID = "11111111-2222-4333-8444-555555555555";
export const SNAPSHOT_ID = "21111111-2222-4333-8444-555555555555";
export const DOCUMENT_ID = "31111111-2222-4333-8444-555555555555";

export function sourceItem(
  overrides: Partial<SourceListItem> = {},
): SourceListItem {
  return {
    id: SOURCE_ID,
    slug: "ornek-kaynak",
    name: "Örnek Kaynak",
    kind: "manual",
    locale: "tr-TR",
    market: "TR",
    lifecycle_state: "active",
    trust_tier: "general",
    discovery_strategy: "manual",
    base_url: "https://ornek.example.test",
    created_at: "2026-09-01T09:00:00+00:00",
    updated_at: "2026-09-01T10:00:00+00:00",
    total_discovery_items: 4,
    discovered_count: 1,
    accepted_count: 1,
    fetched_count: 1,
    fetch_failed_count: 1,
    rejected_count: 0,
    ...overrides,
  };
}

export function sourcePage(
  items: SourceListItem[],
  overrides: Partial<SourceListPage> = {},
): SourceListPage {
  return { items, total: items.length, limit: 50, offset: 0, ...overrides };
}

export function pipelineItem(
  overrides: Partial<PipelineListItem> = {},
): PipelineListItem {
  return {
    id: ITEM_ID,
    source_id: SOURCE_ID,
    source_slug: "ornek-kaynak",
    source_name: "Örnek Kaynak",
    canonical_url: "https://ornek.example.test/haber/uzun-baslik",
    discovery_method: "manual",
    lifecycle_state: "fetched",
    rejection_reason: null,
    discovered_at: "2026-09-01T12:00:00+00:00",
    last_seen_at: "2026-09-01T12:30:00+00:00",
    external_published_at: null,
    fetch_snapshot_id: SNAPSHOT_ID,
    fetch_outcome: "success",
    fetched_at: "2026-09-01T12:05:00+00:00",
    status_code: 200,
    retry_classification: "not_applicable",
    normalized_document_id: DOCUMENT_ID,
    normalization_status: "succeeded",
    normalization_failure_code: null,
    normalized_at: "2026-09-01T12:06:00+00:00",
    duplicate_decision_id: "41111111-2222-4333-8444-555555555555",
    duplicate_outcome: "unique",
    duplicate_evaluated_at: "2026-09-01T12:07:00+00:00",
    evidence_count: 2,
    latest_evidence_at: "2026-09-01T12:08:00+00:00",
    ...overrides,
  };
}

export function pipelinePage(
  items: PipelineListItem[],
  overrides: Partial<PipelineListPage> = {},
): PipelineListPage {
  return { items, total: items.length, limit: 50, offset: 0, ...overrides };
}

export function pipelineDetail(
  overrides: Partial<PipelineDetail> = {},
): PipelineDetail {
  return {
    source: {
      id: SOURCE_ID,
      slug: "ornek-kaynak",
      name: "Örnek Kaynak",
      kind: "manual",
      locale: "tr-TR",
      market: "TR",
      lifecycle_state: "active",
      trust_tier: "general",
      discovery_strategy: "manual",
      base_url: "https://ornek.example.test",
    },
    discovery_item: {
      id: ITEM_ID,
      source_id: SOURCE_ID,
      discovered_url:
        "https://ornek.example.test/haber/uzun-baslik?utm_source=x",
      canonical_url: "https://ornek.example.test/haber/uzun-baslik",
      discovery_method: "manual",
      lifecycle_state: "fetched",
      rejection_reason: null,
      rejection_note: null,
      title_hint: "Uzun Başlık",
      locale: "tr-TR",
      external_published_at: "2026-08-30T09:30:00+00:00",
      discovered_at: "2026-09-01T12:00:00+00:00",
      last_seen_at: "2026-09-01T12:30:00+00:00",
      created_at: "2026-09-01T12:00:00+00:00",
      updated_at: "2026-09-01T12:30:00+00:00",
    },
    fetch_attempts: [
      {
        id: SNAPSHOT_ID,
        fetch_outcome: "success",
        retry_classification: "not_applicable",
        robots_decision: "allowed",
        status_code: 200,
        content_type: "text/html; charset=utf-8",
        body_size_bytes: 2048,
        duration_ms: 41.5,
        failure_detail: null,
        fetched_at: "2026-09-01T12:05:00+00:00",
      },
    ],
    total_fetch_attempts: 1,
    fetch_attempts_truncated: false,
    normalization_attempts: [
      {
        id: DOCUMENT_ID,
        fetch_snapshot_id: SNAPSHOT_ID,
        normalization_status: "succeeded",
        extractor_name: "html-basic",
        extractor_version: "1",
        parser_version: null,
        failure_code: null,
        failure_detail: null,
        title: "İstanbul Rehberi",
        author_name: "Ayşe Yılmaz",
        external_published_at: "2026-08-30T09:30:00+00:00",
        normalized_at: "2026-09-01T12:06:00+00:00",
      },
    ],
    total_normalization_attempts: 1,
    normalization_attempts_truncated: false,
    duplicate_decisions: [
      {
        id: "41111111-2222-4333-8444-555555555555",
        normalized_document_id: DOCUMENT_ID,
        engine_name: "duplicate-engine",
        engine_version: "1",
        decision: "unique",
        rationale_codes: ["no_candidates"],
        match_count: 0,
        evaluated_at: "2026-09-01T12:07:00+00:00",
      },
    ],
    total_duplicate_decisions: 1,
    duplicate_decisions_truncated: false,
    evidence: {
      total: 2,
      by_verification_status: { unverified: 2 },
      by_evidence_type: { observation: 2 },
      latest_extracted_at: "2026-09-01T12:08:00+00:00",
    },
    ...overrides,
  };
}
