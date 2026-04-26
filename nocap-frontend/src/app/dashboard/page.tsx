"use client";

// Owner: DEVIN — Phase 3 task T3.28
//
// Public dashboard at nocap.wiki/dashboard.
//
// Layout: sticky cap-emoji nav → "All verifications" header → 4-card
// stats row → filter bar → responsive 3-col grid of <TraceCard />.
// Stats are derived from the FILTERED list so the user can scope
// "Anomalies caught" to e.g. last 24h.

import Link from "next/link";
import { useMemo, useState } from "react";

import { TraceCard } from "@/components/dashboard/TraceCard";
import { useTraces, type TraceFilters, type Verdict } from "@/lib/api";

const NAV_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
  { href: "https://devpost.com/", label: "Devpost" },
];

const VERDICT_OPTIONS: { value: "all" | Verdict; label: string }[] = [
  { value: "all", label: "All verdicts" },
  { value: "pass", label: "Pass" },
  { value: "anomaly", label: "Anomaly" },
  { value: "inconclusive", label: "Inconclusive" },
];

const RANGE_OPTIONS: { value: NonNullable<TraceFilters["range"]>; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7 days" },
];

function StatsRow({ rows }: { rows: ReturnType<typeof useTraces>["filtered"] }) {
  const total = rows.length;
  const anomalies = rows.filter((r) => r.verdict === "anomaly").length;
  const passes = rows.filter((r) => r.verdict === "pass").length;
  const ratable = rows.filter((r) => r.verdict === "pass" || r.verdict === "anomaly").length;
  const passRate = ratable > 0 ? `${Math.round((passes / ratable) * 100)}%` : "—";
  // The summary endpoint omits elapsed_seconds; show "—" until full doc loads.
  // (TraceSummary intentionally stays minimal; T3.26 surfaces per-stage timing
  // on the trace detail page where the full doc is available.)
  const avgWall = "—";

  const cards = [
    { label: "Total checks", value: String(total) },
    { label: "Anomalies caught", value: String(anomalies) },
    { label: "Pass rate", value: passRate },
    { label: "Avg wall clock", value: avgWall },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-lg border border-border bg-background px-5 py-4"
        >
          <div className="text-xs text-muted-foreground">{c.label}</div>
          <div className="mt-1 text-2xl font-bold tabular-nums tracking-[-0.02em] text-foreground">
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [verdict, setVerdict] = useState<"all" | Verdict>("all");
  const [arxivIdQuery, setArxivIdQuery] = useState("");
  const [range, setRange] = useState<NonNullable<TraceFilters["range"]>>("all");

  const filters: TraceFilters = useMemo(
    () => ({
      verdict: verdict === "all" ? null : verdict,
      arxivIdQuery,
      range,
    }),
    [verdict, arxivIdQuery, range],
  );

  const { data, error, isLoading, filtered } = useTraces({ limit: 200, filters });

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-background/92 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5 sm:px-8">
          <Link
            aria-label="NoCap home"
            className="select-none text-2xl leading-none"
            href="/"
          >
            🧢
          </Link>
          <nav className="flex items-center gap-5 text-sm text-muted-foreground">
            <Link
              className="font-medium text-foreground"
              href="/dashboard"
            >
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

      <main className="mx-auto max-w-7xl px-6 py-10 sm:px-8">
        <h1 className="text-3xl font-bold tracking-[-0.04em] sm:text-4xl">
          All verifications
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Every paper-vs-code check the council has run, newest first.
        </p>

        <div className="mt-8">
          <StatsRow rows={filtered} />
        </div>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <select
            aria-label="Verdict filter"
            value={verdict}
            onChange={(e) => setVerdict(e.target.value as "all" | Verdict)}
            className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {VERDICT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            aria-label="Filter by arXiv ID"
            placeholder="Filter by arXiv ID, e.g. 1412.6980"
            value={arxivIdQuery}
            onChange={(e) => setArxivIdQuery(e.target.value)}
            className="h-10 flex-1 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <select
            aria-label="Date range filter"
            value={range}
            onChange={(e) =>
              setRange(e.target.value as NonNullable<TraceFilters["range"]>)
            }
            className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {RANGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <section className="mt-8">
          {isLoading ? (
            <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
              Loading verifications…
            </div>
          ) : error ? (
            <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
              Couldn&apos;t reach the gateway: {error.message}
            </div>
          ) : (data ?? []).length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
              No verifications yet — try{" "}
              <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
                /nocap verify-impl
              </code>{" "}
              in Slack.
            </div>
          ) : filtered.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
              No verifications match the current filters.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filtered.map((row) => (
                <TraceCard key={row.trace_id ?? Math.random()} trace={row} />
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
