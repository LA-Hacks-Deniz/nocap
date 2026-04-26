"use client";

// Owner: DEVIN — Phase 3 task T3.26
//
// Horizontal recharts bar chart of per-stage wall-clock (ms) for a
// trace doc. Stages come from `trace.stage_timings` (T3.24 plumbed
// these through the orchestrator), insertion-ordered:
//
//   paper_extract → spec → plan → code_extract → code[0:kind] … →
//   polygraph
//
// Grayscale only — bars in foreground (#1a1a1a), background #FAFAFA,
// axis labels #6B7280. No color accents, per Design System.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TraceDoc } from "@/lib/api";

const FG = "#1a1a1a";
const BG = "#fafafa";
const AXIS = "#6b7280";
const GRID = "#e5e7eb";

function shortStageLabel(name: string): string {
  // "code[2:adam]" → "code · adam"
  const m = name.match(/^code\[(\d+):([^\]]+)\]$/);
  if (m) return `code · ${m[2]}`;
  return name;
}

export function TimingChart({ trace }: { trace: TraceDoc }) {
  const timings = trace.stage_timings ?? {};
  const data = Object.entries(timings).map(([name, ms]) => ({
    name,
    label: shortStageLabel(name),
    ms: typeof ms === "number" ? ms : Number(ms) || 0,
  }));
  const total = trace.elapsed_seconds ?? null;

  const hasData = data.length > 0;

  return (
    <div className="rounded-lg border border-border bg-background p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-lg font-bold tracking-[-0.02em]">Timing</h2>
        {total !== null ? (
          <div className="text-sm text-muted-foreground">
            Wall clock:{" "}
            <span className="font-bold tabular-nums text-foreground">
              {total.toFixed(2)}s
            </span>
          </div>
        ) : null}
      </div>
      {hasData ? (
        <div className="h-[max(280px,var(--bar-height))]" style={{
          ["--bar-height" as string]: `${Math.max(280, data.length * 32 + 60)}px`,
        }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 8, right: 24, bottom: 8, left: 24 }}
              barCategoryGap={6}
            >
              <CartesianGrid stroke={GRID} horizontal={false} />
              <XAxis
                type="number"
                stroke={AXIS}
                tick={{ fill: AXIS, fontSize: 12 }}
                tickFormatter={(v) => `${v}ms`}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={140}
                stroke={AXIS}
                tick={{ fill: AXIS, fontSize: 12 }}
              />
              <Tooltip
                cursor={{ fill: GRID }}
                contentStyle={{
                  backgroundColor: BG,
                  border: `1px solid ${GRID}`,
                  borderRadius: 6,
                  color: FG,
                  fontSize: 12,
                }}
                formatter={(v) => [`${v} ms`, "stage"] as [string, string]}
                labelStyle={{ color: FG, fontWeight: 600 }}
              />
              <Bar dataKey="ms" fill={FG} radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border px-4 py-12 text-center text-sm text-muted-foreground">
          No per-stage timings recorded for this trace.
        </div>
      )}
    </div>
  );
}
