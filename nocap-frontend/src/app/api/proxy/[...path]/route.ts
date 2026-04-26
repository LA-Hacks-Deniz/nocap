// Owner: DEVIN — Auth0 OAuth wiring
//
// Server-side proxy that forwards browser requests to the Rust gateway
// at NOCAP_GATEWAY_URL after validating the Auth0 session cookie. The
// browser only ever sees relative URLs like `/api/proxy/api/traces?...`,
// so the gateway never has to be reached directly from the client.
//
// Authorisation tiering (per user direction):
//   - admin email (denizlapsekili@gmail.com)         → no caps; full pass-through
//   - any other authenticated user                    → list endpoint capped at 5
//   - unauthenticated                                 → 401 (also blocked by middleware)
//
// The Rust gateway intentionally has NO auth on its public API in the
// hackathon configuration; trust boundary is "anyone authenticated via
// Auth0 in the proxy can read traces". Tightening to JWT validation in
// Rust is a post-hackathon item.

import { getSession } from "@auth0/nextjs-auth0";
import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL =
  process.env.NOCAP_GATEWAY_URL ?? "https://api.nocap.wiki";

const ADMIN_EMAIL = "denizlapsekili@gmail.com";
const NON_ADMIN_LIST_CAP = 5;

const FORWARDED_REQUEST_HEADERS = new Set([
  "accept",
  "content-type",
  "user-agent",
]);

const FORWARDED_RESPONSE_HEADERS = new Set([
  "content-type",
  "content-length",
  "cache-control",
  "etag",
  "last-modified",
]);

function isAdmin(email: string | null | undefined): boolean {
  return (email ?? "").toLowerCase() === ADMIN_EMAIL;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const session = await getSession();
  if (!session?.user) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  const email = session.user.email ?? null;
  const admin = isAdmin(email);

  const { path } = await ctx.params;
  const joined = path.join("/");
  const target = new URL(`${GATEWAY_URL}/${joined}`);

  // Preserve query string, but enforce non-admin caps on the list route.
  for (const [k, v] of req.nextUrl.searchParams.entries()) {
    target.searchParams.append(k, v);
  }
  if (!admin && joined === "api/traces") {
    target.searchParams.set("limit", String(NON_ADMIN_LIST_CAP));
    target.searchParams.delete("offset");
  }

  const fwdHeaders = new Headers();
  for (const [k, v] of req.headers.entries()) {
    if (FORWARDED_REQUEST_HEADERS.has(k.toLowerCase())) {
      fwdHeaders.set(k, v);
    }
  }
  // Identity headers for the gateway's logs (no auth value attached;
  // gateway is unsecured but tagging requests with the proxied identity
  // makes the access log useful).
  if (email) fwdHeaders.set("X-NoCap-User-Email", email);
  fwdHeaders.set("X-NoCap-User-Tier", admin ? "admin" : "viewer");

  let body: BodyInit | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  const upstream = await fetch(target.toString(), {
    method: req.method,
    headers: fwdHeaders,
    body,
    redirect: "manual",
    cache: "no-store",
  });

  const respHeaders = new Headers();
  for (const [k, v] of upstream.headers.entries()) {
    if (FORWARDED_RESPONSE_HEADERS.has(k.toLowerCase())) {
      respHeaders.set(k, v);
    }
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
