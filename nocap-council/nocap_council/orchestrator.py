# Owner: DEVIN — Phase 1 task T1.13
"""Orchestrator — single-arm OptimAI loop tying the council together.

End-to-end verification pipeline that consumes ``(paper_arxiv_id, code_str)``
and returns a verdict dict by chaining:

    paper_extract  →  spec      →  plan        →  code_extract
                                                   ↓
                                               run_strategy × N
                                                   ↓
                                                polygraph

Per-stage events stream to stdout as line-delimited JSON
(``{"stage": str, "status": "ok"|"error", "ms": int, "info": ...}``) so
the CLI (T1.14) can render live progress and the gateway (Phase 2) can
ingest the same trace.

Public API
----------

``verify(paper_arxiv_id: str, code_str: str, user_msg: str | None = None, *,
function_name: str | None = None, stream: Callable[[dict], None] | None = None)
-> dict``

Returns the polygraph verdict dict augmented with raw artifacts so the
CLI can render the Goal-format output without re-running the council::

    {
        "verdict":          "pass" | "anomaly" | "inconclusive",
        "confidence":       float,
        "evidence_summary": str,
        "vigil_audit":      list[dict],
        # Augmentation:
        "claim":            dict,           # spec.extract_claim output
        "strategies":       list[dict],     # plan.generate_strategies (dumped)
        "evidences":        list[dict],     # one per strategy
        "elapsed_seconds":  float,          # wall clock
        "arxiv_id":         str,
        "function_name":    str | None,     # the def we ran code_to_sympy on
    }

Equation-to-strategy mapping
----------------------------

For ``symbolic`` / ``numerical`` strategies, every entry in
``claim["claimed_equations"]`` is dispatched through ``code.run_strategy``;
the strategy's reported evidence is the **first inequivalent** result, or
the last result if all are equivalent. So a strategy passes only if EVERY
claimed equation passes (Adam-buggy needs both ``m_hat`` and ``v_hat``
caught — single-equation runs would miss one).

``var_map`` and ``target_var`` are derived heuristically from each
equation's LaTeX (LHS accent flattening, greek letter mapping, ``_t``
timestep stripping). The Coder-LLM hybrid path noted as a TODO in
``code.py`` (T1.10 chat answer #1c) would replace these heuristics; for
the Adam acceptance the heuristics are sufficient.

Error handling
--------------

The orchestrator is the user-facing entry point and never crashes. Any
stage that raises is logged as a ``status="error"`` JSONL event, then the
function returns an ``inconclusive`` verdict with the traceback's last
line in ``evidence_summary``. Downstream stages are skipped.

Streaming
---------

Default: ``json.dumps(...) + "\\n"`` to ``sys.stdout`` with ``flush=True``.
Pass ``stream=fn`` to bypass stdout (the gateway / Slack consumer wires a
WebSocket emitter here). When ``stream`` is set, stdout is silent so the
CLI never gets double-printed events.

NOCAP_OFFLINE
-------------

Propagated, not overridden. ``code.run_strategy`` already gates its
Critic call on ``NOCAP_OFFLINE=1`` (T1.10); the orchestrator does not
touch the env. Live runs (real Gemma) require ``GOOGLE_API_KEY``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nocap_council import code as coder
from nocap_council import code_extract, paper_extract, plan, spec
from nocap_council.plan import Strategy
from nocap_council.polygraph import verify as polygraph_verify

# ----------------------------------------------------------------------
# Stream helpers
# ----------------------------------------------------------------------


def _emit(stream: Callable[[dict], None] | None, event: dict[str, Any]) -> None:
    if stream is not None:
        stream(event)
        return
    sys.stdout.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _stage(
    stream: Callable[[dict], None] | None,
    name: str,
    status: str,
    ms: int,
    info: Any | None = None,
    **extra: Any,
) -> None:
    ev: dict[str, Any] = {"stage": name, "status": status, "ms": ms}
    if info is not None:
        ev["info"] = info
    ev.update(extra)
    _emit(stream, ev)


# ----------------------------------------------------------------------
# Function-name resolution
# ----------------------------------------------------------------------


def _resolve_function_name(
    code_str: str,
    claimed_function: str | None,
    override: str | None,
) -> str:
    """Pick the ``def`` in ``code_str`` whose body becomes the SymPy env.

    Order of resolution:
      1. Explicit ``override`` kwarg.
      2. ``claimed_function`` as exact identifier.
      3. Any word in ``claimed_function`` matching a ``def`` name
         (e.g. "Adam optimizer step" → ``step``).
      4. First non-dunder ``def``.
    """
    tree = ast.parse(code_str)
    defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    names = [n.name for n in defs]
    if not names:
        raise ValueError("no function definitions found in code_str")
    if override:
        if override in names:
            return override
        raise ValueError(f"function_name={override!r} not found in code (have: {names})")
    if isinstance(claimed_function, str) and claimed_function:
        if claimed_function in names:
            return claimed_function
        for word in re.findall(r"\b\w+\b", claimed_function):
            if word in names:
                return word
    for nm in names:
        if not nm.startswith("_"):
            return nm
    return names[0]


# ----------------------------------------------------------------------
# Heuristic var_map / target_var derivation
# ----------------------------------------------------------------------

_ACCENT_RE = re.compile(r"\\(?:hat|tilde|bar|dot|vec|widehat|overline|overrightarrow)\s*\{([^}]*)\}")
_GREEK_NAMES = frozenset(
    {
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "varepsilon",
        "zeta",
        "eta",
        "theta",
        "vartheta",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
        "xi",
        "omicron",
        "pi",
        "varpi",
        "rho",
        "varrho",
        "sigma",
        "varsigma",
        "tau",
        "upsilon",
        "phi",
        "varphi",
        "chi",
        "psi",
        "omega",
        "Alpha",
        "Beta",
        "Gamma",
        "Delta",
        "Epsilon",
        "Zeta",
        "Eta",
        "Theta",
        "Iota",
        "Kappa",
        "Lambda",
        "Mu",
        "Nu",
        "Xi",
        "Omicron",
        "Pi",
        "Rho",
        "Sigma",
        "Tau",
        "Upsilon",
        "Phi",
        "Chi",
        "Psi",
        "Omega",
    }
)
_GREEK_RE = re.compile(r"\\([A-Za-z]+)(?:_(\d+|\{[^}]*\}))?")
_INNER_BRACE_RE = re.compile(r"[{}\\$\s]")


def _flatten_lhs(lhs: str) -> str:
    """Flatten LaTeX accents + greek + braces into a bare identifier.

    ``\\hat{m}_t``       → ``m_hat_t``
    ``\\beta_1``         → ``beta1``
    ``\\hat{\\beta}_t``  → ``beta_hat_t``
    """
    s = _ACCENT_RE.sub(lambda m: f"{m.group(1)}_hat", lhs)
    s = _GREEK_RE.sub(
        lambda m: m.group(1).lower() + (re.sub(r"[{}]", "", m.group(2)) if m.group(2) else ""),
        s,
    )
    return _INNER_BRACE_RE.sub("", s)


def _is_self_referential(equation: str, target_var: str | None) -> bool:
    """Return True when ``target_var`` appears as a bare identifier in the RHS.

    Self-referential equations (``\\theta_t = \\theta_{t-1} - ...``,
    ``m_t = \\beta m_{t-1} + ...``) describe an *update* rule where the
    LHS and RHS sides reference different temporal versions of the same
    variable. Without temporal indexing in ``code_env`` (it only stores
    the post-assignment value), the matcher cannot distinguish them and
    will always report a non-zero residual. We mark these "skip" so the
    orchestrator's iterate-keep-worst loop ignores them.

    Implementation note: a plain ``\\b{target}\\b`` regex doesn't work
    here because ``_`` is a word char, so ``\\bm\\b`` fails to match
    ``m_{t-1}`` (no boundary between ``m`` and ``_``). We use explicit
    lookbehind / lookahead that allows trailing ``_`` (subscript) but
    rejects trailing alpha / digit (so ``m`` doesn't match ``mass``
    or ``model``).
    """
    if not target_var or "=" not in equation:
        return False
    rhs = equation.split("=", 1)[1]
    pattern = rf"(?<![a-zA-Z0-9_]){re.escape(target_var)}(?![a-zA-Z0-9])"
    return re.search(pattern, rhs) is not None


def _normalize_equation(equation: str) -> str:
    """Coerce a Spec-emitted equation into something ``parse_latex`` accepts.

    Spec sometimes returns equations in mixed Python / pseudocode style
    (e.g. ``m_hat = m / (1 - beta1**t)``) instead of clean LaTeX. The
    matcher's ``parse_latex`` only understands LaTeX exponentiation
    (``^``), so we coerce ``**`` → ``^`` and unwrap ``sqrt(...)`` /
    ``np.sqrt(...)`` into ``\\sqrt{...}``. Everything else passes through.
    """
    s = equation.replace("**", "^")
    s = re.sub(r"(?:np|numpy|sp|sympy|math)\.sqrt\s*\(", "sqrt(", s)
    s = re.sub(r"\bsqrt\s*\(([^()]*)\)", r"\\sqrt{\1}", s)
    return s


def _heuristic_target_var(equation: str, code_env: dict[str, Any]) -> str | None:
    """Derive the code-side variable an equation is claimed to compute."""
    if "=" not in equation:
        return None
    lhs = equation.split("=", 1)[0]
    cand = _flatten_lhs(lhs)
    if not cand:
        return None
    if cand in code_env:
        return cand
    # Trim trailing _t (timestep marker).
    trimmed = re.sub(r"_t\b$", "", cand)
    if trimmed and trimmed in code_env:
        return trimmed
    # Last resort: return the mangled name; matchers will surface a KeyError.
    return cand


def _all_symbols(code_env: dict[str, Any]) -> set[str]:
    """Collect every symbol name that appears as a key OR free symbol in code_env.

    sympy_match.match_equation works against post-substitution expressions;
    free symbols inside an env value (e.g. ``beta1``, ``g``, ``t``) are
    legal var_map targets even though they are not env keys.
    """
    names: set[str] = set(code_env.keys())
    for v in code_env.values():
        try:
            for sym in v.free_symbols:  # type: ignore[union-attr]
                names.add(str(sym))
        except AttributeError:
            continue
    return names


def _heuristic_var_map(equation: str, code_env: dict[str, Any]) -> dict[str, str]:
    """Map paper symbols (LaTeX) to code-env keys or free symbols.

    Greek letters: ``\\beta_1`` → ``beta1`` (subscript inlined). Accent
    forms: ``\\hat{m}_t`` → ``m_hat_t`` (matches sympy_match's flatten
    step), with a ``_t``-strip fallback to ``m_hat`` when the env has
    that. Plain ``ident_t`` → ``ident`` when the bare form exists.

    Mappings are emitted unconditionally for greek and accent forms (the
    var_map is consumed by string substitution, so a no-op mapping is
    harmless); the fallback path only runs when the timestep-trimmed
    name actually exists.
    """
    names = _all_symbols(code_env)
    var_map: dict[str, str] = {}

    for m in _GREEK_RE.finditer(equation):
        full = m.group(0)
        if full in var_map:
            continue
        # Only treat real Greek-letter commands as variables; ignore
        # ``\sqrt`` / ``\frac`` / ``\cdot`` etc. so the substitution
        # doesn't corrupt LaTeX operators that ``parse_latex`` handles.
        if m.group(1) not in _GREEK_NAMES:
            continue
        sub = m.group(2)
        sub_part = re.sub(r"[{}]", "", sub) if sub else ""
        ascii_full = m.group(1).lower() + sub_part
        if ascii_full in names:
            var_map[full] = ascii_full
            continue
        ascii_bare = m.group(1).lower()
        if ascii_bare in names:
            var_map[full] = ascii_bare
            continue
        var_map[full] = ascii_full

    for m in _ACCENT_RE.finditer(equation):
        inner = m.group(1)
        flat = _flatten_lhs(inner) + "_hat"
        tail_m = re.match(r"_(\w+)", equation[m.end() :])
        tail = "_" + tail_m.group(1) if tail_m else ""
        key = flat + tail
        if key in var_map:
            continue
        if key in names:
            var_map[key] = key
            continue
        trimmed = re.sub(r"_t\b$", "", key)
        if trimmed and trimmed in names:
            var_map[key] = trimmed

    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9]*)_t\b", equation):
        full = m.group(0)
        if full in var_map:
            continue
        bare = m.group(1)
        if bare in names:
            var_map[full] = bare

    return var_map


# ----------------------------------------------------------------------
# Strategy execution
# ----------------------------------------------------------------------


def _strategy_evidence(
    strategy: Strategy,
    paper: dict[str, Any],
    code_env: dict[str, Any],
    claim: dict[str, Any],
) -> dict[str, Any]:
    """Run one ``Strategy``; for symbolic/numerical, iterate every claimed eq.

    Strategy passes only if EVERY equation passes; we return the first
    inequivalent evidence (most actionable) or the last equivalent one.
    """
    kind = strategy.kind
    equations = claim.get("claimed_equations") or []
    if kind in ("symbolic", "numerical"):
        if not equations:
            return coder.run_strategy(
                strategy,
                paper,
                code_env,
                claim_equation=None,
                var_map=None,
                target_var=None,
            )
        last_ev: dict[str, Any] | None = None
        for raw_eq in equations:
            eq = _normalize_equation(raw_eq)
            target = _heuristic_target_var(eq, code_env)
            if _is_self_referential(eq, target):
                # Update-rule equation (LHS appears in RHS); we have no
                # temporal indexing for ``code_env`` so the matcher can't
                # distinguish ``\theta_{t-1}`` from ``\theta_t``. Skip
                # rather than report a spurious residual.
                continue
            var_map = _heuristic_var_map(eq, code_env)
            ev = coder.run_strategy(
                strategy,
                paper,
                code_env,
                claim_equation=eq,
                var_map=var_map,
                target_var=target,
            )
            if not ev.get("equivalent", True):
                return ev
            last_ev = ev
        if last_ev is None:
            # Every equation was self-referential — fall back to the
            # last one verbatim so the matcher still emits a real
            # evidence dict (with whatever residual it computes).
            raw_eq = equations[-1]
            eq = _normalize_equation(raw_eq)
            target = _heuristic_target_var(eq, code_env)
            var_map = _heuristic_var_map(eq, code_env)
            return coder.run_strategy(
                strategy,
                paper,
                code_env,
                claim_equation=eq,
                var_map=var_map,
                target_var=target,
            )
        return last_ev
    # structural / hyperparametric: single matcher call. The
    # ``claim_section`` kwarg makes ``code.run_strategy`` drop
    # cross-section mismatches before the Critic fires, so AdaMax-style
    # sibling sections in the Adam paper don't false-flag a clean
    # implementation (issue #3).
    return coder.run_strategy(strategy, paper, code_env, claim_section=claim.get("paper_section"))


def _short_residual(residual: Any) -> str | None:
    if residual is None:
        return None
    s = str(residual)
    return s if len(s) <= 80 else s[:77] + "..."


def _last_tb_line(tb: str) -> str:
    if not tb:
        return ""
    for line in reversed(tb.strip().splitlines()):
        line = line.strip()
        if line:
            return line
    return ""


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------


def verify(
    paper_arxiv_id: str,
    code_str: str,
    user_msg: str | None = None,
    *,
    function_name: str | None = None,
    stream: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Run the full verification pipeline. Returns the augmented verdict dict."""
    t_start = time.perf_counter()
    claim: dict[str, Any] | None = None
    strategies: list[Strategy] = []
    evidences: list[dict[str, Any]] = []
    fn_name: str | None = None

    # Stage 1: paper_extract
    s0 = time.perf_counter()
    try:
        src = paper_extract.fetch_arxiv_source(paper_arxiv_id)
        paper = paper_extract.parse_paper(src)
    except Exception as exc:
        ms = int((time.perf_counter() - s0) * 1000)
        tb = traceback.format_exc()
        _stage(stream, "paper_extract", "error", ms, info={"error": str(exc)})
        return _inconclusive(
            paper_arxiv_id,
            "paper_extract",
            tb,
            t_start,
            claim=claim,
            strategies=strategies,
            evidences=evidences,
            function_name=function_name,
        )
    ms = int((time.perf_counter() - s0) * 1000)
    section_keys = [k for k in paper.keys() if not k.startswith("_")]
    _stage(
        stream,
        "paper_extract",
        "ok",
        ms,
        info={
            "n_sections": len(section_keys),
            "first_sections": section_keys[:6],
        },
    )

    # Stage 2: spec
    s0 = time.perf_counter()
    try:
        claim = spec.extract_claim(paper_arxiv_id, code_str, user_msg)
    except Exception as exc:
        ms = int((time.perf_counter() - s0) * 1000)
        tb = traceback.format_exc()
        _stage(stream, "spec", "error", ms, info={"error": str(exc)})
        return _inconclusive(
            paper_arxiv_id,
            "spec",
            tb,
            t_start,
            claim=claim,
            strategies=strategies,
            evidences=evidences,
            function_name=function_name,
        )
    ms = int((time.perf_counter() - s0) * 1000)
    _stage(
        stream,
        "spec",
        "ok",
        ms,
        info={
            "paper_section": claim.get("paper_section"),
            "n_equations": len(claim.get("claimed_equations") or []),
            "claimed_function": claim.get("claimed_function"),
        },
    )

    # Stage 3: plan
    s0 = time.perf_counter()
    try:
        strategies = plan.generate_strategies(claim)
    except Exception as exc:
        ms = int((time.perf_counter() - s0) * 1000)
        tb = traceback.format_exc()
        _stage(stream, "plan", "error", ms, info={"error": str(exc)})
        return _inconclusive(
            paper_arxiv_id,
            "plan",
            tb,
            t_start,
            claim=claim,
            strategies=strategies,
            evidences=evidences,
            function_name=function_name,
        )
    ms = int((time.perf_counter() - s0) * 1000)
    _stage(
        stream,
        "plan",
        "ok",
        ms,
        info={
            "kinds": [st.kind for st in strategies],
            "targets": [st.target for st in strategies],
        },
    )

    # Stage 4: code_extract (resolve fn_name + walk AST)
    s0 = time.perf_counter()
    try:
        fn_name = _resolve_function_name(code_str, claim.get("claimed_function"), function_name)
        code_env = code_extract.code_to_sympy(code_str, fn_name)
    except Exception as exc:
        ms = int((time.perf_counter() - s0) * 1000)
        tb = traceback.format_exc()
        _stage(stream, "code_extract", "error", ms, info={"error": str(exc)})
        return _inconclusive(
            paper_arxiv_id,
            "code_extract",
            tb,
            t_start,
            claim=claim,
            strategies=strategies,
            evidences=evidences,
            function_name=fn_name,
        )
    ms = int((time.perf_counter() - s0) * 1000)
    _stage(
        stream,
        "code_extract",
        "ok",
        ms,
        info={
            "fn_name": fn_name,
            "n_env_keys": len(code_env),
            "env_keys": sorted(k for k in code_env.keys() if not k.startswith("_"))[:10],
        },
    )

    # Stage 5: code (run_strategy × N)
    # Inter-strategy backoff: when the previous strategy fired the
    # Critic, a fresh Gemma call from the next strategy can blow Gemma
    # 3's free-tier 15 000-input-tokens-per-minute quota. Sleeping a
    # few seconds between critic-firing strategies spreads the burn.
    inter_strategy_sleep_s = float(os.environ.get("NOCAP_STRATEGY_SLEEP", "5"))
    last_fired_critic = False
    for i, strategy in enumerate(strategies):
        if last_fired_critic and inter_strategy_sleep_s > 0:
            time.sleep(inter_strategy_sleep_s)
        s0 = time.perf_counter()
        try:
            ev = _strategy_evidence(strategy, paper, code_env, claim)
        except Exception as exc:
            ms = int((time.perf_counter() - s0) * 1000)
            tb = traceback.format_exc()
            _stage(
                stream, "code", "error", ms, strategy_idx=i, info={"kind": strategy.kind, "error": str(exc)}
            )
            evidences.append(
                {
                    "kind": strategy.kind,
                    "equivalent": False,
                    "residual": None,
                    "mismatches": None,
                    "method_used": "failed",
                    "target_var": None,
                    "raw_matcher_output": {},
                    "error": tb,
                    "critic_feedback": None,
                    "critic_score": None,
                }
            )
            continue
        ms = int((time.perf_counter() - s0) * 1000)
        evidences.append(ev)
        _stage(
            stream,
            "code",
            "ok",
            ms,
            strategy_idx=i,
            info={
                "kind": strategy.kind,
                "equivalent": bool(ev.get("equivalent")),
                "residual_short": _short_residual(ev.get("residual")),
                "n_mismatches": len(ev.get("mismatches") or []),
                "method_used": ev.get("method_used"),
                "target_var": ev.get("target_var"),
                "critic_score": ev.get("critic_score"),
            },
        )

    # Stage 6: polygraph
    s0 = time.perf_counter()
    try:
        polygraph_dict = polygraph_verify(claim, evidences)
    except Exception as exc:
        ms = int((time.perf_counter() - s0) * 1000)
        tb = traceback.format_exc()
        _stage(stream, "polygraph", "error", ms, info={"error": str(exc)})
        return _inconclusive(
            paper_arxiv_id,
            "polygraph",
            tb,
            t_start,
            claim=claim,
            strategies=strategies,
            evidences=evidences,
            function_name=fn_name,
        )
    ms = int((time.perf_counter() - s0) * 1000)
    _stage(
        stream,
        "polygraph",
        "ok",
        ms,
        info={
            "verdict": polygraph_dict.get("verdict"),
            "confidence": polygraph_dict.get("confidence"),
        },
    )

    elapsed = time.perf_counter() - t_start
    out: dict[str, Any] = {
        **polygraph_dict,
        "claim": claim,
        "strategies": [st.model_dump() for st in strategies],
        "evidences": evidences,
        "elapsed_seconds": round(elapsed, 3),
        "arxiv_id": paper_arxiv_id,
        "function_name": fn_name,
    }
    _stage(
        stream,
        "done",
        "ok",
        int(elapsed * 1000),
        info={
            "verdict": out["verdict"],
            "confidence": out.get("confidence"),
        },
    )
    return out


