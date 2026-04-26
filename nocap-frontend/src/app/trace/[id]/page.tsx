"use client";

// Owner: DEVIN — Phase 3 task T3.30
//
// Trace detail page at nocap.wiki/trace/<trace_id>.
// Composes:
//   - sticky cap-emoji nav
//   - verdict header (icon + headline + confidence)
//   - inline summary row (arxiv link · paper section · function · trace_id
//     copy button · "Replay verification" mutation button)
//   - <PaperCodeViewer />  (T3.25)
//   - <AnomalyPanel />     (only when verdict=anomaly)
//   - <VigilAuditPanel />  (3 roles)
//   - <TimingChart />      (T3.26)
//   - collapsible <details> with raw evidences JSON

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AnomalyPanel } from "@/components/trace/AnomalyPanel";
import { TimingChart } from "@/components/trace/TimingChart";
import { VigilAuditPanel } from "@/components/trace/VigilAuditPanel";
import { useReplay, useTrace, type Verdict } from "@/lib/api";

// react-pdf hits `window` at module scope; keep the viewer client-only.
const PaperCodeViewer = dynamic(
  () =>
    import("@/components/trace/PaperCodeViewer").then((m) => m.PaperCodeViewer),
  {
    ssr: false,
    loading: () => (
      <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
        Loading paper + code…
      </div>
    ),
  },
);

const VERDICT_GLYPHS: Record<string, string> = {
  pass: "🟢",
  anomaly: "🔴",
  inconclusive: "🟡",
};

const VERDICT_HEADLINES: Record<string, string> = {
  pass: "Implementation matches paper",
  anomaly: "Anomaly detected",
  inconclusive: "Inconclusive",
};

export default function TraceDetailPage() {
  const params = useParams<{ id: string }>();
  const traceId = params?.id;
  const router = useRouter();
  const { data: trace, error, isLoading } = useTrace(traceId);
  const replay = useReplay();
  const [copied, setCopied] = useState(false);

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
              className="transition-colors hover:text-foreground"
              href="/dashboard"
            >
              Dashboard
            </Link>
            <Link
              className="transition-colors hover:text-foreground"
              href="https://github.com/LA-Hacks-Deniz/nocap"
              rel="noreferrer"
              target="_blank"
            >
              GitHub
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-10 sm:px-8">
        {isLoading ? (
          <Skeleton text="Loading trace…" />
        ) : error ? (
          <Skeleton text={`Couldn't load trace: ${error.message}`} />
        ) : !trace ? (
          <Skeleton text="Trace not found." />
        ) : (
          <>
            <VerdictHeader
              verdict={trace.verdict ?? "inconclusive"}
              confidence={trace.confidence ?? null}
              summary={trace.evidence_summary ?? null}
            />

            <div className="flex flex-col gap-3 rounded-lg border border-border bg-background px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {trace.arxiv_id ? (
                  <a
                    href={`https://arxiv.org/abs/${trace.arxiv_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    arXiv:{trace.arxiv_id}
                  </a>
                ) : null}
                {trace.claim?.paper_section ? (
                  <span className="text-muted-foreground">
                    · {trace.claim.paper_section}
                  </span>
                ) : null}
                {trace.function_name ? (
                  <span className="font-mono text-xs text-muted-foreground">
                    · {trace.function_name}()
                  </span>
                ) : null}
                <span className="font-mono text-xs text-muted-foreground">
                  · {traceId}
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    if (traceId) {
                      await navigator.clipboard.writeText(traceId);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    }
                  }}
                  className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  {copied ? "Copied" : "Copy id"}
                </button>
              </div>
              <button
                type="button"
                disabled={!traceId || replay.isPending}
                onClick={() => {
                  if (!traceId) return;
                  replay.mutate(traceId, {
                    onSuccess: (resp) => {
                      router.push(`/trace/${resp.trace_id}`);
                    },
                  });
                }}
                className="inline-flex items-center justify-center rounded-md border border-foreground bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                {replay.isPending ? "Replaying…" : "Replay verification"}
              </button>
            </div>
            {replay.error ? (
              <div className="text-sm text-muted-foreground">
                Replay failed: {replay.error.message}
              </div>
            ) : null}

            <PaperCodeViewer trace={trace} />

            <AnomalyPanel trace={trace} />

            <VigilAuditPanel trace={trace} />

            <TimingChart trace={trace} />

            <details className="rounded-lg border border-border bg-background p-5">
              <summary className="cursor-pointer text-sm font-medium text-foreground">
                Raw evidences
              </summary>
              <pre className="mt-3 max-h-[60vh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
                {JSON.stringify(trace.evidences ?? trace, null, 2)}
              </pre>
            </details>
          </>
        )}
      </main>
    </div>
  );
}

function Skeleton({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

function VerdictHeader({
  verdict,
  confidence,
  summary,
}: {
  verdict: Verdict;
  confidence: number | null;
  summary: string | null;
}) {
  const glyph = VERDICT_GLYPHS[verdict] ?? "⚪";
  const headline = VERDICT_HEADLINES[verdict] ?? verdict;
  const confPct = confidence !== null ? `${Math.round(confidence * 100)}%` : "—";
  const confBold = confidence !== null && confidence > 0.8;

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <span aria-hidden className="text-3xl leading-none">
          {glyph}
        </span>
        <h1 className="text-3xl font-bold tracking-[-0.04em] sm:text-4xl">
          {headline}
        </h1>
      </div>
      <div className="text-right">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          Confidence
        </div>
        <div
          className={[
            "text-2xl tabular-nums tracking-[-0.02em] text-foreground",
            confBold ? "font-bold" : "font-medium",
          ].join(" ")}
        >
          {confPct}
        </div>
        {summary ? (
          <p className="mt-1 max-w-prose text-sm text-muted-foreground">
            {summary}
          </p>
        ) : null}
      </div>
    </div>
  );
}
