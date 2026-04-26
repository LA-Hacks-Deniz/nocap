"use client";

// Owner: DEVIN — Auth0 OAuth wiring
//
// Compact account header used by /dashboard. Renders the current user's
// avatar + email + a logout link, or a "Sign in" link when the session
// isn't loaded yet (the dashboard route is protected by middleware so
// `user` should always be set after the auth flow completes — the
// fallback only flashes during cold-cache hydration).

import { useUser } from "@auth0/nextjs-auth0/client";
import Link from "next/link";

export const ADMIN_EMAIL = "denizlapsekili@gmail.com";

export function isAdmin(email: string | null | undefined): boolean {
  return (email ?? "").toLowerCase() === ADMIN_EMAIL;
}

export function UserBadge() {
  const { user, isLoading } = useUser();

  if (isLoading) {
    return (
      <span className="text-xs text-muted-foreground">Loading…</span>
    );
  }

  if (!user) {
    return (
      <Link
        className="text-sm font-medium text-foreground transition-colors hover:text-muted-foreground"
        href="/api/auth/login"
      >
        Sign in
      </Link>
    );
  }

  const email = user.email ?? "";
  const admin = isAdmin(email);

  return (
    <div className="flex items-center gap-3">
      {user.picture ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="h-7 w-7 rounded-full border border-border bg-secondary object-cover"
          src={user.picture}
        />
      ) : (
        <div className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-secondary text-xs font-bold text-foreground">
          {(email || user.name || "?").slice(0, 1).toUpperCase()}
        </div>
      )}
      <div className="hidden flex-col leading-tight sm:flex">
        <span className="text-xs font-medium text-foreground">
          {email || user.name}
        </span>
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {admin ? "Admin · all traces" : "Viewer · latest 5"}
        </span>
      </div>
      <Link
        className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        href="/api/auth/logout"
      >
        Logout
      </Link>
    </div>
  );
}

