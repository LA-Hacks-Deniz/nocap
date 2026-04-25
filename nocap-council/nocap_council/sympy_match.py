# Owner: DEVIN — Phase 1 task T1.5
"""LaTeX -> SymPy matcher for the No Cap polygraph.

Pairs with ``code_extract.py`` (T1.4): T1.4 turns the agent's Python
implementation into a ``{name: sympy.Expr}`` dict; this module turns a
paper LaTeX equation into a ``sympy.Expr`` and decides whether the two
agree.

Public API
----------

``latex_to_sympy(s: str, var_map: dict[str, str] | None = None) -> sympy.Expr``
    Parse a LaTeX equation to a SymPy expression. Pipeline:

    1. **Accent flattening.** Regex-rewrite ``\\hat{m}_t`` to ``m_hat_t``
       (and similar for the other accents in the whitelist) so SymPy's
       ``parse_latex`` doesn't choke on accents.
    2. **var_map substitution.** Apply each ``paper_string -> code_string``
       replacement in the dict, **longest-key-first** (so ``m_hat_t``
       resolves before ``m_t`` and prefix collisions can't happen).
       The keys may contain LaTeX commands like ``\\beta_1`` — the
       value side is the bare code-side identifier.
    3. **Multi-letter -> Greek placeholder.** SymPy's ``parse_latex``
       (both ANTLR and Lark backends) cannot handle multi-letter
       identifiers — ``m_hat`` is tokenized as ``m_{h}*a*t``. Workaround:
       each multi-letter identifier in the post-var_map source is
       replaced by a fresh ``\\alpha``/``\\beta``/``\\gamma``/... command
       from a fixed pool (``_GREEK_POOL`` below). Letters that already
       appear in the LaTeX are skipped to avoid name collisions; if the
       pool is exhausted, ``LaTeXMultiLetterError`` is raised.
    4. ``parse_latex`` does the actual parse.
    5. ``sympy.subs`` swaps each placeholder symbol back to a
       ``Symbol`` named after the original multi-letter identifier.

    The returned expression is either a bare ``sympy.Expr`` (when the
    LaTeX has no ``=``) or a ``sympy.Eq(lhs, rhs)``.

``match_equation(latex: str, code: dict[str, sympy.Expr], var_map: dict[str, str], target_var: str) -> dict``
    Compare a paper equation to a code expression. Returns
    ``{equivalent: bool, residual: sympy.Expr | None, method_used: str}``.

    ``code`` is the dict produced by ``code_extract.code_to_sympy``;
    ``target_var`` is the key into it (e.g. ``"m_hat"``). When
    ``latex`` contains ``=``, the right-hand side is compared; the
    left-hand side is ignored. When it doesn't, the whole expression
    is treated as the right-hand side.

    Method selection:

    - ``"symbolic"`` — ``sympy.simplify(paper.rhs - code.expr) == 0``
      (the cheapest path; covers the clean Adam case).
    - ``"numerical"`` — symbolic returned non-zero residual but
      ``sympy.Expr.equals`` (which itself does heuristic simplification
      *plus* random-point sampling) confirmed equality. *Or* the
      hand-rolled 5-sample loop in ``[0.1, 2.0]`` (seed 0, ``rtol=1e-9``)
      found a counterexample and returned ``equivalent=False``.
    - ``"failed"`` — every numerical sample raised (``TypeError`` /
      ``ZeroDivisionError``) so we couldn't decide.

    Residual: ``None`` on equality; ``sympy.simplify(paper.rhs - code.expr)``
    (un-cancelled, human-readable) on inequality.

Conventions / gotchas (relevant for T1.10 / T1.11)
--------------------------------------------------

- **Subscripted code symbols** like ``Symbol("theta[t - 1]")`` (produced
  by T1.4 from Python ``theta[t-1]``) won't be auto-bridged from a
  paper's ``\\theta_{t-1}``. The current contract is: the var_map must
  spell out the equivalence (e.g. ``{r"\\theta_{t-1}": "theta[t - 1]"}``).
  This is brittle and worth revisiting once a real paper exercises it.
- **Floats vs Integers.** ``code_extract`` emits ``sp.Float(1.0)``
  (because Python ``1.0`` literal); LaTeX gets ``sp.Integer(1)``.
  ``sympy.simplify`` collapses the difference, so this isn't a problem
  in practice — just don't be surprised that the residual sometimes
  carries one or the other depending on which side won.
- **Equivalent reformulations** can defeat ``simplify``; the numerical
  fallback rescues most of them. ``a/b - c/b`` may not symbolically
  simplify but will sample-equal. See [H3] §1 for the underlying
  caveats.

Worked example — Adam's bias-corrected first moment
---------------------------------------------------

Paper: ``\\hat{m}_t = m_t / (1 - \\beta_1^t)``.
Code clean: ``self.m / (1 - beta1 ** t)`` -> ``code["m_hat"] = m / (1.0 - beta1**t)``.
Code buggy: ``self.m`` -> ``code["m_hat"] = m``.

::

    var_map = {"m_hat_t": "m_hat", "m_t": "m", r"\\beta_1": "beta1"}
    match_equation(latex, clean_env, var_map, "m_hat")
    # {"equivalent": True,  "residual": None, "method_used": "symbolic"}

    match_equation(latex, buggy_env, var_map, "m_hat")
    # {"equivalent": False,
    #  "residual": -beta1**t*m/(beta1**t - 1),  # == m * beta1**t / (1 - beta1**t)
    #  "method_used": "numerical"}

The residual itself is the explanation: clean code matches paper;
buggy code is "wrong by a factor of ``beta1**t / (1 - beta1**t)``".
Run ``python -m nocap_council.sympy_match`` to see this end-to-end.
"""

