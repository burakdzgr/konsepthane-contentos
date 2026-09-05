import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// External intelligence providers (Semrush, Search Console, GA4, Google
// Trends, Pinterest Trends): the status board and the per-provider
// connection test. The backend never returns secrets — only states, a
// Turkish detail sentence, bounded error classes and the NAMES of the
// environment variables the operator has to set.

export const PROVIDER_NAMES = [
  "semrush",
  "google_search_console",
  "google_analytics",
  "google_trends",
  "pinterest_trends",
] as const;
export type ProviderName = (typeof PROVIDER_NAMES)[number];

export const PROVIDER_STATES = [
  "healthy",
  "not_configured",
  "access_required",
  "rate_limited",
  "degraded",
  "error",
] as const;
export type ProviderState = (typeof PROVIDER_STATES)[number];

export const PROVIDER_STATE_LABELS: Record<ProviderState, string> = {
  healthy: "Bağlı",
  not_configured: "Yapılandırılmadı",
  access_required: "API erişimi gerekli",
  rate_limited: "Kota sınırında",
  degraded: "Kısıtlı",
  error: "Hata",
};

export const UNVERIFIED_LABEL = "Henüz doğrulanmadı";

export const PROVIDER_STATE_TONES: Record<ProviderState, string> = {
  healthy: "ok",
  not_configured: "neutral",
  access_required: "warn",
  rate_limited: "warn",
  degraded: "warn",
  error: "bad",
};

// Short Turkish hints per provider: WHERE the value comes from, never the
// value itself.
export const PROVIDER_HINTS: Record<ProviderName, string> = {
  semrush:
    "Semrush hesap ayarlarındaki API anahtarını CONTENTOS_SEMRUSH_API_KEY olarak tanımlayın; veritabanı için CONTENTOS_SEMRUSH_DATABASE (varsayılan tr).",
  google_search_console:
    "Google Cloud servis hesabı anahtarını (JSON içeriği ya da dosya yolu) CONTENTOS_GOOGLE_SERVICE_ACCOUNT_JSON, mülk adresini CONTENTOS_GSC_SITE_URL olarak tanımlayın; servis hesabını Search Console mülküne Tam/Kısıtlı yetkiyle ekleyin.",
  google_analytics:
    "Aynı servis hesabına GA4 mülkünde Görüntüleyici rolü verin; mülk kimliğini CONTENTOS_GA4_PROPERTY_ID, varsa anahtar olayları CONTENTOS_GA4_KEY_EVENTS (virgülle) olarak tanımlayın.",
  google_trends:
    "Resmi Google Trends API alfa/izinli erişimi gerekir: CONTENTOS_GOOGLE_TRENDS_API_KEY (gerekirse CONTENTOS_GOOGLE_TRENDS_API_URL). trends.google.com asla kazınmaz.",
  pinterest_trends:
    "Pinterest geliştirici uygulamasından trends:read kapsamlı erişim belirtecini CONTENTOS_PINTEREST_ACCESS_TOKEN olarak tanımlayın; bölge CONTENTOS_PINTEREST_REGION (varsayılan TR).",
};

const integrationSchema = z.object({
  name: z.enum(PROVIDER_NAMES),
  display_name: z.string().min(1),
  purpose: z.string(),
  configured: z.boolean(),
  verified: z.boolean(),
  state: z.enum(PROVIDER_STATES),
  detail: z.string(),
  checked_at: z.string(),
  last_success_at: z.string().nullable(),
  last_error_class: z.string().nullable(),
  freshness: z.string().nullable(),
  daily_budget: z.number().int().nonnegative(),
  requests_today: z.number().int().nonnegative(),
  cache_hours: z.number().int().nonnegative(),
  required_env: z.array(z.string()),
  optional_env: z.array(z.string()),
});

const integrationsSchema = z.object({
  generated_at: z.string(),
  providers: z.array(integrationSchema),
});

export type IntegrationView = z.infer<typeof integrationSchema>;
export type IntegrationsBoard = z.infer<typeof integrationsSchema>;

export async function fetchIntegrations(): Promise<
  BackendResult<IntegrationsBoard>
> {
  const response = await requestBackend("/internal/integrations");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, integrationsSchema, [200]);
}

export type TestIntegrationResult =
  | { kind: "ok"; data: IntegrationView }
  | { kind: "not-found" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

export async function testIntegration(
  name: ProviderName,
): Promise<TestIntegrationResult> {
  const response = await requestBackend(`/internal/integrations/${name}/test`, {
    method: "POST",
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 404) {
    return { kind: "not-found" };
  }
  const parsed = await parseBackendResponse(response, integrationSchema, [200]);
  if (parsed.kind !== "ok") {
    return parsed;
  }
  return { kind: "ok", data: parsed.data };
}
