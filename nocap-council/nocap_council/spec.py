# Owner: CLAUDE — Phase 1 task T1.8 (refactored under T1.21 + T1.22 + T1.24 + T1.25 v3 — DEVIN)
"""Formulator role — extract the verification claim from a paper URL + code.

Wraps `prompts/formulator.txt` (OptimAI Appendix B Formulator with paper-vs-code
domain swaps from T1.7) and routes through Gemma 3 27B with defensive JSON
parsing for single-model simplicity.

Originally routed through Flash-Lite for `response_schema` enforcement
(research.md [H1] §5). T1.21 migrated to Gemma 3 27B because Flash-Lite's
free-tier 20 RPD limit was clipping demos; Gemma 3 27B is ~14,400 RPD on the
same key and is already used by Plan + Critic. Gemma doesn't enforce
`response_schema` (research.md [H1] §5, §9), so the JSON shape is pinned via
a `_JSON_INSTRUCTION` block appended to the prompt — mirroring `plan.py` —
and parsed defensively. On `ValidationError`, a warning is logged to stderr
and an empty-defaults Claim is returned; the Formulator never raises so the
orchestrator's `inconclusive` path stays the only failure mode the gateway
sees.

T1.22 added function-awareness: when `function_name` and `function_source` are
provided, the prompt names the function under verification and asks Gemma to
extract the equation(s) THAT function claims to implement (not random paper
equations). The JSON instruction also asks Spec to rewrite Gaussian
distribution-form equations (`q(x_t | x_0) = N(...)`) into reparameterization
assignment form so the downstream matcher gets an LHS to compare against.
Without function-awareness, Spec is paper-blind to which function the user
asked to verify — for DDPM with `--function q_sample`, Spec picks §3.2
(Training Objective) and extracts L_simple, but L_simple lives in
`loss_simple`, not `q_sample`.

The Formulator's job is to pin the claim to a specific paper section so the
downstream council roles (Planner, Coder, Polygraph) can target the right
equations / hyperparameters / architecture.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from nocap_council import client

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_FORMULATOR_TXT = _PROMPTS_DIR / "formulator.txt"
_TASK_PLACEHOLDER = '{state["messages"][0].content}'


class HyperParam(BaseModel):
    name: str = Field(description="Hyperparameter symbol or name, e.g. 'beta1' or 'learning_rate'.")
    value: str = Field(description="Value as written in the paper, e.g. '0.9' or '1e-4'.")


class Claim(BaseModel):
    paper_section: str = Field(description="Section of the paper the claim originates from, e.g. '§4 Algorithm 1' or 'Algorithm 2'.")
    claimed_equations: list[str] = Field(description="COMPUTATIONAL PIPELINE equations only — state updates, bias corrections, function returns. Excludes initialization and counters (see those buckets).")
    claimed_function: str = Field(description="The claimed function expression — what the implemented function computes.")
    claimed_hyperparams: list[HyperParam] = Field(default_factory=list, description="Hyperparameters declared in the paper.")
    architecture_description: str = Field(default="", description="Description of any architecture diagram present, else empty.")
    initial_conditions: list[str] = Field(default_factory=list, description="t=0 setup equations (e.g. 'm_0 = 0', '\\theta_0 \\sim N(0, I)'). NOT computational pipeline.")
    counters: list[str] = Field(default_factory=list, description="Loop bookkeeping increments (e.g. 't = t + 1'). NOT computational pipeline.")


_FUNCTION_AWARE_INSTRUCTION = """

### Function under verification (REQUIRED — overrides paper-section heuristic)
The user has asked you to verify ONE specific function: `{function_name}`.
Its source (decorators, signature, body, docstring) is:

```python
{function_source}
```

You MUST extract the paper equation(s) THIS function claims to implement.
Reason: the function's LHS-assigned variables (and its return expression) map
to the paper's LHS symbols. Pick the paper section that DEFINES this
function's math, NOT a related section that happens to share notation.

Procedure:
1. Read the function's docstring + body. Identify the LHS variables it
   assigns (and what it returns).
2. Find the paper section / equation whose LHS matches those variables.
3. Set `paper_section` to THAT section (not the loss / training / sampling
   section unless the function genuinely IS the loss / training / sampler).
4. Set `claimed_equations` to ONLY the equations from that section the
   function implements. Drop equations from sibling sections.

Distribution-form rewrite (REQUIRED for Gaussian densities). When the paper
writes a forward / posterior / prior as a Gaussian density
`q(...) = N(mean, variance I)`, you MUST rewrite it as the corresponding
reparameterization assignment so the downstream matcher has an LHS to compare
against. The matcher only handles assignments; it cannot match
`q(x) = N(\\mu, \\sigma^2 I)` against `x = \\mu + \\sigma \\epsilon`.
  - Generic form:
    `q(x | y) = N(x; \\mu(y), \\Sigma(y) I)`
    rewrites to
    `x = \\mu(y) + \\sqrt{{\\Sigma(y)}} \\epsilon`,  `\\epsilon \\sim N(0, I)`.
  - DDPM eq 4 (canonical case):
    `q(x_t | x_0) = N(x_t; \\sqrt{{\\bar{{\\alpha}}_t}} x_0, (1 - \\bar{{\\alpha}}_t) I)`
    rewrites to
    `x_t = \\sqrt{{\\bar{{\\alpha}}_t}} x_0 + \\sqrt{{1 - \\bar{{\\alpha}}_t}} \\epsilon`,
    `\\epsilon \\sim N(0, I)`.
