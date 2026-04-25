# Owner: DEVIN — Phase 1 task T1.11
"""VIGIL Verifier — final pass/anomaly verdict for the No Cap polygraph.

The Polygraph is the "judge" in the council: it consumes a Spec
:class:`~nocap_council.spec.Claim` (T1.8) and a list of Coder
``evidence`` dicts (T1.10) and returns a single verdict +
confidence + audit trail. It is the *only* role with authority to
flip a paper-vs-code check from ``pass`` to ``anomaly``.

Three VIGIL roles fire internally (deterministic Python — see chat
discussion for T1.11 Q2):

- ``_intent_anchor(claim, evidences)`` — VIGIL Fig 5 spirit: does the
  claim's ``paper_section`` align with what the evidences actually
  cover? Implements the canonical "intent decomposition" check by
  asking: do the evidences carry mismatches whose
  ``location.paper_section`` matches the claim, or whose
  ``target_var`` corresponds to a claimed equation? See
  ``prompts/intent_anchor.txt`` for the canonical aspiration.

- ``_sanitize(claim, evidences)`` — VIGIL Fig 6 spirit: detect
  prompt-injection / adversarial framing in the paper or code text
  surfaced through the claim and evidences. Implements a small set
  of regex tripwires (``[SYSTEM]``, ``IGNORE PREVIOUS``, ``URGENT``,
  ``DO NOT``, ``override``) over the stringified claim and the
  ``critic_feedback`` / ``residual`` / ``error`` fields. See
  ``prompts/sanitizer.txt`` for the canonical aspiration.

- ``_grounding_check(claim, evidences)`` — VIGIL Fig 8 spirit: do
  the evidences actually *ground* the verdict, or are they vacuous?
  Implements: at least one evidence has structural content
  (residual / mismatches / error), AND the structural mismatches
  (after section filtering — see below) are non-empty when
  ``equivalent=False``. See ``prompts/grounding_verifier.txt`` for
  the canonical aspiration.

Each role returns a ``{role, pass, note}`` dict. ``vigil_audit``
is the list of all three in fire order.

Public API
----------

``verify(claim, evidences) -> dict``
    Returns::

        {
            "verdict":          "pass" | "anomaly" | "inconclusive",
            "confidence":       float in [0.5, 0.95],
            "evidence_summary": str,
            "vigil_audit":      [
                {"role": "intent_anchor", "pass": bool, "note": str},
                {"role": "sanitize",      "pass": bool, "note": str},
                {"role": "grounding",     "pass": bool, "note": str},
            ],
        }

Verdict aggregation (chat answer #3):

1. ``len(evidences) == 0`` → ``inconclusive`` (defensive).
2. Any ``vigil_audit[*].pass == False`` → ``anomaly`` (confidence 0.95;
   structural integrity beats matcher verdicts).
3. Else if all ``evidences[*].equivalent == True`` → ``pass``
   (confidence 0.95).
4. Else if any ``evidences[*].equivalent == False`` → ``anomaly``,
   confidence weighted by max severity across failing evidences and
   the mean Critic score. Formula::

        sev_w = max severity weight (high=1.0, medium=0.6, low=0.2;
                symbolic/numerical evidences without mismatches → 1.0)
        crit  = mean (critic_score - 1) / 9 across failing evidences
                (0..1; default 0.5 if no Critic ran)
        confidence = clamp(0.5 + 0.4*sev_w + 0.1*crit, 0.5, 0.95)

5. Else → ``inconclusive`` (no equivalents either way; shouldn't
   happen in normal flow).

Section filtering (CRITICAL; chat answer #4):
    Before counting structural mismatches, drop any whose
    ``location.paper_section`` is neither equal to
    ``claim.paper_section`` nor whose ``paper_algorithm_name``
    contains the claim section as a substring. Otherwise AdaMax
    defaults (in the Extensions section of the Adam paper) will
    false-flag Adam code. See issue #3.

Phase-doc compatibility:
    The phase doc names ``V_compliance`` / ``V_entailment``. Per
    chat answer #1 these map to::

        V_compliance = vigil_audit[1]["pass"]   # sanitize
        V_entailment = vigil_audit[2]["pass"]   # grounding
"""

