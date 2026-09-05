"use server";

import { redirect } from "next/navigation";

import {
  PROVIDER_NAMES,
  syncTrendDiscovery,
  testIntegration,
  type ProviderName,
} from "@/lib/integrations-api";

// Two mutations on the integrations page: run a provider's single cheap
// connection test, and queue the Google Trends public-dataset discovery
// sync. The backend persists outcomes; secrets never travel through here.

export async function testIntegrationAction(formData: FormData): Promise<void> {
  const raw = formData.get("provider");
  const name = typeof raw === "string" ? raw.trim() : "";
  if (!(PROVIDER_NAMES as readonly string[]).includes(name)) {
    redirect("/entegrasyonlar?error=invalid");
  }
  const result = await testIntegration(name as ProviderName);
  if (result.kind !== "ok") {
    const code =
      result.kind === "not-found"
        ? "not-found"
        : result.kind === "unreachable"
          ? "unreachable"
          : "malformed";
    redirect(`/entegrasyonlar?error=${code}`);
  }
  redirect(
    `/entegrasyonlar?notice=test-${result.data.state}&provider=${result.data.name}`,
  );
}

export async function syncTrendDiscoveryAction(): Promise<void> {
  const result = await syncTrendDiscovery();
  if (result.kind !== "ok") {
    redirect(
      `/entegrasyonlar?error=${result.kind === "unreachable" ? "unreachable" : "malformed"}`,
    );
  }
  redirect(
    "/entegrasyonlar?notice=sync-queued&provider=google_trends_bigquery",
  );
}
