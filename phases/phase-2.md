# Phase 2 — Slack integration

*Active after Phase 1 ships. Goal: `/nocap verify-impl <github-pr-url>` in Slack returns a threaded reply with verdict + `[View Trace]` link.*

---

## Goal

End-to-end Slack flow:

1. Engineer in Slack: `/nocap verify-impl https://github.com/foo/bar/pull/142`
2. Bot acks within 1s: `🔍 Verifying… [view trace](nocap.wiki/trace/abc)`
3. After ~30s, bot edits the thread reply:

```
🔴 No Cap — Anomaly detected (confidence 0.94)
  Paper §4 (Adam): m̂_t = m_t / (1 - β1^t)
  Code lines 23–24 (PR #142): m_hat = self.m
  Bias correction missing.
  [Replay trace] [Approve anyway]
```

Phase 2 ships when an engineer can `/nocap verify-impl <real-pr-url>` in Slack and get a verdict back without anyone touching the terminal.

---

## Status legend (same as phase-1.md)

- `[ ]` unclaimed — `[~] @owner` in progress — `[x] @owner` done
- **Update before AND after working a task.**

---

## Pre-task (USER decisions)

### T2.0 — Provision Slack workspace + app

- [ ] **@user**
- **Deliverable**: a Slack workspace `nocap-demo` (or join one), a Slack app named "No Cap" with:
  - Bot scopes: `commands`, `chat:write`, `chat:write.public`, `chat:write.customize`, `files:write`
  - Slash command `/nocap` → Request URL `https://nocap.wiki/slack-event`
  - Interactivity → Request URL `https://nocap.wiki/slack-action`
  - Bot token (`xoxb-...`) → `.env` as `SLACK_BOT_TOKEN`
  - Signing secret → `.env` as `SLACK_SIGNING_SECRET`
- **Acceptance**: `.env` has both Slack secrets; the slash command appears in the workspace.
- **Files touched**: `slack/manifest.yaml` (export the manifest from the Slack app dashboard for future-proofing).
- **Hours**: 0.5
- **Reference**: `research.md [H4]` Part B §9.

### T2.2 — Cloudflared tunnel + nocap.wiki DNS

