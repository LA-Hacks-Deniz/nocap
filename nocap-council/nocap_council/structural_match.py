# Owner: DEVIN — Phase 1 task T1.6
"""Structural diff between a parsed paper and an extracted code env.

Companion to ``sympy_match`` (T1.5) — that module checks whether a
single equation in the paper matches a single expression in the code.
This module catches the *other* failure modes: missed bias-correction
steps, dropped RK4 stages, and the single most common honest-mistake
bug in ML implementations, ``lr=3e-4`` in the paper vs ``lr=1e-4`` in
the code.

Public API
----------

``match_structure(paper_extract, code_extract) -> list[dict]``
    Compare the paper-side dict produced by
    ``paper_extract.parse_paper`` (the section-keyed shape, see
    ``paper_extract`` module docstring) against a code-side env
    produced by ``code_extract.code_to_sympy``. Returns a list of
    mismatch dicts, each shaped::

        {
            "type": str,                 # see _MISMATCH_TYPES below
            "location": {
                "paper_section":          str | None,
                "paper_algorithm_name":   str | None,
                "paper_hyperparam_symbol": str | None,
                "code_function":          str | None,
                "code_var":               str | None,
            },
            "expected": Any,             # the paper-side value
            "actual":   Any,             # the code-side value
            "severity": "low" | "medium" | "high",
        }

    The list may be empty when the paper and code agree (or when the
    paper section under inspection is silent on a given axis — see
    "asymmetry" below). Order is: algorithm-step mismatches, then
    hyperparam mismatches, then architecture mismatches; within each,
    deterministic by the paper-side iteration order.

Three structural axes
---------------------

1. **Algorithm step count.** For every ``algorithms[i]`` in every
   section, compare ``len(alg["steps"])`` (count of named lines in
   the paper's ``algorithmic`` block) to the number of distinct
   assignments in ``code_extract`` (``len`` excluding the synthetic
   ``"_return"`` key). Catches RK4 dropping a stage, Adam dropping
   bias correction, etc. Per-algorithm emit — the orchestrator picks
   the right algorithm via ``location.paper_algorithm_name``.

2. **Hyperparameter values.** Walk every ``hyperparams[name]`` in
   every section, look up ``code_extract.get(name)``. Coerce both
   sides to floats (paper-side via a small LaTeX-aware float parser;
   code-side via ``float(expr.evalf())``) and compare with
   ``math.isclose(rtol=1e-6, atol=1e-12)``. When code-side fails to
   coerce (e.g. it's a Symbol or has free symbols), the mismatch is
   still ``"hyperparam_mismatch"`` — we put the symbolic form in
   ``actual`` so the LLM downstream can read it. Asymmetric on
   purpose: paper-declared keys that don't appear in code → flagged
   as "low"; code-only keys → silent (they're not the bug shape we
   care about).

3. **Architecture.** Skeleton; emits nothing today because
   ``code_extract`` doesn't surface ``nn.Module`` info. T1.10 / T1.11
   can extend ``_match_architecture`` once they have a richer code
   shape. Type ``"architecture_mismatch"`` is reserved.

Severity mapping
----------------

::

    high   = algorithm step count off by >= 2  OR  `lr` mismatch
    medium = algorithm step count off by 1     OR  non-`lr` hp drift
    low    = paper-declared hp missing from code env

Asymmetry
---------

We deliberately do *not* flag mismatches that go code-to-paper:

- Code declares a hyperparameter the paper doesn't mention → silent.
- Code has more assignments than the paper's algorithm has steps →
  silent (algorithm count check is one-way: paper > code).

The bug shape we want to catch is "paper says X, code does Y" or
"paper says X, code didn't do X". The reverse direction is much more
likely to be a benign helper variable.

Worked example (live in ``__main__``)
-------------------------------------

Three synthetic cases the unit test exercises::

    (a) RK4 paper algorithm has 4 steps; code env has 3 assigns.
        -> {"type": "algorithm_step_count", "expected": 4,
            "actual": 3, "severity": "high"}
    (b) Paper hp lr="3e-4"; code env lr=sp.Float(1e-4).
        -> {"type": "hyperparam_mismatch", "expected": 0.0003,
            "actual": 0.0001, "severity": "high"}
    (c) Adam-shape paper algorithm has 7 steps; code env has 6 assigns.
        -> {"type": "algorithm_step_count", "expected": 7,
            "actual": 6, "severity": "medium"}

Run ``python -m nocap_council.structural_match`` to see the assertions
pass.
"""