Limitation: only Gaussian densities are auto-rewritten. Bernoulli /
Categorical / discrete densities are out of scope for v1. If the function's
equation is already an assignment (not a density), leave it as-is.
"""


_JSON_INSTRUCTION = """

### Output requirement (overrides "Response Format" above)
Return ONLY a JSON object of the exact form:

{
  "paper_section": "<section identifier from the paper, e.g. 'Algorithm 1' or '§4'>",
  "claimed_equations": [
    "<equation 1 in LaTeX, plain (no \\mathbf), current-state indexing>",
    "<equation 2>",
    "..."
  ],
  "claimed_function": "<one short phrase describing what the function computes>",
  "claimed_hyperparams": [
    {"name": "<symbol or name, e.g. beta1>", "value": "<as in paper, e.g. 0.9>"},
    ... zero or more items ...
  ],
  "architecture_description": "<paragraph if the paper shows an architecture diagram, else empty string>"
}

No prose, no markdown fences. `claimed_hyperparams` MUST be a list of
{name, value} objects (not a dict). Every value MUST be a string. If a
field has no content, return an empty string or empty list, never null.

### Equation conventions (REQUIRED — downstream parsers depend on these)
1. **No text-styling LaTeX.** Do NOT wrap variables in `\\mathbf{...}`,
   `\\textbf{...}`, `\\boldsymbol{...}`, `\\vec{...}`. Plain
   `m_t`, `\\beta_1`, `\\hat{m}_t` only.
2. **Current-state indexing.** For update rules, write the LHS at step
   `t` and reference the previous step `t-1` on the RHS — NEVER write
   the LHS at step `t+1`. The matcher's heuristic looks for the LHS
   variable in the code's post-assignment environment, which holds the
   step-`t` value.
3. **ASCII greek aliases for hyperparameters.** When a hyperparameter has
   a common ASCII alias used in code (`beta1`, `beta2`, `lr`, `eps`,
   `gamma`, `tau`), the `claimed_hyperparams.name` MUST be the ASCII
   alias even if the paper uses `\\beta_1`, `\\alpha`, `\\epsilon`, etc.
   The equation strings can keep the LaTeX form (`\\beta_1`).

### Equation ranking — REQUIRED (function-aware runs)

When a `Code function under verification:` block is provided in this
prompt, RANK `claimed_equations` by how much of the function's behavior
each equation describes:

- **HIGHEST priority — function-defining equations.** The LHS is the
  function's RETURN VALUE (or a synonym for it); the RHS is the full
  pipeline that produces the return. Place these FIRST.
  Example: `Attention(Q, K, V) = softmax(Q K^T / \\sqrt{d_k}) V` is
  HIGHER priority than `scores = Q K^T` because `Attention(Q, K, V)`
  is what `scaled_dot_product_attention` returns. The full formula
  carries scaling, normalization, and post-processing details that
  the intermediate equations drop.
- **LOWER priority — intermediate assignments.** `scores = ...`,
  `mu = ...`, `\\hat{m}_t = m_t / ...`. These describe partial
  computations and may be missing context (e.g. `scores = Q K^T`
  drops the `/\\sqrt{d_k}` scaling that lives in the full Attention
  formula).
- **LOWEST priority — notational definitions.**
  `\\bar{\\alpha}_t = \\prod_{s=1}^{t} \\alpha_s`,
  `\\hat{m}_t \\equiv m_t / (1 - \\beta_1^t)`. These are renames /
  shorthand, not pipeline steps.

Place equations in `claimed_equations[]` in DESCENDING priority order
so the orchestrator iterates the most important ones first. Function-
defining equations carry the most discriminating signal — if the code
implementation has a bug, it is most likely to show up as a mismatch
with the full formula, not the intermediates.

- **OMIT pure notational-definition equations entirely on function-aware
  runs.** Examples to OMIT (do NOT include these in `claimed_equations[]`
  at all): `\\bar{\\alpha}_t = \\prod_{s=1}^{t} \\alpha_s`,
  `\\sigma_t^2 = \\beta_t`, `\\hat{m}_t \\equiv m_t / (1 - \\beta_1^t)`,
  any LHS that defines a symbolic shorthand used elsewhere rather than
  computing a pipeline step inside the function under verification.
  These equations describe NOTATION, not BEHAVIOR — comparing them to
  the function's return value is structurally meaningless and produces
  noise. They are LOWER than "lowest priority": they should not be
  emitted at all on function-aware runs. Notational definitions are
  fine to KEEP on whole-paper runs (no `Code function under verification`
  block), where the matcher can resolve their LHS to a top-level symbol.

### Worked example — the Adam optimizer's update step
Given a paper that defines (in §4 / Algorithm 1) the bias-corrected Adam
step, the correct output is:

