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
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "paper_index": self.paper_index,
            "paper_equation": self.paper_equation,
            "paper_lhs_symbol": self.paper_lhs_symbol,
            "verdict": self.verdict,
            "code_equation": self.code_equation,
            "code_lhs_symbol": self.code_lhs_symbol,
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
# Pair resolver
# ---------------------------------------------------------------------------


def pair_match(paper_claim: dict, code_claim: dict) -> list[PairMatchEntry]:
    """Resolve each paper claimed_equation to one of GATED/PAIRED/UNMATCHED.

    Returns a list of :class:`PairMatchEntry` aligned with
    ``paper_claim["claimed_equations"]`` (one entry per paper equation,
    in order).
    """
    code_params = set(code_claim.get("parameters") or [])
    code_equations: list[str] = list(code_claim.get("computed_equations") or [])

    # Index code equations by LHS symbol for O(1) lookup.
    code_by_lhs: dict[str, str] = {}
    for code_eq in code_equations:
        sym = code_lhs_to_symbol(code_eq)
        # Last write wins — last assignment to a given LHS in the
        # function body is what the matcher ultimately reads.
        code_by_lhs[sym] = code_eq

    entries: list[PairMatchEntry] = []
    for i, paper_eq in enumerate(paper_claim.get("claimed_equations") or []):
        sym = paper_lhs_to_symbol(paper_eq)
        if sym in code_params:
            entries.append(
                PairMatchEntry(
                    paper_index=i,
                    paper_equation=paper_eq,
                    paper_lhs_symbol=sym,
                    verdict="GATED",
                    detail=f"`{sym}` is a function parameter — external contract, not internally computed",
                )
            )
            continue
        code_eq = code_by_lhs.get(sym)
        if code_eq is None:
            entries.append(
                PairMatchEntry(
                    paper_index=i,
                    paper_equation=paper_eq,
                    paper_lhs_symbol=sym,
                    verdict="UNMATCHED",
                    detail=f"no code computed_equation has LHS `{sym}`",
                )
            )
            continue
        entries.append(
            PairMatchEntry(
                paper_index=i,
                paper_equation=paper_eq,
                paper_lhs_symbol=sym,
                verdict="PAIRED",
                code_equation=code_eq,
                code_lhs_symbol=code_lhs_to_symbol(code_eq),
                detail="paper LHS matches a code computed_equation LHS",
            )
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