from __future__ import annotations

import re

import numpy as np
import sympy as sp
from sympy.parsing.latex import parse_latex

__all__ = [
    "LaTeXMultiLetterError",
    "latex_to_sympy",
    "match_equation",
]


# Accents that ``parse_latex`` cannot handle directly. Each accent
# wraps a single token (which is what shows up in real ML papers); the
# regex preprocessor below rewrites ``\hat{m}_t`` -> ``m_hat_t`` and
# ``\hat{m}`` -> ``m_hat``.
_ACCENTS: tuple[str, ...] = (
    "hat",
    "tilde",
    "bar",
    "dot",
    "vec",
    "mathbf",
    "boldsymbol",
    "widehat",
    "overline",
    "overrightarrow",
)

# Greek-letter pool for multi-letter -> single-letter substitution.
# Order matters only for determinism — we hand them out in this order
# (skipping any that already appear as LaTeX commands in the source).
_GREEK_POOL: tuple[str, ...] = (
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "omicron",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "chi",
    "psi",
    "omega",
)


class LaTeXMultiLetterError(RuntimeError):
    """Raised when the Greek placeholder pool can't cover a LaTeX source.

    The current pool is 24 names long. A paper that uses more than 24
    distinct multi-letter identifiers in a single equation is well
    outside our scope — by the time that happens, parsing the LaTeX is
    not the bottleneck.
    """


def _flatten_accents(s: str) -> str:
    """Rewrite ``\\hat{m}_t`` -> ``m_hat_t`` and ``\\hat{m}`` -> ``m_hat``.

    Operates left-to-right on each accent name in ``_ACCENTS``. Both
    forms (with and without trailing subscript) are matched per accent;
    only single-token arguments (``\\w+``) are rewritten — nested
    accents like ``\\hat{\\bar{x}}`` are not handled, which mirrors the
    [H3] §2 reference.
    """
    for tex in _ACCENTS:
        # \hat{name}_sub -> name_<accent>_sub
        s = re.sub(rf"\\{tex}\{{(\w+)\}}_(\w+)", rf"\1_{tex}_\2", s)
        # \hat{name}     -> name_<accent>
        s = re.sub(rf"\\{tex}\{{(\w+)\}}", rf"\1_{tex}", s)
    return s


def _apply_var_map(s: str, var_map: dict[str, str] | None) -> str:
    """Replace each ``var_map`` key with its value, longest-first.

    Longest-key-first ordering prevents partial-prefix collisions:
    ``m_hat_t`` must replace before ``m_t`` so the latter doesn't
    chew up part of the former.
    """
    if not var_map:
        return s
    for key in sorted(var_map.keys(), key=len, reverse=True):
        s = s.replace(key, var_map[key])
    return s


# Multi-letter identifier: starts with a letter or underscore, contains
# letters / underscores / digits, length >= 2. The lookbehind keeps us
# from matching mid-word; the lookahead does the same for the right
# side.
_MULTI_IDENT_RE = re.compile(r"(?<![A-Za-z_0-9\\])([A-Za-z_][A-Za-z_0-9]*)(?![A-Za-z_0-9])")


def _allocate_greek_placeholders(s: str, multi_idents: list[str]) -> dict[str, str]:
    """Pick a Greek LaTeX command for each multi-letter identifier.

    Skips Greek letters whose ``\\name`` form already appears in ``s``
    so we never collide with a real Greek letter the paper used (e.g.
    a literal ``\\alpha = 0.001``). Raises ``LaTeXMultiLetterError`` if
    the pool runs out.
    """
    in_use: set[str] = set()
    for greek in _GREEK_POOL:
        if re.search(rf"\\{greek}(?![A-Za-z])", s) is not None:
            in_use.add(greek)
    available = [g for g in _GREEK_POOL if g not in in_use]
    if len(multi_idents) > len(available):
        raise LaTeXMultiLetterError(
            f"need {len(multi_idents)} placeholders but only "
            f"{len(available)} Greek slots are free "
            f"(in-use: {sorted(in_use)})"
        )
    return dict(zip(multi_idents, available, strict=False))


