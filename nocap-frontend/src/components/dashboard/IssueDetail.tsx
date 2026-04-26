// Owner: DEVIN — Phase 3 task T3.30
//
// Right pane of the split-pane dashboard. Shows the full detail of one
// selected trace, styled like an issue-tracker ticket:
//
//   - Verdict header (icon + label + headline + metadata row)
//   - "Issue Description" card  (trace.evidence_summary)
//   - "Code Location" card      (file path strip + syntax-highlighted code)
//   - "Research Paper" card     (arxiv link strip + abstract + embedded PDF)
//   - <AnomalyPanel /> if verdict=anomaly
//   - <VigilAuditPanel />
//   - <TimingChart />
//
// Mirrors the standalone /trace/[id] page but composed for the
// dashboard's split layout — header is inline, no separate nav bar.

"use client";

import {
  CircleCheck,
  CircleX,
  Clock,
  Code as CodeIcon,
  Copy,
  ExternalLink,
  FileText,
  TriangleAlert,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import oneLight from "react-syntax-highlighter/dist/esm/styles/prism/one-light";

import { AnomalyPanel } from "@/components/trace/AnomalyPanel";
import { TimingChart } from "@/components/trace/TimingChart";
import { VigilAuditPanel } from "@/components/trace/VigilAuditPanel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useReplay, useTrace, type TraceDoc, type Verdict } from "@/lib/api";

const PaperPaneStandalone = dynamic(
  () =>
    import("@/components/trace/PaperCodeViewer").then(
      (m) => m.PaperPaneStandalone,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[480px] items-center justify-center bg-secondary text-sm text-muted-foreground">
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

const VERDICT_LABEL: Record<string, string> = {
  pass: "Match",
  anomaly: "Mismatch",
  inconclusive: "Inconclusive",
};

const VERDICT_BADGE: Record<string, string> = {
  pass: "PASS",
  anomaly: "ANOMALY",
  inconclusive: "INCONCLUSIVE",
};

const VERDICT_ICON = {
  pass: CircleCheck,
  anomaly: CircleX,
  inconclusive: TriangleAlert,
} as const;

function iconFor(verdict: string) {
  return VERDICT_ICON[verdict as keyof typeof VERDICT_ICON] ?? TriangleAlert;
}

export function IssueDetail({ traceId }: { traceId: string | null }) {
  const router = useRouter();
  const { data: trace, error, isLoading } = useTrace(traceId ?? undefined);
  const replay = useReplay();
  const [copied, setCopied] = useState(false);

  if (!traceId) {
    return <EmptyDetail />;
  }
  if (isLoading) {
    return <SkeletonDetail text="Loading issue…" />;
  }
  if (error) {
    return <SkeletonDetail text={`Couldn't load trace: ${error.message}`} />;
  }
  if (!trace) {
    return <SkeletonDetail text="Trace not found." />;
  }

  return (
    <IssueDetailBody
      trace={trace}
      traceId={traceId}
      copied={copied}
      onCopy={async () => {
        await navigator.clipboard.writeText(traceId);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      replayPending={replay.isPending}
      replayError={replay.error?.message ?? null}
      onReplay={() => {
        replay.mutate(traceId, {
          onSuccess: (resp) => {
            router.push(`/dashboard?id=${resp.trace_id}`);
          },
        });
      }}
    />
  );
}

function IssueDetailBody({
  trace,
  traceId,
  copied,
  onCopy,
  replayPending,
  replayError,
  onReplay,
}: {
  trace: TraceDoc;
  traceId: string;
  copied: boolean;
  onCopy: () => void;
  replayPending: boolean;
  replayError: string | null;
  onReplay: () => void;
}) {
  const verdict: Verdict = trace.verdict ?? "inconclusive";
  const headline = VERDICT_HEADLINES[verdict] ?? verdict;
  const label = VERDICT_LABEL[verdict] ?? verdict;
  const badge = VERDICT_BADGE[verdict] ?? verdict.toUpperCase();
  const Icon = iconFor(verdict);
  const conf = trace.confidence ?? null;
  const confPct = conf !== null ? `${Math.round(conf * 100)}%` : "—";
  const confBold = conf !== null && conf > 0.8;

  const arxivId = trace.arxiv_id ?? null;
  const fnName = trace.function_name ?? null;
  const summary = trace.evidence_summary ?? null;
  const code = trace.code_str ?? "";
  const hasCode = code.trim().length > 0;
  const created = trace.created_at ?? null;

  return (
    <div className="space-y-6 px-6 py-6 sm:px-8">
      {/* Verdict header */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
          <Icon className="h-3.5 w-3.5 text-foreground" strokeWidth={2} aria-hidden />
          {label}
        </div>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground sm:text-3xl">
          {headline}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {created ? (
            <span className="inline-flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" aria-hidden />
              <FormattedDate iso={created} />
            </span>
          ) : null}
          {fnName ? (
            <span className="inline-flex items-center gap-1.5 font-mono">
              <CodeIcon className="h-3.5 w-3.5" aria-hidden />
              {fnName}()
            </span>
          ) : null}
          <Badge
            variant="outline"
            className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
          >
            {badge}
          </Badge>
          <span
            className={[
              "tabular-nums",
              confBold ? "font-bold text-foreground" : "text-muted-foreground",
            ].join(" ")}
          >
            confidence {confPct}
          </span>
        </div>
      </div>

      {/* Action row */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2.5 text-xs">
        <div className="flex items-center gap-3 text-muted-foreground">
          <span className="font-mono text-[11px]">{traceId}</span>
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 transition-colors hover:bg-secondary hover:text-foreground"
          >
            <Copy className="h-3 w-3" aria-hidden />
            {copied ? "Copied" : "Copy id"}
          </button>
          <Link
            href={`/trace/${traceId}`}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 transition-colors hover:bg-secondary hover:text-foreground"
          >
            <ExternalLink className="h-3 w-3" aria-hidden />
            Open standalone
          </Link>
        </div>
        <button
          type="button"
          disabled={replayPending}
          onClick={onReplay}
          className="inline-flex items-center justify-center rounded-md border border-foreground bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {replayPending ? "Replaying…" : "Replay verification"}
        </button>
      </div>
      {replayError ? (
        <div className="text-sm text-muted-foreground">
          Replay failed: {replayError}
        </div>
      ) : null}

      {/* Issue description */}
      {summary ? (
        <Card size="sm">
          <CardHeader className="pb-2">
            <h2 className="text-sm font-semibold text-foreground">
              Issue description
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed text-foreground">{summary}</p>
          </CardContent>
        </Card>
      ) : null}

      {/* Anomaly evidence */}
      {verdict === "anomaly" ? (
        <AnomalyPanel trace={trace} variant="compact" />
      ) : null}

      {/* Code Location */}
      {hasCode ? (
        <Card size="sm" className="overflow-hidden">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                <CodeIcon className="h-4 w-4" aria-hidden />
                Code location
              </h2>
              {fnName ? (
                <span className="font-mono text-xs text-muted-foreground">
                  {fnName}()
                </span>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="px-0 py-0">
            <div className="border-y border-border bg-secondary px-4 py-1.5 font-mono text-[11px] text-muted-foreground">
              {fnName ? `${fnName}.py` : "submission.py"}
            </div>
            <div className="max-h-[420px] overflow-auto bg-background text-sm">
              <SyntaxHighlighter
                language="python"
                style={oneLight}
                showLineNumbers
                customStyle={{
                  margin: 0,
                  padding: "1rem",
                  background: "transparent",
                  fontSize: "0.8rem",
                }}
              >
                {code}
              </SyntaxHighlighter>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Research paper */}
      <Card size="sm" className="overflow-hidden">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-3">
            <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
              <FileText className="h-4 w-4" aria-hidden />
              Research paper
            </h2>
            {arxivId ? (
              <a
                href={`https://arxiv.org/abs/${arxivId}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-foreground hover:underline"
              >
                Open in new tab
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="px-0 py-0">
          <div className="h-[640px] border-t border-border">
            <PaperPaneStandalone trace={trace} />
          </div>
        </CardContent>
      </Card>

      <VigilAuditPanel trace={trace} />

      <TimingChart trace={trace} />
    </div>
  );
}

function EmptyDetail() {
  return (
    <div className="flex h-full items-center justify-center px-6 py-16 text-center text-sm text-muted-foreground">
      Select an issue from the list to view its detail.
    </div>
  );
}

function SkeletonDetail({ text }: { text: string }) {
  return (
    <div className="px-6 py-16 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

function FormattedDate({ iso }: { iso: string }) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return <>{iso}</>;
  const d = new Date(t);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return (
    <>
      {yyyy}-{mm}-{dd} {hh}:{mi}
    </>
  );
}
