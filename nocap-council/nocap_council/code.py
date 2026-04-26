# Owner: DEVIN — Phase 1 task T1.10 (extended T1.23)
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

LLM-judge fallback (T1.23)
--------------------------

After ``_run_symbolic`` / ``_run_numerical`` returns, the Coder may invoke
``_run_llm_judge`` — a single Gemma call that decides equivalence
semantically — when the matcher's verdict is non-actionable. The judge
fires on **four** triggers:

1. ``method_used == "failed"`` — matcher raised; nothing to weigh.
2. ``error`` string contains ``"not found"`` (case-insensitive) — symbol
   miss inside the matcher; ``var_map`` couldn't resolve a paper symbol.
3. ``equivalent is False`` AND ``method_used == "failed"`` — symbolic
   reported inequivalence but with no clean residual (the simplification
   path bailed out). Without the judge, the residual would be a sympy
   tree dominated by un-substituted opaque calls.
4. ``equivalent is True`` AND ``code_expr`` contains an undefined function
   call (e.g. ``_gather``, ``randn_like``) that isn't a SymPy builtin —
   numerical's ``equivalent=True`` is **unreliable** because ``subs(...)``
   substitutes the same opaque node on both sides, subtraction cancels
   them symmetrically, and ``np.isclose`` passes regardless of semantic
   difference. When this trigger fires, the evidence is marked
   ``method_used="numerical_unreliable"`` PRE-judge so the trace shows
   why the judge ran (vs "numerical said true but we didn't trust it").

When the judge runs, its verdict replaces the matcher's
``equivalent`` / ``residual`` / ``method_used`` (now ``"llm_judge"``);
the original matcher output is preserved in ``raw_matcher_output`` and
the judge's raw response is stored in ``raw_judge_output``. The judge's
one-sentence ``reasoning`` is surfaced in ``judge_reasoning``.

Token budget: ~800 input tokens worst case (paper equation + function
source + code expression). With T1.22's per-strategy spacing and the
function-source-only trim, this fits inside Gemma's 15 k input-tokens-
per-minute free-tier window.

NOCAP_OFFLINE-gated. The smoke-adam path is symbolic-matchable on every
equation, so the judge never fires there — verified in T1.23 acceptance.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sympy as sp

from nocap_council import numerical_match, structural_match, sympy_match

if TYPE_CHECKING:
    from nocap_council.plan import Strategy

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_CRITIC_TXT = _PROMPTS_DIR / "critic.txt"

_GEMMA_MODEL = "gemma-4-31b-it"
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
        # T1.23: judge-fallback fields. None unless the judge fires.
        "judge_reasoning": None,
        "raw_judge_output": None,
    }


def _has_unknown_function(expr: Any) -> bool:
    """Trigger 4: detect undefined function calls in ``expr``.

    sympy treats unparseable / opaque calls (e.g. ``_gather(bar_alphas, t,
    shape)``, ``randn_like(x0)``) as instances of ``UndefinedFunction``.
    These atoms cancel symmetrically inside ``subs(...)`` (the same
    function node ends up on both sides of the difference), so
    ``numerical_match.numeric_equal`` can return ``True`` even when the
    code is semantically wrong (T1.22's q_sample-buggy flake). When this
    fires we don't trust the numerical "pass" — we ask the judge.
    """
    if not isinstance(expr, sp.Expr):
        return False
    try:
        atoms = expr.atoms(sp.Function)
    except Exception:
        return False
    for f in atoms:
        # ``sp.Function`` itself plus ``UndefinedFunction`` instances both
        # have a ``.func.__name__``; sympy builtins (``sin``, ``log``, …)
        # are attributes of the ``sympy`` module, undefined functions are
        # not.
        name = getattr(getattr(f, "func", None), "__name__", None)
        if not isinstance(name, str):
            continue
        if not hasattr(sp, name):
            return True
    return False


def _stub_llm_judge(paper_equation: str, code_expr: Any, target_var: str) -> dict[str, Any]:
    """Deterministic ``NOCAP_OFFLINE`` stub for ``_run_llm_judge``.

    Defaults to ``equivalent=True`` so smoke-adam stays green when the
    judge spuriously fires (it shouldn't; this is just a safety net).
    """
    return {
        "equivalent": True,
        "residual": "",
        "reasoning": (
            "[NOCAP_OFFLINE stub] judge skipped; assuming equivalent. "
            f"target_var={target_var!r} paper_equation={paper_equation[:80]!r}"
        ),
        "method_used": "llm_judge",
    }


