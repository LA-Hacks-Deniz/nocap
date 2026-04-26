// Owner: DEVIN — Auth0 OAuth wiring
//
// Auth0 Next.js SDK route handlers. This single file mounts:
//   GET /api/auth/login    → redirect to Auth0 Universal Login
//   GET /api/auth/callback → exchange code for tokens, set session cookie
//   GET /api/auth/logout   → clear session, redirect to AUTH0_BASE_URL
//   GET /api/auth/me       → current user JSON (used by <UserProvider>)

import { handleAuth, handleLogin } from "@auth0/nextjs-auth0";

// No `audience` is requested: the gateway is unsecured in this
// hackathon configuration (per user direction) and authorisation is
// enforced in the Next.js proxy layer based on the session cookie.
// Adding `audience` later (with a custom Auth0 API) would yield a
// JWT-format access token suitable for direct gateway validation.
export const GET = handleAuth({
  login: handleLogin({
    authorizationParams: {
      scope: "openid profile email",
    },
    returnTo: "/dashboard",
  }),
});
