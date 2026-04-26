"use client";

// Owner: DEVIN — Phase 3 task T3.30
//
// Per-failing-evidence anomaly panel for the trace detail page.
// Renders the symbolic residual via KaTeX on a dark #1a1a1a surface
// (the ONE allowed dark surface, per Design System) and the Critic's
// natural-language feedback in italic underneath.

import { BlockMath } from "react-katex";

import type { Evidence, TraceDoc } from "@/lib/api";

function failingEvidences(trace: TraceDoc): Evidence[] {
  return (trace.evidences ?? []).filter((e) => e.equivalent === false);
}

export function AnomalyPanel({ trace }: { trace: TraceDoc }) {
  const failing = failingEvidences(trace);
  if (trace.verdict !== "anomaly") return null;
  if (failing.length === 0) return null;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold tracking-[-0.02em]">
        Anomaly evidence
      </h2>
      {failing.map((ev, i) => (
        <EvidenceCard key={i} ev={ev} />
      ))}
    </div>
  );
}

function EvidenceCard({ ev }: { ev: Evidence }) {
  const residual = typeof ev.residual === "string" ? ev.residual : null;
  const targetVar = (ev.target_var as string | null) ?? null;
  const kind = (ev.kind as string | null) ?? "?";
  const method = (ev.method_used as string | null) ?? null;
  const critic = (ev.critic_feedback as string | null) ?? null;

  return (
    <div className="rounded-lg border border-border bg-background">
      <div className="flex items-center justify-between border-b border-border px-5 py-3 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-bold">{kind}</span>
          {method ? (
            <span className="text-muted-foreground">· {method}</span>
          ) : null}
        </div>
        {targetVar ? (
          <span className="font-mono text-xs text-muted-foreground">
            target_var = {targetVar}
          </span>
        ) : null}
      </div>

      <div className="space-y-4 p-5">
        {residual ? (
          <div className="rounded-md bg-[#1a1a1a] px-5 py-6 text-[#fafafa]">
            <div className="mb-2 text-xs uppercase tracking-wider text-[#9ca3af]">
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
      </div>
    </div>
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
