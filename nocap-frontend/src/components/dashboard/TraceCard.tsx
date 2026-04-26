// Owner: DEVIN — Phase 3 task T3.29
//
// Single trace card on the dashboard grid. Click anywhere on the card →
// /trace/<trace_id>. Hover lifts via the secondary surface (#F5F5F5) per
// Design System; verdict is conveyed by glyph + Inter Bold weight, not
// by color (no accent colors anywhere).

import Link from "next/link";

import type { TraceSummary } from "@/lib/api";

const VERDICT_GLYPHS: Record<string, string> = {
  pass: "🟢",
  anomaly: "🔴",
  inconclusive: "🟡",
};

const VERDICT_LABELS: Record<string, string> = {
  pass: "Implementation matches",
  anomaly: "Anomaly detected",
  inconclusive: "Inconclusive",
};

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const diff = Date.now() - t;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} hr ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d} day${d === 1 ? "" : "s"} ago`;
  return new Date(t).toLocaleDateString();
}

export function TraceCard({ trace }: { trace: TraceSummary }) {
  const verdict = trace.verdict ?? "inconclusive";
  const glyph = VERDICT_GLYPHS[verdict] ?? "⚪";
  const label = VERDICT_LABELS[verdict] ?? verdict;
  const conf = trace.confidence ?? null;
  const confPct = conf !== null ? `${Math.round(conf * 100)}%` : "—";
  const confBold = conf !== null && conf > 0.8;

  const href = trace.trace_id ? `/trace/${trace.trace_id}` : "#";

  return (
    <Link
      href={href}
      className="group flex h-full flex-col justify-between gap-4 rounded-lg border border-border bg-background p-5 transition-colors hover:bg-secondary"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span aria-hidden className="text-base leading-none">
            {glyph}
          </span>
          <span className="text-base font-bold tracking-[-0.02em] text-foreground">
            {label}
          </span>
        </div>
        <span
          className={[
            "shrink-0 text-sm tabular-nums text-muted-foreground",
            confBold ? "font-bold text-foreground" : "font-medium",
          ].join(" ")}
        >
          {confPct}
        </span>
      </div>

      <div className="space-y-1.5">
        <div className="text-sm text-foreground">
          <span className="font-medium">{trace.arxiv_id ?? "(unknown paper)"}</span>
          {trace.paper_section ? (
            <span className="text-muted-foreground"> · {trace.paper_section}</span>
          ) : null}
        </div>
        {trace.function_name ? (
          <div className="font-mono text-xs text-muted-foreground">
            {trace.function_name}
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between border-t border-border pt-3">
        <span className="text-xs text-muted-foreground">
          {formatRelative(trace.created_at)}
        </span>
        <span className="text-sm font-medium text-foreground">
          View issue →
        </span>
      </div>
    </Link>
  );
}