_JUDGE_SYSTEM = """You are a paper-vs-code equivalence verifier.

Decide whether ``code_expr`` (canonical, post-substitution) implements
the same math as ``paper_equation``. Default to INEQUIVALENT. Only
return equivalent=true if you can articulate the substitution /
reparameterization that makes them match in 1-2 lines.

CANONICALITY RULE
-----------------
``code_expr`` is the canonical expression. The function body
(``function_source``) is provided FOR CONTEXT ONLY — it shows decorators,
docstring, and surrounding code. When ``code_expr`` and the function
body appear to disagree, trust ``code_expr``.

LOCAL VARIABLE NAMES ARE NOT EVIDENCE
-------------------------------------
A local-variable assignment inside the function body is just a label
chosen by the code author and may be deliberately misleading. For
example, the line::

    sqrt_bar = _gather(self.bar_alphas, t, x0.shape)

names the local variable ``sqrt_bar``, but the array indexed is
``self.bar_alphas`` (NOT ``self.sqrt_bar_alphas``). The values pulled
are bar_alphas, NOT their square roots — regardless of what the local
variable is called. Look at the ARRAY name passed to
``_gather`` / ``index_select`` / ``X[t]``, NOT at the receiving local.

ARRAY-NAME RULE
---------------
Variable names in code carry semantic information. ``sqrt_X`` and ``X``
are NOT interchangeable. If the paper requires ``sqrt(X_t)`` and the
code's ``code_expr`` indexes into an array whose name lacks the
``sqrt_`` prefix, that is a real bug, not a notation difference. Same
for ``log_X`` vs ``X``, ``inv_X`` vs ``X``, ``cum_X`` vs ``X``, etc.

REPARAMETERIZATION RULE
-----------------------
Reparameterizations of probability distributions are equivalent when
they match exactly (e.g. ``q(x|y) = N(mu, sigma^2 I)`` and
``x = mu + sigma * eps`` with ``eps ~ N(0, I)``).

OUTPUT SCHEMA
-------------
Return ONLY a JSON object with these fields, in this order:

  paper_coefficient    : the multiplicative coefficient applied to the
                         leading term in ``paper_equation``, copied
                         verbatim (e.g. "sqrt(bar_alpha_t)").
  code_coefficient     : the multiplicative coefficient on the same
                         term in ``code_expr``, copied verbatim
                         (e.g. "_gather(bar_alphas, t, x0_shape)").
  coefficients_match   : bool — do the two coefficients compute the
                         same value? Indexing helpers like
                         ``_gather(X, t, ...)`` produce ``X[t]``, so
                         compare X's name against the paper's
                         coefficient.
  match_reasoning      : one sentence — why the coefficients do or do
                         not compute the same value, citing array
                         names verbatim.
  equivalent           : bool — overall verdict.
  residual             : symbolic form of the difference; '' if
                         equivalent.
  reasoning            : one-sentence overall verdict statement.

Worked example — CORRECT INEQUIVALENT verdict (the canonical DDPM
q_sample bug, where local var ``sqrt_bar`` is misleading):

  Inputs:
    paper_section : "§4 Forward Process"
    paper_equation: x_t = sqrt(bar_alpha_t) x_0 + sqrt(1 - bar_alpha_t) eps
    code_expr     : _gather(bar_alphas, t, x0_shape) * x_0
                    + _gather(sqrt_one_minus_bar_alphas, t, x0_shape)
                      * randn_like(x0)
    function_source (context only): the function assigns
        sqrt_bar = _gather(self.bar_alphas, t, x0.shape)
        ... return sqrt_bar * x0 + ...

  Output:
    {
      "paper_coefficient": "sqrt(bar_alpha_t)",
      "code_coefficient":  "_gather(bar_alphas, t, x0_shape)",
      "coefficients_match": false,
      "match_reasoning": "paper coefficient applies sqrt to bar_alpha_t; \
code indexes into bar_alphas (no sqrt) — the local variable named \
sqrt_bar is misleading because the ARRAY is bar_alphas.",
      "equivalent": false,
      "residual": "missing sqrt on x_0 coefficient",
      "reasoning": "code's x_0 coefficient is _gather(bar_alphas, ...), \
which has no sqrt prefix; paper requires sqrt(bar_alpha_t)."
    }

Worked example — CORRECT EQUIVALENT verdict (same function with bug
fixed: array changed to ``sqrt_bar_alphas``):

  Inputs:
    paper_section : "§4 Forward Process"
    paper_equation: x_t = sqrt(bar_alpha_t) x_0 + sqrt(1 - bar_alpha_t) eps
    code_expr     : _gather(sqrt_bar_alphas, t, x0_shape) * x_0
                    + _gather(sqrt_one_minus_bar_alphas, t, x0_shape)
                      * randn_like(x0)

  Output:
    {
      "paper_coefficient": "sqrt(bar_alpha_t)",
      "code_coefficient":  "_gather(sqrt_bar_alphas, t, x0_shape)",
      "coefficients_match": true,
      "match_reasoning": "code indexes into sqrt_bar_alphas, the \
precomputed sqrt of bar_alphas; matches paper's sqrt(bar_alpha_t).",
      "equivalent": true,
      "residual": "",
      "reasoning": "code's x_0 coefficient pulls from sqrt_bar_alphas; \
matches paper's sqrt(bar_alpha_t)."
    }

Keep ``match_reasoning`` and ``reasoning`` to ONE sentence each."""


