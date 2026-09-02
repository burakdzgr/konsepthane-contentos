import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/session-constants";

// Server-only session cookie access. The token lives in an HttpOnly cookie
// and never reaches browser JavaScript; outside a request scope (unit
// tests, build-time evaluation) the accessor degrades to "no session".

export { SESSION_COOKIE };

export async function getSessionToken(): Promise<string | null> {
  try {
    const store = await cookies();
    return store.get(SESSION_COOKIE)?.value ?? null;
  } catch {
    return null;
  }
}
