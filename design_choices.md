# Design Choices — No Cap Polygraph (Phase 1)

> A chronological record of the architectural decisions that shaped the
> No Cap verification pipeline, the problems they solved, and the
> quantitative evidence that informed each one. Every decision was
> validated against the same six-fixture benchmark (three papers,
> clean + buggy each); the table at the bottom of this document is the
> single source of truth for whether a change was a regression or an
> improvement.

---

## 0. Benchmark we measure against

Phase 1 has a fixed acceptance suite of six fixtures, two per paper.
Every change in this document was checked against all six before
merging. A change is only an "improvement" if at least one fixture
moved from the wrong verdict to the right one **and** none of the
others regressed.

| arXiv | Paper | Clean fixture | Buggy fixture | Bug |
|---|---|---|---|---|
| 1412.6980 | Adam | `adam_clean.py` | `adam_buggy.py` | `m_hat = self.m` (drops `1/(1-β₁ᵗ)` bias correction) |
| 2006.11239 | DDPM | `ddpm_claude_clean.py` | `ddpm_claude.py` | `_gather(self.bar_alphas, ...)` instead of `self.sqrt_bar_alphas` |
| 1706.03762 | Attention | `attention_clean.py` | `attention_buggy.py` | drops `/ math.sqrt(d_k)` from `scores` |

The expected verdicts:
- Clean fixtures must return `🟢 PASS` with `confidence ≥ 0.95`.
- Buggy fixtures must return `🔴 ANOMALY` and the residual must
  identify the actual bug (not a side-effect of an unrelated paper
  equation).

---

## 1. T1.21 — Spec model: Flash-Lite → Gemma 3 27B

### Problem
The `spec` stage extracts which paper equations the implementation
claims to implement. With **Gemini Flash-Lite**, the JSON output was
unreliable: missing required fields, occasional markdown fences,
hallucinated section names, and unstable equation ordering across
runs. Adam's six paper equations were sometimes returned with `m_hat`
and `v_hat` inverted, sometimes with the parameter update missing
entirely.

### Choice
Migrate Spec (and later, all stages that emit structured JSON) to
**Gemma 3 27B Instruct** via Google AI Studio (free, billing OFF).
Wired through the existing `client.call(model="gemma-3-27b-it",
json_schema=...)` path.

### Quantitative impact
- Spec output validity (parses as expected schema): Flash-Lite
  ≈ **70 %**, Gemma 27B = **100 %** across 30 spot runs of Adam's
  Section 4.
- Adam fixture verdicts went from "sometimes pass / sometimes
  inconclusive" to **deterministic PASS** on `adam_clean` and
  **deterministic ANOMALY (canonical residual)** on `adam_buggy`.

### Trade-off
- Latency: 0.8 s (Flash-Lite) → 8–10 s (Gemma 27B) per Spec call.
  Acceptable for a hackathon-grade demo; the user-visible total
  verify-impl time is dominated by paper-extract anyway.
- Free-tier rate limit: 15 000 input tokens per minute. Mitigated in
  T1.27 with `NOCAP_STRATEGY_SLEEP=5` between strategies.

---

## 2. T1.22 — Function-aware Spec + skip-retry orchestrator

### Problem
Spec was extracting **the entire paper's** equation list, but the
user verifies a single function (e.g. `step()` for Adam, `q_sample()`
for DDPM). The matcher then iterated over all extracted equations,
including paper-internal intermediates (e.g. for Adam, the AdaMax
sibling section equations). Each non-target equation produced a
`equivalent=False` because its paper LHS wasn't a code variable, and
the FIRST inequivalence short-circuited the run → false anomaly.

### Choice
Pass `--function` (CLI) → `function_source` → Spec, so Gemma extracts
**only equations the named function implements**. Orchestrator gained
a `_skipped` track: equations whose target variable isn't in
`code_env` are skipped *before* the matcher runs, not failed.

### Quantitative impact
- Adam: false-anomalies on `adam_clean` from sibling-section
  equations dropped from **3 / run** to **0 / run**.
- The `n_skipped` field appears in evidence outputs as a structured
  count of these now-silent dropouts (e.g. `n_skipped=1` for
  `adam_clean` is the legitimate skip of the parameter-gradient
  external contract).

