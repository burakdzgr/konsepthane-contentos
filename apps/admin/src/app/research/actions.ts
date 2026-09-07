"use server";

import { redirect } from "next/navigation";

import { createMission, runMission } from "@/lib/missions-api";

const field = (data: FormData, name: string) =>
  String(data.get(name) ?? "").trim();

export async function createMissionAction(data: FormData): Promise<void> {
  const created = await createMission({
    topic: field(data, "topic"),
    goal: field(data, "goal"),
    audience: field(data, "audience"),
    seed_keyword: field(data, "seed_keyword") || null,
    topic_cluster_id: field(data, "topic_cluster_id") || null,
  });
  if (!created) redirect("/research?error=create");
  redirect(`/research/${created.id}${created.queued ? "" : "?error=queue"}`);
}

export async function rerunMissionAction(data: FormData): Promise<void> {
  const id = field(data, "id");
  if (!id || !(await runMission(id))) redirect(`/research/${id}?error=run`);
  redirect(`/research/${id}`);
}