def _judge_log(tag: str, body: str, *, max_chars: int = 1500) -> None:
    """Stderr ``[judge]`` log helper. ``tag`` carries strategy_idx so
    multiple judge fires in one run remain distinguishable.
    """
    snippet = body if len(body) <= max_chars else body[:max_chars] + f"… ({len(body) - max_chars} chars truncated)"
    # Keep the line count low so logs don't drown out the streaming UI.
    for line in snippet.splitlines():
        print(f"[judge {tag}] {line}", file=sys.stderr)


def _run_llm_judge(
    paper_equation: str,
    code_expr: Any,
    target_var: str,
    function_source: str | None,
    *,
    paper_section: str | None = None,
    function_name: str | None = None,
    strategy_idx: int | None = None,
) -> dict[str, Any]:
    """Single Gemma call: are ``paper_equation`` and ``code_expr`` equivalent?

    Returns a dict with::

        {
            "equivalent": bool,
            "residual": str,            # "" when equivalent
            "reasoning": str,           # one sentence
            "method_used": "llm_judge"  # or "llm_judge_failed"
        }

    Defensive parse: any malformed response degrades to
    ``equivalent=False, method_used="llm_judge_failed"`` with the raw
    error captured in ``reasoning``. NOCAP_OFFLINE returns a deterministic
    stub.

    Emits ``[judge <strategy_idx|tag>]`` lines to stderr containing the
    truncated user payload and the raw response so prompt iteration can
    happen post-hoc without re-burning Gemma quota.
    """
    if os.environ.get("NOCAP_OFFLINE") == "1":
        return _stub_llm_judge(paper_equation, code_expr, target_var)

    from nocap_council import client  # deferred — needs GOOGLE_API_KEY

    fn_block = (function_source or "<function source unavailable>").strip()
    section_block = paper_section or "(unknown — Spec did not record one)"
    fn_name_line = (
        f"function_name: `{function_name}`\n" if function_name else ""
    )
    # Fix 2 (T1.23 v2): canonical fields first; ``function_source`` is
    # demoted to a context-only footer so its misleading local-variable
    # names lose positional weight.
    user_payload = (
        f"paper_section: {section_block!r}\n"
        f"paper_equation: {paper_equation}\n"
        f"target_var: `{target_var}`\n"
        f"{fn_name_line}"
        "\n"
        f"code_expr (CANONICAL post-substitution sympy expression for `{target_var}`):\n"
        f"  {code_expr}\n"
        "\n"
        "----- function_source (CONTEXT ONLY — local variable names may be "
        "misleading; trust code_expr above) -----\n"
        f"```python\n{fn_block}\n```\n"
        "\n"
        "Decide equivalence per the system rules. Return ONLY the JSON "
        "object specified in the OUTPUT SCHEMA section of the system prompt."
    )
    # Fix 4 (T1.23 v2): structured coefficient comparison forces the
    # model to copy paper_coefficient and code_coefficient verbatim and
    # then compare them — eliminating the "_gather(bar_alphas) →
    # sqrt(bar_alpha) array" hallucination path.
    schema = {
        "type": "object",
        "properties": {
            "paper_coefficient": {"type": "string"},
            "code_coefficient": {"type": "string"},
            "coefficients_match": {"type": "boolean"},
            "match_reasoning": {"type": "string"},
            "equivalent": {"type": "boolean"},
            "residual": {"type": "string"},
            "reasoning": {"type": "string"},
        },
        "required": [
            "paper_coefficient",
            "code_coefficient",
            "coefficients_match",
            "equivalent",
            "reasoning",
        ],
    }

    log_tag = f"strategy_idx={strategy_idx}" if strategy_idx is not None else f"target={target_var!r}"
    _judge_log(log_tag, "PROMPT (user_payload):")
    _judge_log(log_tag, user_payload)

    try:
        raw = client.call_json(
            model=_GEMMA_MODEL,
            system=_JUDGE_SYSTEM,
            user=user_payload,
            schema=schema,
        )
    except Exception as exc:  # network / parse / quota
        _judge_log(log_tag, f"FAILED: {exc!r}")
        return {
            "equivalent": False,
            "residual": "",
            "reasoning": f"judge call failed: {exc!r}",
            "method_used": "llm_judge_failed",
        }
    _judge_log(log_tag, "RESPONSE (raw JSON):", max_chars=800)
    try:
        _judge_log(log_tag, json.dumps(raw, ensure_ascii=False), max_chars=800)
    except Exception:
        _judge_log(log_tag, str(raw), max_chars=800)

    equiv = bool(raw.get("equivalent", False))
    residual = str(raw.get("residual") or "")
    reasoning = str(raw.get("reasoning") or "").strip()
    if not reasoning:
        reasoning = "(judge returned empty reasoning)"
    return {
        "equivalent": equiv,
        "residual": residual,
        "reasoning": reasoning,
        "method_used": "llm_judge",
        "_raw": raw,
    }


