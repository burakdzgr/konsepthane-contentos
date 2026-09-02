"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { loginBackend, logoutBackend } from "@/lib/auth-api";
import { SESSION_COOKIE, getSessionToken } from "@/lib/session";

// Login/logout server actions. The token from the backend goes straight
// into the HttpOnly cookie and is never rendered or logged.

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function loginAction(formData: FormData): Promise<void> {
  const username = field(formData, "username");
  const password = formData.get("password");
  if (!username || typeof password !== "string" || password.length === 0) {
    redirect("/login?error=invalid");
  }
  const result = await loginBackend(username, password);
  if (result.kind === "invalid_credentials") {
    redirect("/login?error=invalid");
  }
  if (result.kind !== "ok") {
    redirect("/login?error=unreachable");
  }
  const store = await cookies();
  store.set(SESSION_COOKIE, result.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    expires: new Date(result.expiresAt),
  });
  redirect("/");
}

export async function logoutAction(): Promise<void> {
  const token = await getSessionToken();
  if (token !== null) {
    // Best effort: revoke server-side; the cookie is cleared regardless.
    await logoutBackend();
  }
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  redirect("/login?notice=logged-out");
}