```json
{
  "paper_section": "Algorithm 1",
  "claimed_equations": [
    "\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)",
    "m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t",
    "v_t = \\beta_2 v_{t-1} + (1 - \\beta_2) g_t^2",
    "\\hat{m}_t = m_t / (1 - \\beta_1^t)",
    "\\hat{v}_t = v_t / (1 - \\beta_2^t)"
  ],
  "claimed_function": "Adam optimizer parameter update step",
  "claimed_hyperparams": [
    {"name": "beta1", "value": "0.9"},
    {"name": "beta2", "value": "0.999"},
    {"name": "lr", "value": "0.001"},
    {"name": "eps", "value": "1e-8"}
  ],
  "architecture_description": ""
}
```

Note specifically:
- `\\theta_t = ...` is FIRST because `\\theta_t` is what Adam's `step()`
  returns (the updated parameter). Bias-correction equations come
  AFTER as lower-priority intermediates.
- `m_t = ... m_{t-1} ...` — current-state indexing, NOT
  `m_{t+1} = ... m_t ...`.
- No `\\mathbf{m}` — plain `m`.
- `beta1` / `beta2` / `lr` / `eps` as hyperparameter NAMES, even though
  the paper uses `\\beta_1` / `\\beta_2` / `\\alpha` / `\\epsilon`.

### Worked example — scaled dot-product attention (Vaswani et al. 2017)
Given a paper that defines (in §3.2.1, equation 1) scaled dot-product
attention as `\\text{Attention}(Q, K, V) = \\text{softmax}(Q K^T / \\sqrt{d_k}) V`,
and the function under verification is `scaled_dot_product_attention(Q, K, V)`,
the CORRECT output is:

```json
{
  "paper_section": "§3.2.1",
  "claimed_equations": [
    "Attention(Q, K, V) = softmax(Q K^T / \\sqrt{d_k}) V",
    "scores = Q K^T / \\sqrt{d_k}",
    "softmax(scores)_{ij} = \\exp(scores_{ij}) / \\sum_k \\exp(scores_{ik})"
  ],
  "claimed_function": "scaled dot-product attention",
  "claimed_hyperparams": [],
  "architecture_description": ""
}
```

The WRONG output (which is what an unranked Spec produces) drops the
function-defining formula entirely and leads with the intermediate:

```json
{
  "claimed_equations": [
    "scores = Q K^T",
    "softmax(scores)",
    "..."
  ]
}
```

