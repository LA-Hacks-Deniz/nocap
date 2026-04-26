"use client";

// Owner: DEVIN — Phase 3 task T3.25
//
// Side-by-side paper-vs-code viewer for the trace detail page.
//
//   ┌─ header strip (arxiv link · paper section · function name) ─┐
//   │                                                              │
//   │  ┌─────────────── paper PDF (react-pdf) ───────────────┐    │
//   │  │ scrollable, paginated; fetched via gateway proxy at │    │
//   │  │ /api/papers/<arxiv_id>/pdf to dodge arxiv CORS      │    │
//   │  └─────────────────────────────────────────────────────┘    │
//   │  ┌────────── code (react-syntax-highlighter) ──────────┐    │
//   │  │ Python; buggy line highlighted by scanning code_str │    │
//   │  │ for the failing evidence's target_var assignment    │    │
//   │  └─────────────────────────────────────────────────────┘    │
//   └──────────────────────────────────────────────────────────────┘
//
// Stacks vertically on mobile (< md), 50/50 on desktop. Atom One Light
// theme matches the Design System (warm off-white surface, near-black
// text, no color accents).
//
// react-pdf needs its worker registered via a Next-friendly URL so
// Turbopack can bundle it; we pin to pdfjs-dist's `pdf.worker.min.mjs`.

import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
// Atom One Light from highlight.js styles — closest match to the
// "warm off-white, near-black" palette the rest of the dashboard uses.
import oneLight from "react-syntax-highlighter/dist/esm/styles/prism/one-light";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import { getPdfUrl, type Evidence, type TraceDoc } from "@/lib/api";

if (typeof window !== "undefined") {
  // Bundled worker via pdfjs-dist; resolved relative to this module so
  // Turbopack/Webpack can ship it as a static asset.
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).toString();
}

function pickFailingEvidence(evidences: Evidence[] | undefined): Evidence | null {
  if (!evidences || evidences.length === 0) return null;
  const failing = evidences.find((e) => e.equivalent === false);
  if (failing) return failing;
  return evidences[0] ?? null;
}

/**
 * Best-effort: scan `code_str` for an assignment of `target_var` and
 * return the 1-based line number. Falls back to null if not found.
 */
function findBuggyLine(code: string, targetVar: string | null | undefined): number | null {
  if (!targetVar) return null;
  const lines = code.split("\n");
  // Match `target_var =` (with possible spaces, indices, dots stripped).
  const stem = targetVar.split(/[.[(]/, 1)[0]?.trim();
  if (!stem) return null;
  const re = new RegExp(`(^|[^A-Za-z0-9_])${escapeReg(stem)}\\s*[+\\-*/%]?=`);
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) return i + 1;
  }
  return null;
}

function escapeReg(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function PaperCodeViewer({ trace }: { trace: TraceDoc }) {
  const arxivId = trace.arxiv_id ?? "";
  const code = trace.code_str ?? "";
  const claim = trace.claim ?? null;
  const paperSection =
    (claim && (claim as { paper_section?: string | null }).paper_section) ?? null;
  const fnName = trace.function_name ?? null;

  const failing = pickFailingEvidence(trace.evidences);
  const buggyLine = useMemo(
    () => findBuggyLine(code, (failing?.target_var as string | null) ?? null),
    [code, failing?.target_var],
  );

  return (
    <div className="rounded-lg border border-border bg-background">
      <div className="flex flex-col gap-1 border-b border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-sm">
          {arxivId ? (
            <a
              href={`https://arxiv.org/abs/${arxivId}`}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              arXiv:{arxivId}
            </a>
          ) : (
            <span className="text-muted-foreground">no arxiv id</span>
          )}
          {paperSection ? (
            <span className="text-muted-foreground"> · {paperSection}</span>
          ) : null}
        </div>
        {fnName ? (
          <div className="font-mono text-xs text-muted-foreground">
            {fnName}()
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2">
        <div className="border-b border-border md:border-b-0 md:border-r">
          <PaperPane arxivId={arxivId} sectionHint={paperSection} />
        </div>
        <div>
          <CodePane code={code} buggyLine={buggyLine} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PaperPane — react-pdf <Document>/<Page> driver
// ---------------------------------------------------------------------------

function PaperPane({
  arxivId,
  sectionHint,
}: {
  arxivId: string;
  sectionHint: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState<number>(420);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 420;
      setWidth(Math.max(280, Math.floor(w)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Best-effort scroll-to-section: search the rendered text layer for the
  // section header text and scroll the matching page into view.
  useEffect(() => {
    if (!sectionHint || !numPages) return;
    const t = setTimeout(() => {
      const root = containerRef.current;
      if (!root) return;
      const needle = sectionHint.toLowerCase();
      const candidates = root.querySelectorAll("[data-page-number]");
      for (const node of Array.from(candidates) as HTMLElement[]) {
        const text = node.innerText.toLowerCase();
        if (text.includes(needle)) {
          node.scrollIntoView({ block: "start", behavior: "smooth" });
          return;
        }
      }
    }, 800);
    return () => clearTimeout(t);
  }, [sectionHint, numPages]);

  if (!arxivId) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center bg-secondary p-6 text-center text-sm text-muted-foreground">
        No arxiv_id on this trace.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="max-h-[calc(100dvh-12rem)] overflow-y-auto bg-secondary"
    >
      {error ? (
        <div className="p-6 text-sm text-muted-foreground">
          Failed to load paper PDF: {error}
        </div>
      ) : (
        <Document
          file={getPdfUrl(arxivId)}
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          onLoadError={(e) => setError(e.message)}
          loading={
            <div className="p-6 text-sm text-muted-foreground">Loading paper…</div>
          }
        >
          {numPages !== null
            ? Array.from({ length: numPages }, (_, i) => (
                <div
                  key={i}
                  data-page-number={i + 1}
                  className="flex justify-center border-b border-border bg-background"
                >
                  <Page
                    pageNumber={i + 1}
                    width={width}
                    renderAnnotationLayer
                    renderTextLayer
                  />
                </div>
              ))
            : null}
        </Document>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CodePane — Prism via react-syntax-highlighter, buggy line highlighted
// ---------------------------------------------------------------------------

function CodePane({
  code,
  buggyLine,
}: {
  code: string;
  buggyLine: number | null;
}) {
  if (!code) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center p-6 text-center text-sm text-muted-foreground">
        No <code className="font-mono">code_str</code> persisted on this trace
        (pre-T3.24).
      </div>
    );
  }

  return (
    <div className="max-h-[calc(100dvh-12rem)] overflow-auto bg-background text-sm">
      <SyntaxHighlighter
        language="python"
        style={oneLight}
        showLineNumbers
        wrapLines
        lineProps={(lineNumber: number) =>
          buggyLine === lineNumber
            ? {
                style: {
                  display: "block",
                  backgroundColor: "#f5f5f5",
                  borderLeft: "3px solid #1a1a1a",
                  fontWeight: 600,
                },
              }
            : { style: { display: "block" } }
        }
        customStyle={{
          margin: 0,
          padding: "1rem",
          background: "transparent",
          fontSize: "0.85rem",
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
