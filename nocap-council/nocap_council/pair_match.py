# Owner: DEVIN — Phase 1 task T1.25 (v3 — decoupled Spec, Stage 6: pair-match)
"""Pair-match a paper claim against a code claim.

Bridges :func:`nocap_council.spec.extract_paper_claim` (paper side) and
:func:`nocap_council.code_claim.extract_code_claim` (code side) by
resolving each paper equation's LHS symbol to one of three buckets:

  * ``GATED`` — the LHS symbol is a function parameter on the code side
    (e.g. paper says ``g_t = \\nabla f(\\theta_{t-1})`` but the code's
    ``step`` receives ``g`` as input). External contract; not verifiable
    inside the function body.

  * ``PAIRED`` — a code computed_equation has the same LHS symbol. The
    matcher will run an equivalence check on the (paper_eq, code_eq)
    pair (sympy first, then LLM-judge fallback at the layer above).

  * ``UNMATCHED`` — no code-side counterpart. Caller decides what to do
    (typically: skip but record).

Pure deterministic logic. No LLM. The equivalence check itself stays in
``sympy_match.py`` / ``code.py`` — this module only resolves PAIRS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PairMatchEntry:
    paper_index: int
    paper_equation: str
    paper_lhs_symbol: str
    verdict: str  # "GATED" | "PAIRED" | "UNMATCHED"
    code_equation: str | None = None  # filled when verdict == "PAIRED"
    code_lhs_symbol: str | None = None
    code_target: str | None = None  # "_return" or code LHS symbol; matcher hint
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "paper_index": self.paper_index,
            "paper_equation": self.paper_equation,
            "paper_lhs_symbol": self.paper_lhs_symbol,
            "verdict": self.verdict,
            "code_equation": self.code_equation,
            "code_lhs_symbol": self.code_lhs_symbol,
            "code_target": self.code_target,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# LHS symbol resolution
# ---------------------------------------------------------------------------


_PAPER_ACCENT_PATTERNS = (
    # \widehat{name}_subscript -> name_hat
    (re.compile(r"\\widehat\{(\w+)\}_\w+"), r"\1_hat"),
    # \widehat{name} -> name_hat
    (re.compile(r"\\widehat\{(\w+)\}"), r"\1_hat"),
    # \hat{name}_subscript -> name_hat
    (re.compile(r"\\hat\{(\w+)\}_\w+"), r"\1_hat"),
    # \hat{name} -> name_hat
    (re.compile(r"\\hat\{(\w+)\}"), r"\1_hat"),
    # \tilde{name}_subscript -> name_tilde
    (re.compile(r"\\tilde\{(\w+)\}_\w+"), r"\1_tilde"),
    # \tilde{name} -> name_tilde
    (re.compile(r"\\tilde\{(\w+)\}"), r"\1_tilde"),
    # \bar{name}_subscript -> name_bar
    (re.compile(r"\\bar\{(\w+)\}_\w+"), r"\1_bar"),
    # \bar{name} -> name_bar
    (re.compile(r"\\bar\{(\w+)\}"), r"\1_bar"),
)


_TRAILING_SUBSCRIPT_RE = re.compile(r"_\{?[t0-9][^}]*\}?$")
_TRAILING_T_RE = re.compile(r"_t$")


def paper_lhs_to_symbol(equation: str) -> str:
    """Reduce a paper equation's LHS to a canonical bare symbol.

    Examples:
      ``\\widehat{m}_t = ...`` -> ``"m_hat"``
      ``\\hat{v}_t = ...``     -> ``"v_hat"``
      ``m_t = ...``            -> ``"m"``
      ``g_t = ...``            -> ``"g"``
      ``\\theta_t = ...``      -> ``"theta"``
      ``\\tilde\\beta_t = ...`` -> ``"beta_tilde"`` (best-effort)
    """
    lhs = equation.split("=", 1)[0].strip()
    for pattern, repl in _PAPER_ACCENT_PATTERNS:
        lhs = pattern.sub(repl, lhs)
    # Strip trailing temporal subscripts.
    lhs = _TRAILING_SUBSCRIPT_RE.sub("", lhs)
    lhs = _TRAILING_T_RE.sub("", lhs)
    # Drop any residual ``\\`` prefix (``\\theta`` -> ``theta``).
    lhs = lhs.lstrip("\\")
    # Strip ``\boldsymbol{...}`` / ``\mathbf{...}`` if any leaked through.
    lhs = re.sub(r"\\(?:boldsymbol|mathbf|mathrm)\{(\w+)\}", r"\1", lhs)
    return lhs.strip()


def code_lhs_to_symbol(equation: str) -> str:
    """Reduce a code equation's LHS to its bare attribute name.

    ``self.m = ...`` -> ``"m"``,  ``m_hat = ...`` -> ``"m_hat"``.
    """
    lhs = equation.split("=", 1)[0].strip()
    if lhs.startswith("self."):
        lhs = lhs[len("self."):]
    return lhs.strip()


# ---------------------------------------------------------------------------
# RHS symbol extraction (used for Jaccard return-value scoring)
# ---------------------------------------------------------------------------


# Math/LaTeX scaffolding tokens that don't carry semantic identity. These
# are stripped from the symbol set BEFORE Jaccard scoring so that
# ``\sqrt(\bar\alpha_t) x_0 + \sqrt(1-\bar\alpha_t) \epsilon`` doesn't
# match every other equation just because they all use ``sqrt``.
_RHS_NOISE_TOKENS = frozenset(
    {
        "sqrt",
        "frac",
        "left",
        "right",
        "cdot",
        "exp",
        "log",
        "sin",
        "cos",
        "max",
        "min",
        "sum",
        "prod",
        "int",
        "norm",
        "abs",
        "boldsymbol",
        "mathbf",
        "mathrm",
        "mathcal",
        "mathbb",
        "operatorname",
        "text",
        "Sigma",
        "sigma",
        "lambda",
        "phi",
        "psi",
        "rho",
        "tau",
        "dtype",
        "float64",
        "float32",
        "np",
        "torch",
        "asarray",
        "zeros_like",
        "ones_like",
        "linspace",
        "tensor",
        "self",
        "shape",
        "device",
        "to",
        "view",
        "reshape",
        "unsqueeze",
        "gather",
        "_gather",
        "and",
        "or",
        "not",
        "if",
        "else",
        "for",
        "in",
        "return",
    }
)


def _extract_rhs_symbols(equation: str) -> set[str]:
    """Return the bag-of-symbols of an equation's RHS (or whole expr).

    Used by the Jaccard scorer when pairing deferred paper equations
    against the function's return expression. The goal is "do these two
    expressions reference the same set of variables" — names like
    ``alpha``, ``beta``, ``x_0``, ``epsilon``, ``noise`` survive; LaTeX
    scaffolding (``sqrt``, ``frac``, ``left``, ``right``) and Python/
    NumPy plumbing (``np``, ``asarray``, ``self``, ``dtype``) are
    filtered out.
    """
    if not equation:
        return set()
    if "=" in equation:
        rhs = equation.split("=", 1)[1]
    else:
        rhs = equation

    text = rhs

    # Flatten LaTeX accents to ``name_hat`` / ``name_tilde`` /
    # ``name_bar`` so e.g. ``\bar\alpha`` and ``alpha_bar`` collide on
    # the canonical token ``alpha_bar``.
    text = re.sub(r"\\widehat\{(\w+)\}", r"\1_hat", text)
    text = re.sub(r"\\hat\{(\w+)\}", r"\1_hat", text)
    text = re.sub(r"\\hat([A-Za-z]+)", r"\1_hat", text)
    text = re.sub(r"\\tilde\{(\w+)\}", r"\1_tilde", text)
    text = re.sub(r"\\tilde\\?(\w+)", r"\1_tilde", text)
    text = re.sub(r"\\bar\{(\w+)\}", r"\1_bar", text)
    text = re.sub(r"\\bar\\?(\w+)", r"\1_bar", text)

    # Drop styling wrappers entirely (``\boldsymbol{x}`` -> ``x``).
    text = re.sub(r"\\(?:boldsymbol|mathbf|mathrm)\{(\w+)\}", r"\1", text)

    # Strip remaining backslashes so ``\alpha`` -> ``alpha``,
    # ``\epsilon`` -> ``epsilon``.
    text = text.replace("\\", "")

    # Tokenize: alphanumeric runs (allow underscores).
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    raw = {t for t in tokens if not t.isdigit()}

    # Drop noise tokens but KEEP plain Greek/algebraic identifiers.
    return {t for t in raw if t not in _RHS_NOISE_TOKENS}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity: |A ∩ B| / |A ∪ B| (0 when both empty)."""
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    if not union:
        return 0.0
    return len(inter) / len(union)