def _rewrite_multi_letter(s: str) -> tuple[str, dict[str, str]]:
    """Substitute multi-letter identifiers with Greek LaTeX commands.

    Returns (rewritten_source, ``{ident: greek_name}``). The rewritten
    source uses ``\\alpha`` / ``\\beta`` / ... in place of each
    multi-letter identifier; the caller is expected to feed it through
    ``parse_latex`` then sympy.subs the placeholder Symbols back to
    real names.
    """
    # Order: deterministic by sort, longest-first so e.g. ``beta1`` is
    # found before ``beta`` would otherwise eat its prefix.
    found = {m.group(1) for m in _MULTI_IDENT_RE.finditer(s)}
    multi_idents = sorted((x for x in found if len(x) > 1), key=lambda v: (-len(v), v))
    if not multi_idents:
        return s, {}
    placeholders = _allocate_greek_placeholders(s, multi_idents)
    out = s
    for ident, greek in placeholders.items():
        out = re.sub(
            rf"(?<![A-Za-z_0-9\\])({re.escape(ident)})(?![A-Za-z_0-9])",
            r"\\" + greek,
            out,
        )
    return out, placeholders


def latex_to_sympy(s: str, var_map: dict[str, str] | None = None) -> sp.Expr:
    """Parse a LaTeX equation string to a SymPy expression.

    See module docstring for the full pipeline. ``var_map`` keys are
    matched verbatim (after accent flattening) and replaced with their
    values — the values become the SymPy symbol names that downstream
    matching uses.
    """
    flat = _flatten_accents(s)
    mapped = _apply_var_map(flat, var_map)
    rewritten, placeholders = _rewrite_multi_letter(mapped)
    parsed = parse_latex(rewritten)
    if not placeholders:
        return parsed
    sub_map = {sp.Symbol(greek): sp.Symbol(ident) for ident, greek in placeholders.items()}
    return parsed.subs(sub_map)


def _split_lhs_rhs(parsed: sp.Expr) -> sp.Expr:
    """Return the right-hand side of an Eq, or the expression itself."""
    if isinstance(parsed, sp.Equality):
        return parsed.rhs
    return parsed


# Numerical fallback constants. See [H3] §5 for rationale.
_NUMERIC_SAMPLES: int = 5
_NUMERIC_LO: float = 0.1
_NUMERIC_HI: float = 2.0
_NUMERIC_SEED: int = 0
_NUMERIC_RTOL: float = 1e-9


def _numeric_equal(a: sp.Expr, b: sp.Expr) -> tuple[bool | None, str]:
    """Five-sample numeric equivalence check.

    Returns ``(verdict, method)`` where verdict is ``True``/``False`` if
    we got a definitive answer and ``None`` if every sample raised.
    Method is always ``"numerical"`` (or ``"failed"`` for the all-raise
    case). Samples are drawn from ``[_NUMERIC_LO, _NUMERIC_HI]`` with a
    fixed seed for reproducibility. Skips samples that hit a
    ``TypeError`` or ``ZeroDivisionError``.
    """
    syms = sorted(a.free_symbols | b.free_symbols, key=lambda x: x.name)
    rng = np.random.default_rng(_NUMERIC_SEED)
    saw_any = False
    for _ in range(_NUMERIC_SAMPLES):
        sub = {s: float(rng.uniform(_NUMERIC_LO, _NUMERIC_HI)) for s in syms}
        try:
            av = float(a.subs(sub))
            bv = float(b.subs(sub))
        except (TypeError, ZeroDivisionError, ValueError):
            continue
        saw_any = True
        if not np.isclose(av, bv, rtol=_NUMERIC_RTOL):
            return False, "numerical"
    if not saw_any:
        return None, "failed"
    return True, "numerical"


