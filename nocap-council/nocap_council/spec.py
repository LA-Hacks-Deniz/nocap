# Owner: CLAUDE — Phase 1 task T1.8
"""Formulator role — extract the verification claim from a paper URL + code.

Wraps `prompts/formulator.txt` (OptimAI Appendix B Formulator with paper-vs-code
domain swaps from T1.7) and routes through Flash-Lite, which supports
`response_schema` for reliable structured output (research.md [H1] §5).

The Formulator's job is to pin the claim to a specific paper section so the
downstream council roles (Planner, Coder, Polygraph) can target the right
equations / hyperparameters / architecture.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

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
    claimed_hyperparams, architecture_description. The schema is enforced by
    Flash-Lite's `response_schema` (overrides the prompt's CamelCase request).
    """
    template = _load_prompt()
    task_content = _format_task_content(paper_url, code_str, user_msg)
    prompt = template.replace(_TASK_PLACEHOLDER, task_content)
    raw = client.call_json(
        model="gemini-2.5-flash-lite",
        system="",
        user=prompt,
        schema=Claim,
    )
    claim = Claim.model_validate(raw)
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