from __future__ import annotations

import math
import re
from typing import Any

import sympy as sp

__all__ = [
    "match_structure",
]

# Mismatch type strings. Public tuple so downstream callers
# (T1.10/T1.11) can pattern-match without copy-pasting literals.
_MISMATCH_TYPES: tuple[str, ...] = (
    "algorithm_step_count",
    "hyperparam_mismatch",
    "hyperparam_missing_in_code",
    "architecture_mismatch",
)

_HP_RTOL: float = 1e-6
_HP_ATOL: float = 1e-12


def _empty_location() -> dict[str, Any]:
    return {
        "paper_section": None,
        "paper_algorithm_name": None,
        "paper_hyperparam_symbol": None,
        "code_function": None,
        "code_var": None,
    }


# Pattern: optional sign, digits, optional decimal, optional Python
# exponent. Used to short-circuit the LaTeX-rewrite path when the
# paper string is already a plain number.
_PLAIN_FLOAT_RE = re.compile(r"^\s*[+-]?\d+(\.\d*)?([eE][+-]?\d+)?\s*$")


def _parse_paper_number(s: str) -> float | None:
    """Best-effort float parse for a paper-side hyperparameter value.

    Handles plain numbers (``"0.001"``, ``"3e-4"``), LaTeX-flavored
    forms (``"3 \\times 10^{-4}"``, ``"3 \\cdot 10^{-4}"``,
    ``"10^{-8}"``), and the bare ``"e-N"`` shorthand. Returns ``None``
    when nothing works — caller treats that as "no comparison
    possible".
    """
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    if _PLAIN_FLOAT_RE.match(raw):
        try:
            return float(raw)
        except ValueError:
            return None
    # Strip TeX clutter: \,, $, math fences, etc.
    s2 = raw
    for token in ("$", r"\,", r"\;", r"\!", r"\\"):
        s2 = s2.replace(token, "")
    s2 = s2.strip()

    # Rewrite LaTeX scientific notation to Python: ``A \times 10^{B}``
    # or ``A \cdot 10^{B}`` -> ``A * 10**B`` -> float.
    sci = re.match(
        r"^\s*(?P<mant>[+-]?\d+(?:\.\d*)?)\s*(?:\\times|\\cdot|\*)?\s*"
        r"10\^\{?(?P<exp>[+-]?\d+)\}?\s*$",
        s2,
    )
    if sci is not None:
        try:
            mant = float(sci.group("mant"))
            exp = int(sci.group("exp"))
            return mant * (10**exp)
        except (TypeError, ValueError):
            return None

    # Bare ``10^{-N}`` (no mantissa).
    bare = re.match(r"^\s*10\^\{?(?P<exp>[+-]?\d+)\}?\s*$", s2)
    if bare is not None:
        try:
            return 10 ** int(bare.group("exp"))
        except (TypeError, ValueError):
            return None

    # Last-ditch: maybe stripping clutter exposed a plain float.
    try:
        return float(s2)
    except ValueError:
        return None


def _coerce_code_value(v: Any) -> tuple[float | None, str]:
    """Coerce a code-env value to a float, with a debug-friendly form.

    Returns ``(value, repr_str)`` where ``value`` is the float (or
    ``None`` when coercion failed) and ``repr_str`` is what the
    mismatch dict's ``actual`` field gets — either the float as a
    string, or the symbolic form of the expression.
    """
    if isinstance(v, (int, float)):
        return float(v), repr(float(v))
    if isinstance(v, sp.Expr):
        try:
            evald = v.evalf()
            return float(evald), repr(float(evald))
        except (TypeError, ValueError):
            # evalf left free symbols in place — symbolic form goes
            # through to the caller as the "actual" string.
            return None, str(v)
    return None, repr(v)


def _hp_severity(name: str) -> str:
    """High for ``lr``-shaped names, medium otherwise.

    ``lr``, ``learning_rate``, ``alpha`` (when used as Adam's step
    size) all count. The check is conservative — a non-``lr`` hp
    drift is still real but less likely to be the bug.
    """
    n = name.lower()
    return "high" if n in {"lr", "learning_rate", "alpha"} else "medium"


def _step_count_severity(diff: int) -> str:
    """``high`` when the count is >= 2 off, ``medium`` for off-by-one."""
    return "high" if diff >= 2 else "medium"