def _should_run_judge(evidence: dict[str, Any], code_expr: Any) -> str | None:
    """Decide whether to fire the judge on ``evidence``.

    Returns the trigger name (str) or ``None``. The trigger name is
    informational; the call site treats any non-None return as
    "fire judge" and stamps ``method_used`` accordingly.
    """
    method = evidence.get("method_used")
    error = (evidence.get("error") or "")
    error_lc = error.lower() if isinstance(error, str) else ""

    if method == "failed":
        return "failed"
    if "not found" in error_lc or "keyerror" in error_lc:
        return "not_found"
    # A symbolic inequivalence with method=="failed" is already caught
    # above; this catches the "False but no clean residual" case where
    # the simplification gave up.
    if evidence.get("equivalent") is False and method in (None, "failed"):
        return "inconclusive"
    # Trigger 4 — numerical lying through opaque function symmetry.
    if (
        evidence.get("equivalent") is True
        and method == "numerical"
        and _has_unknown_function(code_expr)
    ):
        return "numerical_unreliable"
    return None


def _apply_judge(
    evidence: dict[str, Any],
    *,
    paper_equation: str | None,
    code_expr: Any,
    target_var: str | None,
    function_source: str | None,
    trigger: str,
    paper_section: str | None = None,
    function_name: str | None = None,
    strategy_idx: int | None = None,
) -> dict[str, Any]:
    """Replace ``evidence``'s verdict with the judge's, in-place."""
    # Pre-judge bookkeeping so the trace records WHY the judge ran.
    if trigger == "numerical_unreliable":
        # Stamp before the judge call so the JSONL trace would show
        # this even if the judge call crashes.
        evidence["method_used"] = "numerical_unreliable"

    judge = _run_llm_judge(
        paper_equation or "",
        code_expr,
        target_var or "<unknown>",
        function_source,
        paper_section=paper_section,
        function_name=function_name,
        strategy_idx=strategy_idx,
    )
    raw_judge = dict(judge)
    raw_payload = raw_judge.pop("_raw", None)
    evidence["raw_judge_output"] = raw_payload if raw_payload is not None else raw_judge
    evidence["judge_reasoning"] = judge.get("reasoning")
    evidence["method_used"] = judge.get("method_used", "llm_judge_failed")
    evidence["equivalent"] = bool(judge.get("equivalent"))
    residual = judge.get("residual") or ""
    evidence["residual"] = residual if residual else None
    # Track the trigger so cli/polygraph can render context.
    evidence["judge_trigger"] = trigger
    return evidence


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
    function_source: str | None = None,
    paper_section: str | None = None,
    function_name: str | None = None,
    strategy_idx: int | None = None,
) -> dict[str, Any]:
    latex = _require(claim_equation, "claim_equation", "symbolic")
    vmap = _require(var_map, "var_map", "symbolic")
    target = _require(target_var, "target_var", "symbolic")

    ev = _empty_evidence("symbolic", target)
    try:
        raw = sympy_match.match_equation(latex, code_extract, vmap, target)
    except Exception as exc:
        # Matcher raised — record the error and fall through to the
        # judge, which can reason about equivalence directly from the
        # paper LaTeX + function source even when var_map can't resolve.
        ev["error"] = str(exc)
        ev["method_used"] = "failed"
        ev["raw_matcher_output"] = {"error": str(exc)}
        raw = None

    if raw is not None:
        ev["raw_matcher_output"] = {
            "equivalent": raw.get("equivalent"),
            "residual": _stringify_residual(raw.get("residual")),
            "method_used": raw.get("method_used"),
        }
        ev["equivalent"] = bool(raw.get("equivalent"))
        ev["residual"] = _stringify_residual(raw.get("residual"))
        ev["method_used"] = raw.get("method_used")

    # T1.23 judge fallback. ``code_expr_for_check`` is what the matcher
    # actually compared against; we re-fetch it from the env so the
    # unknown-function detector has something to inspect.
    code_expr_for_check = code_extract.get(target) if isinstance(target, str) else None
    trigger = _should_run_judge(ev, code_expr_for_check)
    if trigger is not None:
        ev = _apply_judge(
            ev,
            paper_equation=latex,
            code_expr=code_expr_for_check,
            target_var=target,
            function_source=function_source,
            trigger=trigger,
            paper_section=paper_section,
            function_name=function_name,
            strategy_idx=strategy_idx,
        )
    return ev


