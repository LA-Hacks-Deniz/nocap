# plan.md — No Cap execution plan

*Read this first. Every agent (Claude Code, Devin (cloud agent), the user) starts every session by reading this file and the relevant `phases/phase-N.md`.*

---

## 0. Documents to read

| File | Purpose | Who reads |
|---|---|---|
| **`plan.md`** (this file) | Top-level execution plan, agent split, conventions, coordination | All agents, every session |
| **`research.md`** (gitignored, local-only) | Verbatim research dump — paper specs, sponsor docs, technical guides for every component. Grep for `[H1]`–`[H7]` for technical sections. | All agents, on-demand reference |
| **`phases/phase-1.md`** | CLI agent: nocap verifies a paper-implementation in the terminal. **Active phase first.** | All agents during Phase 1 |
| **`phases/phase-2.md`** | Slack integration | All agents during Phase 2 |
| **`phases/phase-3.md`** | Polished frontend at nocap.wiki | All agents during Phase 3 |
| `../30 - Product/Project Plan.md` | Vault canonical project plan (parent vault) | Reference only |
| `../30 - Product/Pitch Deck.md` | 12-slide pitch | Reference for Devpost copy |
| `../30 - Product/Design System.md` | Visual identity locked spec | Reference during Phase 3 |

---

## 1. Project at a glance

**No Cap** — *does the code match the paper?* A polygraph for AI agents that implement research papers. Give No Cap a paper (arXiv ID) and an agent's code; No Cap returns a verdict — pass or anomaly with confidence and per-equation evidence.

- **Domain**: `nocap.wiki` (registered via GoDaddy, code `MLHLAH26`)
- **Tagline**: *"No Cap — does the code match the paper?"*
- **Tracks**: Cognition Augment-the-Agent ($3K + ACUs + Windsurf Pro), MLH × {Gemma 4, GoDaddy, MongoDB Atlas}, Figma Flicker to Flow, Arista
- **Validated on tape** by Cognition rep at LA Hacks 2026 workshop ([transcript](../20 - Research/Workshops/2026-04-24 Cognition Workshop Transcript.md) lines 1206–1214)

**Architecture**: single-writer, three-judge council (per Walden Yan, Apr 22 2026). One Code agent writes; Spec, Plan, Polygraph judge.

**LLM stack** (locked, all free):
- **Gemma 4** (`gemma-4-26b-a4b-it`) — Plan, Code, Polygraph
- **Gemini 2.5 Flash-Lite** — Spec (cheap NLU)
- Single API key from Google AI Studio fresh project, billing OFF

**Backend stack**: Rust (Axum gateway + rmcp MCP + slack-morphism Slack bot), Python (council orchestrator + sympy/AST matchers), MongoDB Atlas (traces). Hosting: cloudflared tunnel from laptop → `nocap.wiki` for the hackathon demo (DO App Platform deferred to Phase 3 as optional).

**Frontend stack**: Next.js 15, Tailwind v4, shadcn/ui + Aceternity, motion, KaTeX. Locked to `Design System.md`.

---

## 2. Two-agent split

We have two agents working in tandem on this codebase: **Claude (this session)** and **Devin (cloud agent)** ($3K credits, spending all). The user delegates tasks.

### Heuristic for who gets what

| Type of work | Owner | Why |
|---|---|---|
| **Long-form code generation, deep paper-faithful implementation** | **Devin (cloud agent)** | More credits, can pull research.md verbatim into context, Opus 4.7 is best at long structured outputs |
| **Glue code, gateway routes, prompt scaffolding** | **Claude** | Faster iteration, can subagent in parallel for boilerplate |
| **Frontend polish (motion, animations)** | **Either; split by component** | Largest parallelizable surface |
| **Demo recording, paper selection, manual decisions** | **User** | Subjective / requires human judgment |

The phase docs (`phases/phase-N.md`) explicitly assign each task to **Devin**, **Claude**, or **User**, with parallelizable task groups marked.

### Coordination protocol (how we avoid collision)