def _count_distinct_ops(code_env: dict[str, sp.Expr]) -> int:
    """Distinct assigned variables in the code env, excluding ``_return``."""
    return sum(1 for k in code_env if k != "_return")


def _match_algorithm_step_counts(
    paper_extract: dict[str, dict[str, Any]],
    code_env: dict[str, sp.Expr],
) -> list[dict[str, Any]]:
    """Per-algorithm step-count diff. See module docstring."""
    code_ops = _count_distinct_ops(code_env)
    out: list[dict[str, Any]] = []
    for section, bucket in paper_extract.items():
        if not isinstance(bucket, dict):
            continue
        for alg in bucket.get("algorithms") or []:
            steps = alg.get("steps") or []
            paper_n = len(steps)
            if paper_n == 0:
                # No structural signal — skip.
                continue
            if paper_n == code_ops:
                continue
            # We only flag paper > code. Code with more assignments
            # than the paper's named lines is most often helper
            # variables (e.g. caching ``g*g`` separately).
            if paper_n < code_ops:
                continue
            location = _empty_location()
            location["paper_section"] = section
            location["paper_algorithm_name"] = alg.get("name")
            out.append(
                {
                    "type": "algorithm_step_count",
                    "location": location,
                    "expected": paper_n,
                    "actual": code_ops,
                    "severity": _step_count_severity(paper_n - code_ops),
                }
            )
    return out


def _match_hyperparams(
    paper_extract: dict[str, dict[str, Any]],
    code_env: dict[str, sp.Expr],
) -> list[dict[str, Any]]:
    """Hyperparam value diff. See module docstring."""
    out: list[dict[str, Any]] = []
    for section, bucket in paper_extract.items():
        if not isinstance(bucket, dict):
            continue
        hps = bucket.get("hyperparams") or {}
        for name, paper_val in hps.items():
            location = _empty_location()
            location["paper_section"] = section
            location["paper_hyperparam_symbol"] = name
            location["code_var"] = name
            paper_f = _parse_paper_number(paper_val)
            if name not in code_env:
                # Paper declared, code didn't carry it through.
                out.append(
                    {
                        "type": "hyperparam_missing_in_code",
                        "location": location,
                        "expected": paper_f if paper_f is not None else paper_val,
                        "actual": None,
                        "severity": "low",
                    }
                )
                continue
            code_val = code_env[name]
            code_f, code_repr = _coerce_code_value(code_val)
            if paper_f is None:
                # We can't even parse the paper side as a number, so
                # we can't compare. Skip — better silent than noisy.
                continue
            if code_f is None:
                # Code-side is symbolic. Roll into hyperparam_mismatch
                # with the symbolic form in `actual` per chat answer.
                out.append(
                    {
                        "type": "hyperparam_mismatch",
                        "location": location,
                        "expected": paper_f,
                        "actual": code_repr,
                        "severity": _hp_severity(name),
                    }
                )
                continue
            if math.isclose(paper_f, code_f, rel_tol=_HP_RTOL, abs_tol=_HP_ATOL):
                continue
            out.append(
                {
                    "type": "hyperparam_mismatch",
                    "location": location,
                    "expected": paper_f,
                    "actual": code_f,
                    "severity": _hp_severity(name),
                }
            )
    return out


def _match_architecture(
    paper_extract: dict[str, dict[str, Any]],
    code_env: dict[str, sp.Expr],
) -> list[dict[str, Any]]:
    """Architecture diff skeleton.

    Today: returns ``[]``. ``code_extract`` doesn't carry
    ``nn.Module`` shape info, and the Adam acceptance doesn't
    exercise this axis. T1.10 / T1.11 should extend this once they
    have a richer code-side input (e.g. an explicit list of
    ``nn.Linear(in, out)`` calls). The function exists today so
    callers can wire it without a future signature break.
    """
    return []


def match_structure(
    paper_extract: dict[str, dict[str, Any]],
    code_extract: dict[str, sp.Expr],
) -> list[dict[str, Any]]:
    """Diff a parsed paper against an extracted code env.

    See module docstring for the full contract. ``paper_extract`` is
    the section-keyed dict from ``paper_extract.parse_paper``;
    ``code_extract`` is the ``{name: sympy.Expr}`` env from
    ``code_extract.code_to_sympy`` (single function).
    """
    mismatches: list[dict[str, Any]] = []
    mismatches.extend(_match_algorithm_step_counts(paper_extract, code_extract))
    mismatches.extend(_match_hyperparams(paper_extract, code_extract))
    mismatches.extend(_match_architecture(paper_extract, code_extract))
    return mismatches