The wrong version drops the `/\\sqrt{d_k}` scaling because the
intermediate `scores = Q K^T` is not where the scaling lives — the
scaling lives ONLY in the full `Attention(Q, K, V) = ...` formula.
Always lead with the function-defining equation so the matcher sees
the full pipeline.
"""


def _empty_claim() -> Claim:
    """Return an empty-defaults Claim used as the degraded-parse fallback."""
    return Claim(
        paper_section="",
        claimed_equations=[],
        claimed_function="",
        claimed_hyperparams=[],
        architecture_description="",
        initial_conditions=[],
        counters=[],
    )


# JSON spec accepts \" \\ \/ \b \f \n \r \t \uXXXX as legal escapes inside
# string values. Gemma sometimes emits raw `\beta`, `\hat`, `\sqrt`, etc.
# inside JSON strings (single backslash, valid LaTeX, invalid JSON). The
# tricky case is `\b`: it IS a legal JSON escape (backspace control
# character), so a naive sanitizer that allows it lets Gemma's `\beta`
# slip through and `json.loads` parses it as a literal backspace + `eta`.
# Math equations never carry control chars, so we restrict the "legal
# escape" set to `\\ \" \/ \uXXXX` only — every other `\X` sequence is
# treated as LaTeX and gets the backslash doubled. This loses literal
# `\n` / `\r` / `\t` / `\b` / `\f` characters Gemma might emit in
# description fields, which is acceptable: those fields contain prose
# describing diagrams, not control bytes.
_INVALID_BACKSLASH_RE = re.compile(r'(?<!\\)\\(?![\\/"u])')


def _repair_latex_escapes(text: str) -> str:
    """Double unknown `\\X` escapes so `json.loads` accepts the response.

    Gemma 3's chat decoder treats `\\beta`, `\\hat`, `\\sqrt`, etc. as
    literal LaTeX (which is what we want in the equation strings) but
    emits them with a single backslash inside JSON strings — invalid
    per RFC 8259. We rewrite them to `\\\\beta`, `\\\\hat`, `\\\\sqrt`
    so the parsed Python string still contains the single-backslash
    LaTeX form the matchers expect.
    """
    return _INVALID_BACKSLASH_RE.sub(r"\\\\", text)


def _load_prompt() -> str:
    text = _FORMULATOR_TXT.read_text()
    lines = text.splitlines()
    while lines and lines[0].lstrip().startswith("<!--"):
        lines.pop(0)
    return "\n".join(lines).lstrip()


def _format_task_content(
    paper_url: str,
    code_str: str,
    user_msg: str | None,
    *,
    function_source: str | None = None,
) -> str:
    """Build the per-call task block.

    When ``function_source`` is set (T1.22 function-aware path), we show ONLY
    the function's source as the "Code under verification" body — the rest
    of the class is hidden so the extraction stays focused on the equation
    THIS function implements, and so we stay under Gemma's 15 k input-token
    per-minute free-tier window on large fixtures (DDPM's full class is
    ~600 lines / ~5-8 k tokens; the function alone is ~30 lines / ~500 tokens).
    """
    if function_source:
        code_block = function_source.rstrip()
        body_label = (
            "Code under verification (function under --function override; "
            "rest of the class is hidden to focus the extraction):"
        )
    else:
        code_block = code_str.strip()
        body_label = "Code under verification:"
    parts = [
        f"Paper URL: {paper_url}",
        "",
        body_label,
        "```python",
        code_block,
        "```",
    ]
    if user_msg:
        parts += ["", f"User context / claim: {user_msg}"]
    return "\n".join(parts)


def extract_claim(
    paper_url: str,
    code_str: str,
    user_msg: str | None = None,
    *,
    function_name: str | None = None,
    function_source: str | None = None,
    paper_dict: dict | None = None,
) -> dict:
    """Run the Formulator on a paper URL + Python code, return the structured claim.

    Returns a dict with keys: paper_section, claimed_equations, claimed_function,
    claimed_hyperparams, architecture_description. Routed through Gemma 3 27B
    via two passes (T1.25 v3 — decoupled Spec):

      Pass 1 (always): :func:`extract_paper_claim` extracts a canonical
        paper claim from the paper's parsed sections — CODE-BLIND. This
        eliminates the v1/v2 failure mode where Gemma over-indexed on the
        implementing code's body and dropped paper equations the code
        appeared to "skip" (e.g. dropping `\\hat{m}_t` for an `adam_buggy`
        whose body has the buggy `m_hat = self.m` alias).
      Pass 2 (only when ``function_name`` + ``function_source`` are
        provided): :func:`focus_claim_to_function` reorders the pass-1
        claim against the function source. Re-ranking only — NEVER drops
        equations. If the focuser response is invalid, the pass-1 claim
        is returned unchanged.

    The ``paper_dict`` kwarg lets the orchestrator pass through its
    already-fetched ``paper_extract.parse_paper`` output to avoid a
    second arXiv round-trip; if None, this function fetches + parses
    on demand for back-compat with callers that don't have it handy.
    Validation failures in either pass degrade to an empty-defaults
    Claim with a warning logged to stderr — the Formulator never
    raises so the orchestrator's ``inconclusive`` path stays the only
    failure mode the gateway sees.

    The legacy single-shot prompt (formulator.txt + ``_JSON_INSTRUCTION``
    + ``_FUNCTION_AWARE_INSTRUCTION``) is no longer used by this
    function; those constants remain for reference only and may be
    removed in a follow-up cleanup once T1.25 v3 is merged.
    """
    # ``code_str`` and ``user_msg`` are accepted for API back-compat but
    # are no longer fed into Gemma — pass 1 is intentionally code-blind.
    del code_str, user_msg
    if paper_dict is None:
        # Back-compat: callers without an already-parsed paper_dict
        # (e.g. ad-hoc scripts) pay the fetch + parse round-trip here.
        from nocap_council import paper_extract  # local import to avoid cycles
        src = paper_extract.fetch_arxiv_source(paper_url)
        paper_dict = paper_extract.parse_paper(src)
    paper_arxiv_id = paper_url
    claim = extract_paper_claim(paper_arxiv_id, paper_dict)
    if function_name and function_source:
        claim = focus_claim_to_function(claim, function_name, function_source)
    return claim


# ----------------------------------------------------------------------
# T1.25 v3 — decoupled Spec: code-blind paper-claim extractor
# ----------------------------------------------------------------------
#
# v1 (OMIT-rule tightening) and v2 (Path A revert) both failed to keep
# Gemma from dropping `\hat{m}_t` / `\hat{v}_t` on `adam_buggy`. Root
# cause: the single-shot ``extract_claim`` mixes paper context AND code
# body into the same prompt, and Gemma over-indexes on the code — when
# it sees ``m_hat = self.m`` (the buggy alias, no division), it omits
# the bias-correction equations from ``claimed_equations[]`` because
# they don't appear to be "implemented" in the code. The bias is in the
# combined prompt; no amount of prompt-text tweaks can override it.
#
# T1.25 v3 splits the extraction in two passes (orchestrator wires both
# in stage 3):
#
#   Pass 1: ``extract_paper_claim`` — code-BLIND. Gemma sees ONLY the
#           paper sections / equations / algorithms. It lists every
#           equation the paper defines, capturing what the paper says.
#   Pass 2: ``focus_claim_to_function`` — re-ranks the pass-1 claim
#           against the function-under-verification source. Reorders
#           only; never drops.
#
# Token-budget impact: 2 Gemma calls per ``extract_claim`` instead of
# 1. Gemma 3 27B free-tier ceiling is ~14,400 RPD; the additional call
# is comfortably within budget. No inter-stage sleep needed.

_PAPER_CLAIM_SYSTEM = (
    "You are a paper-claim categorizer. Given the paper's sections and "
    "equations, sort every equation the paper writes into THREE buckets: "
    "(1) `claimed_equations` — the COMPUTATIONAL PIPELINE: state updates, "
    "bias corrections, normalization, the function-defining return; "
    "(2) `initial_conditions` — t=0 setup (e.g. `m_0 = 0`, "
    "`\\theta_0 \\sim N(0, I)`); "
    "(3) `counters` — bookkeeping increments (e.g. `t = t + 1`). "
    "Every equation goes into EXACTLY ONE bucket. Do NOT infer what "
    "implementing code might or might not do — categorize by mathematical "
    "shape, not by code presence. Pure-constant assignments to a "
    "hyperparameter symbol (e.g. `\\epsilon = 10^{-8}`) belong in "
    "`claimed_hyperparams`, not in any of the three equation buckets. "
    "Preserve each equation EXACTLY as the paper writes it. When the "
    "paper introduces a new symbol via an equation (e.g. "
    "`\\hat{m}_t = m_t / (1 - \\beta_1^t)` introduces \\hat{m}_t), keep "
    "the LHS symbol VERBATIM. Do NOT substitute the LHS with its RHS "
    "definition. Do NOT inline bias-corrections or other derived symbols "
    "into downstream equations — keep \\hat{m}_t, \\hat{v}_t etc. as-is "
    "in the parameter update. Verbatim applies to SYMBOLS — STRIP "
    "text-styling LaTeX (\\mathbf, \\boldsymbol, \\mathrm); those are "
    "formatting, not semantic content. "
    "EXCEPTION — probability density definitions: verbatim preservation "
    "applies to symbol-level equations (m_t = ..., \\hat{m}_t = ...); it "
    "does NOT apply to probability density definitions, which describe "
    "distributions rather than computable values and cannot be verified "
    "by the matcher in their density form. When the paper writes a "
    "Gaussian density definition like `p(x | y) = N(x; mean, variance * "
    "I)`, emit instead the REPARAMETERIZATION form (assignment-style, "
    "matchable against code that samples from this density): "
    "`x = mean + sqrt(variance) * \\epsilon` where \\epsilon is "
    "implicitly ~ N(0, I). Worked examples (DDPM, arXiv 2006.11239 §2): "
    "(a) `q(x_t | x_{t-1}) = N(x_t; sqrt(1 - \\beta_t) x_{t-1}, "
    "\\beta_t I)` becomes `x_t = sqrt(1 - \\beta_t) x_{t-1} + "
    "sqrt(\\beta_t) \\epsilon`; "
    "(b) `q(x_t | x_0) = N(x_t; sqrt(\\bar\\alpha_t) x_0, "
    "(1 - \\bar\\alpha_t) I)` becomes `x_t = sqrt(\\bar\\alpha_t) x_0 + "
    "sqrt(1 - \\bar\\alpha_t) \\epsilon`; "
    "(c) `p_\\theta(x_{t-1} | x_t) = N(x_{t-1}; \\mu_\\theta(x_t, t), "
    "\\Sigma_\\theta(x_t, t))` becomes `x_{t-1} = \\mu_\\theta(x_t, t) + "
    "sqrt(\\Sigma_\\theta(x_t, t)) \\epsilon`. This rewrite is REQUIRED "
    "for ALL Gaussian density definitions. Non-density equations "
    "(`\\tilde\\mu_t(x_t, x_0) = ...`, `\\tilde\\beta_t = ...`) stay "
    "verbatim per the main rule."
)

_PAPER_CLAIM_INSTRUCTION = """
### Output requirement
Return ONLY a JSON object of the exact form:

{
  "paper_section": "<the section the central claim originates from, e.g. 'Algorithm 1' or '§4'>",
  "claimed_equations": [
    "<computational-pipeline equation 1 in LaTeX, plain (no \\mathbf), current-state indexing>",
    "<computational-pipeline equation 2>",
    "..."
  ],
  "initial_conditions": [
    "<t=0 setup equation (e.g. 'm_0 = 0', '\\theta_0 \\sim N(0, I)')>",
    "..."
  ],
  "counters": [
    "<bookkeeping increment (e.g. 't = t + 1')>",
    "..."
  ],
  "claimed_function": "<one short phrase describing what the paper's central function computes>",
  "claimed_hyperparams": [
    {"name": "<symbol or name, e.g. beta1>", "value": "<as in paper, e.g. 0.9>"},
    ... zero or more items ...
  ],
  "architecture_description": "<paragraph if the paper shows an architecture diagram, else empty string>"
}

No prose, no markdown fences. `claimed_hyperparams` MUST be a list of
{name, value} objects (not a dict). Every value MUST be a string. If a
field has no content, return an empty string or empty list, never null.
The three equation lists (`claimed_equations`, `initial_conditions`,
`counters`) MUST be present even if empty.

### Categorization rules — every equation in the paper goes into EXACTLY ONE bucket

**`claimed_equations`** — COMPUTATIONAL PIPELINE only. An equation
belongs here iff it expresses a mathematical relationship between
values that are computed at runtime: state-update rules,
bias-correction terms, normalization steps, the function-defining
return expression. These are the equations a verifier would actually
match against a code implementation.
  Examples (Adam):
    `m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t`
    `\\hat{m}_t = m_t / (1 - \\beta_1^t)`
    `\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)`