1. **Branch per agent**: `devin/<feature>` and `claude/<feature>`. Merge to `main` after smoke test.
2. **One agent per file**: only one agent edits a given source file at a time. Check `git status` and `git log -1 --name-only` before starting.
3. **Comment-tag in code**: `# DEVIN:` or `# CLAUDE:` near the top of each file marks the owner.
4. **Update phase doc on start/complete**: when starting a task, check `[ ]` → `[~]` (in progress); when done, `[~]` → `[x]`. Commit the phase-doc edit alongside the task.
5. **No PRs for hackathon**: push directly to `main`. If two agents conflict, the agent who pushed second resolves and re-pushes.
6. **Pull before push**: `git pull --rebase` always before pushing.
7. **Lock conflict avoidance via the phase doc table**: each task has a "Files touched" column; agents check that no other in-progress task touches the same file.

---

## 3. Repo structure (target end-state)

```
nocap-repo/
├── README.md                          # public-facing, written last
├── plan.md                            # this file
├── research.md                        # local research dump (gitignored)
├── .gitignore
├── agents.md                          # Cognition's process-eval signal
│
├── phases/
│   ├── phase-1.md                     # CLI agent
│   ├── phase-2.md                     # Slack integration
│   └── phase-3.md                     # Frontend polish
│
├── nocap-council/                     # Python — the brain
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── nocap_council/
│   │   ├── __init__.py
│   │   ├── client.py                  # Gemma 4 + Flash-Lite dispatcher
│   │   ├── paper_extract.py           # arXiv LaTeX → structured
│   │   ├── code_extract.py            # Python AST → structured
│   │   ├── sympy_match.py             # symbolic equivalence
│   │   ├── structural_match.py        # architecture / hyperparam / algo-step diff
│   │   ├── numerical_match.py         # runtime sample-input comparison
│   │   ├── spec.py                    # Formulator role (Flash-Lite)
│   │   ├── plan.py                    # Planner role (Gemma 4)
│   │   ├── code.py                    # Coder role (Gemma 4)
│   │   ├── polygraph.py               # VIGIL Verifier (Gemma 4)
│   │   ├── orchestrator.py            # top-level Spec → Plan → Code → Polygraph
│   │   ├── mongo_log.py               # MongoDB Atlas trace logger
│   │   ├── github_fetch.py            # PR API → diff + new-file contents
│   │   ├── prompts/                   # verbatim prompts from OptimAI + VIGIL papers
│   │   │   ├── formulator.txt
│   │   │   ├── planner.txt
│   │   │   ├── coder.txt
│   │   │   ├── critic.txt
│   │   │   ├── intent_anchor.txt      # VIGIL Fig 5
│   │   │   ├── sanitizer.txt          # VIGIL Fig 6
│   │   │   └── grounding_verifier.txt # VIGIL Fig 8
│   │   └── cli.py                     # `nocap verify-impl <arxiv> <code-file>` CLI
│   └── README.md
│
├── nocap-gateway/                     # Rust — the perimeter
│   ├── Cargo.toml
│   ├── Cargo.lock
│   ├── src/
│   │   ├── main.rs
│   │   ├── routes/
│   │   │   ├── verify.rs              # POST /verify-impl
│   │   │   ├── stream.rs              # WS /stream/:trace_id
│   │   │   ├── slack.rs               # POST /slack-event + /slack-action
│   │   │   └── trace.rs               # GET /trace/:id (replay)
│   │   ├── middleware/
│   │   │   └── slack_sig.rs
│   │   └── council.rs                 # spawns Python orchestrator + Redis pub/sub
│   ├── Dockerfile
│   └── README.md
│
├── nocap-mcp/                         # Rust — MCP server (3 tools, DeepWiki contract)
│   ├── Cargo.toml
│   ├── src/main.rs                    # verify_impl, replay_trajectory, score_paper_match
│   └── README.md
│
├── nocap-frontend/                    # Next.js 15 — the demo surface
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── components.json                # shadcn + aceternity registries
│   ├── public/
│   │   ├── favicon.svg                # `~` glyph (no-cap pun)
│   │   └── og.png
│   └── src/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx               # landing
│       │   ├── globals.css            # Design System tokens
│       │   ├── verify-impl/page.tsx   # form
│       │   ├── trace/[id]/page.tsx    # live trace viewer
│       │   └── results/page.tsx       # past verifications
│       ├── components/
│       │   ├── canvas/DotBackground.tsx
│       │   ├── motion/FadeIn.tsx
│       │   ├── trace/{CouncilCard,SideBySideViewer,VerdictModal,CodeBlock}.tsx
│       │   └── ui/                    # shadcn primitives + aceternity
│       ├── hooks/useReducedMotion.ts
│       └── lib/{ws.ts, katex-render.ts}
│
├── benchmark/                         # 20-instance custom benchmark
│   ├── papers/                        # cached arXiv source tarballs
│   ├── implementations/
│   │   ├── adam_clean.py
│   │   ├── adam_buggy.py
│   │   ├── transformer_attn_clean.py
│   │   ├── transformer_attn_buggy.py
│   │   └── ...                        # 20 papers × 2 (clean + buggy) = 40 files
│   ├── manifest.yaml                  # paper_arxiv_id, code_file, expected_verdict
│   ├── run_all.py                     # iterate manifest, call council, log to MongoDB
│   └── analyze.py                     # precision/recall/F1/FPR + headline chart
│
├── do/
│   └── app.yaml                       # DigitalOcean App Platform spec
│
├── slack/
│   └── manifest.yaml                  # Slack app manifest (slash commands, scopes)
│
├── docs/
│   ├── architecture.md                # diagram + component summary
│   └── DEMO.md                        # 90-second demo script
│
└── .github/
    └── workflows/                     # (hackathon: minimal CI; smoke test only)
        └── smoke.yml
```