def _print_mismatch(idx: int, m: dict[str, Any]) -> None:
    print(f"[{idx}] type      : {m['type']}")
    print(f"    severity  : {m['severity']}")
    print(f"    expected  : {m['expected']}")
    print(f"    actual    : {m['actual']}")
    loc_kept = {k: v for k, v in m["location"].items() if v is not None}
    print(f"    location  : {loc_kept}")


def _run_demo() -> int:
    """Synthetic acceptance per phases/phase-1.md §T1.6.

    Three independent cases, each shaped to exercise one axis of the
    structural diff. Inputs are inline (not produced by paper_extract
    / code_extract) so the test stays hermetic.
    """

    def _alg(name: str, n_steps: int) -> dict[str, Any]:
        return {
            "name": name,
            "label": None,
            "steps": [{"cmd": "\\State", "text": f"step {i + 1}", "line": i + 1} for i in range(n_steps)],
            "raw": "",
        }

    def _env(*names: str) -> dict[str, sp.Expr]:
        return {n: sp.Symbol(n) for n in names}

    print("=== (a) RK4: paper has 4 stages, code has 3 ===")
    paper_a = {
        "Section 4 — Time integration": {
            "equations": [],
            "algorithms": [_alg("Algorithm 1: Runge-Kutta 4", 4)],
            "hyperparams": {},
            "architecture": [],
        }
    }
    code_a = _env("k1", "k2", "k3")  # missing k4
    out_a = match_structure(paper_a, code_a)
    for i, m in enumerate(out_a):
        _print_mismatch(i, m)
    print()

    print("=== (b) hp drift: paper lr=3e-4, code lr=Float(1e-4) ===")
    paper_b = {
        "Section 6 — Training": {
            "equations": [],
            "algorithms": [],
            "hyperparams": {"lr": "3e-4"},
            "architecture": [],
        }
    }
    code_b = {"lr": sp.Float(1e-4)}
    out_b = match_structure(paper_b, code_b)
    for i, m in enumerate(out_b):
        _print_mismatch(i, m)
    print()

    print("=== (c) Adam-shape: paper algo 7 lines, code 6 ops ===")
    paper_c = {
        "§3 Algorithm": {
            "equations": [],
            "algorithms": [_alg("Algorithm 1: Adam", 7)],
            "hyperparams": {},
            "architecture": [],
        }
    }
    # 6 distinct assigns plus a synthetic _return (which is excluded
    # from the count).
    code_c = {
        "g": sp.Symbol("g"),
        "m": sp.Symbol("m"),
        "v": sp.Symbol("v"),
        "m_hat": sp.Symbol("m"),  # buggy: skipped bias correction
        "theta": sp.Symbol("theta"),
        "loss": sp.Symbol("loss"),
        "_return": sp.Symbol("theta"),
    }
    out_c = match_structure(paper_c, code_c)
    for i, m in enumerate(out_c):
        _print_mismatch(i, m)
    print()

    # Acceptance assertions.
    # Per the agreed severity mapping (chat answer #4): off-by-one is
    # medium; >= 2 off is high. RK4 4->3 is off-by-one -> medium.
    assert any(
        m["type"] == "algorithm_step_count"
        and m["expected"] == 4
        and m["actual"] == 3
        and m["severity"] == "medium"
        for m in out_a
    ), f"(a) RK4 case: expected algorithm_step_count medium mismatch 4->3, got {out_a}"

    assert any(
        m["type"] == "hyperparam_mismatch"
        and math.isclose(m["expected"], 3e-4, rel_tol=1e-9)
        and math.isclose(m["actual"], 1e-4, rel_tol=1e-9)
        and m["severity"] == "high"
        for m in out_b
    ), f"(b) lr case: expected hyperparam_mismatch high lr=3e-4 vs 1e-4, got {out_b}"

    assert any(
        m["type"] == "algorithm_step_count"
        and m["expected"] == 7
        and m["actual"] == 6
        and m["severity"] == "medium"
        for m in out_c
    ), f"(c) Adam case: expected algorithm_step_count medium 7->6, got {out_c}"

    print("ACCEPTANCE: all three structural mismatches caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_demo())
