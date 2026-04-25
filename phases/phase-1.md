# Phase 1 — CLI agent

_Active phase. Goal: a working `nocap verify-impl <arxiv-id> <code-file>` CLI that runs the council against an implementation Claude Code wrote of a trendy econ/quant paper, and prints the verdict in the terminal._

---

## Goal

End-to-end demo, terminal-only:

```bash
$ nocap verify-impl 1412.6980 ./adam_buggy.py
🔴 Anomaly detected — confidence 0.94
  Paper §4 Algorithm 1, equation 3:  m_hat_t = m_t / (1 - β1^t)
  Code line 23:                       m_hat = self.m
  Residual: m_t · β1^t / (1 - β1^t)   (bias correction missing)
$
```

That output proves the entire council works. No Slack, no frontend, no MCP — just terminal. Phase 1 ships when Claude Code generates a buggy implementation of the chosen econ/quant paper and `nocap verify-impl` correctly catches it.

**Test plan**: pick a trendy econ/quant paper (T1.0), have Claude Code implement it (T1.18), run `nocap verify-impl` (T1.19), capture demo (T1.20).

---

## Status legend

- `[ ]` unclaimed
- `[~] @owner — yyyy-mm-dd hh:mm` claimed and in progress
- `[x] @owner` done

**Update this file before AND after working on a task.** See `CLAUDE.md` §"NON-NEGOTIABLE rules" §1.

---

## Pre-task (USER decision required)

### T1.0 — Pick the trendy paper ✅ LOCKED 2026-04-25

- [x] **@user**
- **Chosen paper**: **DDPM (Denoising Diffusion Probabilistic Models)**
- **Citation**: Ho, Jain, Abbeel 2020. _Denoising Diffusion Probabilistic Models_. NeurIPS 2020.
- **arXiv ID**: **`2006.11239`**
- **Source**: `https://arxiv.org/abs/2006.11239` · LaTeX source: `https://arxiv.org/e-print/2006.11239`
- **Why DDPM (recap)**: foundational post-2020 ML paper, universally recognized (Stable Diffusion, Sora derive from this). Math is rich and verifiable. Five canonical LLM-implementation bugs we expect to catch:
  1. Predicting `x_0` instead of `ε` (the simplified loss target).
  2. Wrong direction of `β_t` schedule (linear vs cosine, or reversed).
  3. `α_bar = ∏α` product off-by-one.
  4. Wrong sign in KL term of `L_VLB`.
  5. Forgetting `√(1-α_bar)` scaling in sampling.
- **Demo asset**: the cold-open script becomes _"Claude Code wrote DDPM in 14 seconds. It's predicting the wrong target."_
- **Equations to anchor on**:
  - **Eq 4** — forward process `q(x_t | x_0)`, with `α_bar_t = ∏_s α_s`.
  - **Eq 8 / Eq 14** — simplified loss `L_simple = E_{t,x_0,ε}[||ε - ε_θ(√α_bar_t · x_0 + √(1-α_bar_t)·ε, t)||²]`.
  - **Algorithm 1** — training procedure (5 steps).
  - **Algorithm 2** — sampling procedure (4 steps).

---

## Task block A — Foundation (sequential, 1 task)

### T1.1 — Repo setup

- [x] **@claude**
- **Deliverable**: scaffolded `nocap-council/` Python package with `pyproject.toml`, `uv.lock`, `nocap_council/__init__.py` (empty), `nocap_council/prompts/` empty dir, `.env.example` with `GOOGLE_API_KEY`.
- **Acceptance**: `cd nocap-council && uv sync && python -c "import nocap_council"` exits 0.
- **Files touched**: `nocap-council/{pyproject.toml, uv.lock, nocap_council/__init__.py, nocap_council/prompts/.gitkeep, .env.example}`.
- **Hours**: 0.5
- **Reference**: `research.md [H1]` §2 for SDK install commands.

---

## Task block B — LLM client (sequential after T1.1, 1 task)

### T1.2 — `client.py`

