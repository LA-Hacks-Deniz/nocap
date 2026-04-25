# Owner: DEVIN — Phase 1 task T1.26 (LLM-based pair-match)
"""Pair-match a paper claim against a code claim.

Bridges :func:`nocap_council.spec.extract_paper_claim` (paper side) and
:func:`nocap_council.code_claim.extract_code_claim` (code side) by
resolving each paper equation to one of three buckets:

  * ``GATED`` — the LHS symbol is a function parameter on the code side
    (e.g. paper says ``g_t = \\nabla f(\\theta_{t-1})`` but the code's
    ``step`` receives ``g`` as input). External contract; not verifiable
    inside the function body.

  * ``PAIRED`` — a code computed_equation, initial_condition, or the
    function's return value implements the paper equation. The matcher
    will run an equivalence check on the (paper_eq, code_eq) pair.

  * ``UNMATCHED`` — paper-internal intermediate; no code-side
    counterpart at all. Caller decides what to do (typically: skip).

Two-stage resolver:

1. **LHS equality fast path** (deterministic, no LLM). For each paper
   equation, if its LHS symbol matches a code parameter -> ``GATED``;
   if it matches a code computed_equation LHS -> ``PAIRED``. This
   resolves all six Adam equations with zero LLM cost.

2. **LLM pair-match** for whatever the fast path defers (when the
   function returns its result inline rather than naming a local LHS,
   or when paper/code use different naming conventions). One Gemma call
   classifies all deferred equations against the code claim in a single
   batch and emits structured JSON. This is what lets DDPM's q_sample
   pair its closed-form return expression against paper equation [2]
   while correctly skipping the one-step-forward and posterior-reparam
   rows that share the same paper LHS symbol.

The equivalence check itself stays in ``sympy_match.py`` / ``code.py``
— this module only resolves which paper equation pairs to which code
target.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass

from nocap_council import client


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
# LLM-based resolver for deferred equations
# ---------------------------------------------------------------------------


_LLM_PAIR_MATCH_SYSTEM = (
    "You are a paper-to-code pair-matcher. You receive a list of paper "
    "equations whose LHS symbols did not match any code-side LHS, plus "
    "the full code claim (parameters, precomputed coefficients in "
    "__init__, computed equations in the function body, and the return "
    "expression). For EACH paper equation, decide which (if any) code "
    "element implements it. Output strict JSON only — no prose, no "
    "markdown fences."
)


_LLM_PAIR_MATCH_INSTRUCTION = """
### Task

For each DEFERRED paper equation in the input, decide its verdict:

- `"PAIRED_RETURN"` — the paper equation describes what the function
  RETURNS. The code computes the same quantity inline in the return
  expression (possibly via different names: `x_0` ↔ `x0`, `\\epsilon` ↔
  `noise`, `\\bar\\alpha_t` ↔ `bar_alphas[t]` ↔ `sqrt_bar` after
  substitution). Set `code_target = "_return"`.

- `"PAIRED_INIT"` — the paper equation describes a coefficient that the
  code precomputes in `__init__` (e.g. `\\tilde\\beta_t = ...` ↔
  `self.posterior_variance = ...`). Set `code_target` to the code-side
  attribute name (e.g. `"posterior_variance"`).

- `"PAIRED_LOCAL"` — the paper equation matches a code computed_equation
  with a different LHS name (rare; usually the LHS-equality fast path
  catches this). Set `code_target` to the code LHS symbol.

- `"UNMATCHED"` — the paper equation is a paper-internal intermediate
  (a definitional shorthand, a notational identity, or a quantity used
  in the derivation but never realized in code). No code counterpart.

### Disambiguation rules

1. **Multiple paper equations sharing the same LHS symbol** (e.g. three
   DDPM rows all written `x_t = ...`): at most ONE of them can pair
   against the function's return. Pick the one whose RHS variables
   actually appear in the return expression (after accounting for
   alias differences). Mark the others UNMATCHED.

2. **`\\mathbf{I}` or other malformed terms** in a paper equation
   (e.g. an identity matrix where a noise sample should be): treat the
   equation as malformed and mark it UNMATCHED unless there is a clear
   alias-aware match against the code.

