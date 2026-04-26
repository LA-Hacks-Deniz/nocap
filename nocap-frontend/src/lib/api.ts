// Owner: DEVIN — Phase 3 task T3.31
//
// TanStack Query hooks against the Rust gateway at NEXT_PUBLIC_API_URL
// (default: https://api.nocap.wiki). Used by the dashboard at
// /dashboard and the trace detail page at /trace/[id].
//
// All endpoints round-trip JSON `{"error": "..."}` shapes for failures
// (T3.23 ApiError); we surface those as thrown Errors so the dashboard's
// error boundary / toast layer can catch + render them uniformly.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

// Browser fetches go through the Next.js auth-aware server proxy at
// /api/proxy/* (defined in app/api/proxy/[...path]/route.ts). The proxy
// validates the Auth0 session, attaches the user's access token as
// `Authorization: Bearer <jwt>`, and forwards to the Rust gateway at
// NOCAP_GATEWAY_URL. Override via NEXT_PUBLIC_API_URL only in tests / SSR.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api/proxy";

// ---------------------------------------------------------------------------
// Types — minimal shape the dashboard relies on; trace-detail consumes the
// full Mongo doc as a loosely-typed `Record<string, unknown>` since the
// schema includes nested per-strategy evidence + per-stage timings.
// ---------------------------------------------------------------------------

export type Verdict = "pass" | "anomaly" | "inconclusive" | string;

export interface TraceSummary {
  trace_id: string | null;
  arxiv_id: string | null;
  function_name: string | null;
  verdict: Verdict | null;
  confidence: number | null;
  paper_section: string | null;
  created_at: string | null;
}

export interface Evidence {
  kind?: string;
  equivalent?: boolean | null;
  residual?: string | null;
  mismatches?: unknown[] | null;
  method_used?: string | null;
  target_var?: string | null;
  critic_feedback?: string | null;
  critic_score?: number | null;
  judge_trigger?: string | null;
  // matchers may attach arbitrary metadata; allow it through.
  [key: string]: unknown;
}

export interface Claim {
  paper_section?: string | null;
  claimed_function?: string | null;
  claimed_equations?: unknown[] | null;
  [key: string]: unknown;
}

export interface VigilAuditEntry {
  role?: string;
  passed?: boolean;
  note?: string;
  [key: string]: unknown;
}

export interface TraceDoc {
  _id?: string;
  trace_id?: string;
  arxiv_id?: string;
  function_name?: string | null;
  verdict?: Verdict;
  confidence?: number;
  evidence_summary?: string;
  vigil_audit?: VigilAuditEntry[];
  claim?: Claim | null;
  strategies?: unknown[];
  evidences?: Evidence[];
  elapsed_seconds?: number;
  code_str?: string | null;
  stage_timings?: Record<string, number>;
  created_at?: string;
  error?: string | null;
  [key: string]: unknown;
}

export interface TraceFilters {
  verdict?: Verdict | null;
  arxivIdQuery?: string | null;
  // "24h" | "7d" | "all"
  range?: "24h" | "7d" | "all";
}

// ---------------------------------------------------------------------------
// Internal fetch helper — surfaces gateway error JSON as thrown Errors.
// ---------------------------------------------------------------------------

async function gatewayFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Accept": "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }
  if (!res.ok) {
    const msg =
      (payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : null) ??
      (typeof payload === "string" ? payload : null) ??
      `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return payload as T;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export interface UseTracesArgs {
  limit?: number;
  offset?: number;
  filters?: TraceFilters;
}

/**
 * Fetch the paginated trace summary list. Filters are applied client-side
 * because the gateway endpoint (T3.23) returns the full set sorted by
 * `created_at desc` — at hackathon volumes this is fine and keeps the
 * filter UI snappy without a network round-trip per keystroke.
 */
export function useTraces(
  args: UseTracesArgs = {},
): UseQueryResult<TraceSummary[], Error> & { filtered: TraceSummary[] } {
  const limit = args.limit ?? 50;
  const offset = args.offset ?? 0;
  const query = useQuery<TraceSummary[], Error>({
    queryKey: ["traces", { limit, offset }],
    queryFn: () =>
      gatewayFetch<TraceSummary[]>(`/api/traces?limit=${limit}&offset=${offset}`),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });

  const filtered = applyFilters(query.data ?? [], args.filters);
  return Object.assign(query, { filtered });
}

export function applyFilters(
  rows: TraceSummary[],
  filters?: TraceFilters,
): TraceSummary[] {
  if (!filters) return rows;
  const now = Date.now();
  const cutoff =
    filters.range === "24h"
      ? now - 24 * 60 * 60 * 1000
      : filters.range === "7d"
        ? now - 7 * 24 * 60 * 60 * 1000
        : null;

  return rows.filter((r) => {
    if (filters.verdict && filters.verdict !== "all" && r.verdict !== filters.verdict) {
      return false;
    }
    if (filters.arxivIdQuery && filters.arxivIdQuery.trim()) {
      const q = filters.arxivIdQuery.trim().toLowerCase();
      if (!(r.arxiv_id ?? "").toLowerCase().includes(q)) return false;
    }
    if (cutoff !== null) {
      const ts = r.created_at ? Date.parse(r.created_at) : NaN;
      if (!Number.isFinite(ts) || ts < cutoff) return false;
    }
    return true;
  });
}

export function useTrace(traceId: string | undefined): UseQueryResult<TraceDoc, Error> {
  return useQuery<TraceDoc, Error>({
    enabled: !!traceId,
    queryKey: ["trace", traceId],
    queryFn: () => gatewayFetch<TraceDoc>(`/api/traces/${encodeURIComponent(traceId!)}`),
    staleTime: 60_000,
  });
}

export interface ReplayResp {
  trace_id: string;
}

export function useReplay(): UseMutationResult<ReplayResp, Error, string> {
  const qc = useQueryClient();
  return useMutation<ReplayResp, Error, string>({
    mutationFn: (traceId) =>
      gatewayFetch<ReplayResp>(
        `/api/traces/${encodeURIComponent(traceId)}/replay`,
        { method: "POST", body: "{}" },
      ),
    onSuccess: () => {
      // The new trace lands in the list as soon as the orchestrator
      // finishes (~30s); proactively invalidate so the dashboard polls.
      qc.invalidateQueries({ queryKey: ["traces"] });
    },
  });
}

/** Stable URL for `react-pdf` to load an arXiv paper through the gateway proxy. */
export function getPdfUrl(arxivId: string): string {
  return `${API_BASE_URL}/api/papers/${encodeURIComponent(arxivId)}/pdf`;
}
