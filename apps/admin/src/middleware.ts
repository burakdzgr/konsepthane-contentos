import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session-constants";

// Phase 5 G2: every page requires the session cookie except the login page
// and the health route. Cookie PRESENCE gates navigation; the backend
// remains the authority — an expired/revoked token still 401s server-side
// and redirects back here.

const OPEN_PATHS = ["/login", "/api/health"];

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  if (
    OPEN_PATHS.some(
      (open) => pathname === open || pathname.startsWith(`${open}/`),
    )
  ) {
    return NextResponse.next();
  }
  if (request.cookies.get(SESSION_COOKIE) === undefined) {
    const login = new URL("/login", request.url);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