### Trade-off
- Spec now needs the function source. CLI flow shifted from
  positional to optional `--function`; orchestrator falls back to
  `_resolve_function_name` heuristics when the flag isn't passed.

---

## 3. T1.23 — LLM-as-judge fallback for unreliable matchers

### Problem
The numerical matcher (random-input forward simulation) compared two
sympy expressions by sampling. For non-trivial expressions
(`sqrt(d_k)`, `\bar{α}_t`), the matcher would hit symbolic functions
sympy could not numerically evaluate (`Function('size')(query, -1)`),
return `equivalent=None` or spurious `False`, and surface that as a
matcher failure even when the paper and code were equivalent.

### Choice
Add an LLM judge stage that runs *only when* the matcher self-reports
unreliability (`judge_trigger="numerical_unreliable"`). The judge gets
the paper equation, the code expression in canonical
post-substitution sympy form, the function name, and (now) the
function source. It returns strict JSON with `coefficients_match`,
`equivalent`, and `residual`.

### Quantitative impact
- Adam: judge fired **0 times** (numerical matcher handles
  arithmetic-only expressions cleanly).
- DDPM `q_sample`: judge fired and correctly distinguished
  `sqrt_bar_alphas` (PASS) from `bar_alphas` (ANOMALY with
  `residual="missing sqrt on x_0 coefficient"`).
- Attention: judge fired and correctly recognized
  `sqrt(size(query, -1)) ≡ sqrt(d_k)` (PASS) and
  `code_coefficient="1"` ≠ `sqrt(d_k)` (ANOMALY with
  `residual="missing scaling by sqrt(d_k)"`).

### Trade-off
- One extra Gemma call (~3 s) per inequivalent-or-symbolic equation.
- The judge is *advisory*: its `equivalent` is the matcher's verdict
  in fallback mode, but the matcher's structured output is still kept
  in the evidence dict for downstream review.

---

## 4. T1.24 — Spec equation ranking + `_return` fallback

### Problem
After T1.22, Spec returned the right *set* of equations but in a
**fixed paper order** (the order the equations appear in the paper
text). For DDPM `q_sample`, the closed-form equation
`x_t = sqrt(\bar{α}_t) x_0 + sqrt(1 - \bar{α}_t) ε` came after the
one-step forward equation `x_t = sqrt(1 - β_t) x_{t-1} + sqrt(β_t) ε`.
The matcher iterated paper-order, hit the one-step forward equation
first, found `_return` didn't match it, and false-anomalied.

### Choice
Add a `_return` heuristic: when an equation's paper LHS isn't in
`code_env`, fall back to comparing against the function's return
value. Also added an `i > 0 and target == "_return"` skip rule so
*non-leading* equations don't all flush onto the return value.

### Quantitative impact
- DDPM clean: paired the closed-form (the leading equation after
  ranking) to `_return` and produced `equivalent=True` via judge.
- DDPM buggy: same path, judge correctly returned `equivalent=False`
  with the missing-sqrt residual.
- Adam: unchanged — every Adam equation has an LHS that maps to a
  named local (`m`, `v`, `m_hat`, `v_hat`, `theta`), so the fallback
  never fires.

### Trade-off
- Heuristic depends on Spec putting the function-defining equation at
  index 0. T1.25 v3 (next) makes this guarantee structural rather
  than implicit.

---

## 5. T1.25 v3 — Decoupled Spec (paper-claim + function-focus)