def match_equation(
    latex: str,
    code: dict[str, sp.Expr],
    var_map: dict[str, str],
    target_var: str,
) -> dict:
    """Decide whether ``code[target_var]`` equals the paper's RHS.

    See module docstring for the full contract. Raises ``KeyError`` if
    ``target_var`` is not in ``code``.
    """
    if target_var not in code:
        raise KeyError(f"target_var {target_var!r} not in code env (have: {sorted(code.keys())})")
    code_expr = code[target_var]
    paper = latex_to_sympy(latex, var_map)
    paper_rhs = _split_lhs_rhs(paper)

    # Cheapest path: simplify(paper - code) == 0.
    try:
        residual = sp.simplify(paper_rhs - code_expr)
    except Exception:
        # If sympy itself blows up on simplify (rare but possible for
        # exotic inputs), fall through to the numerical path.
        residual = paper_rhs - code_expr
    if residual == 0:
        return {"equivalent": True, "residual": None, "method_used": "symbolic"}

    # Slightly more powerful path: Expr.equals does its own internal
    # simplification + numerical sampling at random complex points.
    try:
        equals_verdict = paper_rhs.equals(code_expr)
    except Exception:
        equals_verdict = None
    if equals_verdict is True:
        return {"equivalent": True, "residual": None, "method_used": "numerical"}

    # Last line: explicit 5-sample loop in [0.1, 2.0]. Catches the
    # buggy-Adam case and any other input where simplify left a
    # non-zero residual.
    verdict, method = _numeric_equal(paper_rhs, code_expr)
    if verdict is None:
        return {"equivalent": False, "residual": residual, "method_used": "failed"}
    if verdict:
        return {"equivalent": True, "residual": None, "method_used": method}
    return {"equivalent": False, "residual": residual, "method_used": method}


def _run_adam_demo() -> int:
    """Worked Adam example — see phases/phase-1.md §T1.5 acceptance."""
    # Paper: \hat{m}_t = m_t / (1 - \beta_1^t). Hardcoded per chat;
    # the paper_extract path is T1.16's job.
    LATEX = r"\hat{m}_t = m_t / (1 - \beta_1^t)"
    # var_map keys are post-flatten (so \hat{m}_t becomes m_hat_t in
    # the source the var_map sees).
    var_map = {
        "m_hat_t": "m_hat",
        "m_t": "m",
        r"\beta_1": "beta1",
    }
    target = "m_hat"

    # Late import so the module has zero internal cycles at import
    # time — this matters once T1.10 / T1.11 import sympy_match.
    from nocap_council.code_extract import code_to_sympy

    repo_root = _find_repo_root()
    clean_src = (repo_root / "benchmark" / "implementations" / "adam_clean.py").read_text()
    buggy_src = (repo_root / "benchmark" / "implementations" / "adam_buggy.py").read_text()
    clean_env = code_to_sympy(clean_src, "step")
    buggy_env = code_to_sympy(buggy_src, "step")

    paper = latex_to_sympy(LATEX, var_map)
    print("paper LaTeX     :", LATEX)
    print("paper SymPy     :", paper)
    print("var_map         :", var_map)
    print("target_var      :", target)
    print()

    print("--- adam_clean ---")
    print(f"code[{target!r}]    :", clean_env[target])
    clean_result = match_equation(LATEX, clean_env, var_map, target)
    for k, v in clean_result.items():
        print(f"  {k:<13s} : {v}")
    print()

    print("--- adam_buggy ---")
    print(f"code[{target!r}]    :", buggy_env[target])
    buggy_result = match_equation(LATEX, buggy_env, var_map, target)
    for k, v in buggy_result.items():
        print(f"  {k:<13s} : {v}")
    print()

    # Acceptance assertions per phases/phase-1.md §T1.5.
    assert clean_result["equivalent"] is True, f"clean should be equivalent, got {clean_result}"
    assert clean_result["residual"] is None
    assert buggy_result["equivalent"] is False, f"buggy should NOT be equivalent, got {buggy_result}"
    assert buggy_result["residual"] is not None

    # Phase doc says residual should be `m * beta1**t / (1 - beta1**t)`
    # (or sympy-equivalent). Simplify(diff) is the canonical equivalence
    # test; any sympy-equivalent form satisfies the spec.
    expected_residual = (
        sp.Symbol("m") * sp.Symbol("beta1") ** sp.Symbol("t") / (1 - sp.Symbol("beta1") ** sp.Symbol("t"))
    )
    diff = sp.simplify(buggy_result["residual"] - expected_residual)
    assert diff == 0, (
        f"buggy residual {buggy_result['residual']} not sympy-equivalent "
        f"to expected {expected_residual} (simplify(diff)={diff})"
    )

    print("ACCEPTANCE: clean=equivalent, buggy=not-equivalent with expected residual.")
    return 0


def _find_repo_root():
    """Walk up from this file until we find ``benchmark/implementations``.

    The Adam fixtures live at the repo root; this module ships inside
    ``nocap-council/nocap_council/`` so we have to climb two parents.
    """
    from pathlib import Path

    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "benchmark" / "implementations").is_dir():
            return ancestor
    raise FileNotFoundError("could not locate repo root with benchmark/implementations/")


if __name__ == "__main__":
    raise SystemExit(_run_adam_demo())