def _run_numerical(
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    claim_equation: str | None,
    var_map: dict[str, str] | None,
    target_var: str | None,
    function_source: str | None = None,
    paper_section: str | None = None,
    function_name: str | None = None,
    strategy_idx: int | None = None,
) -> dict[str, Any]:
    latex = _require(claim_equation, "claim_equation", "numerical")
    vmap = _require(var_map, "var_map", "numerical")
    target = _require(target_var, "target_var", "numerical")

    ev = _empty_evidence("numerical", target)
    code_expr: Any = None
    try:
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
    except Exception as exc:
        ev["error"] = str(exc)
        ev["method_used"] = "failed"
        ev["raw_matcher_output"] = {"error": str(exc)}

    # T1.23 judge fallback. Inspects ``code_expr`` for opaque function
    # calls (trigger 4); otherwise fires on failed/not-found triggers.
    trigger = _should_run_judge(ev, code_expr)
    if trigger is not None:
        ev = _apply_judge(
            ev,
            paper_equation=latex,
            code_expr=code_expr,
            target_var=target,
            function_source=function_source,
            trigger=trigger,
            paper_section=paper_section,
            function_name=function_name,
            strategy_idx=strategy_idx,
        )
    return ev


def _run_structural(
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    filter_hyperparam: bool,
    function_source: str | None = None,
) -> dict[str, Any]:
    kind = "hyperparametric" if filter_hyperparam else "structural"
    ev = _empty_evidence(kind, None)
    raw_mismatches = structural_match.match_structure(paper_extract, code_extract)
    ev["raw_matcher_output"] = {"mismatches": raw_mismatches}
    # T1.27: drop ``hyperparam_missing_in_code`` rows whose paper-side
    # symbol does NOT lexically appear in the function-under-verification
    # source. Papers expose model-level hyperparams (Transformer's
    # ``N=6`` encoder/decoder stack depth, ``h=8`` heads) that are
    # genuinely outside the scope of a kernel-level function like
    # ``scaled_dot_product_attention``. Without this filter the
    # structural / hyperparametric strategies fire ``equivalent=False``
    # purely because the paper declared a hyperparam the function
    # doesn't (and shouldn't) reference.
    if function_source:
        raw_mismatches = _filter_irrelevant_hyperparams(raw_mismatches, function_source)
    if filter_hyperparam:
        filtered = [m for m in raw_mismatches if str(m.get("type", "")).startswith(_HP_PREFIX)]
    else:
        filtered = list(raw_mismatches)
    ev["mismatches"] = filtered
    ev["equivalent"] = len(filtered) == 0
    ev["method_used"] = None
    return ev