- [x] **@claude**
- **Deliverable**: `nocap_council/client.py` exposing `call(model, system, user, json_schema=None)` and `call_json(model, system, user, schema)` that route to Gemma 4 / Flash-Lite via `google-genai` SDK.
- **Acceptance**: `python -m nocap_council.client` (sets `if __name__ == "__main__"`) makes one call to each model and prints "ready" twice.
- **Files touched**: `nocap-council/nocap_council/client.py`.
- **Hours**: 1
- **Reference**: `research.md [H1]` §10 has the complete drop-in module.
- **Gotchas**: Gemma doesn't support `system_instruction` config field; fold system prompt into user message. See `[H1]` §6.

---

## Task block C — Extractors + matchers (parallelizable after T1.2, 5 tasks)

> **Parallelism**: T1.3, T1.4, T1.5, T1.6, T1.7 are all independent — they don't import from each other. **Two agents can pick up two of these simultaneously.** Just pick different files.

### T1.3 — `paper_extract.py`

- [x] **@devin**
- **Deliverable**: `nocap_council/paper_extract.py` with `fetch_arxiv_source(arxiv_id) -> Path` and `parse_paper(source_dir) -> dict` returning `{section: {equations[], algorithms[], hyperparams{}, architecture[]}}`.
- **Acceptance**: `python -c "from nocap_council.paper_extract import *; src=fetch_arxiv_source('1412.6980'); print(parse_paper(src))"` returns a dict with at least 4 equations and 1 algorithm for Adam.
- **Files touched**: `nocap-council/nocap_council/paper_extract.py`.
- **Hours**: 3
- **Reference**: `research.md [H2]` has a complete production-ready module (~110 lines) drop-in. Copy and adapt.
- **Dependencies to add to pyproject**: `requests`, `TexSoup`, `pylatexenc`.

### T1.4 — `code_extract.py`

- [x] **@devin**
- **Deliverable**: `nocap_council/code_extract.py` with `code_to_sympy(code, fn_name) -> dict[str, sympy.Expr]` that walks Python AST and converts arithmetic to sympy.
- **Acceptance**: `python -c "from nocap_council.code_extract import *; print(code_to_sympy(open('test_adam_clean.py').read(), 'step'))"` returns dict with `m_hat`, `v_hat`, `theta` keys mapped to sympy exprs.
- **Files touched**: `nocap-council/nocap_council/code_extract.py`.
- **Hours**: 2.5
- **Reference**: `research.md [H3]` §3 has the complete `CodeToSympy` visitor class.
- **Dependencies**: `sympy>=1.12`, `numpy`.

### T1.5 — `sympy_match.py`

- [x] **@devin**
- **Deliverable**: `nocap_council/sympy_match.py` with `latex_to_sympy(s, var_map)`, `match_equation(latex, code, var_map, target_var) -> {equivalent, residual, method_used}`. Includes accent regex preprocessor and 5-sample numerical fallback.
- **Acceptance**: `python -m nocap_council.sympy_match` runs the worked Adam example (clean → True; buggy → False with residual `m·β1^t/(1-β1^t)`).
- **Files touched**: `nocap-council/nocap_council/sympy_match.py`.
- **Hours**: 3
- **Reference**: `research.md [H3]` §2, §4, §5 has full implementation.
- **Dependencies**: `sympy>=1.12`, `antlr4-python3-runtime==4.11`, `numpy`.
- **Critical gotcha**: `parse_latex` doesn't handle `\hat{m}_t` — apply `_flatten_accents` regex preprocessor BEFORE `parse_latex`. See `[H3]` §2.

### T1.6 — `structural_match.py`

- [x] **@devin**
- **Deliverable**: `nocap_council/structural_match.py` with `match_structure(paper_extract, code_extract) -> [{type, location, expected, actual, severity}]` returning a list of mismatches.
- **Acceptance**: tests catch (a) "paper has 4 RK4 stages, code has 3", (b) "paper lr=3e-4, code lr=1e-4", (c) "paper Algorithm 1 has 7 lines, code body has 6 distinct ops".
- **Files touched**: `nocap-council/nocap_council/structural_match.py`.
- **Hours**: 2
- **Reference**: `research.md [H3]` §6.

### T1.7 — Verbatim prompt files

