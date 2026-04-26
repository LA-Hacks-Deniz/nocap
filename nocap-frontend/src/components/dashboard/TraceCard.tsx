// Owner: DEVIN — Phase 3 task T3.29
//
// Single trace card on the dashboard grid. Click anywhere on the card →
// /trace/<trace_id>. Hover lifts via the secondary surface (#F5F5F5) per
// Design System; verdict is conveyed by an uppercase tracked badge +
// Inter Bold weight, not by glyph or color.

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import type { TraceSummary } from "@/lib/api";

const VERDICT_LABELS: Record<string, string> = {
  pass: "Implementation matches",
  anomaly: "Anomaly detected",
  inconclusive: "Inconclusive",
};

const VERDICT_BADGE: Record<string, string> = {
  pass: "PASS",
  anomaly: "ANOMALY",
  inconclusive: "INCONCLUSIVE",
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
  const label = VERDICT_LABELS[verdict] ?? verdict;
  const badge = VERDICT_BADGE[verdict] ?? verdict.toUpperCase();
  const conf = trace.confidence ?? null;
  const confPct = conf !== null ? `${Math.round(conf * 100)}%` : "—";
  const confBold = conf !== null && conf > 0.8;

  const href = trace.trace_id ? `/trace/${trace.trace_id}` : "#";

  return (
    <Link
      href={href}
      className="group block h-full transition-transform hover:-translate-y-0.5"
    >
      <Card className="h-full justify-between gap-3 transition-colors group-hover:bg-secondary">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <Badge
                variant="outline"
                className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
              >
                {badge}
              </Badge>
              <div className="text-base font-bold tracking-[-0.02em] text-foreground">
                {label}
              </div>
            </div>
            <span
              className={[
                "shrink-0 text-sm tabular-nums",
                confBold
                  ? "font-bold text-foreground"
                  : "font-medium text-muted-foreground",
              ].join(" ")}
            >
              {confPct}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-1.5">
          <div className="text-sm text-foreground">
            <span className="font-medium">
              {trace.arxiv_id ?? "(unknown paper)"}
            </span>
            {trace.paper_section ? (
              <span className="text-muted-foreground">
                {" · "}
                {trace.paper_section}
              </span>
            ) : null}
          </div>
          {trace.function_name ? (
            <div className="font-mono text-xs text-muted-foreground">
              {trace.function_name}
            </div>
          ) : null}
        </CardContent>
        <CardFooter className="border-t bg-transparent pt-3">
          <div className="flex w-full items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {formatRelative(trace.created_at)}
            </span>
            <span className="text-sm font-medium text-foreground transition-transform group-hover:translate-x-0.5">
              View issue →
            </span>
          </div>
        </CardFooter>
      </Card>
    </Link>
  );
}