- [ ] **@user**
- **Deliverable**:
  1. Install `cloudflared` (`brew install cloudflared`).
  2. Move `nocap.wiki` nameservers from GoDaddy to Cloudflare (Cloudflare → Add Site → free plan → Cloudflare gives you 2 nameservers; paste them into GoDaddy's DNS Nameservers panel). Propagation ~1-24h, but the tunnel works on the trycloudflare.com URL while you wait.
  3. `cloudflared tunnel login` (browser auth) → `cloudflared tunnel create nocap` → returns a UUID.
  4. Create `~/.cloudflared/config.yml` mapping `nocap.wiki` → `localhost:8787` (the gateway port).
  5. `cloudflared tunnel route dns nocap nocap.wiki` (creates the CNAME on Cloudflare automatically).
  6. `cloudflared tunnel run nocap` (leaves the tunnel up for the demo).
- **Acceptance**: `curl https://nocap.wiki/health` returns 200 once the gateway is running locally and DNS has propagated. Until then, the trycloudflare URL works immediately.
- **Hours**: 0.5 (signup + tunnel) + 1-24h DNS propagation in the background.
- **Note**: production hosting (DO App Platform) moves to Phase 3 as optional. Cloudflared + laptop is the hackathon-grade demo path.

---

## Task block A — Council secondary (parallelizable, 2 tasks)

> **Parallelism**: T2.4, T2.5 are independent.

### T2.4 — `mongo_log.py`

- [x] **@claude**
- **Deliverable**: `nocap-council/nocap_council/mongo_log.py` with `init_trace`, `log_event`, `finalize`, `get_trace`. Schema follows Cognition Agent Trace format.
- **Acceptance**: `python -c "from nocap_council.mongo_log import *; tid = init_trace('1412.6980', {'source':'test'}); log_event(tid, 'spec', {'foo':'bar'}); finalize(tid, {'verdict':'pass'}); print(get_trace(tid))"` round-trips.
- **Files touched**: `nocap-council/nocap_council/mongo_log.py`.
- **Hours**: 1
- **Reference**: `research.md [H7]` Part A.

### T2.5 — `github_fetch.py`

- [ ] **@claude**
- **Deliverable**: `nocap-council/nocap_council/github_fetch.py` with `fetch_pr(pr_url) -> {diff, title, body, files, head_sha, owner, repo, number}` using GitHub REST API + `unidiff`.
- **Acceptance**: `python -c "from nocap_council.github_fetch import *; print(fetch_pr('https://github.com/anthropics/claude-code/pull/1')['title'])"` returns the PR title.
- **Files touched**: `nocap-council/nocap_council/github_fetch.py`.
- **Hours**: 1.5
- **Reference**: `research.md [H7]` Part B (complete drop-in module).
- **Dependencies**: `unidiff`, `requests`. Note: ALWAYS set `GITHUB_TOKEN` in `.env`.

---

## Task block B — Rust gateway (sequential, 4 tasks)

### T2.8 — Gateway scaffold

- [ ] **@claude**
- **Deliverable**: `nocap-gateway/Cargo.toml` with deps + `src/main.rs` Axum server on `:8787` with `GET /health` returning "ok".
- **Acceptance**: `cargo run -p nocap-gateway` then `curl localhost:8787/health` returns "ok".
- **Files touched**: `nocap-gateway/Cargo.toml`, `nocap-gateway/src/main.rs`.
- **Hours**: 1
- **Reference**: `research.md [H4]` Part C §13.

### T2.9 — `POST /verify-impl`

- [ ] **@claude**
- **Deliverable**: `nocap-gateway/src/routes/verify.rs` accepting `{paper_arxiv_id, code, claim?}` body. Generates trace_id, writes init record to MongoDB, spawns Python orchestrator subprocess via `tokio::process::Command`, returns `{trace_id}`.
- **Acceptance**: `curl -X POST -d '{"paper_arxiv_id":"1412.6980","code":"..."}' localhost:8787/verify-impl` returns `{"trace_id":"<uuid>"}` and the orchestrator process spawns.
- **Files touched**: `nocap-gateway/src/routes/verify.rs`, `nocap-gateway/src/main.rs` (route mount).
- **Hours**: 2
- **Reference**: `research.md [H4]` §13 (`spawn_council` pattern).

### T2.10 — `POST /slack-event` (slash command + interactivity)

- [ ] **@claude**
- **Deliverable**: `nocap-gateway/src/routes/slack.rs` with two handlers:
  - Slash command: parses `/nocap verify-impl <pr-url>`, verifies signing secret, posts immediate ack ("🔍 Verifying… [view trace]"), spawns the verify flow async, posts final verdict to Slack via `chat.postMessage` (with thread_ts).
  - Interactivity: parses button payload, dispatches on `action_id` (`view_trace` / `approve_anyway`).
- **Acceptance**: typing `/nocap verify-impl https://github.com/foo/bar/pull/142` in the demo Slack workspace returns the threaded reply with the verdict within 30s.
- **Files touched**: `nocap-gateway/src/routes/slack.rs`, `nocap-gateway/src/middleware/slack_sig.rs`.
- **Hours**: 3
- **Reference**: `research.md [H4]` Part B §10–§11. Critical: ack within 3s (use `tokio::spawn` for the verify flow).

### T2.12 — `Dockerfile` for gateway

- [ ] **@claude**
- **Deliverable**: `nocap-gateway/Dockerfile` multi-stage with `cargo-chef` cache + distroless runtime.
- **Acceptance**: `docker build -t nocap-gateway nocap-gateway/` succeeds, image < 100 MB.
- **Files touched**: `nocap-gateway/Dockerfile`.
- **Hours**: 1
- **Reference**: `research.md [H4]` §15 + `research.md [H5]` §4.

---

> **Hosting note**: T2.2 (cloudflared tunnel) is the hackathon-grade hosting path. The gateway runs on the user's laptop; cloudflared exposes it via `nocap.wiki`. Production hosting on DigitalOcean App Platform is an optional Phase 3 task (see phase-3.md).

---

## Task block D — End-to-end smoke (sequential)

### T2.15 — Discord webhook fallback (defensive)

- [ ] **@claude**
- **Deliverable**: alongside Slack post, gateway also POSTs the verdict to a configured Discord webhook URL (`.env` `DISCORD_WEBHOOK_URL`). Useful if Slack workspace flakes during demo.
- **Acceptance**: verdict appears in Discord channel within 2s of Slack thread edit.
- **Files touched**: `nocap-gateway/src/routes/slack.rs` (fanout).
- **Hours**: 0.5

### T2.16 — Live Slack demo

- [ ] **@user**
- **Deliverable**: terminal recording (or screen capture) of typing `/nocap verify-impl <real PR URL>` in Slack and seeing the threaded verdict.
- **Acceptance**: capture saved to `docs/screenshots/phase2-slack-demo.mp4`.
- **Hours**: 0.5

### T2.17 — Phase 2 retrospective

- [ ] **@user**
- **Deliverable**: 3-bullet summary in `docs/PRIVATE-phase2-retro.md`. User explicitly approves Phase 3.
- **Hours**: 0.25

---

## Phase 2 — done when

- [ ] T2.0–T2.17 all checked
- Slack demo recording exists
- `nocap.wiki/health` returns 200 (gateway live on DO)
- User signs off in T2.17

---

## Sponsor signals captured this phase

- **MongoDB Atlas**: trace storage live (proof: dashboard screenshot showing `traces` collection populated). Cloudflared tunnel exposes the laptop-hosted gateway at `nocap.wiki` for the demo.
- **Cognition Augment-the-Agent**: same as Phase 1 + now Slack-native (sequential to swyx's "Slack is the killer agent UI").

---

## Hours estimate

| Block | Hours | Notes |
|---|---|---|
| T2.0–T2.3 (user provisioning) | 1.5 | parallel with Block A |
| Block A (4 parallel) | 4 if serial, **~1.5 if 2-way parallel** | |
| Block B (gateway, sequential) | 9 | bulk of Claude work |
| Block C (DO deploy) | 2.25 | sequential |
| Block D (smoke + retro) | 1.25 | mostly user |
| **Total** | **~18h serial / ~12h parallel** | |

---

← Back to [`phase-1.md`](phase-1.md) · Forward to [`phase-3.md`](phase-3.md)