- [x] **@devin**
- **Deliverable**: 7 prompt files in `nocap-council/nocap_council/prompts/`:
  - `formulator.txt` — OptimAI Appendix B Formulator prompt, **verbatim**, with `{decision_variables}` reframed for paper-vs-code (`{claimed_equations}`, `{claimed_function}`, `{claimed_hyperparams}`)
  - `planner.txt` — OptimAI Planner, verbatim, with `{Available_Tools}` → `{symbolic, numerical, structural, hyperparametric}`
  - `coder.txt` — OptimAI Coder, verbatim
  - `critic.txt` — OptimAI Code Critic, verbatim
  - `intent_anchor.txt` — VIGIL Fig 5, verbatim
  - `sanitizer.txt` — VIGIL Fig 6, verbatim
  - `grounding_verifier.txt` — VIGIL Fig 8, verbatim
- **Acceptance**: each file is non-empty, contains the canonical paper prompt with our domain swaps. Reviewer can diff against `../20 - Research/Papers/{OptimAI - Spec, VIGIL - Prompts}.md`.
- **Files touched**: `nocap-council/nocap_council/prompts/*.txt`.
- **Hours**: 1.5
- **Reference**: paper specs are in the parent vault — see `../20 - Research/Papers/OptimAI - Spec.md` §12 and `../20 - Research/Papers/VIGIL - Prompts.md`.

---

## Task block D — Council agents (parallelizable after T1.2 + T1.7, 4 tasks)

> **Parallelism**: T1.8 needs T1.2 + T1.7 only. T1.9 same. T1.10 needs T1.5/T1.6/T1.7. T1.11 needs T1.7. **All four can run in parallel** once Block C is done.

### T1.8 — `spec.py` (Formulator role, Flash-Lite)

- [x] **@claude**
- **Deliverable**: `nocap_council/spec.py` with `extract_claim(paper_url, code_str, user_msg=None) -> {paper_section, claimed_equations, claimed_function, claimed_hyperparams}` calling `client.call_json("gemini-2.5-flash-lite", prompt_from_formulator_txt, ...)`.
- **Acceptance**: on the chosen demo paper + Claude Code's implementation, returns a structured JSON pinning the claim to specific paper sections.
- **Files touched**: `nocap-council/nocap_council/spec.py`.
- **Hours**: 1.5
- **Reference**: `research.md [H1]` §5 (JSON mode via Flash-Lite).

### T1.9 — `plan.py` (Planner role, Gemma 4)

- [x] **@claude**
- **Deliverable**: `nocap_council/plan.py` with `generate_strategies(spec) -> [strategy1, strategy2, strategy3]` always returning exactly 3.
- **Acceptance**: returns 3 distinct strategies, each tagged `symbolic | numerical | structural | hyperparametric`.
- **Files touched**: `nocap-council/nocap_council/plan.py`.
- **Hours**: 1.5
- **Reference**: prompt from T1.7 (`planner.txt`).

### T1.10 — `code.py` (Coder role, Gemma 4)

- [x] **@devin**
- **Deliverable**: `nocap_council/code.py` with `run_strategy(strategy, paper_extract, code_extract) -> evidence` that dispatches to `sympy_match` / `numerical_match` / `structural_match` based on strategy type. On failure, runs Critic prompt and returns `{evidence, critic_feedback, critic_score}`.
- **Acceptance**: on Adam buggy, at least 2 of the 3 strategies return `evidence.equivalent=False` with specific residual / mismatch.
- **Files touched**: `nocap-council/nocap_council/code.py`.
- **Hours**: 2.5
- **Reference**: prompt from T1.7 (`coder.txt`, `critic.txt`).

### T1.11 — `polygraph.py` (VIGIL Verifier, Gemma 4)

- [x] **@devin**
- **Deliverable**: `nocap_council/polygraph.py` with three sub-functions:
  - `intent_anchor(user_msg, paper_extract) -> (S, C)` using Fig 5 prompt
  - `sanitize(claim) -> claim_clean` using Fig 6 prompt
  - `verify(evidence, S, C, q) -> {verdict, confidence, V_compliance, V_entailment, evidence_summary}` using Fig 8 prompt