def _filter_irrelevant_hyperparams(
    mismatches: list[dict[str, Any]],
    function_source: str,
) -> list[dict[str, Any]]:
    """Drop ``hyperparam_missing_in_code`` rows whose symbol isn't in the function.

    A hyperparam declared at the paper / model level (e.g. ``N=6``,
    ``h=8`` for Transformer) is irrelevant to a function whose source
    never references it (e.g. ``scaled_dot_product_attention`` only
    cares about ``d_k``). Lexical word-boundary check.
    """
    out: list[dict[str, Any]] = []
    for m in mismatches:
        if str(m.get("type", "")) != "hyperparam_missing_in_code":
            out.append(m)
            continue
        loc = m.get("location") or {}
        sym = (loc.get("paper_hyperparam_symbol") or "").strip()
        if not sym:
            out.append(m)
            continue
        if re.search(rf"\b{re.escape(sym)}\b", function_source):
            out.append(m)
    return out


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


def _section_match(mismatch_location: Any, claim_section: str) -> bool:
    """Keep mismatches whose location is in ``claim_section`` (T1.13)."""
    if not isinstance(mismatch_location, dict):
        return False
    sec = mismatch_location.get("paper_section")
    if isinstance(sec, str) and sec == claim_section:
        return True
    algo = mismatch_location.get("paper_algorithm_name")
    if isinstance(algo, str) and claim_section in algo:
        return True
    return False


def run_strategy(
    strategy: Strategy,
    paper_extract: dict[str, Any],
    code_extract: dict[str, sp.Expr],
    *,
    claim_equation: str | None = None,
    var_map: dict[str, str] | None = None,
    target_var: str | None = None,
    claim_section: str | None = None,
    function_source: str | None = None,
    function_name: str | None = None,
    strategy_idx: int | None = None,
) -> dict[str, Any]:
    """Dispatch a verification strategy and return an evidence dict.

    See module docstring for the evidence shape and arg requirements.

    ``claim_section`` (added for T1.13) — when set, structural and
    hyperparametric mismatches whose ``location.paper_section`` is
    outside the claimed section are dropped before the equivalence
    decision and the Critic call. This stops AdaMax-style sibling
    sections from false-flagging a clean implementation (issue #3) and
    keeps the Critic from firing on filtered-out noise.
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
                function_source=function_source,
                paper_section=claim_section,
                function_name=function_name,
                strategy_idx=strategy_idx,
            )
        elif kind == "numerical":
            evidence = _run_numerical(
                paper_extract,
                code_extract,
                claim_equation=claim_equation,
                var_map=var_map,
                target_var=target_var,
                function_source=function_source,
                paper_section=claim_section,
                function_name=function_name,
                strategy_idx=strategy_idx,
            )
        elif kind == "structural":
            evidence = _run_structural(
                paper_extract,
                code_extract,
                filter_hyperparam=False,
                function_source=function_source,
            )
        elif kind == "hyperparametric":
            evidence = _run_structural(
                paper_extract,
                code_extract,
                filter_hyperparam=True,
                function_source=function_source,
            )
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

    if claim_section and kind in ("structural", "hyperparametric"):
        kept = [
            m for m in (evidence.get("mismatches") or []) if _section_match(m.get("location"), claim_section)
        ]
        evidence["mismatches"] = kept
        evidence["equivalent"] = len(kept) == 0

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
