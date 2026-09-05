"use server";

import { redirect } from "next/navigation";

import {
  AUTOPILOT_MODES,
  setAutopilotMode,
  type AutopilotMode,
} from "@/lib/operations-api";

// The ONLY mutation on the live operations page: the autopilot mode. It is
// a named, reasoned decision recorded by the backend (ADR 0012); every
// other control stays on its governed surface.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function setAutopilotModeAction(
  formData: FormData,
): Promise<void> {
  const raw = field(formData, "mode");
  const reason = field(formData, "reason");
  if (!(AUTOPILOT_MODES as readonly string[]).includes(raw) || !reason) {
    redirect("/operasyon?error=invalid");
  }
  const result = await setAutopilotMode(raw as AutopilotMode, reason);
  if (result.kind !== "ok") {
    const code =
      result.kind === "invalid"
        ? "invalid"
        : result.kind === "queue_failed"
          ? "queue-failed"
          : result.kind === "unreachable"
            ? "unreachable"
            : "malformed";
    redirect(`/operasyon?error=${code}`);
  }
  redirect(`/operasyon?notice=mode-${result.data.mode}`);
}