**`initial_conditions`** — t=0 setup. An equation belongs here iff
its LHS has subscript `_0` (or it explicitly states a starting value)
AND its RHS is a constant or distribution sample at t=0.
  Examples:
    `m_0 = 0`, `v_0 = 0`, `t = 0` (Adam initialization)
    `\\theta_0 \\sim N(0, I)` (parameter initialization)
    `x_T \\sim N(0, I)` (DDPM sampling start)

**`counters`** — bookkeeping increments. An equation belongs here
iff its full form is `var = var ± constant`. These advance loop
state; they don't compute pipeline values.
  Examples:
    `t = t + 1`, `i = i - 1`

**`claimed_hyperparams`** (NOT one of the three equation buckets) —
pure-constant assignments to a hyperparameter symbol go here, NOT
into any equation list.
  Examples:
    `\\epsilon = 10^{-8}` → `{"name": "eps", "value": "1e-8"}`
    `\\alpha = 0.001` → `{"name": "lr", "value": "0.001"}`

### Formatting rules (apply to every bucket)

1. **No text-styling LaTeX.** Do NOT wrap variables in `\\mathbf{...}`,
   `\\textbf{...}`, `\\boldsymbol{...}`, `\\vec{...}`. Plain
   `m_t`, `\\beta_1`, `\\hat{m}_t` only.
2. **Current-state indexing.** For update rules, write the LHS at step
   `t` and reference the previous step `t-1` on the RHS — NEVER write
   the LHS at step `t+1`. The downstream matcher's heuristic looks for
   the LHS variable in the post-assignment environment.
3. **Distribution-form rewrite (REQUIRED for `claimed_equations`).** When
   the paper writes a forward / posterior / prior as a Gaussian density
   `q(...) = N(mean, variance I)`, REWRITE it as the corresponding
   reparameterization assignment so the matcher has an LHS to compare
   against.
   - Generic: `q(x | y) = N(x; \\mu(y), \\Sigma(y) I)` → `x = \\mu(y) + \\sqrt{\\Sigma(y)} \\epsilon`, `\\epsilon \\sim N(0, I)`.
   - DDPM eq 4: `q(x_t | x_0) = N(x_t; \\sqrt{\\bar{\\alpha}_t} x_0, (1 - \\bar{\\alpha}_t) I)` → `x_t = \\sqrt{\\bar{\\alpha}_t} x_0 + \\sqrt{1 - \\bar{\\alpha}_t} \\epsilon`.
4. **ASCII greek aliases for hyperparameters.** When a hyperparameter
   has a common ASCII alias used in code (`beta1`, `beta2`, `lr`, `eps`,
   `gamma`, `tau`), the `claimed_hyperparams.name` MUST be the ASCII
   alias even if the paper uses `\\beta_1`, `\\alpha`, `\\epsilon`. The
   equation strings can keep the LaTeX form (`\\beta_1`).

### Worked example — Adam optimizer (Kingma & Ba 2014, Algorithm 1)
Algorithm 1 lists (in paper order):
  `m_0 = 0`, `v_0 = 0`, `t = 0`,
  while not converged:
    `t = t + 1`,
    `g_t = \\nabla_{\\theta} f_t(\\theta_{t-1})`,
    `m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t`,
    `v_t = \\beta_2 v_{t-1} + (1 - \\beta_2) g_t^2`,
    `\\hat{m}_t = m_t / (1 - \\beta_1^t)`,
    `\\hat{v}_t = v_t / (1 - \\beta_2^t)`,
    `\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)`