from __future__ import annotations

import re
from typing import Any

_VERDICT_PASS = "pass"
_VERDICT_ANOMALY = "anomaly"
_VERDICT_INCONCLUSIVE = "inconclusive"

_SEVERITY_WEIGHT: dict[str, float] = {"high": 1.0, "medium": 0.6, "low": 0.2}

_CONF_HIGH = 0.95
_CONF_MIN = 0.5

# VIGIL Fig 6 (sanitizer) tripwires — case-insensitive regex against the
# stringified claim + selected evidence fields. Mirrors the high-signal
# subset of sanitizer.txt §A/§B/§C without invoking Gemma.
_SANITIZER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[\s*(?:system|admin|root)\s*\]", re.IGNORECASE),
    re.compile(r"\bignore\s+(?:previous|prior|all|the)\s+(?:instruction|message|prompt)", re.IGNORECASE),
    re.compile(r"\boverride\s+(?:safety|security|previous|the\s+system)", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:previous|prior|safety|the)", re.IGNORECASE),
    re.compile(r"\b(?:urgent|immediately|asap)\s*[:!]", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bDAN\b\s+mode", re.IGNORECASE),
    re.compile(r"</?\s*(?:system|admin)\s*>", re.IGNORECASE),
)


def _claim_paper_section(claim: dict[str, Any]) -> str | None:
    sec = claim.get("paper_section")
    return sec if isinstance(sec, str) and sec.strip() else None


def _claim_equation_targets(claim: dict[str, Any]) -> list[str]:
    """Heuristically pull identifiers from claimed_equations LHS for matching.

    Returns both the full mangled name (e.g. ``m_hat_t``) and the
    accent-suffixed prefix (``m_hat``) so a LaTeX LHS ``\\hat{m}_t``
    matches a code-side ``target_var="m_hat"``.
    """
    out: list[str] = []
    for eq in claim.get("claimed_equations", []):
        if not isinstance(eq, str):
            continue
        head = eq.split("=", 1)[0]
        head = re.sub(
            r"\\(?:hat|tilde|bar|dot|vec|mathbf|boldsymbol|widehat|overline|overrightarrow)\s*\{([^}]*)\}",
            r"\1_hat",
            head,
        )
        head = re.sub(r"[\\{}\s$]", "", head)
        if not head:
            continue
        out.append(head)
        prefix = re.sub(r"_t\b.*$", "", head)
        if prefix and prefix != head:
            out.append(prefix)
    return out


def _location_matches_claim(location: dict[str, Any], claim_section: str | None) -> bool:
    if not claim_section or not isinstance(location, dict):
        return False
    sec = location.get("paper_section")
    if isinstance(sec, str) and sec == claim_section:
        return True
    alg = location.get("paper_algorithm_name")
    if isinstance(alg, str) and isinstance(sec, str):
        # Substring match either direction (claim "§3 Algorithm 1" vs
        # algorithm "Algorithm 1: Adam"; or claim "Adam" vs algorithm
        # "Algorithm 1: Adam").
        if claim_section in alg or alg in claim_section:
            return True
    if isinstance(alg, str) and claim_section in alg:
        return True
    return False


def _filter_mismatches(
    mismatches: list[dict[str, Any]] | None, claim_section: str | None
) -> list[dict[str, Any]]:
    if not mismatches:
        return []
    if not claim_section:
        return list(mismatches)
    return [m for m in mismatches if _location_matches_claim(m.get("location", {}), claim_section)]


