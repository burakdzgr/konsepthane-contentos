"use server";

import { redirect } from "next/navigation";

import {
  PAUSE_SCOPES,
  sendPauseCommand,
  type PauseScope,
} from "@/lib/dashboard-api";

// The ONLY mutations on the control center: audited intake pause/resume.
// Everything else on the page is read-only projection; workflow commands
// stay on their own governed surfaces.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function boundedScope(raw: string): PauseScope | null {
  return (PAUSE_SCOPES as readonly string[]).includes(raw)
    ? (raw as PauseScope)
    : null;
}

async function runPauseCommand(
  command: "pause" | "resume",
  formData: FormData,
): Promise<void> {
  const scope = boundedScope(field(formData, "scope"));
  const reason = field(formData, "reason");
  if (scope === null || !reason) {
    redirect("/kontrol?error=invalid");
  }
  const result = await sendPauseCommand(command, scope, reason);
  if (result.kind !== "ok") {
    const code =
      result.kind === "unreachable"
        ? "unreachable"
        : result.kind === "conflict"
          ? "conflict"
          : result.kind === "invalid"
            ? "invalid"
            : "malformed";
    redirect(`/kontrol?error=${code}`);
  }
  const notice = command === "pause" ? "durduruldu" : "devam";
  redirect(`/kontrol?notice=${notice}&scope=${scope}`);
}

export async function pauseIntakeAction(formData: FormData): Promise<void> {
  await runPauseCommand("pause", formData);
}

export async function resumeIntakeAction(formData: FormData): Promise<void> {
  await runPauseCommand("resume", formData);
}
