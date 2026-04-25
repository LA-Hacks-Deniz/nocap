# CLAUDE.md — Agent Quick Reference

*Auto-loaded by Claude Code at session start. Devin (cloud agent) reads this file every session after cloning the repo — it is the navigation map for `nocap-repo`.*

> **Tracked-for-now, untracked-at-submission**: `CLAUDE.md`, `plan.md`, `phases/`, and `research.md` are TEMPORARILY committed so Devin can read them after `git clone`. The user will `git rm -r --cached` them and re-enable the gitignore lines before publishing the final public repo.

---

## Read order (every session, in this order)

1. **`CLAUDE.md`** (this file) — navigation, ownership rules, conflict-avoidance protocol.
2. **`plan.md`** — full execution plan, conventions, sponsor track checklist, gotchas.
3. **`phases/phase-N.md`** — current active phase. Find your unclaimed task.
4. **`research.md`** — verbatim technical references (grep `[H1]`–`[H7]`). On-demand only.

---

## Project in 3 lines

**No Cap** = polygraph for AI agents that implement research papers. Give it a paper + agent's code; it returns a verdict (pass / anomaly + confidence + per-equation evidence). Stack: Rust gateway + Python council + Next.js frontend, all LLMs on Gemma 4 + Flash-Lite (Google AI Studio, free, billing OFF). Targets Cognition $3K + MLH stacks at LA Hacks 2026. Domain: `nocap.wiki`.

---

## Two-agent split

| Agent | Role | Best at | How it commits |
|---|---|---|---|
| **Claude (this session)** | Glue, scaffolding, gateway routes, prompt wiring, frontend polish | Fast iteration, parallel subagents, Rust + TypeScript | Edits files locally; user reviews diff and commits |
| **Devin (cloud agent)** | Long-form structured implementations of paper-faithful logic | Heavy code generation with research.md as context | Clones repo in its sandbox, branches per task, opens a PR per task — user pulls, asks Claude to review the diff, then merges |
| **User** | Paper selection, manual setup (Slack/Atlas/DO), demo capture, ALL git operations on `main` | Decisions, judgment calls | `git add` / `commit` / `push` / merging Devin PRs |

The phase docs (`phases/phase-N.md`) explicitly assign each task to one of these.

---

## NON-NEGOTIABLE rules (read carefully)

### 1. Update the phase doc when you start AND finish a task

Every task in `phases/phase-N.md` has a status checkbox:

- `[ ]` — unclaimed, anyone can take it
- `[~]` — in progress, currently owned (do not touch)
- `[x]` — done

**Workflow depends on which agent you are:**

**Claude Code (local):**
```
1. Open phases/phase-N.md, find your unclaimed task (owner = @claude).
2. Edit the checkbox in place: [ ] → [~] @claude — yyyy-mm-dd hh:mm
3. SAVE the file. DO NOT run any git command. The user owns git.
4. Do the work. Write code, run smoke tests, etc.
5. When done, edit the checkbox: [~] → [x] @claude
6. SAVE. Tell the user the task is done so they can review and commit.
```

