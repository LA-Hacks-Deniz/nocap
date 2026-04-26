// Owner: DEVIN — Auth0 OAuth wiring
//
// Next.js middleware: blocks unauthenticated access to /dashboard,
// /trace/*, and the /api/proxy/* routes. Anonymous visitors get
// redirected to /api/auth/login → Auth0 Universal Login → callback →
// /dashboard. Public routes (/, /api/auth/*) remain accessible.

import { withMiddlewareAuthRequired } from "@auth0/nextjs-auth0/edge";

export default withMiddlewareAuthRequired();

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/trace/:path*",
    "/api/proxy/:path*",
  ],
};
