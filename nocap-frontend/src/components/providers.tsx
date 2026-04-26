"use client";

// Owner: DEVIN — Phase 3 task T3.31; Auth0 OAuth wiring adds <UserProvider>
//
// Client-side QueryClient + Auth0 UserProvider so the dashboard can read
// the current user via `useUser()` and TanStack Query hooks below this
// boundary share a single QueryClient.

import { UserProvider } from "@auth0/nextjs-auth0/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Hackathon traffic is tiny; one stale-while-refetch pass on
            // window focus is plenty.
            refetchOnWindowFocus: true,
            retry: 1,
          },
        },
      }),
  );
  return (
    <UserProvider>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </UserProvider>
  );
}