**Devin (cloud sandbox):**
```
1. `git clone` + `git pull origin main` to get the latest state INCLUDING
   any phase-doc edits Claude made locally that the user has since pushed.
2. Open phases/phase-N.md, find an unclaimed task owned by @devin.
   IMPORTANT: also check whether any task is currently [~] @claude — if
   your target task's "Files touched" overlap with a [~] @claude task,
   pick a different unclaimed task to avoid collision.
3. **READ FIRST, ASK BEFORE CODING.** Before writing a single line, read:
   the full task block in phases/phase-N.md, all `Reference:` sections it
   cites in research.md (`[Hx]`), the parent vault path (`../20 - Research/...`)
   if cited, and any sibling files in the same directory. Then decide if
   anything is ambiguous — file path, function signature, edge case, choice
   of library, dependency to add, etc.
4. **If ANY question, ASK THE USER directly in chat (Devin's chat interface,
   not the PR).** Bundle every question into a single numbered list, send
   it, and WAIT. Do not start coding speculatively. Do not open the PR yet.
   Examples of things to ask: "should I use TexSoup or pylatexenc for
   accent flattening?", "the phase doc says Adam test fixture but T1.15 is
   already done — should I use a different paper?", "spec says return dict
   keyed by section name — what if the paper has no numbered sections?".
   ONLY skip this step if you genuinely have no questions.
5. After the user answers (or if you have no questions), create a branch:
   `devin/T<task-id>-<short-slug>` (e.g. `devin/T1.3-paper-extract`).
6. Edit the checkbox in phases/phase-N.md: [ ] → [~] @devin — yyyy-mm-dd hh:mm
7. Commit JUST the phase-doc claim with message "claim T<id>" and push the
   branch. Open a draft PR titled "T<id> — <task-title> (WIP)" so the
   claim is visible on GitHub.
8. Do the work. Commit incrementally on the same branch. If a NEW question
   arises mid-task, STOP and ask the user in chat (not PR) — same rule.
9. When acceptance criteria pass, edit the checkbox: [~] → [x] @devin
10. Convert the PR from draft to ready-for-review. Title format:
    "T<id> — <task-title>". Body must include: (a) link to the phase-doc
    task, (b) acceptance-criteria checklist with each box ticked, (c) the
    actual command + output that proves acceptance, (d) any deviations
    from the task spec and why. Do NOT use the PR body for open questions
    — those should already be resolved via chat before the PR is ready.
11. STOP. Do not merge. Do not push to main. The user reviews + merges.
```

If you skip the claim step, the other agent may pick the same task and you'll collide. **Always claim before working.**

### 2. One agent per file at any time

Before editing any source file:

```
1. Read phases/phase-N.md and check which tasks are currently [~] (in progress).
2. If your target file appears in the "Files touched" of an in-progress
   task owned by the OTHER agent, do NOT edit it. Ask the user (Claude)
   or pick a different unclaimed task (Devin).
3. Otherwise, proceed.
```

Claude Code does NOT run `git pull` — the user pushes from this machine, so its filesystem is already canonical. Devin DOES run `git pull origin main` at the start of each session and again before opening a PR (to rebase if needed).

### 3. Tag file ownership in code

The first non-shebang line of every source file should be:

```python
# Owner: DEVIN — Phase 1 task T1.5
```

or

```rust
// Owner: CLAUDE — Phase 2 task T2.3
```

This makes it grep-able who wrote what when bug-hunting.

### 4. Git rules differ per agent

**Claude Code**: NEVER runs git. Period. No `add`, `commit`, `push`, `pull`, `status`, `log`, `rebase`, `merge`, `reset`, `checkout`, `stash`. The user runs git from this machine. When a task is done, tell the user in chat ("T1.2 done, ready for review"); the user runs `git diff` and commits.

**Devin**: runs git inside its cloud sandbox to fetch the repo, branch per task, commit work, and push the branch. Devin is **forbidden** from:
- pushing to `main` (always work on a `devin/T<id>-*` branch)
- merging its own PRs
- force-pushing anything (no `--force`, no `--force-with-lease`)
- rewriting published history (no rebase + force-push, no amend after push)
- skipping hooks (no `--no-verify`)
- committing `.env` or anything matching `*.key`, `*.pem`, `secrets/**` (these are gitignored — if Devin sees them, it must STOP and ask the user)

Why the asymmetry: Claude Code shares the user's local filesystem and the user wants visual control over local commits. Devin runs in an isolated sandbox; PRs are the only sane way to surface its work for review. The PR review is the diff review.

### 5. Never commit secrets

`.env` is in `.gitignore`. If you accidentally write a key into source, tell the user immediately so they can rotate it.

---

## Repo navigation cheat sheet

| You want to… | Look at |
|---|---|
| Understand the whole system | `plan.md` §1 + `plan.md` §3 (repo structure) |
| Find your active task | `phases/phase-1.md` (or `-2`/`-3` once active) |
| Look up a technical detail (Gemma API, sympy parsing, rmcp, Slack, Mongo, etc.) | `research.md` — grep `[H1]` through `[H7]` |
| Check if a Cognition / MLH track is wired | `plan.md` §7 (sponsor track checklist) |
| Avoid a known footgun | `plan.md` §8 (common gotchas) |
| Edit visual identity | `../30 - Product/Design System.md` (parent vault, read-only) |
| Find verbatim paper prompts | `nocap-council/prompts/` once Phase 1 task T1.7 is done |

