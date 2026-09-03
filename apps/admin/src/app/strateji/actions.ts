"use server";

import { redirect } from "next/navigation";

import { saveStrategy, STRATEGY_STATUSES } from "@/lib/strategy-api";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function common(formData: FormData) {
  const priority = Number(field(formData, "priority"));
  const rawStatus = field(formData, "status");
  const status = STRATEGY_STATUSES.includes(
    rawStatus as (typeof STRATEGY_STATUSES)[number],
  )
    ? rawStatus
    : "active";
  if (!Number.isInteger(priority) || priority < 0 || priority > 100) {
    redirect("/strateji?error=invalid");
  }
  return { priority, status, notes: field(formData, "notes") || null };
}

export async function saveAudienceAction(formData: FormData): Promise<void> {
  const name = field(formData, "name");
  const id = field(formData, "id") || undefined;
  if (
    !name ||
    !(await saveStrategy("audiences", { name, ...common(formData) }, id))
  ) {
    redirect("/strateji?error=save");
  }
  redirect("/strateji?notice=saved");
}

export async function saveClusterAction(formData: FormData): Promise<void> {
  const name = field(formData, "name");
  const id = field(formData, "id") || undefined;
  if (
    !name ||
    !(await saveStrategy("clusters", { name, ...common(formData) }, id))
  ) {
    redirect("/strateji?error=save");
  }
  redirect("/strateji?notice=saved");
}

export async function saveKeywordAction(formData: FormData): Promise<void> {
  const phrase = field(formData, "phrase");
  const id = field(formData, "id") || undefined;
  const topicClusterId = field(formData, "topic_cluster_id") || null;
  if (
    !phrase ||
    !(await saveStrategy(
      "keywords",
      {
        phrase,
        topic_cluster_id: topicClusterId,
        ...common(formData),
      },
      id,
    ))
  ) {
    redirect("/strateji?error=save");
  }
  redirect("/strateji?notice=saved");
}