# ---------------------------------------------------------------------------
# Pair resolver
# ---------------------------------------------------------------------------


def pair_match(paper_claim: dict, code_claim: dict) -> list[PairMatchEntry]:
    """Resolve each paper claimed_equation to GATED/PAIRED/UNMATCHED.

    Two-pass resolver:

    1. **LHS equality pass.** For each paper equation, if its LHS
       symbol is a function parameter -> ``GATED``; if it matches a
       code computed_equation LHS -> ``PAIRED`` (``code_target`` set
       to the code-side LHS symbol). Otherwise the equation is
       ``DEFERRED`` for pass 2.

    2. **Return-value Jaccard pass.** Among deferred equations, score
       each one's RHS symbol set against the function's return value
       symbol set (Jaccard = |∩| / |∪|). The single best-scoring
       deferred equation is paired against ``_return``
       (``code_target="_return"``); all others become ``UNMATCHED``.

       This is what makes pair-match work for "function returns inline
       expression with no named LHS" cases like DDPM's ``q_sample``,
       which returns ``sqrt_alpha_bar * x0 + sqrt_one_minus_alpha_bar
       * noise`` without ever assigning to a local ``x_t``. Among the
       three DDPM paper equations whose LHS is ``x_t`` (one-step
       forward, closed-form, posterior reparam), only the closed-form
       has high RHS overlap with the return expression — so only that
       one is paired, and the other two are correctly excluded from
       the matcher.

    A score floor of 0 means: if the best deferred equation has zero
    variable overlap with the return value, nothing pairs and
    everything stays ``UNMATCHED`` (no false positives from forcing a
    bad pairing).

    Returns a list of :class:`PairMatchEntry` aligned with
    ``paper_claim["claimed_equations"]`` (one entry per paper
    equation, in input order).
    """
    code_params = set(code_claim.get("parameters") or [])
    code_equations: list[str] = list(code_claim.get("computed_equations") or [])
    return_value: str = (code_claim.get("return_value") or "").strip()

    # Index code equations by LHS symbol for O(1) lookup. Last write
    # wins — last assignment to a given LHS in the function body is
    # what the matcher ultimately reads.
    code_by_lhs: dict[str, str] = {}
    for code_eq in code_equations:
        sym = code_lhs_to_symbol(code_eq)
        code_by_lhs[sym] = code_eq

    # Pass 1: LHS-equality resolution.
    entries: list[PairMatchEntry] = []
    deferred_indices: list[int] = []
    for i, paper_eq in enumerate(paper_claim.get("claimed_equations") or []):
        sym = paper_lhs_to_symbol(paper_eq)
        if sym in code_params:
            entries.append(
                PairMatchEntry(
                    paper_index=i,
                    paper_equation=paper_eq,
                    paper_lhs_symbol=sym,
                    verdict="GATED",
                    detail=f"`{sym}` is a function parameter — external contract",
                )
            )
            continue
        code_eq = code_by_lhs.get(sym)
        if code_eq is not None:
            entries.append(
                PairMatchEntry(
                    paper_index=i,
                    paper_equation=paper_eq,
                    paper_lhs_symbol=sym,
                    verdict="PAIRED",
                    code_equation=code_eq,
                    code_lhs_symbol=code_lhs_to_symbol(code_eq),
                    code_target=code_lhs_to_symbol(code_eq),
                    detail="paper LHS matches a code computed_equation LHS",
                )
            )
            continue
        # Defer: maybe this equation pairs against the function's
        # return value. Mark UNMATCHED for now; pass 2 may upgrade it.
        deferred_indices.append(len(entries))
        entries.append(
            PairMatchEntry(
                paper_index=i,
                paper_equation=paper_eq,
                paper_lhs_symbol=sym,
                verdict="UNMATCHED",
                detail=f"no code computed_equation has LHS `{sym}`",
            )
        )

    # Pass 2: among deferred equations, the single one whose RHS has
    # the most variable overlap with the function's return expression
    # is paired against ``_return``.
    if return_value and deferred_indices:
        return_symbols = _extract_rhs_symbols(return_value)
        if return_symbols:
            scored: list[tuple[float, int]] = []
            for ent_idx in deferred_indices:
                paper_rhs_symbols = _extract_rhs_symbols(
                    entries[ent_idx].paper_equation
                )
                score = _jaccard(paper_rhs_symbols, return_symbols)
                scored.append((score, ent_idx))
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best_idx = scored[0]
            if best_score > 0.0:
                e = entries[best_idx]
                e.verdict = "PAIRED"
                e.code_equation = f"_return = {return_value}"
                e.code_lhs_symbol = "_return"
                e.code_target = "_return"
                e.detail = (
                    f"paired against function return value via RHS-Jaccard "
                    f"score={best_score:.2f} (no LHS match for `{e.paper_lhs_symbol}`)"
                )
                # Mark the losers explicitly so the trace says why they
                # were not picked.
                for score, ent_idx in scored[1:]:
                    if entries[ent_idx].verdict == "UNMATCHED":
                        entries[ent_idx].detail = (
                            f"deferred to return-value contest; "
                            f"lost to paper_index={entries[best_idx].paper_index} "
                            f"(score={score:.2f} < {best_score:.2f})"
                        )

    return entries


def format_pair_match_table(entries: list[PairMatchEntry]) -> str:
    """Pretty-print the pair-match table for logging/debugging."""
    lines = [
        f"{'idx':<4} {'paper_lhs':<14} {'verdict':<12} {'detail'}",
        "-" * 100,
    ]
    for e in entries:
        head = f"{e.paper_index:<4} {e.paper_lhs_symbol:<14} {e.verdict:<12}"
        if e.verdict == "PAIRED":
            paper_short = (e.paper_equation or "")[:60]
            code_short = (e.code_equation or "")[:60]
            lines.append(f"{head} paper: {paper_short}")
            lines.append(f"{'':<4} {'':<14} {'':<12} code:  {code_short}")
        else:
            lines.append(f"{head} {e.detail}")
    return "\n".join(lines)
