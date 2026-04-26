// Owner: DEVIN — Phase 3 task T3.29
//
// Left sidebar list of trace "issues" for the split-pane dashboard.
//
// Each row is a verifiable, sortable trace summary card. The active row
// is highlighted via the secondary surface (#F5F5F5) plus a thin
// foreground accent strip on the left edge. Verdict is conveyed through
// icon shape (CircleX / CircleCheck / TriangleAlert) and uppercase
// severity text — no color accents, per Design System.

"use client";

import {
  CircleCheck,
  CircleX,
  ListFilter,
  Search,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { TraceSummary, Verdict } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VERDICT_LABELS: Record<string, string> = {
  pass: "Match",
  anomaly: "Mismatch",
  inconclusive: "Inconclusive",
};

const VERDICT_ICON = {
  pass: CircleCheck,
  anomaly: CircleX,
  inconclusive: TriangleAlert,
} as const;

function iconFor(verdict: string) {
  return VERDICT_ICON[verdict as keyof typeof VERDICT_ICON] ?? TriangleAlert;
}

export type Severity = "high" | "medium" | "low";

export function deriveSeverity(row: TraceSummary): Severity {
  const v = row.verdict ?? "inconclusive";
  const c = row.confidence ?? 0;
  if (v === "anomaly" && c > 0.8) return "high";
  if (v === "anomaly" && c > 0.5) return "medium";
  return "low";
}

const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
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

function issueTitle(row: TraceSummary): string {
  const fn = row.function_name ?? null;
  const v = row.verdict ?? "inconclusive";
  if (v === "anomaly") return fn ? `Anomaly in ${fn}()` : "Anomaly detected";
  if (v === "pass") return fn ? `${fn}() matches paper` : "Implementation matches";
  return fn ? `${fn}() — inconclusive` : "Inconclusive";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface IssueListProps {
  rows: TraceSummary[];
  selectedId: string | null;
  onSelect: (traceId: string) => void;
  search: string;
  onSearchChange: (q: string) => void;
  verdictFilter: "all" | Verdict;
  onVerdictFilterChange: (v: "all" | Verdict) => void;
  totalCount: number;
}

export function IssueList({
  rows,
  selectedId,
  onSelect,
  search,
  onSearchChange,
  verdictFilter,
  onVerdictFilterChange,
  totalCount,
}: IssueListProps) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-border bg-background lg:w-[360px] lg:border-r xl:w-[400px]">
      <div className="space-y-3 border-b border-border px-4 py-4">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search issues…"
            aria-label="Search issues"
            className="h-9 w-full rounded-md border border-border bg-secondary/40 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="flex items-center gap-2">
          <FilterChip
            label={
              verdictFilter === "all"
                ? `All issues (${totalCount})`
                : `${VERDICT_LABELS[verdictFilter] ?? verdictFilter} (${rows.length})`
            }
            value={verdictFilter}
            onChange={onVerdictFilterChange}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-muted-foreground">
            No issues match the current filter.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((row) => {
              const id = row.trace_id ?? "";
              const isSelected = id === selectedId;
              return (
                <li key={id || Math.random()}>
                  <IssueRow
                    row={row}
                    selected={isSelected}
                    onClick={() => id && onSelect(id)}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

function FilterChip({
  label,
  value,
  onChange,
}: {
  label: string;
  value: "all" | Verdict;
  onChange: (v: "all" | Verdict) => void;
}) {
  return (
    <label className="relative inline-flex items-center">
      <span className="pointer-events-none absolute left-3 flex h-full items-center text-muted-foreground">
        <ListFilter className="h-3.5 w-3.5" aria-hidden />
      </span>
      <select
        aria-label="Filter by verdict"
        value={value}
        onChange={(e) => onChange(e.target.value as "all" | Verdict)}
        className="h-8 appearance-none rounded-md border border-border bg-background pl-8 pr-3 text-xs font-medium text-foreground hover:bg-secondary focus:outline-none focus:ring-2 focus:ring-ring"
      >
        <option value="all">{label}</option>
        <option value="anomaly">Anomalies only</option>
        <option value="pass">Passes only</option>
        <option value="inconclusive">Inconclusive only</option>
      </select>
    </label>
  );
}

function IssueRow({
  row,
  selected,
  onClick,
}: {
  row: TraceSummary;
  selected: boolean;
  onClick: () => void;
}) {
  const verdict = row.verdict ?? "inconclusive";
  const Icon = iconFor(verdict);
  const severity = deriveSeverity(row);
  const title = issueTitle(row);

  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? "true" : undefined}
      className={[
        "group relative block w-full px-4 py-3 text-left transition-colors",
        selected
          ? "bg-secondary"
          : "bg-background hover:bg-secondary/60",
      ].join(" ")}
    >
      {selected ? (
        <span
          aria-hidden
          className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-sm bg-foreground"
        />
      ) : null}
      <div className="flex items-start gap-3">
        <Icon
          className="mt-0.5 h-4 w-4 shrink-0 text-foreground"
          strokeWidth={1.75}
          aria-hidden
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
              {title}
            </h3>
            <Badge
              variant="outline"
              className="shrink-0 text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
            >
              {SEVERITY_LABEL[severity]}
            </Badge>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {row.arxiv_id ? `arXiv:${row.arxiv_id}` : "(no arxiv id)"}
            {row.paper_section ? ` · ${row.paper_section}` : ""}
          </p>
          <p className="text-[11px] text-muted-foreground">
            {formatRelative(row.created_at)}
          </p>
        </div>
      </div>
    </button>
  );
}
