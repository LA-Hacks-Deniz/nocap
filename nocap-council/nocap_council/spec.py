# Owner: CLAUDE — Phase 1 task T1.8 (refactored under T1.21 + T1.22 + T1.24 — DEVIN)
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
    claimed_equations: list[str] = Field(description="Equations the code is claimed to implement, in LaTeX or readable math.")
    claimed_function: str = Field(description="The claimed function expression — what the implemented function computes.")
    claimed_hyperparams: list[HyperParam] = Field(default_factory=list, description="Hyperparameters declared in the paper.")
    architecture_description: str = Field(default="", description="Description of any architecture diagram present, else empty.")


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
) -> dict:
    """Run the Formulator on a paper URL + Python code, return the structured claim.

    Returns a dict with keys: paper_section, claimed_equations, claimed_function,
    claimed_hyperparams, architecture_description. Routed through Gemma 3 27B —
    the JSON shape is pinned via the prompt's `_JSON_INSTRUCTION` block (Gemma
    does not enforce `response_schema`). Validation failures degrade to an
    empty-defaults Claim with a warning logged to stderr.

    When ``function_name`` and ``function_source`` are provided (T1.22), the
    prompt names the function under verification and asks Gemma to extract
    the equation(s) THAT function claims to implement. Without these args,
    Spec falls back to its T1.21 paper-blind behavior (back-compat for
    callers that don't pass ``--function``).
    """
    template = _load_prompt()
    task_content = _format_task_content(
        paper_url, code_str, user_msg, function_source=function_source
    )
    function_block = ""
    if function_name and function_source:
        function_block = _FUNCTION_AWARE_INSTRUCTION.format(
            function_name=function_name,
            function_source=function_source.rstrip(),
        )
    prompt = template.replace(_TASK_PLACEHOLDER, task_content) + function_block + _JSON_INSTRUCTION
    # T1.22 token-budget log: rough char-to-token ratio is ~4 for English / Python
    # source; this is a sanity check, not a hard cap. If we ever see this above
    # ~10k for a function-aware call, the trim isn't doing its job.
    print(
        f"[spec] prompt_chars={len(prompt)} est_tokens={len(prompt) // 4} "
        f"function_aware={bool(function_name and function_source)}",
        file=sys.stderr,
    )
    raw_text = client.call(
        model="gemma-3-27b-it",
        system="",
        user=prompt,
        json_schema={"type": "object"},
    )
    # T1.22: ``_repair_latex_escapes`` doubles single-backslash LaTeX
    # escapes (``\beta``) so ``json.loads`` accepts them as ``\\beta``.
    # The negative-lookbehind in the regex skips already-doubled pairs
    # (``\\epsilon``), which Gemma sometimes emits — without that, the
    # repair would corrupt valid JSON. Defensive parse: validation
    # errors degrade to an empty-defaults Claim with a warning.
    repaired = _repair_latex_escapes(raw_text)
    try:
        raw = json.loads(repaired)
        claim = Claim.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as e:
        print(
            f"[spec] WARNING: Claim parse/validate failed ({type(e).__name__}), "
            f"returning empty Claim. Detail: {str(e)[:200]}",
            file=sys.stderr,
        )
        claim = _empty_claim()
    out = claim.model_dump()
    # Per phase-1.md T1.8 return shape, claimed_hyperparams is a flat dict.
    out["claimed_hyperparams"] = {h["name"]: h["value"] for h in out["claimed_hyperparams"]}
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