---

## 4. Phase plan

### Phase 1: CLI agent (active)

**Goal**: A working `nocap verify-impl <arxiv-id> <code-file>` CLI that:
1. Pulls a trendy econ/quant paper (chosen by user from 3 candidates).
2. Runs the council against an implementation that Claude Code wrote.
3. Prints the verdict — pass/anomaly, confidence, per-equation evidence — directly in the terminal.

**Why CLI first**: smallest viable surface to prove the council works end-to-end before we add Slack and frontend complexity. Failure here means anything else is theatre.

**See `phases/phase-1.md`** for task breakdown.

### Phase 2: Slack integration

**Goal**: `/nocap verify-impl <pr-url>` in Slack returns a threaded reply with verdict + `[View Trace]` button.

**See `phases/phase-2.md`** for task breakdown.

### Phase 3: Frontend polish

**Goal**: `nocap.wiki` live with landing + verify form + live WebSocket trace viewer + verdict modal. Notion/Vercel-grade polish per Design System.

**See `phases/phase-3.md`** for task breakdown.

---

## 5. Conventions

### Python

- **Type hints everywhere** (`from __future__ import annotations` at top of every file).
- **`ruff` + `mypy --strict`** (config in `pyproject.toml`).
- **No `print` for logs** — use `logging` module with `logging.basicConfig(level=INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")`.
- **Docstrings on every public function**: one-line summary, Args, Returns, Raises.
- **No `assert` for runtime checks** — use explicit `raise ValueError(...)`.
- **Package install via `uv`**, not pip directly.

### Rust

- **`clippy::pedantic` + `rustfmt`** (config in `rustfmt.toml`).
- **No `unwrap()` in main paths** — use `?` with `anyhow::Result`.
- **Use `tracing` not `log` or `println!`** — initialize `tracing_subscriber::fmt().with_writer(std::io::stderr).init()` at top of `main`.
- **`thiserror` for library errors, `anyhow` for application errors**.
- **Pin major versions in Cargo.toml**: `rmcp = "=1.5.0"` (rmcp churns; pin exact).

### TypeScript

- **`strict: true`** in `tsconfig.json`. **No `any`**.
- **Named exports only** (no `default export`).
- **Components are functions, not arrow functions assigned to const** (for better stack traces).
- **`'use client'` only when necessary** — server components by default.

### Commits

- **AGENTS DO NOT COMMIT.** Only the user runs `git add / commit / push / pull / etc.`
- Agents write code, edit phase docs locally, and tell the user when ready for review.
- The user uses conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`) when committing — this is human discipline, not enforced on agents.

### File touch protocol

When you start a task, before editing any file:
1. Read `phases/phase-N.md` and check what's currently `[~]` (in progress).
2. If your target file is in the "Files touched" of an in-progress task owned by the OTHER agent, do NOT edit it. Ask the user.
3. Add `# Owner: CLAUDE — Phase N task T<id>` (or `DEVIN`) comment near the top of any file you create.

You do NOT need to `git pull` — both agents share the local filesystem; coordination is via the phase doc only.

---

## 6. Definitions of done