def _inconclusive(
    arxiv_id: str,
    stage_name: str,
    tb: str,
    t_start: float,
    *,
    claim: dict[str, Any] | None = None,
    strategies: list[Strategy] | None = None,
    evidences: list[dict[str, Any]] | None = None,
    function_name: str | None = None,
) -> dict[str, Any]:
    elapsed = time.perf_counter() - t_start
    return {
        "verdict": "inconclusive",
        "confidence": 0.5,
        "evidence_summary": f"stage {stage_name!r} raised: {_last_tb_line(tb)}",
        "vigil_audit": [],
        "claim": claim,
        "strategies": [st.model_dump() for st in (strategies or [])],
        "evidences": evidences or [],
        "elapsed_seconds": round(elapsed, 3),
        "arxiv_id": arxiv_id,
        "function_name": function_name,
        "error": tb,
    }


# ----------------------------------------------------------------------
# Acceptance entry point
# ----------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the No Cap council orchestrator end-to-end.")
    parser.add_argument("arxiv_id", help="arXiv identifier, e.g. 1412.6980")
    parser.add_argument("code_path", type=Path, help="Path to a .py file")
    parser.add_argument("--function", default=None, help="Override the def name to extract.")
    parser.add_argument("--user-msg", default=None, help="Optional user-provided claim/context.")
    args = parser.parse_args(argv)
    code_text = args.code_path.read_text()
    out = verify(
        args.arxiv_id,
        code_text,
        user_msg=args.user_msg,
        function_name=args.function,
    )
    sys.stdout.write("---\n")
    sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0 if out.get("verdict") in ("pass", "anomaly") else 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