def _intent_anchor(claim: dict[str, Any], evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """VIGIL Fig 5 spirit — does the claim align with the evidences?

    The claim names a paper section + claimed equations; we check that
    *some* evidence either touches the section (via location) or the
    target_var is a claimed equation LHS.
    """
    claim_section = _claim_paper_section(claim)
    targets = _claim_equation_targets(claim)
    aligned = 0
    for ev in evidences:
        target_var = ev.get("target_var")
        if isinstance(target_var, str) and target_var in targets:
            aligned += 1
            continue
        # T1.22: ``_return`` is the orchestrator's reparameterization-form
        # fallback (paper writes ``x_t = ...``, code returns the value
        # directly without naming it). The matcher compared the function's
        # return expression against the claim's RHS, so this evidence IS
        # aligned with the claim regardless of paper LHS naming.
        if target_var == "_return":
            aligned += 1
            continue
        # Structural evidence: any mismatch whose location matches the claim
        mismatches = ev.get("mismatches") or ev.get("raw_matcher_output", {}).get("mismatches") or []
        if _filter_mismatches(mismatches, claim_section):
            aligned += 1
    if aligned == 0:
        return {
            "role": "intent_anchor",
            "pass": False,
            "note": (
                f"No evidence aligns with claim.paper_section={claim_section!r} "
                f"or claim equation targets={targets!r}."
            ),
        }
    return {
        "role": "intent_anchor",
        "pass": True,
        "note": f"{aligned}/{len(evidences)} evidences aligned with claim.",
    }


def _sanitize(claim: dict[str, Any], evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """VIGIL Fig 6 spirit — flag prompt-injection markers in claim/evidence text."""
    blobs: list[str] = []
    for k in ("paper_section", "claimed_function", "architecture_description"):
        v = claim.get(k)
        if isinstance(v, str):
            blobs.append(v)
    for eq in claim.get("claimed_equations", []) or []:
        if isinstance(eq, str):
            blobs.append(eq)
    for ev in evidences:
        for k in ("residual", "critic_feedback", "error"):
            v = ev.get(k)
            if isinstance(v, str):
                blobs.append(v)
    text = "\n".join(blobs)
    hits: list[str] = []
    for pat in _SANITIZER_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(m.group(0))
    if hits:
        sample = ", ".join(repr(h) for h in hits[:3])
        return {
            "role": "sanitize",
            "pass": False,
            "note": f"Detected prompt-injection markers: {sample}.",
        }
    return {
        "role": "sanitize",
        "pass": True,
        "note": "No prompt-injection markers detected in claim or evidence text.",
    }


def _grounding_check(claim: dict[str, Any], evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """VIGIL Fig 8 spirit — do the evidences ground the verdict?"""
    if not evidences:
        return {"role": "grounding", "pass": False, "note": "Empty evidences list."}
    claim_section = _claim_paper_section(claim)
    grounded = 0
    vacuous = 0
    for ev in evidences:
        equivalent = bool(ev.get("equivalent"))
        residual = ev.get("residual")
        mismatches = ev.get("mismatches") or []
        error = ev.get("error")
        if equivalent:
            grounded += 1
            continue
        # Inequivalent: needs concrete grounding.
        if residual or error:
            grounded += 1
            continue
        filtered = _filter_mismatches(mismatches, claim_section)
        if filtered:
            grounded += 1
        else:
            vacuous += 1
    if vacuous:
        return {
            "role": "grounding",
            "pass": False,
            "note": (
                f"{vacuous}/{len(evidences)} evidences report inequivalence without "
                "concrete grounding (no residual, no error, no section-filtered mismatches)."
            ),
        }
    return {
        "role": "grounding",
        "pass": True,
        "note": f"{grounded}/{len(evidences)} evidences carry concrete grounding.",
    }


def _critic_score_norm(score: Any) -> float | None:
    if score is None:
        return None
    try:
        s = int(score)
    except (TypeError, ValueError):
        return None
    s = max(1, min(10, s))
    return (s - 1) / 9.0


def _max_severity_weight(evidences: list[dict[str, Any]], claim_section: str | None) -> float:
    weight = 0.0
    saw_inequivalent = False
    for ev in evidences:
        if ev.get("equivalent"):
            continue
        saw_inequivalent = True
        mismatches = ev.get("mismatches") or []
        filtered = _filter_mismatches(mismatches, claim_section)
        if not filtered:
            # symbolic/numerical or pre-filter empties → strong signal.
            weight = max(weight, 1.0)
            continue
        for m in filtered:
            sev = m.get("severity", "low")
            weight = max(weight, _SEVERITY_WEIGHT.get(sev, 0.2))
    return weight if saw_inequivalent else 0.0


def _confidence(evidences: list[dict[str, Any]], claim_section: str | None) -> float:
    sev_w = _max_severity_weight(evidences, claim_section)
    norms = [
        n
        for n in (_critic_score_norm(ev.get("critic_score")) for ev in evidences if not ev.get("equivalent"))
        if n is not None
    ]
    crit = sum(norms) / len(norms) if norms else 0.5
    raw = 0.5 + 0.4 * sev_w + 0.1 * crit
    return max(_CONF_MIN, min(_CONF_HIGH, raw))


def _evidence_summary(claim: dict[str, Any], evidences: list[dict[str, Any]], verdict: str) -> str:
    claim_section = _claim_paper_section(claim)
    parts: list[str] = []
    parts.append(f"verdict={verdict}; claim section={claim_section!r}.")
    for i, ev in enumerate(evidences, 1):
        kind = ev.get("kind", "?")
        equivalent = ev.get("equivalent")
        if equivalent:
            parts.append(f"[{i}] {kind}: equivalent.")
            continue
        residual = ev.get("residual")
        mismatches = _filter_mismatches(ev.get("mismatches") or [], claim_section)
        if residual:
            r = str(residual)
            if len(r) > 120:
                r = r[:117] + "..."
            parts.append(f"[{i}] {kind}: residual={r}.")
        elif mismatches:
            kinds = sorted({str(m.get("type", "?")) for m in mismatches})
            severities = sorted({str(m.get("severity", "?")) for m in mismatches})
            parts.append(f"[{i}] {kind}: {len(mismatches)} mismatch(es) types={kinds} severity={severities}.")
        else:
            parts.append(f"[{i}] {kind}: inequivalent (no concrete grounding).")
    return " ".join(parts)


def verify(claim: dict[str, Any], evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the three VIGIL roles and aggregate into a final verdict.

    See module docstring for the full shape and aggregation rules.
    """
    if not isinstance(evidences, list):
        raise TypeError(f"evidences must be a list, got {type(evidences).__name__}")
    audit = [
        _intent_anchor(claim, evidences),
        _sanitize(claim, evidences),
        _grounding_check(claim, evidences),
    ]
    if not evidences:
        return {
            "verdict": _VERDICT_INCONCLUSIVE,
            "confidence": _CONF_MIN,
            "evidence_summary": "No evidences provided.",
            "vigil_audit": audit,
        }

    # T1.22: ``equivalent=None`` marks a synthetic no-signal evidence
    # (the orchestrator skipped every claimed equation as non-comparable).
    # Filter those out before voting; they contribute neither pass nor
    # anomaly weight. If EVERY evidence is no-signal, the verdict is
    # inconclusive (we couldn't actually compare the code to the paper).
    voting = [ev for ev in evidences if ev.get("equivalent") is not None]
    if any(not a["pass"] for a in audit):
        verdict = _VERDICT_ANOMALY
        confidence = _CONF_HIGH
    elif not voting:
        verdict = _VERDICT_INCONCLUSIVE
        confidence = _CONF_MIN
    elif all(bool(ev.get("equivalent")) for ev in voting):
        verdict = _VERDICT_PASS
        confidence = _CONF_HIGH
    elif any(not bool(ev.get("equivalent")) for ev in voting):
        verdict = _VERDICT_ANOMALY
        confidence = _confidence(voting, _claim_paper_section(claim))
    else:
        verdict = _VERDICT_INCONCLUSIVE
        confidence = _CONF_MIN

    return {
        "verdict": verdict,
        "confidence": confidence,
        "evidence_summary": _evidence_summary(claim, evidences, verdict),
        "vigil_audit": audit,
    }


# ----------------------------------------------------------------------
# Acceptance demo (T1.11): synthetic Adam-buggy claim + 3 Coder evidences.
# Hardcoded per chat answer #10 — isolates polygraph testing from the
# matcher modules. Asserts verdict=anomaly, confidence>0.85,
# V_compliance (sanitize.pass) == False is NOT what we want — the
# acceptance is for buggy code, not injected text, so V_compliance and
# V_entailment shapes per phase doc map to the *failing-equivalence*
# axis, not the VIGIL-role axis. See assertion comments below.
# ----------------------------------------------------------------------
_DEMO_CLAIM: dict[str, Any] = {
    "paper_section": "§3 Algorithm 1 — Adam",
    "claimed_equations": [
        r"\hat{m}_t = m_t / (1 - \beta_1^t)",
        r"\hat{v}_t = v_t / (1 - \beta_2^t)",
        r"\theta_t = \theta_{t-1} - lr \cdot \hat{m}_t / (\sqrt{\hat{v}_t} + \epsilon)",
    ],
    "claimed_function": "Adam optimizer step with bias correction.",
    "claimed_hyperparams": {"beta1": "0.9", "beta2": "0.999", "lr": "1e-3", "eps": "1e-8"},
    "architecture_description": "",
}


def _demo_evidences() -> list[dict[str, Any]]:
    """Three Coder-shape evidence dicts mirroring T1.10's Adam-buggy demo output."""
    sym_residual = "(-m + (beta1**t - 1)*(-beta1*m + g*(beta1 - 1)))/(beta1**t - 1)"
    structural_mismatches = [
        {
            "type": "algorithm_step_count",
            "location": {
                "paper_section": "§3 Algorithm 1 — Adam",
                "paper_algorithm_name": "Algorithm 1: Adam",
                "paper_hyperparam_symbol": None,
                "code_function": None,
                "code_var": None,
            },
            "expected": 7,
            "actual": 6,
            "severity": "medium",
        },
        {
            "type": "hyperparam_missing_in_code",
            "location": {
                "paper_section": "§3 Algorithm 1 — Adam",
                "paper_algorithm_name": None,
                "paper_hyperparam_symbol": "lr",
                "code_function": None,
                "code_var": "lr",
            },
            "expected": 0.001,
            "actual": None,
            "severity": "low",
        },
    ]
    return [
        {
            "kind": "symbolic",
            "equivalent": False,
            "residual": sym_residual,
            "mismatches": None,
            "method_used": "numerical",
            "target_var": "m_hat",
            "raw_matcher_output": {"residual": sym_residual, "method_used": "numerical"},
            "error": None,
            "critic_feedback": "[stub] symbolic mismatch.",
            "critic_score": 5,
        },
        {
            "kind": "numerical",
            "equivalent": False,
            "residual": sym_residual,
            "mismatches": None,
            "method_used": "numerical",
            "target_var": "m_hat",
            "raw_matcher_output": {"residual": sym_residual},
            "error": None,
            "critic_feedback": "[stub] numerical mismatch.",
            "critic_score": 5,
        },
        {
            "kind": "structural",
            "equivalent": False,
            "residual": None,
            "mismatches": structural_mismatches,
            "method_used": None,
            "target_var": None,
            "raw_matcher_output": {"mismatches": structural_mismatches},
            "error": None,
            "critic_feedback": "[stub] structural mismatch.",
            "critic_score": 5,
        },
    ]


def _print_audit(result: dict[str, Any]) -> None:
    print(f"verdict           : {result['verdict']!r}")
    print(f"confidence        : {result['confidence']:.4f}")
    print(f"evidence_summary  : {result['evidence_summary']}")
    print("vigil_audit:")
    for entry in result["vigil_audit"]:
        print(f"  - role={entry['role']!r}  pass={entry['pass']}  note={entry['note']}")


def _run_demo() -> int:
    print("# T1.11 Polygraph acceptance — Adam buggy synthetic case.")
    evidences = _demo_evidences()
    result = verify(_DEMO_CLAIM, evidences)
    _print_audit(result)

    # Phase-doc mapping per chat answer #1:
    #   V_compliance = vigil_audit[1].pass  (sanitize)
    #   V_entailment = vigil_audit[2].pass  (grounding)
    audit = result["vigil_audit"]
    v_compliance = audit[1]["pass"]
    v_entailment = audit[2]["pass"]
    print(f"\nV_compliance (sanitize)    : {v_compliance}")
    print(f"V_entailment (grounding)   : {v_entailment}")

    # Phase-doc acceptance: verdict='Anomaly', confidence>0.85,
    # V_compliance=False, V_entailment=False on Adam buggy.
    # The chat task supersedes phase-doc on V_compliance/V_entailment:
    # for buggy-equivalence (NOT injection), sanitize and grounding
    # should both PASS (no injection, evidences are well-grounded).
    # The phase doc's "False/False" maps to a different axis. Per
    # chat answer #10 we assert verdict and confidence; we additionally
    # assert sanitize/grounding PASS to lock the deterministic
    # behavior into the test (the "phase-doc requires False" reading
    # is wrong for an honest-bug case — that's prompt-injection
    # territory).
    assert result["verdict"] == _VERDICT_ANOMALY, (
        f"expected verdict={_VERDICT_ANOMALY!r}, got {result['verdict']!r}"
    )
    assert result["confidence"] > 0.85, f"expected confidence>0.85, got {result['confidence']:.4f}"
    assert v_compliance is True, (
        "sanitize should pass on a clean honest-bug input; only flips False on injection."
    )
    assert v_entailment is True, "grounding should pass when evidences carry residuals/mismatches."

    # Symmetry check: same claim with all-equivalent evidences → 'pass'.
    clean_evidences = [
        dict(ev, equivalent=True, residual=None, error=None, mismatches=None) for ev in evidences
    ]
    clean_result = verify(_DEMO_CLAIM, clean_evidences)
    assert clean_result["verdict"] == _VERDICT_PASS, (
        f"clean evidences should produce verdict={_VERDICT_PASS!r}, got {clean_result['verdict']!r}"
    )

    # Empty-evidences defensive (chat answer #6).
    empty_result = verify(_DEMO_CLAIM, [])
    assert empty_result["verdict"] == _VERDICT_INCONCLUSIVE

    # Section filtering smoke: synthesize a foreign-section mismatch and
    # confirm it doesn't drive the confidence higher than the in-section
    # one would alone.
    foreign = {
        "type": "algorithm_step_count",
        "location": {
            "paper_section": "§7 Extensions — AdaMax",
            "paper_algorithm_name": "Algorithm 2: AdaMax",
            "paper_hyperparam_symbol": None,
            "code_function": None,
            "code_var": None,
        },
        "expected": 5,
        "actual": 2,
        "severity": "high",
    }
    poisoned = _demo_evidences()
    poisoned[2]["mismatches"] = poisoned[2]["mismatches"] + [foreign]
    poisoned[2]["raw_matcher_output"]["mismatches"] = list(poisoned[2]["mismatches"])
    poisoned_result = verify(_DEMO_CLAIM, poisoned)
    assert poisoned_result["verdict"] == _VERDICT_ANOMALY, "still anomaly even with foreign-section noise"
    # Foreign high-severity mismatch must NOT inflate confidence beyond
    # the in-section medium severity (it should be filtered out).
    assert poisoned_result["confidence"] <= result["confidence"] + 1e-9, (
        f"foreign-section mismatch inflated confidence "
        f"({result['confidence']:.4f} -> {poisoned_result['confidence']:.4f})"
    )

    print("\nACCEPTANCE: Adam buggy verified as anomaly with confidence>0.85;")
    print("            clean variant produces 'pass'; empty produces 'inconclusive';")
    print("            foreign-section mismatches do NOT inflate confidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_demo())
