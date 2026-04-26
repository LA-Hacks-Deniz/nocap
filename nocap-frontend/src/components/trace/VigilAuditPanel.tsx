// Owner: DEVIN — Phase 3 task T3.30
//
// 3-role VIGIL audit summary block for the trace detail page.
// Each role line shows a check/cross glyph + role name + short note.
// Glyphs convey pass/fail (no color accents).

import type { TraceDoc, VigilAuditEntry } from "@/lib/api";

function passed(entry: VigilAuditEntry): boolean {
  if (typeof entry.passed === "boolean") return entry.passed;
  // Some emitters use {"ok": bool} or {"verdict": "pass"|"fail"}.
  const ok = (entry as { ok?: unknown }).ok;
  if (typeof ok === "boolean") return ok;
  const v = (entry as { verdict?: unknown }).verdict;
  if (typeof v === "string") return v.toLowerCase() === "pass";
  return false;
}

export function VigilAuditPanel({ trace }: { trace: TraceDoc }) {
  const audit = trace.vigil_audit ?? [];
  return (
    <div className="rounded-lg border border-border bg-background p-5">
      <h2 className="text-lg font-bold tracking-[-0.02em]">VIGIL audit</h2>
      {audit.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          No audit entries recorded.
        </p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm">
          {audit.map((e, i) => {
            const ok = passed(e);
            const role = (e.role as string | null) ?? `role ${i + 1}`;
            const note =
              (e.note as string | null) ??
              (e as { reason?: string }).reason ??
              "";
            return (
              <li key={i} className="flex items-start gap-3">
                <span aria-hidden className="mt-0.5 select-none font-bold text-foreground">
                  {ok ? "✓" : "✗"}
                </span>
                <div>
                  <span className="font-medium text-foreground">{role}</span>
                  {note ? (
                    <span className="text-muted-foreground"> — {note}</span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
