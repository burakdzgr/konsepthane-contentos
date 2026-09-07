"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { saveDailyPlan } from "@/lib/bot-api";

export async function saveBotAction(form: FormData) {
  const target = Number(form.get("target"));
  const sources = form
    .getAll("sources")
    .filter((value): value is string => typeof value === "string");
  if (
    !Number.isInteger(target) ||
    target < 1 ||
    target > 50 ||
    sources.length === 0
  ) {
    redirect("/bot?error=invalid");
  }
  const enabled = form.get("intent") === "start";
  const result = await saveDailyPlan(target, sources, enabled);
  if (result.kind !== "ok") redirect(`/bot?error=${result.kind}`);
  revalidatePath("/bot");
  redirect(`/bot?saved=${enabled ? "started" : "paused"}`);
}