Correct output (categorization, NOT filtering — every paper line is
preserved, just sorted into the right bucket):
```json
{
  "paper_section": "Algorithm 1",
  "claimed_equations": [
    "g_t = \\nabla_{\\theta} f_t(\\theta_{t-1})",
    "m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t",
    "v_t = \\beta_2 v_{t-1} + (1 - \\beta_2) g_t^2",
    "\\hat{m}_t = m_t / (1 - \\beta_1^t)",
    "\\hat{v}_t = v_t / (1 - \\beta_2^t)",
    "\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)"
  ],
  "initial_conditions": [
    "m_0 = 0",
    "v_0 = 0",
    "t = 0"
  ],
  "counters": [
    "t = t + 1"
  ],
  "claimed_function": "Adam optimizer parameter update step",
  "claimed_hyperparams": [
    {"name": "beta1", "value": "0.9"},
    {"name": "beta2", "value": "0.999"},
    {"name": "lr", "value": "0.001"},
    {"name": "eps", "value": "1e-8"}
  ],
  "architecture_description": ""
}
```
Note: BOTH bias-correction equations (`\\hat{m}_t`, `\\hat{v}_t`) are
in `claimed_equations` because they compute pipeline values. The
initialization and counter lines are sorted into their dedicated
buckets — they are NOT dropped, just moved out of the pipeline list.
"""


def _format_paper_for_extraction(paper_dict: dict) -> str:
    """Serialize ``parse_paper`` output into a flat text view for Gemma.

    The pass-1 prompt is code-blind, so we lay out every section's
    equations, algorithms, and hyperparams as plain text. Skips the
    ``_preamble`` / ``_unsectioned`` buckets unless they're the only
    ones present.
    """
    lines: list[str] = []
    skip_keys = {"_error"}
    sections = [
        (name, bucket)
        for name, bucket in paper_dict.items()
        if name not in skip_keys and isinstance(bucket, dict)
    ]
    # Drop empty buckets — they add noise to the prompt without signal.
    sections = [
        (name, bucket)
        for name, bucket in sections
        if bucket.get("equations") or bucket.get("algorithms") or bucket.get("hyperparams")
    ]
    for name, bucket in sections:
        lines.append(f"## Section: {name}")
        eqs = bucket.get("equations") or []
        if eqs:
            lines.append("### Equations")
            for i, eq in enumerate(eqs):
                latex = (eq.get("latex") or "").strip()
                label = eq.get("label")
                tag = f" (label={label})" if label else ""
                lines.append(f"  [eq{i}{tag}] {latex}")
        algos = bucket.get("algorithms") or []
        if algos:
            lines.append("### Algorithms")
            for i, algo in enumerate(algos):
                raw = (algo.get("raw") or "").strip()
                lines.append(f"  [alg{i}]")
                for ln in raw.splitlines():
                    lines.append(f"    {ln}")
        hp = bucket.get("hyperparams") or {}
        if hp:
            lines.append("### Hyperparameters")
            for sym, val in hp.items():
                lines.append(f"  {sym} = {val}")
        lines.append("")
    return "\n".join(lines)


def extract_paper_claim(
    paper_arxiv_id: str,
    paper_dict: dict,
) -> dict:
    """Pass 1 of T1.25 v3: code-BLIND paper-claim extraction.

    Inputs are ONLY the arxiv ID + ``paper_extract.parse_paper`` output
    (the section-keyed dict). NO code is shown to Gemma. The returned
    claim categorizes every equation the paper writes into THREE
    buckets — ``claimed_equations`` (computational pipeline only),
    ``initial_conditions`` (t=0 setup), ``counters`` (loop bookkeeping).
    Categorization is delegated entirely to Gemma; we trust its
    judgment and emit the result as-is.

    Returns the same dict shape as :func:`extract_claim` (with
    ``claimed_hyperparams`` flattened to a name→value dict).
    """
    paper_text = _format_paper_for_extraction(paper_dict)
    user_prompt = (
        f"Paper arXiv ID: {paper_arxiv_id}\n\n"
        f"Paper sections (from LaTeX source):\n\n{paper_text}\n"
        f"{_PAPER_CLAIM_INSTRUCTION}"
    )
    print(
        f"[spec.paper_claim] prompt_chars={len(user_prompt)} "
        f"est_tokens={len(user_prompt) // 4}",
        file=sys.stderr,
    )
    raw_text = client.call(
        model="gemma-3-27b-it",
        system=_PAPER_CLAIM_SYSTEM,
        user=user_prompt,
        json_schema={"type": "object"},
    )
    repaired = _repair_latex_escapes(raw_text)
    try:
        raw = json.loads(repaired)
        claim = Claim.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as e:
        print(
            f"[spec.paper_claim] WARNING: Claim parse/validate failed "
            f"({type(e).__name__}), returning empty Claim. "
            f"Detail: {str(e)[:200]}",
            file=sys.stderr,
        )
        claim = _empty_claim()
    out = claim.model_dump()
    # Match ``extract_claim`` final shape: claimed_hyperparams as flat dict.
    out["claimed_hyperparams"] = {h["name"]: h["value"] for h in out["claimed_hyperparams"]}
    return out


# ----------------------------------------------------------------------
# T1.25 v3 pass 2 — function-focuser (re-rank, never drop)
# ----------------------------------------------------------------------

_FOCUS_SYSTEM = (
    "You are a function-focuser. Given a canonical paper claim and the "
    "source of a function-under-verification, REORDER claimed_equations "
    "so the equation that defines the function's RETURN VALUE is FIRST, "
    "intermediate computations next, notational definitions last. NEVER "
    "drop equations from the input claim — only reorder them. The "
    "orchestrator decides what to verify."
)

_FOCUS_INSTRUCTION = """
### Task
You are given:
1. A canonical paper claim's `claimed_equations`, presented as a numbered
   list with stable indices.
2. The source of a Python function under verification.

Decide a re-ranking that puts the equation defining the function's
RETURN VALUE FIRST, intermediate computations next (in pipeline order),
and notational / shorthand definitions last. The orchestrator iterates
the ranked list — putting the function-defining equation first lets the
matcher catch full-pipeline bugs (e.g. a missing scaling factor) rather
than chasing intermediate symbols that hide context.

### Output requirement
Return ONLY a JSON object of the exact form:

{
  "order": [<integer index>, <integer index>, ...]
}

Constraints (STRICTLY enforced — violations cause your output to be
discarded and the input order to be used unchanged):
- `order` MUST be a PERMUTATION of `[0, 1, ..., N-1]` where N is the
  number of input equations. Every input index appears EXACTLY ONCE.
- Do NOT add new equations. Do NOT drop equations. Do NOT rewrite
  equation strings.
- Output JSON only — no prose, no markdown fences.

### Ranking guide

