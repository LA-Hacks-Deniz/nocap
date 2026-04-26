"use client";

// Owner: DEVIN — Phase 3 task T3.30
//
// Trace detail page at nocap.wiki/trace/<trace_id>.
// Composes:
//   - sticky cap-emoji nav
//   - verdict header (uppercase tracked status badge + headline + confidence)
//   - inline summary row (arxiv link · paper section · function · trace_id
//     copy button · "Replay verification" mutation button)
//   - main grid:
//       * if `code_str` present → <PaperCodeViewer /> (paper | code) full-width
//         with <AnomalyPanel /> below
//       * else if anomaly with content → <PaperPaneStandalone /> + <AnomalyPanel />
//         side-by-side so the right column never sits empty
//       * else → <PaperCodeViewer /> with empty-state right pane
//   - <VigilAuditPanel />
//   - <TimingChart />
//   - collapsible <details> with raw evidences JSON

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { AnomalyPanel } from "@/components/trace/AnomalyPanel";
import { TimingChart } from "@/components/trace/TimingChart";
import { VigilAuditPanel } from "@/components/trace/VigilAuditPanel";
import { Badge } from "@/components/ui/badge";
import { useReplay, useTrace, type TraceDoc, type Verdict } from "@/lib/api";

// react-pdf hits `window` at module scope; keep the viewer client-only.
const PaperCodeViewer = dynamic(
  () =>
    import("@/components/trace/PaperCodeViewer").then((m) => m.PaperCodeViewer),
  {
    ssr: false,
    loading: () => (
      <div className="rounded-xl bg-card px-6 py-16 text-center text-sm text-muted-foreground ring-1 ring-foreground/10">
        Loading paper + code…
      </div>
    ),
  },
);

const PaperPaneStandalone = dynamic(
  () =>
    import("@/components/trace/PaperCodeViewer").then(
      (m) => m.PaperPaneStandalone,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="rounded-xl bg-card px-6 py-16 text-center text-sm text-muted-foreground ring-1 ring-foreground/10">
        Loading paper…
      </div>
    ),
  },
);

const VERDICT_HEADLINES: Record<string, string> = {
  pass: "Implementation matches paper",
  anomaly: "Anomaly detected",
  inconclusive: "Inconclusive",
};

const VERDICT_BADGE: Record<string, string> = {
  pass: "PASS",
  anomaly: "ANOMALY",
  inconclusive: "INCONCLUSIVE",
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
          <TraceDetailBody
            trace={trace}
            traceId={traceId}
            copied={copied}
            onCopy={async () => {
              if (traceId) {
                await navigator.clipboard.writeText(traceId);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }
            }}
            replayPending={replay.isPending}
            replayError={replay.error?.message ?? null}
            onReplay={() => {
              if (!traceId) return;
              replay.mutate(traceId, {
                onSuccess: (resp) => {
                  router.push(`/trace/${resp.trace_id}`);
                },
              });
            }}
          />
        )}
      </main>
    </div>
  );
}

function TraceDetailBody({
  trace,
  traceId,
  copied,
  onCopy,
  replayPending,
  replayError,
  onReplay,
}: {
  trace: TraceDoc;
  traceId: string | undefined;
  copied: boolean;
  onCopy: () => void;
  replayPending: boolean;
  replayError: string | null;
  onReplay: () => void;
}) {
  const verdict = trace.verdict ?? "inconclusive";
  const hasCode = (trace.code_str ?? "").trim().length > 0;
  const hasAnomalyContent =
    verdict === "anomaly" &&
    (trace.evidences ?? []).some(
      (e) =>
        e.equivalent === false &&
        ((typeof e.residual === "string" && e.residual.trim().length > 0) ||
          (typeof e.critic_feedback === "string" &&
            e.critic_feedback.trim().length > 0) ||
          (typeof e.target_var === "string" &&
            e.target_var.trim().length > 0)),
    );

  // Layout decision tree:
  //   1. code_str present  → full-width PaperCodeViewer + AnomalyPanel below
  //   2. anomaly content   → 2-col PaperPane + AnomalyPanel (no empty pane)
  //   3. otherwise         → PaperCodeViewer with built-in "no code" pane
  const sideBySideAnomaly = !hasCode && hasAnomalyContent;

  return (
    <>
      <VerdictHeader
        verdict={verdict}
        confidence={trace.confidence ?? null}
        summary={trace.evidence_summary ?? null}
      />

      <div className="flex flex-col gap-3 rounded-xl bg-card px-5 py-4 text-sm ring-1 ring-foreground/10 sm:flex-row sm:items-center sm:justify-between">
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
            onClick={onCopy}
            className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            {copied ? "Copied" : "Copy id"}
          </button>
        </div>
        <button
          type="button"
          disabled={!traceId || replayPending}
          onClick={onReplay}
          className="inline-flex items-center justify-center rounded-md border border-foreground bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {replayPending ? "Replaying…" : "Replay verification"}
        </button>
      </div>
      {replayError ? (
        <div className="text-sm text-muted-foreground">
          Replay failed: {replayError}
        </div>
      ) : null}

      {sideBySideAnomaly ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          <PaperPaneStandalone trace={trace} />
          <div className="space-y-4">
            <AnomalyPanel trace={trace} variant="compact" />
          </div>
        </div>
      ) : (
        <>
          <PaperCodeViewer trace={trace} />
          {verdict === "anomaly" ? <AnomalyPanel trace={trace} /> : null}
        </>
      )}

      <VigilAuditPanel trace={trace} />

      <TimingChart trace={trace} />

      <details className="rounded-xl bg-card p-5 ring-1 ring-foreground/10">
        <summary className="cursor-pointer text-sm font-medium text-foreground">
          Raw evidences
        </summary>
        <pre className="mt-3 max-h-[60vh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground">
          {JSON.stringify(trace.evidences ?? trace, null, 2)}
        </pre>
      </details>
    </>
  );
}

function Skeleton({ text }: { text: string }) {
  return (
    <div className="rounded-xl bg-card px-6 py-16 text-center text-sm text-muted-foreground ring-1 ring-foreground/10">
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
  const headline = VERDICT_HEADLINES[verdict] ?? verdict;
  const badge = VERDICT_BADGE[verdict] ?? verdict.toUpperCase();
  const confPct = confidence !== null ? `${Math.round(confidence * 100)}%` : "—";
  const confBold = confidence !== null && confidence > 0.8;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-2">
        <Badge
          variant="outline"
          className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground"
        >
          {badge}
        </Badge>
        <h1 className="text-3xl font-bold tracking-[-0.04em] sm:text-4xl">
          {headline}
        </h1>
        {summary ? (
          <p className="max-w-prose text-sm text-muted-foreground">{summary}</p>
        ) : null}
      </div>
      <div className="text-left sm:text-right">
        <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
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
      </div>
    </div>
  );
}