---

## File ownership map (current target state)

When a phase is done, the phase doc updates this table.

| Component | Owner | Status |
|---|---|---|
| `nocap-council/client.py` | Claude | Phase 1 |
| `nocap-council/paper_extract.py` | Devin | Phase 1 |
| `nocap-council/code_extract.py` | Devin | Phase 1 |
| `nocap-council/sympy_match.py` | Devin | Phase 1 |
| `nocap-council/structural_match.py` | Devin | Phase 1 |
| `nocap-council/numerical_match.py` | Claude | Phase 1 |
| `nocap-council/spec.py` | Claude | Phase 1 |
| `nocap-council/plan.py` | Claude | Phase 1 |
| `nocap-council/code.py` | Devin | Phase 1 |
| `nocap-council/polygraph.py` | Devin | Phase 1 |
| `nocap-council/orchestrator.py` | Devin | Phase 1 |
| `nocap-council/cli.py` | Devin | Phase 1 |
| `nocap-council/prompts/*.txt` | Devin | Phase 1 |
| `nocap-council/mongo_log.py` | Claude | Phase 2 |
| `nocap-council/github_fetch.py` | Claude | Phase 2 |
| `nocap-gateway/src/main.rs` | Claude | Phase 2 |
| `nocap-gateway/src/routes/*.rs` | Claude | Phase 2 |
| `nocap-mcp/src/main.rs` | Claude | Phase 2 |
| `nocap-frontend/src/components/canvas/DotBackground.tsx` | Devin | Phase 3 |
| `nocap-frontend/src/components/trace/SideBySideViewer.tsx` | Devin | Phase 3 |
| `nocap-frontend/src/app/page.tsx` (landing) | Devin | Phase 3 |
| `nocap-frontend/src/app/trace/[id]/page.tsx` | Devin | Phase 3 |
| `nocap-frontend/everything else` | Claude | Phase 3 |
| `slack/manifest.yaml` | User | Phase 2 |
| `benchmark/manifest.yaml` + `implementations/*` | Devin + User | Phase 1 stretch |

---

## What NOT to do

- ❌ **Claude Code**: run any `git` command. ANY. The user owns local git.
- ❌ **Devin**: push to `main`, merge your own PR, force-push, rewrite published history, or skip hooks.
- ❌ Edit `phases/phase-N.md` to mark `[x]` without actually completing the acceptance criterion.
- ❌ Start a task without claiming it `[~]` first.
- ❌ Edit a file currently owned by the other agent.
- ❌ Add new top-level dependencies without updating `Cargo.toml` / `pyproject.toml` AND noting in the relevant phase doc.
- ❌ Refactor or "clean up" code in another agent's owned files. Ask the user instead (both agents: ask in chat, not in code or PR comments).
- ❌ Write secrets into source files (the `.env` is the only place keys live). Devin specifically: if a `.env` ever appears in your working tree, do NOT commit it — `.env` is gitignored for a reason.
- ❌ Commit anything in the "Tracked-for-now" set (`CLAUDE.md`, `plan.md`, `phases/`, `research.md`) for Devin sessions after the user has flipped them back to gitignored. Check `.gitignore` first.

---

## What to do when you're confused

1. Check `plan.md` §8 (gotchas) for your component.
2. Grep `research.md` for the relevant `[Hx]` section.
3. Look at the parent vault canonical: `../30 - Product/Project Plan.md` and `../30 - Product/Pitch Deck.md`.
4. If still stuck: STOP and ask the user in chat. Both agents — Claude in this session's chat, Devin in Devin's chat interface (not the PR description). Mark the phase task `[~]` with `(BLOCKED — awaiting user)` so the other agent doesn't claim it.

---

← Continue to [`plan.md`](plan.md)
