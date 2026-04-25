# Phase 2 — Slack integration

*Active after Phase 1 ships. Goal: `/nocap verify-impl <github-pr-url>` in Slack returns a threaded reply with verdict + voice playback button + `[View Trace]` link.*

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
  [Replay trace] [Play voice] [Approve anyway]
```

4. Click `[Play voice]` → ElevenLabs voice plays inline in Slack.

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

### T2.1 — Provision ElevenLabs

- [ ] **@user**
- **Deliverable**: ElevenLabs free-tier account, API key in `.env` as `ELEVENLABS_API_KEY`, voice ID in `.env` as `ELEVENLABS_VOICE_ID` (recommend `EXAVITQu4vr4xnSDxMaL` "Sarah" or `JBFqnCBsd6RMkjVDRZzb` "George").
- **Acceptance**: `curl -H "xi-api-key: $ELEVENLABS_API_KEY" https://api.elevenlabs.io/v1/voices` returns 200.
- **Hours**: 0.25
- **Reference**: `research.md [H7]` Part C §1.

### T2.2 — Provision DigitalOcean App Platform

- [ ] **@user**
- **Deliverable**: DO account with $200 MLH credit (signup via https://mlh.link/digitalocean-signup), `doctl` CLI installed locally, project `nocap` created in DO control panel, GitHub App installed on the `nocap-team/nocap` repo.
- **Acceptance**: `doctl account get` succeeds; project `nocap` visible in dashboard.
- **Hours**: 0.5
- **Reference**: `research.md [H5]` §1.

### T2.3 — Provision Gradient AI key

- [ ] **@user**
- **Deliverable**: in DO control panel → AI/ML → Model Access Keys → Create. Save as `.env` `GRADIENT_API_KEY` (`sk-do-v1-...`).
- **Acceptance**: `curl -H "Authorization: Bearer $GRADIENT_API_KEY" -H "Content-Type: application/json" -d '{"model":"gte-large-en-v1.5","input":["test"]}' https://inference.do-ai.run/v1/embeddings` returns 200 with an embedding vector.
- **Hours**: 0.25
- **Reference**: `research.md [H5]` §10.

---

## Task block A — Council secondary (parallelizable, 4 tasks)

> **Parallelism**: T2.4, T2.5, T2.6, T2.7 are independent.

### T2.4 — `mongo_log.py`

- [ ] **@claude**
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

### T2.6 — `gradient_embeddings.py`

- [ ] **@claude**
- **Deliverable**: `nocap-council/nocap_council/gradient_embeddings.py` with `embed`, `embed_batch`, `cosine`, `best_section` using DO Gradient AI via `openai` SDK pointed at `https://inference.do-ai.run/v1`.
- **Acceptance**: `python -c "from nocap_council.gradient_embeddings import *; print(best_section('Adam optimizer', ['§3 Loss function', '§4 Optimization', '§5 Experiments']))"` returns `(1, <score>)` (the §4 match).
- **Files touched**: `nocap-council/nocap_council/gradient_embeddings.py`.
- **Hours**: 1
- **Reference**: `research.md [H5]` §11 (complete drop-in module).
- **Dependencies**: `openai` (used as a generic OpenAI-API-compatible client).

### T2.7 — `voice_text.py`

- [ ] **@devin**
- **Deliverable**: `nocap-council/nocap_council/voice_text.py` with `render_verdict(verdict_dict) -> str` that produces ElevenLabs-friendly text (numbers spelled out, brand voice "no cap"/"cap detected").
- **Acceptance**: pass a verdict dict, output is grammatically correct sentence ≤ 200 chars suitable for TTS.
- **Files touched**: `nocap-council/nocap_council/voice_text.py`.
- **Hours**: 0.5
- **Reference**: `research.md [H7]` Part C §3.

---

## Task block B — Rust gateway (sequential, 5 tasks)

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
  - Interactivity: parses button payload, dispatches on `action_id` (`view_trace` / `play_voice` / `approve_anyway`).
- **Acceptance**: typing `/nocap verify-impl https://github.com/foo/bar/pull/142` in the demo Slack workspace returns the threaded reply with the verdict within 30s.
- **Files touched**: `nocap-gateway/src/routes/slack.rs`, `nocap-gateway/src/middleware/slack_sig.rs`.
- **Hours**: 3
- **Reference**: `research.md [H4]` Part B §10–§11. Critical: ack within 3s (use `tokio::spawn` for the verify flow).

### T2.11 — `GET /voice/:trace_id` (ElevenLabs proxy)

- [ ] **@devin**
- **Deliverable**: `nocap-gateway/src/routes/voice.rs` that fetches the verdict from MongoDB by `trace_id`, runs `render_verdict(verdict)` (call into the Python module via subprocess OR re-implement in Rust), calls ElevenLabs TTS, returns MP3 bytes with `Content-Type: audio/mpeg`.
- **Acceptance**: `curl localhost:8787/voice/<known-trace-id> > out.mp3 && file out.mp3` shows it's a valid MP3.
- **Files touched**: `nocap-gateway/src/routes/voice.rs`.
- **Hours**: 2
- **Reference**: `research.md [H7]` Part C §2 (Rust snippet) + `research.md [H4]` §12.
- **Cache**: hash verdict text → cache MP3 in MongoDB (gridfs OR base64 in trace doc) to avoid burning ElevenLabs free-tier credits during demo prep.

### T2.12 — `Dockerfile` for gateway

- [ ] **@claude**
- **Deliverable**: `nocap-gateway/Dockerfile` multi-stage with `cargo-chef` cache + distroless runtime.
- **Acceptance**: `docker build -t nocap-gateway nocap-gateway/` succeeds, image < 100 MB.
- **Files touched**: `nocap-gateway/Dockerfile`.
- **Hours**: 1
- **Reference**: `research.md [H4]` §15 + `research.md [H5]` §4.

---

## Task block C — DigitalOcean deployment (sequential, 2 tasks)

### T2.13 — `do/app.yaml` + first deploy

- [ ] **@claude**
- **Deliverable**: `do/app.yaml` with `nocap-gateway` (web, port 8080) + `nocap-council` (worker) + Redis (managed) + Mongo external + domain `nocap.wiki`. All env vars + secrets configured.
- **Acceptance**: `doctl apps create --spec do/app.yaml` succeeds, `nocap.wiki/health` returns "ok" within 10 minutes.
- **Files touched**: `do/app.yaml`, `nocap-council/Dockerfile`.
- **Hours**: 2
- **Reference**: `research.md [H5]` Part A §3 (complete spec).

### T2.14 — Wire DNS (GoDaddy → DO)

- [ ] **@user**
- **Deliverable**: GoDaddy DNS for `nocap.wiki` pointed at the DO App Platform CNAME target.
- **Acceptance**: `dig nocap.wiki` returns DO IP within 15 min; HTTPS auto-issues.
- **Hours**: 0.25
- **Reference**: `research.md [H5]` §6.

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
- **Deliverable**: terminal recording (or screen capture) of typing `/nocap verify-impl <real PR URL>` in Slack and seeing the threaded verdict + clicking Play Voice and hearing the verdict.
- **Acceptance**: capture saved to `docs/screenshots/phase2-slack-demo.mp4`.
- **Hours**: 0.5

### T2.17 — Phase 2 retrospective

- [ ] **@user**
- **Deliverable**: 3-bullet summary in `docs/PRIVATE-phase2-retro.md`. User explicitly approves Phase 3.
- **Hours**: 0.25

---

## Phase 2 — done when

- [x] T2.0–T2.17 all checked
- Slack demo recording exists
- `nocap.wiki/health` returns 200 (gateway live on DO)
- ElevenLabs voice plays in Slack
- User signs off in T2.17

---

## Sponsor signals captured this phase

- **MLH × DigitalOcean**: gateway hosted on DO App Platform; `gradient_embeddings.py` calls Gradient AI for embedding similarity (proof: `do/app.yaml` shows DO config + screenshot of dashboard).
- **MLH × ElevenLabs**: `/voice/:trace_id` route works in Slack (proof: demo recording).
- **MongoDB Atlas**: trace storage live (proof: dashboard screenshot showing `traces` collection populated).
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