- **Acceptance**: on Adam buggy with Block C results, returns `verdict='Anomaly'`, `confidence > 0.85`, `V_compliance=False`, `V_entailment=False` with specific `evidence_summary`.
- **Files touched**: `nocap-council/nocap_council/polygraph.py`.
- **Hours**: 3
- **Reference**: prompts from T1.7 (`intent_anchor.txt`, `sanitizer.txt`, `grounding_verifier.txt`). VIGIL spec at `../20 - Research/Papers/VIGIL - Spec.md` §4.

---

## Task block E — Optional matchers (parallel with D, optional)

### T1.12 — `numerical_match.py`

- [x] **@claude**
- **Deliverable**: `nocap_council/numerical_match.py` with `numeric_equal(a, b, n_samples=5, rtol=1e-9) -> bool` (5-sample random eval).
- **Acceptance**: returns True for symbolically-different-but-mathematically-equal expressions; False for the buggy Adam case.
- **Files touched**: `nocap-council/nocap_council/numerical_match.py`.
- **Hours**: 1
- **Reference**: `research.md [H3]` §5.

---

## Task block F — Orchestration + CLI (sequential after Block D + E, 2 tasks)

### T1.13 — `orchestrator.py`

- [x] **@devin — 2026-04-25 15:45**
- **Deliverable**: `nocap_council/orchestrator.py` with `verify(paper_arxiv_id, code_str, user_msg=None) -> verdict_dict`. Top-level loop: `paper_extract → spec → plan → for strategy in plans: code → polygraph(evidence)`. Streams events to stdout as line-delimited JSON.
- **Acceptance**: end-to-end run on Adam clean returns `verdict='Pass'`, on Adam buggy returns `verdict='Anomaly'`. Each call < 30s wall clock with Gemma 4.
- **Files touched**: `nocap-council/nocap_council/orchestrator.py`.
- **Hours**: 2
- **Reference**: OptimAI Algorithm 1 single-arm version (no UCB bandit).

### T1.14 — `cli.py` (Click app)

- [x] **@devin — 2026-04-25 16:30**
- **Deliverable**: `nocap_council/cli.py` with Click command `nocap verify-impl <arxiv-id> <code-file> [--claim TEXT]`. Pretty-prints verdict with colors (use `rich`). Wires up to `nocap-council/pyproject.toml` as `[project.scripts] nocap = "nocap_council.cli:cli"` so `pip install -e .` exposes the `nocap` command.
- **Acceptance**: `nocap verify-impl 1412.6980 ./adam_buggy.py` prints the verdict shown in this file's "Goal" section.
- **Files touched**: `nocap-council/nocap_council/cli.py`, `nocap-council/pyproject.toml`.
- **Hours**: 1
- **Dependencies**: `click`, `rich`.

---

## Task block G — Demo capture (sequential, USER-driven, after F)

### T1.15 — Test fixtures: Adam clean + buggy

- [x] **@devin** (parallelizable with all of Block C, D, E if started early)
- **Deliverable**: two files at the repo root for development testing:
  - `benchmark/implementations/adam_clean.py` — correct Adam implementation
  - `benchmark/implementations/adam_buggy.py` — Adam with the bias-correction bug
- **Acceptance**: `python -c "from benchmark.implementations.adam_clean import Adam; ..."` runs.
- **Files touched**: `benchmark/implementations/adam_{clean,buggy}.py`.
- **Hours**: 0.5

### T1.16 — Smoke test on Adam fixtures

- [x] **@devin — 2026-04-25 16:40**
- **Deliverable**: a `Makefile` target `make smoke-adam` that runs `nocap verify-impl 1412.6980 benchmark/implementations/adam_clean.py` and `... adam_buggy.py` and asserts the verdicts.
- **Acceptance**: `make smoke-adam` exits 0 on both and prints the pretty verdicts.
- **Files touched**: `Makefile`.
- **Hours**: 0.5

### T1.21 — Migrate `spec.py` from Flash-Lite to Gemma 3 27B (post-T1.16 follow-up)

