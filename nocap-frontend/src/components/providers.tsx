"use client";

// Owner: DEVIN — Phase 3 task T3.31
//
// Client-side QueryClient provider so server components in app/ can
// import this single boundary and consume `useTraces` / `useTrace` /
// `useReplay` further down the tree.

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
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
