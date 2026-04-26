"use client";

// Owner: DEVIN — Phase 3 task T3.28
//
// Split-pane dashboard at nocap.wiki/dashboard.
//
//   ┌──────────── header (cap-emoji nav) ────────────┐
//   │                                                 │
//   │  ┌── IssueList ──┐  ┌── IssueDetail ─────────┐ │
//   │  │ search        │  │ verdict header         │ │
//   │  │ filter chip   │  │ issue description card │ │
//   │  │ row 1 (sel)   │  │ anomaly evidence       │ │
//   │  │ row 2         │  │ code location          │ │
//   │  │ row 3         │  │ research paper + PDF   │ │
//   │  │ ...           │  │ vigil audit / timing   │ │
//   │  └───────────────┘  └────────────────────────┘ │
//   └─────────────────────────────────────────────────┘
//
// URL: /dashboard?id=<trace_id> — deep links into a specific issue.
// First load with no `id` query param auto-selects the most recent
// trace in the filtered list.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { IssueDetail } from "@/components/dashboard/IssueDetail";
import { IssueList } from "@/components/dashboard/IssueList";
import { useTraces, type TraceFilters, type Verdict } from "@/lib/api";

const NAV_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
  { href: "https://devpost.com/", label: "Devpost" },
];

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center bg-background text-sm text-muted-foreground">
          Loading dashboard…
        </div>
      }
    >
      <DashboardInner />
    </Suspense>
  );
}

function DashboardInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedId = searchParams.get("id");

  const [verdictFilter, setVerdictFilter] = useState<"all" | Verdict>("all");
  const [search, setSearch] = useState("");

  const filters: TraceFilters = useMemo(
    () => ({
      verdict: verdictFilter === "all" ? null : verdictFilter,
      arxivIdQuery: null,
      range: "all",
    }),
    [verdictFilter],
  );

  const { data, error, isLoading, filtered } = useTraces({
    limit: 200,
    filters,
  });

  // Apply free-text search on top of the verdict-filtered set.
  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return filtered;
    return filtered.filter((r) => {
      return (
        (r.arxiv_id ?? "").toLowerCase().includes(q) ||
        (r.function_name ?? "").toLowerCase().includes(q) ||
        (r.paper_section ?? "").toLowerCase().includes(q) ||
        (r.verdict ?? "").toLowerCase().includes(q) ||
        (r.trace_id ?? "").toLowerCase().includes(q)
      );
    });
  }, [filtered, search]);

  // Auto-select the first row if the URL has no id (or the id no longer
  // appears in the filtered list).
  useEffect(() => {
    if (visibleRows.length === 0) return;
    const ids = new Set(visibleRows.map((r) => r.trace_id ?? ""));
    if (!selectedId || !ids.has(selectedId)) {
      const first = visibleRows[0]?.trace_id;
      if (first) {
        router.replace(`/dashboard?id=${first}`, { scroll: false });
      }
    }
  }, [visibleRows, selectedId, router]);

  const onSelect = (id: string) => {
    router.replace(`/dashboard?id=${id}`, { scroll: false });
  };

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-background/92 backdrop-blur-md">
        <div className="flex items-center justify-between px-6 py-4 sm:px-8">
          <div className="flex items-center gap-6">
            <Link
              aria-label="NoCap home"
              className="select-none text-2xl leading-none"
              href="/"
            >
              🧢
            </Link>
            <div className="hidden flex-col leading-tight sm:flex">
              <span className="text-sm font-bold tracking-[-0.01em] text-foreground">
                Research paper validator
              </span>
              <span className="text-xs text-muted-foreground">
                Compare implementations against research paper specifications
              </span>
            </div>
          </div>
          <nav className="flex items-center gap-5 text-sm text-muted-foreground">
            <Link className="font-medium text-foreground" href="/dashboard">
              Dashboard
            </Link>
            {NAV_LINKS.map((link) => (
              <Link
                key={link.label}
                className="transition-colors hover:text-foreground"
                href={link.href}
                rel="noreferrer"
                target="_blank"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {isLoading ? (
          <div className="flex flex-1 items-center justify-center px-6 py-16 text-sm text-muted-foreground">
            Loading verifications…
          </div>
        ) : error ? (
          <div className="flex flex-1 items-center justify-center px-6 py-16 text-sm text-muted-foreground">
            Couldn&apos;t reach the gateway: {error.message}
          </div>
        ) : (data ?? []).length === 0 ? (
          <EmptyDashboard />
        ) : (
          <>
            <IssueList
              rows={visibleRows}
              selectedId={selectedId}
              onSelect={onSelect}
              search={search}
              onSearchChange={setSearch}
              verdictFilter={verdictFilter}
              onVerdictFilterChange={setVerdictFilter}
              totalCount={(data ?? []).length}
            />
            <section className="min-h-0 flex-1 overflow-y-auto bg-background">
              <IssueDetail traceId={selectedId} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function EmptyDashboard() {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-16 text-center text-sm text-muted-foreground">
      No verifications yet — try{" "}
      <code className="mx-1 rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
        /nocap verify-impl
      </code>{" "}
      in Slack.
    </div>
  );
}