A task is **done** when:
1. The deliverable file(s) exist and pass syntax check (no compile errors).
2. The acceptance criterion in the phase doc is verifiable on the command line in <60s.
3. The phase doc table is updated `[~]` → `[x]`.
4. Agent tells the user "T<id> done, ready for review." User reviews diff and commits if satisfied.

A **phase** is done when:
1. All `[x]` in its phase doc.
2. The phase's "Smoke test" passes end-to-end on the user's machine.
3. The user reviews + explicitly approves the next phase to start.

---

## 7. Sponsor track checklist (mention in Devpost)

When any phase produces a sponsor-touching artifact, the agent that wrote the code is responsible for:
1. Adding the sponsor name to the relevant section of `README.md` "Built With".
2. Capturing one screenshot proving the sponsor's tech is live (saved to `docs/screenshots/`).
3. Naming the sponsor explicitly in the relevant `phases/phase-N.md` "Sponsor signals" section.

| Track | Required | Where it lands |
|---|---|---|
| **Cognition Augment-the-Agent** | Tool that makes AI coding agents measurably more capable | Whole project + benchmark numbers + dogfood capture |
| **MLH × Gemma 4** | Use Gemma 4, free via AI Studio billing-OFF | `nocap-council/client.py` |
| **MLH × GoDaddy Registry** | Punny domain via code `MLHLAH26` | `nocap.wiki` registered |
| **MLH × MongoDB Atlas** | Cloud Atlas trace store (not local) | `nocap-council/mongo_log.py` |
| **Figma Flicker to Flow** | Friction-into-function for ML researchers | Devpost narrative + landing page design |
| **Arista Networks** | Web/mobile/desktop app | `nocap-frontend/` deployed at `nocap.wiki` |

---

## 8. Common gotchas (quick reference; full detail in `research.md`)

| Issue | Where | research.md section |
|---|---|---|
| Gemma doesn't support `system_instruction` config field | `client.py` | `[H1]` §6 |
| Gemma doesn't support `response_schema` — use Flash-Lite for structured output | `client.py`, `spec.py` | `[H1]` §5 |
| arXiv source URL is `e-print/<id>`, not `pdf/<id>` | `paper_extract.py` | `[H2]` §1 |
| `parse_latex` doesn't handle `\hat{m}_t` — regex preprocess to `m_hat_t` | `sympy_match.py` | `[H3]` §2 |
| `sympy.simplify(a-b) == 0` is one-sided: zero⇒equal, nonzero⇒unknown. Always fall back to `Expr.equals()` then numerical. | `sympy_match.py` | `[H3]` §1, §5 |
| Gateway logs to stderr (not stdout) — stdout is the MCP transport | `nocap-mcp/src/main.rs` | `[H4]` §3 |
| rmcp 1.5 needs `serde_json::Value` return type, not typed struct | `nocap-mcp/src/main.rs` | `[H4]` §5 |
| Slack ack must be HTTP 200 within 3 seconds — defer real work via `tokio::spawn` | `nocap-gateway/src/routes/slack.rs` | `[H4]` §10 |
| MongoDB Atlas: allowlist `0.0.0.0/0` for hackathon (App Platform has no static egress IP) | `do/app.yaml` | `[H5]` §18, `[H7]` A.1 |
| Vercel cannot host long-lived WebSockets — proxy to DO `wss://` | `nocap-frontend/src/lib/ws.ts` | `[H6]` §12 |
| KaTeX `throwOnError: true` crashes the page on bad equations — set `false` | `nocap-frontend/src/lib/katex-render.ts` | `[H6]` §6 |
| GitHub PR API: 60 req/hr unauthenticated — always set `GITHUB_TOKEN` | `nocap-council/github_fetch.py` | `[H7]` B.3 |

---

## 9. Quick start for a new agent reading this for the first time

1. **Read this file top to bottom** (you're doing it now).
2. **Read `phases/phase-1.md`** to find the active task for your owner role.
3. **Find your unclaimed task** (status `[ ]`, owner = you).
4. **Mark it `[~]`** in the phase doc and commit.
5. **Reference the relevant `[Hx]` section in `research.md`** for the technical spec.
6. **Build the deliverable**, verify the acceptance criterion runs in <60s.
7. **Mark `[x]`**, commit, push.
8. **Pick the next unclaimed task in your column.** Repeat.

If you're stuck: read the gotcha for your component in §8, then ask the user — don't guess.

---

← Back to [project plan](../30%20-%20Product/Project%20Plan.md) (vault canonical)