- **Function-defining equation (FIRST)**: the LHS is the function's
  return value (or a synonym). Example: for `Adam.step()` returning
  `theta`, the highest-priority equation is
  `\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / ...`. For
  `scaled_dot_product_attention(Q,K,V)`, it is
  `Attention(Q,K,V) = softmax(QK^T / \\sqrt{d_k}) V`.
- **Intermediate computations (next)**: equations whose LHS is a
  variable the function explicitly assigns / computes en route to the
  return — e.g. `m_t`, `v_t`, `\\hat{m}_t`, `\\hat{v}_t`, `scores`.
- **Notational definitions (last)**: equations whose LHS defines paper
  shorthand the function does NOT explicitly compute — e.g.
  `\\bar{\\alpha}_t = \\prod_s \\alpha_s` (typically a precomputed
  table looked up by index, not computed inline).

### Worked example

Input equations (indices [0..4]):
  [0] m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t
  [1] v_t = \\beta_2 v_{t-1} + (1 - \\beta_2) g_t^2
  [2] \\hat{m}_t = m_t / (1 - \\beta_1^t)
  [3] \\hat{v}_t = v_t / (1 - \\beta_2^t)
  [4] \\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)

Function: `Adam.step(g, t)` returns `self.theta` after computing
`m`, `v`, `m_hat`, `v_hat`, then updating `theta`.

Correct output:
```json
{"order": [4, 2, 3, 0, 1]}
```
Reason: equation [4] is function-defining (theta is the return);
[2] and [3] are the bias-correction intermediates closest to the
return; [0] and [1] are the moment-update intermediates further back
in the pipeline.

WRONG output (drops equations):
```json
{"order": [4, 0, 1]}
```
You MUST keep every input index. Reordering only.
"""


def _format_function_for_focus(function_name: str, function_source: str) -> str:
    """Render the function source as a labeled code block for the focuser."""
    return (
        f"### Function under verification: `{function_name}`\n\n"
        f"```python\n{function_source.rstrip()}\n```\n"
    )


def _format_equations_for_focus(equations: list[str]) -> str:
    """Render the input equations as an indexed list for the focuser."""
    lines = ["### Paper claim equations (indices to reorder)"]
    for i, eq in enumerate(equations):
        lines.append(f"  [{i}] {eq}")
    return "\n".join(lines)


def focus_claim_to_function(
    paper_claim: dict,
    function_name: str,
    function_source: str,
) -> dict:
    """Pass 2 of T1.25 v3: re-rank paper_claim's equations for a function.

    Takes a paper_claim from :func:`extract_paper_claim` and a
    function-under-verification source. Returns a NEW dict (paper_claim
    is not mutated) with `claimed_equations` reordered so the
    function-defining equation is first.

    NEVER drops equations from the input. If the focuser's response is
    invalid (not a permutation of input indices, parse error, etc.),
    falls back to returning the input claim unchanged so the caller is
    no worse off than the code-blind extraction.
    """
    equations = list(paper_claim.get("claimed_equations") or [])
    n = len(equations)
    if n <= 1:
        # Nothing to reorder — pass through.
        return dict(paper_claim)
    user_prompt = (
        _format_equations_for_focus(equations)
        + "\n\n"
        + _format_function_for_focus(function_name, function_source)
        + _FOCUS_INSTRUCTION
    )
    print(
        f"[spec.focus] prompt_chars={len(user_prompt)} "
        f"est_tokens={len(user_prompt) // 4} n_equations={n}",
        file=sys.stderr,
    )
    raw_text = client.call(
        model="gemma-3-27b-it",
        system=_FOCUS_SYSTEM,
        user=user_prompt,
        json_schema={"type": "object"},
    )
    repaired = _repair_latex_escapes(raw_text)
    try:
        raw = json.loads(repaired)
        order = raw.get("order")
        if not isinstance(order, list):
            raise ValueError(f"order is not a list: {type(order).__name__}")
        order_ints = [int(i) for i in order]
        # Strict permutation check — guarantees never-drop semantics.
        if sorted(order_ints) != list(range(n)):
            raise ValueError(
                f"order {order_ints} is not a permutation of [0..{n - 1}]"
            )
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(
            f"[spec.focus] WARNING: invalid order ({type(e).__name__}: "
            f"{str(e)[:200]}) — falling back to paper_claim unchanged.",
            file=sys.stderr,
        )
        return dict(paper_claim)
    out = dict(paper_claim)
    out["claimed_equations"] = [equations[i] for i in order_ints]
    return out


if __name__ == "__main__":
    sample_code = (
        "def step(self, g, t, beta1=0.9, beta2=0.999, lr=1e-3, eps=1e-8):\n"
        "    self.m = beta1 * self.m + (1 - beta1) * g\n"
        "    self.v = beta2 * self.v + (1 - beta2) * g * g\n"
        "    m_hat = self.m / (1 - beta1**t)\n"
        "    v_hat = self.v / (1 - beta2**t)\n"
        "    return -lr * m_hat / (v_hat**0.5 + eps)\n"
    )
    out = extract_claim(
        paper_url="https://arxiv.org/abs/1412.6980",
        code_str=sample_code,
        user_msg="Implementation of Adam optimizer step.",
    )
    print(json.dumps(out, indent=2)[:1500])