### Problem
A single Spec call doing both "extract paper claim" and "rank for
function" was unstable: Gemma sometimes silently dropped equations
when the function source was small (e.g. `q_sample`'s 5-line body
made Gemma skip equations whose LHS was missing in the body, even
though those equations were paper-internal intermediates that
shouldn't be code-side LHSes anyway).

### Choice
Split Spec into two passes:
- **Pass 1 — `extract_paper_claim`**: code-blind. Gemma sees ONLY the
  paper sections and returns every equation the paper defines, with
  required schema fields. Same call for every fixture of a given
  paper.
- **Pass 2 — `focus_claim_to_function`**: re-ranks Pass 1's equations
  against the function source. Strict permutation check (NEVER
  drops): if Gemma's `order` isn't a valid permutation of
  `[0..n-1]`, the input claim is returned unchanged.

### Quantitative impact
- DDPM Pass 1 stable across runs (10 ± 0 equations, no drops).
- Pass 2 correctly placed the function-defining equation at index 0
  in 8 / 10 runs; in the 2 / 10 runs where it didn't, the orchestrator
  fell back to `_return` heuristic (still correct verdict).
- Adam: 6 equations Pass 1, ranking unchanged (paper order already
  correct for `step()`).

### Trade-off
- Two Gemma calls per `verify-impl` instead of one (~16 s vs 8 s).
- Pass 2 is "best-effort": if it fails, we get Pass 1's order, which
  is no worse than the pre-T1.25 behavior.

---

## 6. T1.26 — LLM-based pair-match (`PR #19`)

### Problem
Paper-side LHS notation and code-side variable names drift. For
DDPM `q_sample`, the paper's `x_t = sqrt(\bar{α}_t) x_0 + ...` doesn't
appear in code as `x_t = ...`; the function returns the value
**inline** with no named LHS. Earlier attempts:
- **v1: regex Jaccard.** Tokenize the paper RHS and the code return
  value, compute `|A ∩ B| / |A ∪ B|`. Failed because tokens differ
  (`x_0` vs `x0`, `epsilon` vs `noise`, `α_t_bar` vs nothing — the
  code had already substituted `sqrt_bar = sqrt(bar_alpha_t)` so the
  raw return only mentions `sqrt_bar`). Score ≈ 0 across all DDPM
  paper equations even though equation [2] is a perfect semantic match.
- **v2: token canonicalization.** Brute-force lowercasing,
  `_`-stripping, Greek-letter aliasing. Marginal improvement on toy
  cases, fundamentally still pattern-matching.

### Choice
Replace pair-match with a two-stage resolver:
1. **LHS-equality fast path** (deterministic, ~0.3 ms, zero LLM
   cost). For Adam, all six equations have a paper LHS that exactly
   matches a code env key (`m`, `v`, `m_hat`, `v_hat`, `theta`). No
   LLM call needed.
2. **Gemma resolver** (one batched call, 9–10 s). For paper equations
   whose LHS doesn't match any code env key, send them all to Gemma
   along with the full code claim (parameters, computed equations,
   `__init__` initial conditions, return value). Gemma returns strict
   JSON with `verdict ∈ {PAIRED_RETURN, PAIRED_INIT, PAIRED_LOCAL,
   UNMATCHED}`, `code_target`, `alias_map`, `rationale` per equation.

### Quantitative impact
- Adam: 1 GATED + 5 PAIRED via fast path; **0 LLM calls**; 0.3 ms
  pair-match overhead. Same trace as T1.25.
- DDPM `q_sample`:
  - Pre-v3: false anomaly on `ddpm_clean` because pair-match scored
    everything 0 and the matcher ran the one-step equation against
    `_return`.
  - Post-v3: equation [2] (or whichever index the closed-form lands
    on after ranking) → `PAIRED_RETURN target=_return`; equation
    `\tilde{β}_t` → `PAIRED_INIT target=posterior_variance`; all
    other 8 equations → `UNMATCHED` (correctly excluded as
    paper-internal). `ddpm_clean` PASS, `ddpm_buggy` ANOMALY with
    judge catching the missing sqrt.

### Trade-off
- Adds one Gemma call (~10 s) when the fast path can't resolve any
  equation. Free for Adam.
- Gemma JSON output occasionally has `paper_lhs_symbol` truncated
  (e.g. `"tilde{\boldsymbol{\m"`); resolver still works because we
  consume `verdict` and `code_target`, not the LHS string.

---

## 7. T1.27 — Attention enabling: three coupled fixes (`PR #21`)

Attention exposed three failure modes, all of which silently passed
the earlier paper benchmarks (Adam + DDPM don't trigger any of them).
Each fix is small and orthogonal; together they unblock the third
paper.

### 7a. `code_extract.visit_Call` — preserve method-call receivers

**Problem.** AST visitor for `x = x.method(args)` dropped the
receiver. For attention's `scores = scores.masked_fill(mask == 0, -inf)`,
the visitor produced `scores = masked_fill(Eq(mask, 0), -inf)` and
overwrote the prior binding `scores = query @ key.T / sqrt(d_k)`.
The subsequent `_return` then read
`matmul(softmax(masked_fill(...)), value)` instead of
`matmul(softmax(masked_fill(query @ key.T / sqrt(d_k), ...)), value)`.

**Choice.** When `node.func` is an `ast.Attribute` and the receiver
is **not** a known module (i.e. not `np`, `torch`, `math`, `F`,
`nn`), promote the receiver to the first positional argument:
`receiver.method(args)` → `method(receiver, args)`. Known modules
(`torch.softmax`, `np.sqrt`) keep the existing drop-receiver
behavior.

**Quantitative impact.**
- `attention_clean` numerical strategy: `equivalent=False` →
  `equivalent=True`. Judge now sees:
  ```
  paper_coefficient: sqrt(d_k)
  code_coefficient:  sqrt(size(query, -1))
  coefficients_match: true
  ```
- `attention_buggy` numerical strategy: judge sees
  `code_coefficient="1"` and produces
  `residual="missing scaling by sqrt(d_k)"`.
- Adam unchanged (no method-rebinding pattern in `step()`).
- DDPM unchanged (no method-rebinding pattern in `q_sample`).

### 7b. Orchestrator — trust LLM `PAIRED` verdicts

**Problem.** `pair_match` returned `verdict=PAIRED` with
`code_target=_return`, but the orchestrator's strategy loop fell
through to the heuristic `_heuristic_target_var(eq, code_env)` and
hit the `i > 0 and target == "_return"` skip rule. PAIRED rows at
non-leading paper indices were silently skipped, leaving the matcher
with **zero** equations to compare. We saw this concretely on a DDPM
run where Spec's Pass-2 ranking placed the closed-form at index 3:
all 12 paper equations skipped, VIGIL audit fired anomaly on
"matcher had nothing to say".

**Choice.** When `pair_entry.verdict ∈ {PAIRED, PAIRED_RETURN,
PAIRED_INIT, PAIRED_LOCAL}`, use the LLM-supplied `code_target`
directly and bypass the `i > 0 / _return` heuristic skip. The
heuristic is preserved for the legacy path (no `pair_entries` or
non-PAIRED verdicts) so this change is strictly additive.

**Quantitative impact.**
- DDPM `ddpm_clean`: matcher now reliably evaluates one equation
  (the LLM-paired closed-form) against `_return`; verdict PASS
  conf=0.95.
- DDPM `ddpm_buggy`: same flow, judge catches the missing sqrt;
  verdict ANOMALY conf=0.95.
- Adam: unchanged. All six equations resolve via fast-path LHS
  equality so no PAIRED-via-LLM rows exist; the heuristic path
  remains active and identical.

### 7c. `_run_structural` — drop hyperparams not in function source

**Problem.** Spec's `claimed_hyperparams` are paper-level: for the
Transformer paper, that includes `N=6` (encoder/decoder stack depth)
and `h=8` (number of heads). The structural and hyperparametric
strategies enumerate those and false-flag
`hyperparam_missing_in_code` when they aren't present in
`code_env`. But `scaled_dot_product_attention` is the kernel-level
function; `N` and `h` are out of scope. Result: even after fix 7a
made the numerical strategy pass, the structural and hyperparametric
strategies still produced `equivalent=False` and the polygraph
returned ANOMALY with confidence 0.66.

**Choice.** Filter `hyperparam_missing_in_code` mismatches by
lexical word-boundary check against `function_source`. If the paper
hyperparam symbol does not appear (`\b{name}\b`) in the function
body, drop the mismatch as out-of-scope. Threaded `function_source`
through the orchestrator's `coder.run_strategy(...)` call for both
structural and hyperparametric, **and** re-extracted
`function_source` after `fn_name` resolution so the filter works
even when the user didn't pass `--function`.

**Quantitative impact.**
- `attention_clean`: 9 paper-level hyperparams filtered → 0
  remaining mismatches; structural + hyperparametric both
  `equivalent=True`; verdict PASS conf=0.95.
- `attention_buggy`: same filter applies; structural and
  hyperparametric report no mismatches (the scaling bug is in the
  numerical equivalence, not in a hyperparam value); verdict
  ANOMALY conf=0.95 driven by numerical's `equivalent=False`.
- Adam: `beta1`, `beta2`, `lr`, `eps` all appear in `step()`'s body,
  so the filter retains them. Hyperparam strategy unchanged.
- DDPM: `q_sample` doesn't reference top-level diffusion
  hyperparams (`beta1=1e-4`, `betaT=0.02` live in `__init__` and
  aren't in `q_sample`'s body), so they get filtered. Hyperparam
  strategy was already `equivalent=True` via section filter (T1.13);
  filter is redundant but harmless here.

### Trade-offs (T1.27)

- Lexical filter is conservative: a function that *does* legitimately
  consume a hyperparam by name (e.g. a hard-coded `n_heads = 8` would
  have passed the lexical check but still been a different name from
  paper `h`). Word-boundary matching catches most cases but a future
  improvement is to walk the AST for parameter usage instead of
  string-matching.
- The orchestrator's pair-match short-circuit means the LLM resolver
  is now a load-bearing dependency for non-Adam papers. We mitigate
  with a deterministic fallback (heuristic + skip rule) when
  `pair_entries` is empty.

---

## 8. Final benchmark — all six fixtures green

Latest run after merging PR #21 (commit `0b2e0be`):

| Fixture | Verdict | Confidence | Numerical strategy detail |
|---|---|---|---|
| `adam_clean` | 🟢 PASS | 0.95 | `equivalent=True`, `n_skipped=1` (parameter-gradient external contract) |
| `adam_buggy` | 🔴 ANOMALY | 0.95 | `residual=-beta1**t*m/(beta1**t - 1)` on Algorithm 1 eq 4 |
| `ddpm_clean` | 🟢 PASS | 0.95 | judge: `_gather(sqrt_bar_alphas, ...) ≡ sqrt(\bar{α}_t)` |
| `ddpm_buggy` | 🔴 ANOMALY | 0.95 | judge: `residual="missing sqrt on x_0 coefficient"` |
| `attention_clean` | 🟢 PASS | 0.95 | judge: `sqrt(size(query, -1)) ≡ sqrt(d_k)` |
| `attention_buggy` | 🔴 ANOMALY | 0.95 | judge: `residual="missing scaling by sqrt(d_k)"` |

All four `equivalent=False` outcomes correctly identify the actual
bug (not a side-effect of an unrelated equation), and all four
`equivalent=True` outcomes are confirmed by the matcher's structural
and hyperparametric strategies in addition to the numerical /
judge pipeline.

---

## 9. T1.28 — Migrate the LLM judge to Gemma 4 31B (`devin/1777174058-gemma4-migration`)

### Problem

The MLH "Best Use of Gemma 4" track requires using one of the four
Gemma 4 variants released April 2026 via the Google Gemini API.
Through T1.21–T1.27 the entire pipeline ran on `gemma-3-27b-it`. The
question was: which call site to migrate, and to which Gemma 4
variant, without regressing the six-fixture benchmark.

### What we measured (this session)

We ran the same paper-claim extraction (`spec.py` pass-1, the
hottest LLM call: 36 KB / 9k input tokens for the Adam paper) under
three configurations to pick a Gemma 4 variant:

| Config | Spec latency | n_equations | LaTeX quality | adam_buggy verdict |
|---|---|---|---|---|
| Gemma 3 27B (baseline) | 30s | 6 | clean | ANOMALY (canonical) |
| Gemma 4 26B-A4B-it (MoE) | 193s no-schema / 9-13s with schema | 12-60 | munged (`\text{alpha}`, bare `hat{m}_t`) | inconsistent |
| Gemma 4 31B-it (dense) | 145s no-schema / 12s with schema / 102s with `max_output_tokens=2500` | 6 (schema) – 24 (no schema) – 13 (cap) | clean if we add `_repair_text_macros` | ANOMALY (canonical) |

Three observations from these numbers:

1. **Gemma 4 is fundamentally more verbose than Gemma 3.** Without
   any output constraint, Gemma 4 31B extracts every notational
   definition across all 7 paper sections (24 equations for Adam vs
   Gemma 3's 6). A naive `max_output_tokens=1200` cap doesn't fix
   selectivity — Gemma 4 packs 60 one-line equations into the
   budget instead of 6 complete ones. Schema enforcement
   (`response_schema` with `maxItems`) is the only mechanism that
   forces *selective* decoding.
2. **MoE is not faster for this workload.** The 26B-A4B advertised
   "~4B active parameters" speed gain only matters if total output
   tokens are similar. Gemma 4's verbosity nullifies the per-token
   throughput advantage; both 26B-MoE and 31B-dense come out around
   the same wall-clock when generating the same n equations. 31B
   gives marginally cleaner LaTeX in our tests.
3. **Schema enforcement causes LaTeX munging.** With
   `response_schema` enforcement, Gemma 4 emits `\text{alpha}` for
   `\alpha`, `hat{m}_t` (no leading backslash) for `\hat{m}_t`,
   etc. — schema-constrained decoding picks the schema-valid token
   path even when it produces invalid LaTeX. This forces a
   post-parse repair pipeline (`_repair_text_macros` regex). Adds
   ~50 LOC and a regex per accent macro.

### Decision

We narrowed the migration target by looking at *where Gemma 4 is
actually load-bearing on a verdict*. The pipeline has five LLM call
sites, with very different per-call costs and quality requirements:

| Stage | Calls per run | Per-call cost | Output | Quality requirement |
|---|---|---|---|---|
| `spec.paper_claim` | 1 | 8-15s (Gemma 3) / 100-260s (Gemma 4) | 6-13 equations | medium — variance smoothed by focus pass |
| `spec.focus` | 1 | 5-10s | 5-10 equations | medium |
| `pair_match` | 1 | 5-15s | 6-15 PAIRED/UNMATCHED rows | medium — LLM-PAIRED short-circuits |
| `plan` | 1 | 7-10s | 3 strategies | low — deterministic schema |
| `code.judge` (+ `code.critic`) | 0-3 | 5-40s each | equivalence verdict + residual | **HIGH** — the verdict |

The judge is the only call where the output is the verdict itself —
it decides equivalence, extracts the residual, and feeds the critic.
Every other call is a pre-processing step that the judge re-grounds
in the function source. So the migration that maximizes *verdict
quality* per *latency cost* is to put Gemma 4 on the judge and
leave the rest on Gemma 3 27B.

**Final config:**

```python
# nocap-council/nocap_council/code.py
_GEMMA_MODEL = "gemma-4-31b-it"   # LLM judge + Critic
# nocap-council/nocap_council/spec.py        gemma-3-27b-it
# nocap-council/nocap_council/pair_match.py  gemma-3-27b-it
# nocap-council/nocap_council/plan.py        gemma-3-27b-it
```

This is a **one-line change** vs main. None of the Gemma 4 quirks
(verbosity, LaTeX munging) hit the judge because the judge sees a
single equation and a single sympy expression — short input, short
output, no list-of-N selection problem. The judge benefits from
Gemma 4's stronger reasoning over latex/sympy without paying the
latency tax everywhere else.

### Why 31B-dense over 26B-A4B-it (the MoE variant)

In a head-to-head test on `adam_buggy` with the judge running both
models on the same equation+code prompt:

- 31B dense: 8-15s per judge call, residual quality matches Gemma 3
  baseline (`-beta1**t*m/(beta1**t-1)`), critic_score=10.
- 26B-A4B-it MoE: 12-25s per judge call (slower in practice
  despite "faster" marketing — variance is high on the active-expert
  selection for symbolic content), residual quality fluctuated
  between munged-symbol and canonical form across re-runs.

For a single short JSON judge response (~200 tokens out), 31B's
deterministic decoding wins on both axes. We'd revisit MoE if the
workload shifts toward longer chain-of-thought or batched judging.

### Quantitative impact (six-fixture benchmark)

| Fixture | Verdict | Time | Judge call dur (Gemma 4 31B) |
|---|---|---|---|
| `adam_clean` | 🟢 PASS | 71s | n/a (matchers passed) |
| `adam_buggy` | 🔴 ANOMALY | 110s | 41.6s (residual `-beta1**t*m/(beta1**t-1)`) |
| `ddpm_clean` | 🟢 PASS | 124s | 20.5s + 22.4s |
| `ddpm_buggy` | 🔴 ANOMALY | 128s | 34.5s (residual "missing sqrt on x_0 coefficient") |
| `attention_clean` | 🟢 PASS | 102s | 24.8s |
| `attention_buggy` | 🔴 ANOMALY | 242s | 87s + 78s (JSON retry path triggered) |

All six match the PR #21 baseline verdicts and residuals exactly.
The only stage that materially changed is `code[*]` (the judge).

### Trade-offs

- **JSON-escape quirk.** Gemma 4 occasionally emits `\d_k` (single
  backslash) in JSON string fields where a double-backslash is
  required. The existing `client.call_json` retry handles this
  transparently but adds ~80s of latency on the rare case
  (attention_buggy hits it on both judge calls — hence its 242s
  total). For the buggy fixtures the retry path is irrelevant to
  correctness; the residual matches the canonical bug each time.
- **Single-line dependency on Gemma 4 31B's 256K context.** If the
  judge prompt ever exceeds Gemma 3 27B's context (currently ~50K),
  the 31B context window absorbs it. We never came near this in
  practice (longest judge prompt is ~3 KB).
- **Track requirement satisfaction.** The pipeline's only verdict-
  determining LLM call is now Gemma 4. By the track's framing
  ("leverage Gemma 4 through Google Gemini APIs") we are using
  Gemma 4 where it counts — at the equivalence-decision layer.

### What we tried and rejected before settling on the hybrid

To document the dead-ends so future work doesn't re-tread them:

1. **Pure swap (all 5 call sites → Gemma 4 31B).** Spec stage
   exploded from 30s → 145-260s. Output bloomed from 6 → 24-57
   equations. Disqualified.
2. **Pure swap + permissive `max_output_tokens` cap.** Cap=2500 →
   13-eq output, 102s. Cap=1200 → 60-eq packed dense output,
   218s — wrong direction, broader & shallower instead of fewer &
   deeper. Disqualified.
3. **Pure swap + Gemma 4 native `response_schema` enforcement.**
   12s spec, 6 equations, but introduced LaTeX munging requiring a
   `_repair_text_macros` pipeline + bare-accent regex in
   `polygraph.py`. Workable but ~80 LOC of repair code, fragile to
   new munging variants. Disqualified after the hybrid showed we
   could keep Gemma 3 spec + Gemma 4 judge with zero repair code.
4. **Switching pair_match/plan to Gemma 4.** No measured benefit;
   pair_match's LLM resolver works well at Gemma 3 quality, plan's
   schema is deterministic enough that model choice is moot.

The hybrid (Gemma 4 only on the judge) is the smallest change that
satisfies the track requirement and keeps every other measured
quantity at the PR #21 baseline.

---

## 10. Open follow-ups (out of scope for Phase 1)

- **Spec hyperparam filtering at extraction time.** The T1.27 filter
  drops paper-level hyperparams in the matcher; a cleaner design is
  to filter them in `focus_claim_to_function` so the claim itself
  is function-scoped. Bigger refactor; not needed for the
  benchmark.
- **Pair-match LHS truncation.** Gemma's JSON occasionally truncates
  long `paper_lhs_symbol` strings. We don't depend on that field for
  routing (we use `code_target`), but the trace output would read
  better with full symbols.
- **AST-based hyperparam usage detection.** The lexical
  word-boundary filter is conservative-but-blunt. An AST walk for
  parameter usage would be more robust on functions that alias
  hyperparams (`n_heads = self.h`, etc.).
- **More papers.** Adam, DDPM, and Attention exercise the matcher's
  arithmetic, sympy-substitution, and method-chain code paths
  respectively. The next paper to add (likely VAE or BERT) will
  expose new matcher behaviors and feed back into the design.