- [x] **@devin — 2026-04-25 17:10**
- **Deliverable**: refactor `nocap_council/spec.py` to route through `gemma-3-27b-it` (single-model stack — already used by Plan + Critic). Drop `response_schema=Claim` reliance (Gemma doesn't enforce it); pin shape via a `_JSON_INSTRUCTION` block in the prompt mirroring `plan.py`. Defensive parse: try `Claim.model_validate()` → on `ValidationError`, log warning to stderr and return a Claim with empty defaults. NEVER raise.
- **Why**: Flash-Lite's free-tier 20 RPD limit keeps clipping demos. Gemma 3 27B is ~14,400 RPD on the same key, so going single-model removes a real demo risk.
- **Acceptance**: `make smoke-adam` still exits 0 with both verdicts (clean=pass, buggy=anomaly), wall clock <30s per run. Spec stage still emits `paper_section="Algorithm 1"` and a non-empty `claimed_equations` list.
- **Files touched**: `nocap-council/nocap_council/spec.py`.
- **Hours**: 0.5

### T1.22 — Function-aware Spec + skip-retry orchestrator (post-T1.21 follow-up)

- [x] **@devin**
- **Deliverable**: (1) `spec.extract_claim` gains `function_name` / `function_source` kwargs; when set, the prompt names the function under verification and asks Gemma to extract the equation(s) THAT function claims to implement (not random paper equations). The JSON instruction also asks Spec to rewrite Gaussian distribution-form equations (`q(x_t|x_0) = N(...)`) into reparameterization assignment form so the matcher has an LHS to compare against (Ho et al. 2020 §3.1 eq 4 worked example). (2) `orchestrator._strategy_evidence` skips equations whose `target_var` isn't in `code_env` (or whose matcher returns "X not found") instead of treating them as inequivalent — bundles `skipped_equations` into the evidence dict and emits `status="skipped"` on the JSONL stream when a strategy has no comparable equation. (3) When `--function` is provided, the orchestrator does an early ast resolution pre-spec and passes `function_source` (the def block via `ast.unparse`, decorators + docstring included) to `extract_claim`. Back-compat preserved when `--function` is omitted.
- **Why**: Spec is currently paper-blind to which function the user asked to verify. For DDPM with `--function q_sample`, Spec picks §3.2 (Training Objective) and extracts `L_simple` — but `L_simple` lives in `loss_simple`, not `q_sample`. Matcher then fails on "variable not found" and the run is lost. Same root cause has made every non-Adam paper undemoable.
- **Acceptance**: (1) `make smoke-adam` still exits 0 (regression — Adam was the only paper that worked before, must still work). (2) Live DDPM `q_sample` on the buggy fixture → `verdict=anomaly` with a real symbolic residual reflecting the missing `sqrt` (not "variable not found"). (3) Live DDPM `q_sample` on the clean fixture → `verdict=pass`. (4) Live DDPM `loss_simple` on the buggy fixture → `verdict=pass` (the bug is in `q_sample`'s mean, not the loss).
- **Files touched**: `nocap-council/nocap_council/spec.py`, `nocap-council/nocap_council/orchestrator.py`, `nocap-council/nocap_council/cli.py`, `benchmark/implementations/ddpm_claude_clean.py` (new fixture).
- **Hours**: 4

### T1.23 — LLM-as-judge fallback for non-symbolic-matchable equations (post-T1.22 follow-up)

- [x] **@devin**
- **Deliverable**: (1) New `code._run_llm_judge(paper_equation, code_expr, target_var, function_source) -> dict` — single Gemma call returning `{equivalent, residual, reasoning, method_used="llm_judge"}`. Defensive parse, NOCAP_OFFLINE-gated stub. (2) Wired into `_run_symbolic` and `_run_numerical` as a fallback when the matcher result is non-actionable. Four trigger conditions: (a) `method_used=="failed"`, (b) error message contains "not found" / "KeyError", (c) symbolic result `equivalent=False, method_used=="failed"` (no clean residual), (d) NEW: numerical's `equivalent=True` is unreliable when `code_expr.atoms(sp.Function)` contains symbols not native to SymPy (opaque calls like `_gather`, `randn_like` cancel symmetrically in `subs(...)` and produce false-passes). When trigger (d) fires, set evidence `method_used="numerical_unreliable"` pre-judge so the trace shows WHY the judge ran. (3) Thread `function_source` through `orchestrator._strategy_evidence` → `code.run_strategy(..., function_source=...)`. (4) `polygraph` treats `method_used="llm_judge"` as a strong signal (same weight as symbolic/numerical with no mismatches — the existing 1.0-severity branch already covers this). (5) `cli.py` renders `[symbolic→llm_judge]` / `[numerical→llm_judge]` in the strategy panel header and surfaces the judge's `reasoning` field alongside Critic feedback.
- **Why**: T1.22's q_sample-buggy verdict flakes between `anomaly` and `pass` because numerical strategy treats unknown functions (`_gather`, `randn_like`) as opaque atoms that cancel symmetrically; `subs()` lies. A deterministic LLM judge call as a fallback (~800 input tokens, 1 call per failing strategy) eliminates the flake and unlocks distribution-form / notation-drift cases generally.
- **Acceptance**: (1) `make smoke-adam` still exits 0 with NO `method_used="llm_judge"` entries (Adam is symbolic-matchable; judge shouldn't fire). (2) Live DDPM `q_sample` (buggy) → `verdict=anomaly`, confidence > 0.85, `method_used="llm_judge"` on the catching evidence, reasoning explicitly mentions the `bar_alphas` vs `sqrt_bar_alphas` swap. (3) Live DDPM `q_sample` (clean) → `verdict=pass`, judge reasoning confirms reparameterization equivalence.
- **Files touched**: `nocap-council/nocap_council/code.py`, `nocap-council/nocap_council/orchestrator.py`, `nocap-council/nocap_council/cli.py`, possibly `nocap-council/nocap_council/polygraph.py` (only if the 1.0-severity branch needs adjustment for `llm_judge`).
- **Hours**: 3

### T1.24 — Spec equation ranking + orchestrator `_return` target_var fallback (post-T1.23 follow-up)

- [~] **@devin — 2026-04-25 19:50**
- **Deliverable**: (1) `spec.py` `_JSON_INSTRUCTION` gains an "Equation ranking — REQUIRED" section that tells the function-aware Spec to rank `claimed_equations` in descending priority order — function-defining equations (LHS = function output) FIRST, intermediate assignments next, notational definitions last. Updates the Adam worked example to lead with `\theta_t = ...` and adds a new transformer-attention worked example showing `Attention(Q,K,V) = softmax(QK^T/sqrt(d_k)) V` correctly leading the equation list (vs the wrong version that drops `sqrt(d_k)` by extracting only the intermediate `scores = QK^T`). (2) `orchestrator._strategy_evidence` symbolic/numerical iteration loop: when `_heuristic_target_var` returns a target that isn't a `code_env` key, fall back to `_return` (the orchestrator's canonical "function output" key). The fallback fires BEFORE the `_is_self_referential` check and REPLACES the heuristic outright (no double matcher calls). Function-defining equations (e.g. `Attention(Q,K,V)` with LHS = the function call) need this bridge because their LHS isn't a Python identifier in the function's env.
- **Why**: on `attention_buggy.py` (planted bug: missing `/sqrt(d_k)` scaling in `scaled_dot_product_attention`), Spec extracted equation 1 as the intermediate `scores = QK^T` instead of the full `Attention(Q,K,V) = softmax(QK^T/sqrt(d_k)) V`. The `sqrt(d_k)` scaling lives ONLY in the full formula, so the diagnosis came back as "missing matrix multiplication" rather than "missing 1/sqrt(d_k)". Two coupled root causes: Spec doesn't know which equation is the function's RETURN value (priority signal), and the orchestrator's target_var heuristic can't bridge `Attention(Q,K,V)`-style function-call LHSes to `code_env["_return"]`.
- **Acceptance**: (1) `make smoke-adam` still exits 0 (regression — the new Adam ranking must not break the old equation set). (2) Live transformer attention buggy: `verdict=anomaly` with judge response showing `paper_coefficient` mentioning `sqrt(d_k)` and `code_coefficient` lacking it; `coefficients_match=false`; residual mentions sqrt / scaling — NOT "missing matrix multiplication". (3) Live DDPM `q_sample` (buggy + clean) — T1.23 regression must still pass with the same diagnoses.
- **Files touched**: `nocap-council/nocap_council/spec.py`, `nocap-council/nocap_council/orchestrator.py`.
- **Hours**: 2

### T1.17 — Sponsor track wiring (Gemma 4 + GoDaddy + Atlas seeds)

- [ ] **@user** (manual setup steps; agents can't do these)
- **Deliverables**:
  1. Create AI Studio project `nocap-hack`, billing OFF, copy API key into `.env` as `GOOGLE_API_KEY`. Steps in `research.md [H1]` §1.
  2. Register `nocap.wiki` via GoDaddy with code `MLHLAH26`.
  3. Create MongoDB Atlas M0 cluster (us-east-1), copy SRV connection string into `.env` as `MONGODB_URI`. (Used in Phase 2 — but provision now to avoid blocking.)
- **Acceptance**: all three env vars present in `.env`; `python -m nocap_council.client` runs successfully.
- **Hours**: 0.5

### T1.18 — Have Claude Code implement the chosen paper

- [ ] **@user**
- **Deliverable**: a single Python file `demo/<paper-slug>.py` containing Claude Code's implementation of the paper from T1.0. **Do NOT review or fix it** — submit it raw to capture honest agent output.
- **Acceptance**: file exists, has at least one function, and Claude Code claims (in commit message or PR title) which paper section it implements.
- **Files touched**: `demo/<paper-slug>.py`.
- **Hours**: 0.5 (mostly waiting for Claude Code).

### T1.19 — Run nocap on Claude Code's output

- [ ] **@user**
- **Deliverable**: terminal recording (`asciinema rec demo.cast` or screen capture) showing `nocap verify-impl <arxiv> demo/<paper-slug>.py` running and printing the verdict.
- **Acceptance**: a verdict (pass OR anomaly with evidence) appears within 30s. **Either outcome is fine** — we want to capture honest behavior.
- **Files touched**: `docs/screenshots/phase1-cli-demo.cast` (or `.mp4`).
- **Hours**: 0.25

### T1.20 — Phase 1 retrospective + go/no-go for Phase 2

- [ ] **@user**
- **Deliverable**: a 3-bullet summary in `docs/PRIVATE-phase1-retro.md` (gitignored) covering: what worked, what surprised us, what to change in Phase 2.
- **Acceptance**: user explicitly approves moving to Phase 2.
- **Hours**: 0.25

---

## Phase 1 — done when

- [x] T1.0–T1.20 all checked
- `make smoke-adam` exits 0
- `nocap verify-impl <chosen-paper-arxiv> demo/<paper-slug>.py` runs end-to-end and emits a verdict
- User signs off in T1.20

---

## Sponsor signals captured this phase

- **MLH × Gemma 4**: `nocap-council/client.py` calls `gemma-4-26b-a4b-it` (mention in README "Built With").
- **MLH × GoDaddy**: `nocap.wiki` registered (proof: domain resolves).
- **Cognition Augment-the-Agent**: working CLI verifier of paper implementations (the entire phase).

(MongoDB / DigitalOcean / Arista signals land in Phase 2 + 3.)

---

## Hours estimate

| Block                             | Hours                                               | Notes                       |
| --------------------------------- | --------------------------------------------------- | --------------------------- |
| T1.0 (paper choice)               | 0.25                                                | user, blocking              |
| T1.1 (setup)                      | 0.5                                                 | sequential                  |
| T1.2 (client)                     | 1                                                   | sequential                  |
| Block C (5 parallel tasks)        | 12 wall-clock if serial, **~3.5 if 4-way parallel** | Devin takes 3-4 of these |
| Block D (4 parallel tasks)        | 8.5 if serial, **~3 if 4-way parallel**             | mix                         |
| Block E (1 optional)              | 1                                                   | parallel with D             |
| Block F (orchestrator + CLI)      | 3                                                   | sequential                  |
| Block G (fixtures + smoke + demo) | 1.5                                                 | mostly user                 |
| **Total**                         | **~30h serial / ~13h parallel**                     | aim parallel                |

---

← Back to [`plan.md`](../plan.md) · Forward to [`phase-2.md`](phase-2.md)
