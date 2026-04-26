"use client";

// Owner: DEVIN — Phase 3 task T3.30
//
// Per-failing-evidence anomaly panel for the trace detail page.
// Renders the symbolic residual via KaTeX on a dark #1a1a1a surface
// (the ONE allowed dark surface, per Design System) and the Critic's
// natural-language feedback in italic underneath.
//
// Empty failed evidences (e.g. `kind=symbolic, method_used=failed` with
// no residual / critic_feedback / target_var) are suppressed — they
// add noise without conveying anything.

import { BlockMath } from "react-katex";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { Evidence, TraceDoc } from "@/lib/api";

function hasContent(ev: Evidence): boolean {
  const residual = typeof ev.residual === "string" && ev.residual.trim().length > 0;
  const critic =
    typeof ev.critic_feedback === "string" && ev.critic_feedback.trim().length > 0;
  const target =
    typeof ev.target_var === "string" && ev.target_var.trim().length > 0;
  return residual || critic || target;
}

function failingEvidences(trace: TraceDoc): Evidence[] {
  return (trace.evidences ?? []).filter(
    (e) => e.equivalent === false && hasContent(e),
  );
}

export function AnomalyPanel({
  trace,
  variant = "stack",
}: {
  trace: TraceDoc;
  variant?: "stack" | "compact";
}) {
  const failing = failingEvidences(trace);
  if (trace.verdict !== "anomaly") return null;
  if (failing.length === 0) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-bold tracking-[-0.02em]">
          Anomaly evidence
        </h2>
        <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
          {failing.length} {failing.length === 1 ? "finding" : "findings"}
        </span>
      </div>
      <div className="space-y-3">
        {failing.map((ev, i) => (
          <EvidenceCard key={i} ev={ev} compact={variant === "compact"} />
        ))}
      </div>
    </div>
  );
}

function EvidenceCard({ ev, compact }: { ev: Evidence; compact: boolean }) {
  const residual = typeof ev.residual === "string" ? ev.residual : null;
  const targetVar = (ev.target_var as string | null) ?? null;
  const kind = (ev.kind as string | null) ?? "?";
  const method = (ev.method_used as string | null) ?? null;
  const critic = (ev.critic_feedback as string | null) ?? null;

  return (
    <Card size="sm" className="gap-3">
      <CardHeader className="border-b pb-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="text-[10px] uppercase tracking-[0.12em]"
            >
              {kind}
            </Badge>
            {method ? (
              <span className="text-xs text-muted-foreground">
                via {method}
              </span>
            ) : null}
          </div>
          {targetVar ? (
            <span className="font-mono text-xs text-muted-foreground">
              target_var = {targetVar}
            </span>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className={compact ? "space-y-3" : "space-y-4"}>
        {residual ? (
          <div className="rounded-md bg-[#1a1a1a] px-5 py-5 text-[#fafafa]">
            <div className="mb-2 text-[10px] uppercase tracking-[0.16em] text-[#9ca3af]">
              Residual
            </div>
            <ResidualMath src={residual} />
          </div>
        ) : null}

        {critic ? (
          <p className="border-l-2 border-foreground pl-4 text-sm italic text-muted-foreground">
            {critic}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ResidualMath({ src }: { src: string }) {
  // The orchestrator stores residuals as raw TeX or a SymPy `srepr`.
  // BlockMath handles TeX; on parse failure we fall back to a <pre>.
  try {
    return (
      <div className="overflow-x-auto text-base">
        <BlockMath math={src} />
      </div>
    );
  } catch {
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-sm">
        {src}
      </pre>
    );
  }
}
