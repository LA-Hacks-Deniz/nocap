# Owner: CLAUDE — Phase 1 task T1.8 (refactored under T1.21 — DEVIN)
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

### Worked example — the Adam optimizer's update step
Given a paper that defines (in §4 / Algorithm 1) the bias-corrected Adam
step, the correct output is:

```json
{
  "paper_section": "Algorithm 1",
  "claimed_equations": [
    "m_t = \\beta_1 m_{t-1} + (1 - \\beta_1) g_t",
    "v_t = \\beta_2 v_{t-1} + (1 - \\beta_2) g_t^2",
    "\\hat{m}_t = m_t / (1 - \\beta_1^t)",
    "\\hat{v}_t = v_t / (1 - \\beta_2^t)",
    "\\theta_t = \\theta_{t-1} - \\alpha \\hat{m}_t / (\\sqrt{\\hat{v}_t} + \\epsilon)"
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
- `m_t = ... m_{t-1} ...` — current-state indexing, NOT `m_{t+1} = ... m_t ...`.
- No `\\mathbf{m}` — plain `m`.
- `beta1` / `beta2` / `lr` / `eps` as hyperparameter NAMES, even though
  the paper uses `\\beta_1` / `\\beta_2` / `\\alpha` / `\\epsilon`.
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
_INVALID_BACKSLASH_RE = re.compile(r'\\(?![\\/"u])')


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


def _format_task_content(paper_url: str, code_str: str, user_msg: str | None) -> str:
    parts = [
        f"Paper URL: {paper_url}",
        "",
        "Code under verification:",
        "```python",
        code_str.strip(),
        "```",
    ]
    if user_msg:
        parts += ["", f"User context / claim: {user_msg}"]
    return "\n".join(parts)


def extract_claim(paper_url: str, code_str: str, user_msg: str | None = None) -> dict:
    """Run the Formulator on a paper URL + Python code, return the structured claim.

    Returns a dict with keys: paper_section, claimed_equations, claimed_function,
    claimed_hyperparams, architecture_description. Routed through Gemma 3 27B —
    the JSON shape is pinned via the prompt's `_JSON_INSTRUCTION` block (Gemma
    does not enforce `response_schema`). Validation failures degrade to an
    empty-defaults Claim with a warning logged to stderr.
    """
    template = _load_prompt()
    task_content = _format_task_content(paper_url, code_str, user_msg)
    prompt = template.replace(_TASK_PLACEHOLDER, task_content) + _JSON_INSTRUCTION
    raw_text = client.call(
        model="gemma-3-27b-it",
        system="",
        user=prompt,
        json_schema={"type": "object"},
    )
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