3. **Paper-side function-call LHS** (e.g. `\\mu_\\theta(x_t, t) = ...`):
   look for a code-side equation that defines the same quantity by any
   name. If only intermediate, mark UNMATCHED.

4. **Loss equations** (`L_{t-1} = ...`): pair with the function's
   return ONLY if the function actually computes a loss. Otherwise
   UNMATCHED.

### Output schema (strict)

Return a JSON object of EXACTLY this shape:

{
  "pairings": [
    {
      "paper_index": <int>,
      "verdict": "PAIRED_RETURN" | "PAIRED_INIT" | "PAIRED_LOCAL" | "UNMATCHED",
      "code_target": <string or null>,
      "alias_map": {<paper symbol>: <code symbol>, ...},
      "rationale": <one short sentence>
    }
  ]
}

- One entry per DEFERRED paper equation, in the same order they were
  presented in the input.
- `paper_index` MUST equal the input index given.
- `code_target`: required when verdict starts with PAIRED; otherwise null.
- `alias_map`: paper-side symbols on left, code-side names on right.
  Empty object {} if none. Only include symbols actually used in the
  pairing (don't dump the whole vocabulary).
- `rationale`: one terse sentence (max ~20 words). No prose explanations.
- ENFORCE: at most ONE PAIRED_RETURN across all entries. Multiple
  PAIRED_RETURN responses are a violation; you will be re-prompted.

Return JSON only.
"""


_LLM_PAIR_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "pairings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_index": {"type": "integer"},
                    "verdict": {"type": "string"},
                    "code_target": {"type": ["string", "null"]},
                    "alias_map": {"type": "object"},
                    "rationale": {"type": "string"},
                },
                "required": ["paper_index", "verdict"],
            },
        }
    },
    "required": ["pairings"],
}


def _format_deferred_for_prompt(
    deferred: list[tuple[int, str, str]],
    code_claim: dict,
) -> str:
    """Render the deferred equations + full code claim as a prompt body."""
    lines: list[str] = []
    lines.append("### Code claim")
    lines.append(f"function_name: {code_claim.get('function_name', '')}")
    params = code_claim.get("parameters") or []
    lines.append(f"parameters: {params}")
    init = code_claim.get("initial_conditions") or []
    if init:
        lines.append("initial_conditions (precomputed in __init__):")
        for eq in init:
            lines.append(f"  - {eq}")
    computed = code_claim.get("computed_equations") or []
    if computed:
        lines.append("computed_equations (function body):")
        for eq in computed:
            lines.append(f"  - {eq}")
    rv = (code_claim.get("return_value") or "").strip()
    if rv:
        lines.append(f"return_value: {rv}")
    lines.append("")
    lines.append("### Deferred paper equations to classify")
    for paper_index, paper_lhs, paper_eq in deferred:
        lines.append(f"  [{paper_index}] paper_lhs=`{paper_lhs}`  eq: {paper_eq}")
    return "\n".join(lines)


def _resolve_deferred_via_llm(
    deferred_indices: list[int],
    entries: list[PairMatchEntry],
    code_claim: dict,
) -> None:
    """Mutate `entries`: upgrade deferred UNMATCHED rows to PAIRED via LLM.

    On any error the deferred entries are left as-is (UNMATCHED), so a
    transient API failure simply means we lose pair-match resolution
    for that run — never a wrong pairing.
    """
    if not deferred_indices:
        return
    deferred_payload = [
        (
            entries[ent_idx].paper_index,
            entries[ent_idx].paper_lhs_symbol,
            entries[ent_idx].paper_equation,
        )
        for ent_idx in deferred_indices
    ]
    user_prompt = _format_deferred_for_prompt(deferred_payload, code_claim) + "\n" + _LLM_PAIR_MATCH_INSTRUCTION
    try:
        raw = client.call(
            model="gemma-3-27b-it",
            system=_LLM_PAIR_MATCH_SYSTEM,
            user=user_prompt,
            json_schema=_LLM_PAIR_MATCH_SCHEMA,
        )
        parsed = json.loads(raw)
        pairings = parsed.get("pairings") or []
    except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
        print(
            f"[pair_match.llm] WARNING: deferred resolver failed "
            f"({type(exc).__name__}: {str(exc)[:120]}); leaving "
            f"{len(deferred_indices)} entries as UNMATCHED",
            file=sys.stderr,
        )
        return

    by_paper_index: dict[int, dict] = {}
    for p in pairings:
        try:
            by_paper_index[int(p["paper_index"])] = p
        except (KeyError, ValueError, TypeError):
            continue

    # Enforce at-most-one PAIRED_RETURN constraint defensively (in case
    # the LLM misbehaves). Pick the one whose alias_map has the largest
    # intersection with the function's return-value text as the winner.
    return_winners = [
        p for p in by_paper_index.values()
        if p.get("verdict") == "PAIRED_RETURN"
    ]
    if len(return_winners) > 1:
        rv = (code_claim.get("return_value") or "").lower()
        scored = sorted(
            return_winners,
            key=lambda p: sum(
                1 for v in (p.get("alias_map") or {}).values()
                if isinstance(v, str) and v.lower() in rv
            ),
            reverse=True,
        )
        winner = scored[0]
        for p in return_winners:
            if p is not winner:
                p["verdict"] = "UNMATCHED"
                p["rationale"] = (
                    "demoted: more than one PAIRED_RETURN; lost to "
                    f"paper_index={winner.get('paper_index')}"
                )

    for ent_idx in deferred_indices:
        entry = entries[ent_idx]
        p = by_paper_index.get(entry.paper_index)
        if not p:
            continue
        verdict = p.get("verdict") or "UNMATCHED"
        rationale = p.get("rationale") or ""
        if verdict == "UNMATCHED":
            if rationale:
                entry.detail = rationale
            continue
        code_target = p.get("code_target") or ""
        if not code_target:
            entry.detail = "LLM proposed PAIRED but missing code_target — kept UNMATCHED"
            continue
        entry.verdict = "PAIRED"
        entry.code_target = code_target
        entry.code_lhs_symbol = code_target
        entry.detail = rationale
        if verdict == "PAIRED_RETURN":
            rv = (code_claim.get("return_value") or "").strip()
            entry.code_equation = f"_return = {rv}" if rv else "_return"
        elif verdict == "PAIRED_INIT":
            init = code_claim.get("initial_conditions") or []
            match = next(
                (eq for eq in init if eq.split("=", 1)[0].strip().endswith(code_target)),
                None,
            )
            entry.code_equation = match or f"<init>{code_target}"
        elif verdict == "PAIRED_LOCAL":
            computed = code_claim.get("computed_equations") or []
            match = next(
                (eq for eq in computed if eq.split("=", 1)[0].strip() == code_target),
                None,
            )
            entry.code_equation = match or f"<local>{code_target}"


# ---------------------------------------------------------------------------
# Pair resolver (public API)
# ---------------------------------------------------------------------------


def pair_match(
    paper_claim: dict,
    code_claim: dict,
    *,
    use_llm: bool = True,
) -> list[PairMatchEntry]:
    """Resolve each paper claimed_equation to GATED/PAIRED/UNMATCHED.

    1. **LHS equality fast path** (deterministic, no LLM). For each
       paper equation, if its LHS symbol matches a code parameter ->
       ``GATED``; if it matches a code computed_equation LHS ->
       ``PAIRED``. Otherwise the equation is deferred.

    2. **LLM pair-match** (when `use_llm=True`). Deferred equations
       are batched into a single Gemma call which returns structured
       pairings against the function's return value, init-time
       coefficients, or computed equations. Aliasing (``\\epsilon`` ↔
       ``noise``, ``\\bar\\alpha_t`` ↔ ``sqrt_bar_alphas``) is handled
       by the LLM, eliminating the need for regex symbol matching.

    Returns a list of :class:`PairMatchEntry` aligned with
    ``paper_claim["claimed_equations"]`` (one entry per paper equation,
    in input order).
    """
    code_params = set(code_claim.get("parameters") or [])
    code_equations: list[str] = list(code_claim.get("computed_equations") or [])

    code_by_lhs: dict[str, str] = {}
    for code_eq in code_equations:
        sym = code_lhs_to_symbol(code_eq)
        # Last write wins.
        code_by_lhs[sym] = code_eq

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

    if use_llm and deferred_indices:
        _resolve_deferred_via_llm(deferred_indices, entries, code_claim)

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
