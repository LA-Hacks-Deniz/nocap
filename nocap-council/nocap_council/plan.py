# Owner: CLAUDE — Phase 1 task T1.9
"""Planner role — generate exactly 3 verification strategies for a Spec claim.

Wraps `prompts/planner.txt` (OptimAI Appendix B Planner with paper-vs-code
domain swaps from T1.7) and routes through Gemma 4. The Planner consumes the
structured claim from `spec.extract_claim` and returns three strategies, each
tagged `symbolic | numerical | structural | hyperparametric`, that the Coder
will execute.

Gemma does not enforce `response_schema` (research.md [H1] §5, §9), so the
JSON shape is pinned via prompt engineering and parsed defensively. If the
LLM returns fewer than 3 valid strategies we deterministically pad from the
unused kinds — the orchestrator must never see len(result) != 3.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from nocap_council import client

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PLANNER_TXT = _PROMPTS_DIR / "planner.txt"

StrategyKind = Literal["symbolic", "numerical", "structural", "hyperparametric"]
_KIND_ORDER: tuple[StrategyKind, ...] = ("symbolic", "numerical", "structural", "hyperparametric")


class Strategy(BaseModel):
    kind: StrategyKind
    rationale: str
    target: str | None = None


_JSON_INSTRUCTION = """

### Output requirement (overrides "Response Format" above)
Return ONLY a JSON object of the exact form:

{
  "strategies": [
    {"kind": "symbolic|numerical|structural|hyperparametric",
     "rationale": "<one paragraph: why this strategy fits the claim>",
     "target": "<paper section, equation label, or null>"},
    ... exactly 3 items, distinct kinds preferred ...
  ]
}

No prose, no markdown fences. `kind` MUST be one of:
symbolic, numerical, structural, hyperparametric.
"""


def _load_prompt() -> str:
    text = _PLANNER_TXT.read_text()
    lines = text.splitlines()
    while lines and lines[0].lstrip().startswith("<!--"):
        lines.pop(0)
    return "\n".join(lines).lstrip()


def _format_system(spec: dict) -> str:
    template = _load_prompt()
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)
    task_desc = (
        "Verify that a Python implementation matches the claim in §Paper Model below. "
        f"Claim is pinned to paper section: {spec.get('paper_section', 'unknown')}."
    )
    out = template.replace('{state["messages"][0].content}', task_desc)
    out = out.replace("{UserFeedbackRecord.user_recommendations}", "")
    out = out.replace('{state["components"]}', spec_json)
    return out + _JSON_INSTRUCTION


def _parse_strategies(raw: object) -> list[Strategy]:
    if not isinstance(raw, dict):
        return []
    items = raw.get("strategies")
    if not isinstance(items, list):
        return []
    out: list[Strategy] = []
    for it in items:
        try:
            out.append(Strategy.model_validate(it))
        except ValidationError:
            continue
    return out


def _ensure_three(strategies: list[Strategy]) -> list[Strategy]:
    used = {s.kind for s in strategies}
    for kind in _KIND_ORDER:
        if len(strategies) >= 3:
            break
        if kind in used:
            continue
        strategies.append(
            Strategy(
                kind=kind,
                rationale=f"Fallback {kind} verification (Planner returned <3 valid items).",
                target=None,
            )
        )
        used.add(kind)
    return strategies[:3]


def generate_strategies(spec: dict) -> list[Strategy]:
    """Return exactly 3 verification strategies for the given Spec claim dict."""
    system = _format_system(spec)
    user = json.dumps(spec, ensure_ascii=False)
    raw = client.call_json(
        model="gemma-3-27b-it",
        system=system,
        user=user,
        schema={"type": "object"},
    )
    return _ensure_three(_parse_strategies(raw))


if __name__ == "__main__":
    sample_spec = {
        "paper_section": "§4 Algorithm 1",
        "claimed_equations": [
            "m_hat_t = m_t / (1 - beta1**t)",
            "v_hat_t = v_t / (1 - beta2**t)",
            "theta_t = theta_{t-1} - lr * m_hat_t / (sqrt(v_hat_t) + eps)",
        ],
        "claimed_function": "Adam optimizer step",
        "claimed_hyperparams": {"beta1": "0.9", "beta2": "0.999", "lr": "1e-3", "eps": "1e-8"},
        "architecture_description": "",
    }
    out = generate_strategies(sample_spec)
    for i, s in enumerate(out, 1):
        print(f"--- Strategy {i} [{s.kind}] target={s.target}")
        print(s.rationale[:300])
