# Owner: DEVIN — Phase 1 task T1.10
"""Coder role — dispatch a verification ``Strategy`` to the right matcher.

The Coder is the "single writer" in the No Cap council: given a
:class:`~nocap_council.plan.Strategy` produced by the Planner (T1.9), it
runs the corresponding matcher (``sympy_match`` / ``numerical_match`` /
``structural_match``) and packages the verdict + evidence into a single
dict the Polygraph (T1.11) can grade.

T1.10 is a **deterministic dispatcher** — there is no Coder LLM call here.
The OptimAI ``coder.txt`` prompt that the Planner uses to *generate* solver
code is not invoked because we already have first-class matcher modules;
``coder.txt`` is preserved in ``prompts/`` as documentation of the role's
intent so the orchestrator (T1.13) can opt into a Coder-LLM hybrid later
if it wants to resolve ``var_map`` / ``target_var`` from a real paper
claim.

When the matcher reports inequivalence (``equivalent=False``) or raises an
exception, the Coder fires the Critic (Gemma 4, ``critic.txt``) for
feedback. The Critic call is gated by the ``NOCAP_OFFLINE`` environment
variable so the acceptance demo can stay hermetic.

Public API
----------

``run_strategy(strategy, paper_extract, code_extract, *, claim_equation=None, var_map=None, target_var=None) -> dict``
    Dispatch on ``strategy.kind``:

    - ``"symbolic"``    → :func:`sympy_match.match_equation`
    - ``"numerical"``   → :func:`sympy_match.latex_to_sympy` then
      :func:`numerical_match.numeric_equal`
    - ``"structural"``  → :func:`structural_match.match_structure`
    - ``"hyperparametric"`` → ``match_structure`` then filter mismatches
      to ``type.startswith("hyperparam")``

    Returns an evidence dict with keys::

        {
            "kind":               str,           # echo of strategy.kind
            "equivalent":         bool,          # the verdict
            "residual":           str | None,    # str(sympy.Expr); only for symbolic/numerical
            "mismatches":         list[dict] | None,  # only for structural/hyperparametric
            "method_used":        str | None,    # "symbolic" | "numerical" | "failed"
            "target_var":         str | None,    # echo of resolved target
            "raw_matcher_output": dict,          # full matcher dict (un-filtered, full residual)
            "error":              str | None,    # traceback string when matcher raised
            "critic_feedback":    str | None,    # Critic's prose feedback (None on success or offline-stub)
            "critic_score":       int | None,    # 1..10, raw scale per critic.txt
        }

    Required arguments per ``kind``:

    - ``symbolic`` / ``numerical`` need both ``claim_equation`` (paper LaTeX)
      and ``var_map`` (paper→code symbol map) AND ``target_var`` (key into
      ``code_extract``). All three raise :class:`ValueError` if missing.
    - ``structural`` / ``hyperparametric`` need only ``paper_extract`` and
      ``code_extract``; ``target_var`` is unused.

Equivalence semantics
---------------------

For ``structural`` and ``hyperparametric``, ``equivalent`` is **strict**:
``len(filtered_mismatches) == 0``. Even ``low``-severity mismatches flip
the verdict. The Polygraph (T1.11) is the right place to weigh severity
into the final ``Pass`` / ``Anomaly`` call — the Coder reports raw
structural truth and lets the verifier decide.

Critic
------

Fires when ``equivalent=False`` OR the matcher raised. Sends the prompt
template at ``prompts/critic.txt`` (with placeholders filled) to Gemma
4. Returns ``{"feedback": str, "score": int (1..10)}``. Score scale per
``critic.txt``: confidence that successive LLM calls could debug the
verification code (a meta-property; the Polygraph normalizes to 0..1 if
it wants).

Set ``NOCAP_OFFLINE=1`` to stub the Critic with a deterministic
placeholder; useful for hermetic acceptance and CI.
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sympy as sp

from nocap_council import numerical_match, structural_match, sympy_match

if TYPE_CHECKING:
    from nocap_council.plan import Strategy

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_CRITIC_TXT = _PROMPTS_DIR / "critic.txt"

_GEMMA_MODEL = "gemma-3-27b-it"
_HP_PREFIX = "hyperparam"


def _empty_evidence(kind: str, target_var: str | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "equivalent": False,
        "residual": None,
        "mismatches": None,
        "method_used": None,
        "target_var": target_var,
        "raw_matcher_output": {},
        "error": None,
        "critic_feedback": None,
        "critic_score": None,
    }


def _stringify_residual(residual: Any) -> str | None:
    if residual is None:
        return None
    try:
        return str(residual)
    except Exception:
        return repr(residual)


def _require(value: Any, name: str, kind: str) -> Any:
    if value is None:
        raise ValueError(f"strategy.kind={kind!r} requires {name!r}; got None")
    return value


def _run_symbolic(
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    claim_equation: str | None,
    var_map: dict[str, str] | None,
    target_var: str | None,
) -> dict[str, Any]:
    latex = _require(claim_equation, "claim_equation", "symbolic")
    vmap = _require(var_map, "var_map", "symbolic")
    target = _require(target_var, "target_var", "symbolic")

    ev = _empty_evidence("symbolic", target)
    raw = sympy_match.match_equation(latex, code_extract, vmap, target)
    ev["raw_matcher_output"] = {
        "equivalent": raw.get("equivalent"),
        "residual": _stringify_residual(raw.get("residual")),
        "method_used": raw.get("method_used"),
    }
    ev["equivalent"] = bool(raw.get("equivalent"))
    ev["residual"] = _stringify_residual(raw.get("residual"))
    ev["method_used"] = raw.get("method_used")
    return ev


def _run_numerical(
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    claim_equation: str | None,
    var_map: dict[str, str] | None,
    target_var: str | None,
) -> dict[str, Any]:
    latex = _require(claim_equation, "claim_equation", "numerical")
    vmap = _require(var_map, "var_map", "numerical")
    target = _require(target_var, "target_var", "numerical")

    ev = _empty_evidence("numerical", target)
    paper_expr = sympy_match.latex_to_sympy(latex, vmap)
    if isinstance(paper_expr, sp.Equality):
        paper_rhs = paper_expr.rhs
    else:
        paper_rhs = paper_expr
    if target not in code_extract:
        raise KeyError(f"target_var {target!r} not in code_extract (keys={sorted(code_extract)!r})")
    code_expr = code_extract[target]
    equal = numerical_match.numeric_equal(paper_rhs, code_expr)
    residual = sp.simplify(paper_rhs - code_expr)
    ev["raw_matcher_output"] = {
        "equivalent": bool(equal),
        "paper_rhs": str(paper_rhs),
        "code_expr": str(code_expr),
        "residual": str(residual),
    }
    ev["equivalent"] = bool(equal)
    ev["method_used"] = "numerical"
    ev["residual"] = None if equal else str(residual)
    return ev


def _run_structural(
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    filter_hyperparam: bool,
) -> dict[str, Any]:
    kind = "hyperparametric" if filter_hyperparam else "structural"
    ev = _empty_evidence(kind, None)
    raw_mismatches = structural_match.match_structure(paper_extract, code_extract)
    ev["raw_matcher_output"] = {"mismatches": raw_mismatches}
    if filter_hyperparam:
        filtered = [m for m in raw_mismatches if str(m.get("type", "")).startswith(_HP_PREFIX)]
    else:
        filtered = list(raw_mismatches)
    ev["mismatches"] = filtered
    ev["equivalent"] = len(filtered) == 0
    ev["method_used"] = None
    return ev


def _format_critic_prompt(
    strategy: Strategy,
    paper_extract: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    template = _CRITIC_TXT.read_text()
    lines = template.splitlines()
    while lines and lines[0].lstrip().startswith("<!--"):
        lines.pop(0)
    cleaned = "\n".join(lines).lstrip()

    task_desc = (
        f"Verify that a Python implementation matches the paper claim. "
        f"Strategy kind: {strategy.kind!r}. Target: {strategy.target!r}."
    )
    components_json = json.dumps(paper_extract, indent=2, ensure_ascii=False, default=str)
    strategy_json = strategy.model_dump_json(indent=2)
    solver_code = _synthesized_solver_code(strategy, evidence)
    error_msg = evidence.get("error") or _failure_summary(evidence)

    out = cleaned.replace('{state["messages"][0].content}', task_desc)
    out = out.replace('{state["components"]}', components_json)
    out = out.replace(
        '{state[active_branch][len(state[active_branch]) - 1]["strategy"]}',
        strategy_json,
    )
    out = out.replace("{solver_code}", solver_code)
    out = out.replace("{error_msg}", error_msg)
    return out


def _synthesized_solver_code(strategy: Strategy, evidence: dict[str, Any]) -> str:
    target = evidence.get("target_var")
    if strategy.kind in ("symbolic", "numerical"):
        return (
            f"# Coder dispatched {strategy.kind!r} matcher\n"
            f"# matcher = nocap_council.{('sympy_match.match_equation' if strategy.kind == 'symbolic' else 'numerical_match.numeric_equal')}\n"
            f"# target_var = {target!r}\n"
            f"# raw_matcher_output = {evidence.get('raw_matcher_output')!r}\n"
        )
    return (
        f"# Coder dispatched {strategy.kind!r} matcher\n"
        f"# matcher = nocap_council.structural_match.match_structure\n"
        f"# raw_matcher_output = {evidence.get('raw_matcher_output')!r}\n"
    )


def _failure_summary(evidence: dict[str, Any]) -> str:
    if evidence.get("residual"):
        return f"Matcher reported inequivalence with residual: {evidence['residual']}"
    if evidence.get("mismatches"):
        return f"Matcher reported {len(evidence['mismatches'])} mismatches: {evidence['mismatches']}"
    return "Matcher reported equivalent=False with no residual or mismatches."


def _stub_critic(strategy: Strategy, evidence: dict[str, Any]) -> tuple[str, int]:
    summary = _failure_summary(evidence)
    feedback = (
        f"[NOCAP_OFFLINE stub] Strategy {strategy.kind!r} reported inequivalence. {summary} "
        "Real Critic would diagnose root cause and suggest fixes; unset NOCAP_OFFLINE to enable."
    )
    return feedback, 5


def _run_critic(
    strategy: Strategy,
    paper_extract: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[str, int]:
    if os.environ.get("NOCAP_OFFLINE") == "1":
        return _stub_critic(strategy, evidence)
    from nocap_council import client  # deferred: requires GOOGLE_API_KEY at import

    prompt = _format_critic_prompt(strategy, paper_extract, evidence)
    raw = client.call_json(
        model=_GEMMA_MODEL,
        system=prompt,
        user=json.dumps({"strategy": strategy.model_dump(), "evidence_summary": _failure_summary(evidence)}),
        schema={"type": "object"},
    )
    feedback = str(raw.get("feedback", "")).strip()
    try:
        score = int(raw.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(1, min(10, score))
    return feedback, score


def run_strategy(
    strategy: Strategy,
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    claim_equation: str | None = None,
    var_map: dict[str, str] | None = None,
    target_var: str | None = None,
) -> dict[str, Any]:
    """Dispatch a verification strategy and return an evidence dict.

    See module docstring for the evidence shape and arg requirements.
    """
    kind = strategy.kind
    try:
        if kind == "symbolic":
            evidence = _run_symbolic(
                paper_extract,
                code_extract,
                claim_equation=claim_equation,
                var_map=var_map,
                target_var=target_var,
            )
        elif kind == "numerical":
            evidence = _run_numerical(
                paper_extract,
                code_extract,
                claim_equation=claim_equation,
                var_map=var_map,
                target_var=target_var,
            )
        elif kind == "structural":
            evidence = _run_structural(paper_extract, code_extract, filter_hyperparam=False)
        elif kind == "hyperparametric":
            evidence = _run_structural(paper_extract, code_extract, filter_hyperparam=True)
        else:
            raise ValueError(f"unknown strategy.kind={kind!r}")
    except Exception as exc:
        evidence = _empty_evidence(kind, target_var)
        evidence["method_used"] = "failed"
        evidence["error"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        feedback, score = _run_critic(strategy, paper_extract, evidence)
        evidence["critic_feedback"] = feedback
        evidence["critic_score"] = score
        return evidence

    if not evidence["equivalent"]:
        feedback, score = _run_critic(strategy, paper_extract, evidence)
        evidence["critic_feedback"] = feedback
        evidence["critic_score"] = score
    return evidence


# ----------------------------------------------------------------------
# Acceptance demo (T1.10): three strategies on Adam-buggy fixture.
# Hermetic — sets NOCAP_OFFLINE=1 to stub the Critic. Unset
# NOCAP_OFFLINE before running to see live Gemma critic feedback.
# ----------------------------------------------------------------------
_DEMO_LATEX = r"\hat{m}_t = m_t / (1 - \beta_1^t)"
_DEMO_VAR_MAP = {
    "m_hat_t": "m_hat",
    "m_t": "m",
    r"\beta_1": "beta1",
}
_DEMO_TARGET = "m_hat"


def _demo_paper_extract() -> dict[str, Any]:
    """Synthetic paper bucket exercising the structural axis (7 algorithm steps)."""
    section = "§3 Algorithm 1 — Adam"
    return {
        section: {
            "section_name": section,
            "equations": [{"env": "equation", "latex": _DEMO_LATEX, "label": None}],
            "algorithms": [
                {
                    "name": "Algorithm 1: Adam",
                    "steps": [{"cmd": "State", "text": f"step {i}", "line": i} for i in range(1, 8)],
                }
            ],
            "hyperparams": {"lr": "1e-3"},
            "architecture": [],
            "prose": "",
        }
    }


def _demo_code_extract_buggy() -> dict[str, sp.Expr]:
    """Mirror what code_extract.code_to_sympy(adam_buggy.py, 'step') emits.

    Only the keys we touch in the acceptance assertions matter. We hand-build
    the env so this module can be exercised without re-walking the AST.
    """
    g, beta1, beta2, eps, lr, m_prev, v_prev, theta_prev, t = sp.symbols("g beta1 beta2 eps lr m v theta t")
    m = beta1 * m_prev + (1 - beta1) * g
    v = beta2 * v_prev + (1 - beta2) * g * g
    m_hat = m  # buggy: missing /(1 - beta1**t)
    v_hat = v  # buggy: missing /(1 - beta2**t)
    theta = theta_prev - lr * m_hat / (sp.sqrt(v_hat) + eps)
    return {
        "g": g,
        "m": m,
        "v": v,
        "m_hat": m_hat,
        "v_hat": v_hat,
        "theta": theta,
        "_return": theta,
    }


def _print_evidence(idx: int, strategy: Strategy, evidence: dict[str, Any]) -> None:
    print(f"\n=== [{idx}] strategy.kind={strategy.kind!r} ===")
    for k in ("kind", "equivalent", "residual", "method_used", "target_var", "error"):
        v = evidence.get(k)
        if v is None:
            continue
        s = str(v)
        if len(s) > 200:
            s = s[:197] + "..."
        print(f"    {k:18s}: {s}")
    mismatches = evidence.get("mismatches")
    if mismatches:
        print(f"    mismatches    ({len(mismatches)}):")
        for j, m in enumerate(mismatches):
            print(f"      [{j}] {m}")
    if evidence.get("critic_feedback"):
        feedback = evidence["critic_feedback"]
        if len(feedback) > 220:
            feedback = feedback[:217] + "..."
        print(f"    critic_score      : {evidence.get('critic_score')}")
        print(f"    critic_feedback   : {feedback}")


def _run_demo() -> int:
    os.environ.setdefault("NOCAP_OFFLINE", "1")
    os.environ.setdefault("GOOGLE_API_KEY", "demo-stub")  # plan.py imports client at top
    from nocap_council.plan import Strategy

    print("# T1.10 Coder acceptance — Adam buggy, three strategies.")
    print(f"# NOCAP_OFFLINE={os.environ.get('NOCAP_OFFLINE')!r} (unset to enable live Gemma Critic).")

    paper_extract = _demo_paper_extract()
    code_extract = _demo_code_extract_buggy()

    strategies = [
        Strategy(
            kind="symbolic",
            rationale="Compare paper bias-correction equation to code m_hat via SymPy simplify.",
            target="§3 Algorithm 1 — Adam",
        ),
        Strategy(
            kind="numerical",
            rationale="Sample-evaluate paper m_hat formula vs code m_hat at random points.",
            target="§3 Algorithm 1 — Adam",
        ),
        Strategy(
            kind="structural",
            rationale="Compare paper algorithm step count to code env op count.",
            target="§3 Algorithm 1 — Adam",
        ),
    ]

    evidences: list[dict[str, Any]] = []
    for i, strat in enumerate(strategies, 1):
        ev = run_strategy(
            strat,
            paper_extract,
            code_extract,
            claim_equation=_DEMO_LATEX if strat.kind in ("symbolic", "numerical") else None,
            var_map=_DEMO_VAR_MAP if strat.kind in ("symbolic", "numerical") else None,
            target_var=_DEMO_TARGET if strat.kind in ("symbolic", "numerical") else None,
        )
        _print_evidence(i, strat, ev)
        evidences.append(ev)

    inequivalent = [e for e in evidences if not e["equivalent"]]
    print(f"\nACCEPTANCE: {len(inequivalent)}/3 strategies caught the bug (equivalent=False). Required: ≥2.")
    assert len(inequivalent) >= 2, f"expected ≥2 strategies to flag the buggy Adam, got {len(inequivalent)}"
    sym_ev = next((e for e in evidences if e["kind"] == "symbolic"), None)
    if sym_ev is not None and not sym_ev["equivalent"]:
        assert sym_ev["residual"] is not None, "symbolic mismatch must carry a residual"
    struct_ev = next((e for e in evidences if e["kind"] == "structural"), None)
    if struct_ev is not None and not struct_ev["equivalent"]:
        assert struct_ev["mismatches"], "structural mismatch must carry a mismatch list"

    if os.environ.get("NOCAP_DEMO_LIVE_CRITIC"):
        print("\n--- NOCAP_DEMO_LIVE_CRITIC: re-running symbolic case with live Critic ---")
        os.environ.pop("NOCAP_OFFLINE", None)
        live = run_strategy(
            strategies[0],
            paper_extract,
            code_extract,
            claim_equation=_DEMO_LATEX,
            var_map=_DEMO_VAR_MAP,
            target_var=_DEMO_TARGET,
        )
        _print_evidence(0, strategies[0], live)
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_demo())
