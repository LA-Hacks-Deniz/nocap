# Phase 3 — Frontend polish

*Active after Phase 2 ships. Goal: `nocap.wiki` live with landing + verify form + live WebSocket trace viewer + verdict modal. Notion/Vercel-grade polish per Design System.*

---

## Goal

End-to-end visual story:

1. Visitor lands at `nocap.wiki` — large `~` logo, tagline "does the code match the paper?", interactive cursor-reactive dot canvas, paper URL + code paste form.
2. Submit → redirect to `/trace/:id` — live WebSocket dashboard with 4 council cards (Spec / Plan / Code / Polygraph) animating in as the council progresses.
3. Side-by-side viewer: KaTeX-rendered paper math (left) ↔ syntax-highlighted code (right). Mismatched equations rendered in **bold weight** (no color — per Design System).
4. Final verdict modal: confidence band (Bold / Medium / Regular weight), per-equation pass/fail.
5. `/results` shows past verifications.

Phase 3 ships when a judge can hit `nocap.wiki` from their phone and watch a live verification in real time.

**Visual identity is locked**: see `../30 - Product/Design System.md`. Warm off-white #FAFAFA + warm near-black #1a1a1a. **No accent colors.** Inter Bold. Interactive dot canvas is the signature visual.

---

## Status legend (same as phase-1.md)

- `[ ]` unclaimed — `[~] @owner` in progress — `[x] @owner` done

---

## Pre-task

### T3.0 — Verify Phase 2 deployment is stable

- [ ] **@user**
- **Acceptance**: `nocap.wiki/health` returns 200; one Slack `/nocap verify-impl` call ran end-to-end in the last 24h.
- **Hours**: 0.1

---

## Task block A — Scaffold + theme (sequential, 3 tasks)

### T3.1 — Next.js scaffold

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/` from `npx create-next-app@15 nocap-frontend --typescript --tailwind --eslint --app --src-dir --import-alias="@/*" --turbopack`.
- **Acceptance**: `cd nocap-frontend && npm run dev` shows the default page at `localhost:3000`.
- **Files touched**: `nocap-frontend/{package.json, tsconfig.json, next.config.ts, postcss.config.mjs, src/app/{layout.tsx, page.tsx, globals.css}}`.
- **Hours**: 0.5
- **Reference**: `research.md [H6]` §2.

### T3.2 — Theme tokens + Inter font + favicon

- [ ] **@claude**
- **Deliverable**: replace default `globals.css` with Design System theme tokens (warm off-white bg, warm near-black fg, no accents). Inter via `next/font/google` in `layout.tsx`. `~` favicon SVG in `public/favicon.svg`.
- **Acceptance**: page background is `#FAFAFA`, body text Inter, favicon shows in browser tab as a `~`.
- **Files touched**: `nocap-frontend/src/app/{globals.css, layout.tsx}`, `nocap-frontend/public/favicon.svg`.
- **Hours**: 0.5
- **Reference**: `research.md [H6]` §2 + §3 + the Design System §"Quick Reference".

### T3.3 — shadcn + Aceternity install

- [ ] **@claude**
- **Deliverable**: `npx shadcn@latest init` then `npx shadcn@latest add button input` + register Aceternity registry in `components.json` and `npx shadcn@latest add @aceternity/placeholders-and-vanish-input`.
- **Acceptance**: `import { Button } from '@/components/ui/button'` works. `import { PlaceholdersAndVanishInput } from '@/components/ui/placeholders-and-vanish-input'` works.
- **Files touched**: `nocap-frontend/components.json`, `nocap-frontend/src/components/ui/{button.tsx, input.tsx, placeholders-and-vanish-input.tsx}`.
- **Hours**: 0.5
- **Reference**: `research.md [H6]` §1.

---

## Task block B — Reusable primitives (parallelizable, 3 tasks)

> **Parallelism**: T3.4, T3.5, T3.6 are independent.

### T3.4 — `DotBackground.tsx` (the signature canvas)

- [ ] **@devin**
- **Deliverable**: `nocap-frontend/src/components/canvas/DotBackground.tsx`. Cursor-reactive on desktop (28px spacing, 0.8→2.5px radius, 150px influence, lerp 0.08, quadratic falloff `t*t`). Mobile: ambient sine drift. Reduced-motion: static. DPR-aware.
- **Acceptance**: render `<DotBackground />` on landing; cursor over the page makes nearby dots smoothly grow + darken; mobile shows ambient drift.
- **Files touched**: `nocap-frontend/src/components/canvas/DotBackground.tsx`.
- **Hours**: 2.5
- **Reference**: `research.md [H6]` §4 (complete component drop-in). Design System §"Interactive Dot Background".

### T3.5 — `FadeIn.tsx`

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/components/motion/FadeIn.tsx` using `motion/react` with `{ opacity: 0, y: 20 } → { opacity: 1, y: 0 }`, easeOut, 500ms, respects `useReducedMotion()`.
- **Acceptance**: wrap any element in `<FadeIn delay={0.2}>...</FadeIn>` and it slides up + fades in 200ms after page load.
- **Files touched**: `nocap-frontend/src/components/motion/FadeIn.tsx`.
- **Hours**: 0.5
- **Reference**: `research.md [H6]` §5.

### T3.6 — `katex-render.ts` + `CodeBlock.tsx`

- [ ] **@claude**
- **Deliverable**: 
  - `nocap-frontend/src/lib/katex-render.ts` with `renderTeX(src, displayMode=false)` using `katex.renderToString` (SSR-safe), with custom macros (`\bm`, `\argmin`, `\E`, `\R`).
  - `nocap-frontend/src/components/trace/CodeBlock.tsx` using `react-syntax-highlighter` with the monochrome theme from H6.
- **Acceptance**: `<div dangerouslySetInnerHTML={{__html: renderTeX('\\hat{m}_t')}}/>` renders proper LaTeX. `<CodeBlock code="..." flagged={[23,24]} />` renders syntax-highlighted Python with lines 23-24 in **bold**.
- **Files touched**: `nocap-frontend/src/lib/katex-render.ts`, `nocap-frontend/src/components/trace/CodeBlock.tsx`.
- **Hours**: 1.5
- **Reference**: `research.md [H6]` §6 + §7. Use `@matejmazur/react-katex` (the maintained fork; `react-katex` is unmaintained).

---

## Task block C — Pages (sequential after Block A + B, 4 tasks)

### T3.7 — Landing page (`app/page.tsx`)

- [ ] **@devin**
- **Deliverable**: `nocap-frontend/src/app/page.tsx`. Hero `~` (text-5xl Inter Bold) + tagline ("No Cap — does the code match the paper?") + arxiv URL + code paste fields. Staggered fade-in: logo (0ms), tagline (200ms), form (400ms), footer (600ms). Mounts `<DotBackground />` as the signature visual.
- **Acceptance**: visiting `localhost:3000/` shows the design-system-compliant landing with all elements animating in. Lighthouse 95+ across all categories.
- **Files touched**: `nocap-frontend/src/app/page.tsx`.
- **Hours**: 2.5
- **Reference**: `research.md [H6]` §3.

### T3.8 — Verify form (`app/verify-impl/page.tsx`)

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/app/verify-impl/page.tsx`. Aceternity `PlaceholdersAndVanishInput` for arxiv URL (cycling placeholders: "1412.6980", "1706.03762 (Transformer)", etc.) + textarea for code OR "fetch from PR URL" toggle. On submit, POSTs to gateway `/verify-impl`, redirects to `/trace/:id`.
- **Acceptance**: submit form with `1412.6980` + a code paste → URL changes to `/trace/<uuid>`.
- **Files touched**: `nocap-frontend/src/app/verify-impl/page.tsx`.
- **Hours**: 1.5
- **Reference**: `research.md [H6]` §5 + Aceternity input docs.

### T3.9 — `useTraceStream` hook (`lib/ws.ts`)

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/lib/ws.ts` with `useTraceStream(traceId)` hook using `react-use-websocket`. Connects to `wss://nocap.wiki/stream/:traceId`. Reducer handles event types `spec_done | plan_done | code_done | polygraph_done`. Reconnect with exponential backoff.
- **Acceptance**: `const s = useTraceStream(id)` returns reactive state that updates as council events arrive.
- **Files touched**: `nocap-frontend/src/lib/ws.ts`.
- **Hours**: 1
- **Reference**: `research.md [H6]` §9.

### T3.10 — Trace page (`app/trace/[id]/page.tsx`)

- [ ] **@devin**
- **Deliverable**: `nocap-frontend/src/app/trace/[id]/page.tsx`. Subscribes to `useTraceStream(id)`. Renders 4 council cards in a grid; each card animates in (FadeIn) when its `*_done` event arrives. Below: `<SideBySideViewer>` with paper math (KaTeX) ↔ code (CodeBlock). On `polygraph_done`, opens `<VerdictModal>`.
- **Acceptance**: opening `/trace/<id>` for a verification-in-progress shows live council animation; mismatched lines are bold; on completion, modal opens.
- **Files touched**: `nocap-frontend/src/app/trace/[id]/page.tsx`.
- **Hours**: 4
- **Reference**: `research.md [H6]` §10.

---

## Task block D — UI components (parallelizable with C, 3 tasks)

> **Parallelism**: T3.11, T3.12, T3.13 are independent of each other and of T3.7–T3.10.

### T3.11 — `CouncilCard.tsx`

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/components/trace/CouncilCard.tsx`. Renders a single stage card with title + model used + latency + content. Skeleton state when `model` is undefined.
- **Acceptance**: 4 instances side-by-side with various state (waiting/running/done) render correctly per Design System.
- **Files touched**: `nocap-frontend/src/components/trace/CouncilCard.tsx`.
- **Hours**: 1
- **Reference**: `research.md [H6]` §10.

### T3.12 — `SideBySideViewer.tsx`

- [ ] **@devin**
- **Deliverable**: `nocap-frontend/src/components/trace/SideBySideViewer.tsx`. Split-pane layout: left = KaTeX paper equations, right = `<CodeBlock>`. Mismatched equations rendered with `font-bold`. Click on a code line → scroll to its corresponding equation.
- **Acceptance**: render with 5 equations + code with line flags `[23,24]` → equations corresponding to those lines render bold; clicking line 23 in code scrolls equation pane.
- **Files touched**: `nocap-frontend/src/components/trace/SideBySideViewer.tsx`.
- **Hours**: 2.5
- **Reference**: `research.md [H6]` §8.

### T3.13 — `VerdictModal.tsx`

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/components/trace/VerdictModal.tsx`. Modal with `motion` AnimatePresence. Confidence band as **typographic weight** (Bold for >0.8, Medium for 0.5-0.8, Regular below) — never color (per Design System §"What NOT to do"). Per-equation pass/fail list.
- **Acceptance**: passing a verdict object renders the modal with correct weight.
- **Files touched**: `nocap-frontend/src/components/trace/VerdictModal.tsx`.
- **Hours**: 1.5
- **Reference**: `research.md [H6]` §11.

---

## Task block E — Secondary pages (sequential, 1 task)

### T3.14 — `/results` page

- [ ] **@claude**
- **Deliverable**: `nocap-frontend/src/app/results/page.tsx`. Server component fetching `GET /api/results` (proxies to gateway `GET /traces?limit=20`). Renders a typographic table of past verifications: trace_id · paper_arxiv_id · verdict · confidence · timestamp. Each row links to `/trace/:id`.
- **Acceptance**: visiting `/results` shows last 20 verifications.
- **Files touched**: `nocap-frontend/src/app/results/page.tsx`, `nocap-frontend/src/app/api/results/route.ts`.
- **Hours**: 1
- **Reference**: `research.md [H7]` Part A schema + `[H6]` §13.

---

## Task block F — Deploy (sequential, 2 tasks)

### T3.15 — Vercel deploy + DNS wiring

- [ ] **@claude**
- **Deliverable**: `npx vercel link` then `npx vercel --prod`. In Vercel Project → Domains, add `nocap.wiki` and `www.nocap.wiki`. GoDaddy DNS: `A @ 76.76.21.21` + `CNAME www cname.vercel-dns.com.`.
- **Acceptance**: `nocap.wiki` resolves and serves the landing page over HTTPS within 15 minutes.
- **Files touched**: `nocap-frontend/vercel.json` (if needed).
- **Hours**: 0.5
- **Reference**: `research.md [H6]` §12.
- **Critical**: WebSockets cannot terminate on Vercel. Frontend connects directly to `wss://nocap.wiki/stream/:id`, which the cloudflared tunnel routes to the laptop-hosted gateway. (If T3.X "migrate to DO App Platform" lands first, swap `nocap.wiki` for `api.nocap.wiki` and add the ALIAS domain to the DO spec.)

### T3.16 — Polish pass

- [ ] **@devin** (with Claude touch-up)
- **Deliverable**: end-to-end design pass. Lighthouse 95+ all categories. No layout shift. Font preloading. OG image (`public/og.png`) for social sharing. Smooth animations on every page.
- **Acceptance**: Lighthouse mobile run on `nocap.wiki` shows 95+ Performance, 100 Accessibility, 100 Best Practices, 100 SEO. Vercel deploy preview link sent to user for visual review.
- **Files touched**: any page or component that fails the audit.
- **Hours**: 3

---

## Task block G — Demo capture (sequential, USER-driven)

### T3.17 — Live frontend demo recording

- [ ] **@user**
- **Deliverable**: 60-second screen recording of the landing → verify form → live trace animation → verdict modal. Saved to `docs/screenshots/phase3-frontend-demo.mp4`.
- **Acceptance**: recording exists and shows the polished UI with smooth animations.
- **Hours**: 0.5

### T3.18 — Final integration smoke

- [ ] **@user**
- **Deliverable**: end-to-end run from a phone:
  1. Open `nocap.wiki` on phone.
  2. Paste arxiv ID + code.
  3. Watch trace page animate.
  4. See verdict modal.
- **Acceptance**: all 4 steps work without intervention.
- **Hours**: 0.25

### T3.19 — Phase 3 retrospective + Devpost prep

- [ ] **@user**
- **Deliverable**: 3-bullet summary in `docs/PRIVATE-phase3-retro.md`. Devpost draft started using `../30 - Product/Pitch Deck.md` and the `Meta Patterns.md` template.
- **Hours**: 0.5

### T3.20 — (OPTIONAL) Migrate hosting to DigitalOcean App Platform

- [ ] **@claude**
- **Deliverable**: `do/app.yaml` with `nocap-gateway` (web, port 8080) + `nocap-council` (worker) + Mongo external + domain `nocap.wiki`. All env vars + secrets configured. Replaces the cloudflared-from-laptop hosting (Phase 2 T2.2) for production-grade uptime.
- **Acceptance**: `doctl apps create --spec do/app.yaml` succeeds, `nocap.wiki/health` returns "ok" within 10 minutes from a clean DNS lookup. Cloudflared tunnel can be torn down after.
- **Files touched**: `do/app.yaml`, `nocap-council/Dockerfile`, Cloudflare DNS (CNAME swap from tunnel → DO).
- **Hours**: 2-3
- **When to do this**: only if the hackathon judging is over and you're keeping nocap.wiki running for the Harvard pilot. Not needed for the demo itself (cloudflared is sufficient).
- **Reference**: `research.md [H5]` Part A §3 (full DO App Platform spec).

### T3.21 — Landing page MVP (localhost only)

- [x] **@devin** — 2026-04-25 20:36 (deployed to Vercel via user)
- **Deliverable**: `nocap-frontend/` localhost-perfect single-page landing site for the hackathon judging demo. Includes sticky nav, hero wordmark with cap emoji on the `p`, cursor-reactive dot canvas with mobile static fallback, "What it does" copy + Slack mockup, monochrome sponsors/tracks row, and footer links. Uses Next.js 15 App Router, Tailwind v4, shadcn/ui, `motion`, React 19, and Inter via `next/font/google`.
- **Acceptance**:
  1. `cd nocap-frontend && npm run dev` serves at `localhost:3000` with all 5 sections rendering, dot canvas animating on desktop, and hero wordmark cap emoji correctly positioned over the `p`.
  2. `cd nocap-frontend && npm run build && npm run start` succeeds.
  3. Lighthouse mobile run on local returns Performance ≥ 90, Accessibility 100, Best Practices 100, SEO 100.
  4. Visual screenshots of each section at iPhone 14 viewport are pasted in the PR body.
- **Files touched**: `nocap-frontend/**`, `phases/phase-3.md`.
- **Hours**: 4
- **Reference**: User-provided inline Design System + Devpost "What it does" brief in Devin session.
- **Non-goals**: no Vercel deploy, no DNS work, no Slack gateway/live trace viewer/verdict modal.

---

## Task block H — Dashboard MVP (parallelizable, 11 tasks)

*Active scope: a public dashboard at `nocap.wiki/dashboard` where any visitor can browse all No Cap verifications as cards. Click a card → trace detail page at `nocap.wiki/trace/<trace_id>` with the paper PDF, code, residual, critic, and VIGIL audit. Slack verdict messages get a "View Issue" button linking to the relevant trace page.*

**Architecture decisions (locked):**

1. **Storage**: every verdict already lands in MongoDB Atlas via `mongo_log.log_verdict` (T2.4). For the dashboard, we extend the trace document to also include the original `code_str` so the side-by-side viewer can render it. Paper PDF is fetched live from `arxiv.org/pdf/<arxiv_id>.pdf` via a gateway proxy (no PDF storage needed).
2. **No auth, public read** — hackathon scope. Anyone can browse all traces. Post-hackathon: per-workspace filter via Slack OAuth.
3. **Data flow**: Vercel-hosted frontend → fetch from `api.nocap.wiki/api/traces` → cloudflared tunnel → laptop gateway → Mongo.
4. **Routing**: `nocap.wiki` (landing — done), `nocap.wiki/dashboard` (browse), `nocap.wiki/trace/[id]` (detail). API at `api.nocap.wiki/api/*`.
5. **Branding**: drop the `~` (tilde) logo from the original Design System entirely. Use the Apple iOS cap emoji 🧢 in the wordmark "NoCap" (cap on the `p`) consistently across nav, favicon, hero, and footer.
6. **Styling**: same Design System as landing — warm off-white #FAFAFA, near-black #1a1a1a, NO accent colors, Inter Bold, restraint over decoration. The ONE allowed dark surface is the Slack mockup style (preserved for the residual block in trace detail).
7. **Tech stack**: Next.js 15 App Router (already), Tailwind v4 (already), shadcn/ui (already), TanStack Query for fetching, react-pdf for paper PDF, react-syntax-highlighter for code, KaTeX for math, recharts for the timing chart, framer-motion (`motion`) for animations.

**Owner split:**
- **Devin** = harder/structural (Rust API endpoints, complex viewer component, replay endpoint)
- **Claude** (parallel session) = page-level wiring (dashboard page, card component, detail page, API client, branding cleanup, Slack button update)

> **Parallelism**: T3.23 (gateway endpoints) blocks T3.31 (API client). Otherwise tasks are largely independent — UI work can stub the API while Devin builds it.

### T3.22 — User: deploy landing + DNS + cap-emoji favicon

- [ ] **@user**
- **Deliverable**: 
  1. nocap.wiki points at the Vercel deployment of `nocap-frontend/` (CNAME at apex per the Phase 2 T2.2 split — `nocap.wiki` → Vercel, `api.nocap.wiki` → cloudflared)
  2. Update Slack manifest Request URLs to `https://api.nocap.wiki/slack-event` (per Phase 2 plan)
  3. Generate a 32×32 favicon containing the cap emoji 🧢 on warm-off-white background, save to `nocap-frontend/public/favicon.ico`
- **Acceptance**: `https://nocap.wiki` shows landing; `https://api.nocap.wiki/health` returns "ok"; favicon is the cap emoji.
- **Hours**: 0.5

### T3.23 — Gateway trace API endpoints

- [x] **@devin**
- **Deliverable**: `nocap-gateway/src/routes/traces.rs` with three endpoints:
  - `GET /api/traces?limit=N&offset=N` — paginated list of trace summaries (trace_id, arxiv_id, function_name, verdict, confidence, paper_section, created_at). Default limit=50, max=200. Sorted by created_at desc.
  - `GET /api/traces/:trace_id` — full trace document from Mongo by trace_id.
  - `GET /api/papers/:arxiv_id/pdf` — proxy fetch of `https://arxiv.org/pdf/<arxiv_id>.pdf` (avoids CORS issues with react-pdf reading directly from arxiv).
  - All endpoints set permissive CORS headers (`Access-Control-Allow-Origin: *`) so the Vercel frontend can call them. Add a tower middleware layer for CORS.
- **Acceptance**: 
  - `curl https://api.nocap.wiki/api/traces?limit=5` returns JSON array with 5 most recent trace summaries
  - `curl https://api.nocap.wiki/api/traces/<known-trace-id>` returns the full trace document
  - `curl https://api.nocap.wiki/api/papers/1412.6980/pdf > out.pdf && file out.pdf` confirms it's a valid PDF
- **Files touched**: `nocap-gateway/src/routes/traces.rs`, `nocap-gateway/src/routes/mod.rs`, `nocap-gateway/src/main.rs` (route mounts + CORS middleware), `nocap-gateway/Cargo.toml` (add `tower-http` with `cors` feature).
- **Hours**: 2
- **Dependencies**: existing mongodb crate from T2.10, `tower-http` for CORS.

### T3.24 — Persist `code_str` in trace docs

- [x] **@devin**
- **Deliverable**: update `mongo_log.log_verdict` and `orchestrator.verify` so the persisted trace document includes `code_str` (the raw Python source the gateway received). Currently the orchestrator's `verify()` doesn't carry `code_str` through to the augmented dict; needs a small refactor to plumb it through.
- **Acceptance**: query a trace doc post-Slack-run via mongosh, confirm `code_str` field is present and non-empty (the original Python source the user pasted).
- **Files touched**: `nocap-council/nocap_council/orchestrator.py` (add `code_str` to augmented dict), `nocap-council/nocap_council/mongo_log.py` (no change if it stores the dict verbatim).
- **Hours**: 0.5

### T3.25 — `PaperCodeViewer.tsx` component

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/components/trace/PaperCodeViewer.tsx`. Side-by-side layout (50/50 desktop, stacked mobile):
  - Left pane: react-pdf renders the paper PDF (fetched from `api.nocap.wiki/api/papers/<arxiv_id>/pdf`). User can scroll, zoom basic. Highlight the equation that caused the anomaly (best-effort: scroll to the section name from `claim.paper_section`).
  - Right pane: react-syntax-highlighter renders `code_str` with Python syntax highlighting. Highlight the line that contains the buggy assignment (use the `code_line` from the verdict if available; otherwise the line containing the target_var name).
  - Header strip across both panes: arxiv link + paper section + function name.
- **Acceptance**: passing a trace doc to the component renders both panes; clicking a paper page works; the buggy line in code is visually highlighted in the right pane.
- **Files touched**: `nocap-frontend/src/components/trace/PaperCodeViewer.tsx`, plus `package.json` deps (react-pdf, react-syntax-highlighter).
- **Hours**: 3
- **Reference**: react-pdf docs for PDF rendering setup (worker file, etc.)

### T3.26 — `TimingChart.tsx` component

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/components/trace/TimingChart.tsx`. Horizontal bar chart of per-stage timings using `recharts`. Each bar is a stage (paper_extract / spec / plan / code_extract / code[*] / polygraph), labeled with stage name + ms. Total wall clock at the bottom. Grayscale only (no color); use weight + size for hierarchy per Design System.
- **Acceptance**: passing a trace doc with `evidences[].method_used` + per-stage ms field renders the chart correctly. All 7-9 stages visible. No color accents.
- **Files touched**: `nocap-frontend/src/components/trace/TimingChart.tsx`, `package.json` (recharts).
- **Hours**: 1.5

### T3.27 — Replay endpoint

- [x] **@devin**
- **Deliverable**: `nocap-gateway/src/routes/replay.rs` with `POST /api/traces/:trace_id/replay`. Reads the trace doc from Mongo, extracts `arxiv_id` + `code_str` + `function_name` + `claim`, calls the existing `/api/verify-impl` endpoint internally (or directly spawns the council subprocess), returns the new `trace_id`.
- **Acceptance**: `curl -X POST https://api.nocap.wiki/api/traces/<known-trace-id>/replay` returns `{"trace_id": "<new-uuid>"}` and a fresh trace doc lands in Mongo within 30s.
- **Files touched**: `nocap-gateway/src/routes/replay.rs`, route mount in `main.rs`.
- **Hours**: 1

### T3.28 — Dashboard page

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/app/dashboard/page.tsx`. Full page:
  - Header: nav (cap-emoji wordmark + "Dashboard" / "GitHub" / "Devpost"), section title "All verifications"
  - Stats row: 4 cards — Total checks, Anomalies caught, Pass rate, Avg wall clock — pulled from the trace list
  - Filter bar: verdict dropdown (all/pass/anomaly/inconclusive), paper search (filter by arxiv_id), date range (last 24h / 7d / all)
  - Card grid: responsive 3-column desktop / 1-column mobile, each card is `<TraceCard />`
  - Empty state: "No verifications yet — try `/nocap verify-impl` in Slack"
- **Acceptance**: visiting `/dashboard` on the Vercel deploy renders all sections. Filter bar updates the card grid live (TanStack Query refetch on filter change). Stats reflect filtered subset.
- **Files touched**: `nocap-frontend/src/app/dashboard/page.tsx`, plus optional `nocap-frontend/src/components/dashboard/StatsRow.tsx` and `FilterBar.tsx`.
- **Hours**: 1.5

### T3.29 — `TraceCard.tsx` component

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/components/dashboard/TraceCard.tsx`. Single card UI:
  - Top: verdict icon (🟢 / 🔴 / 🟡) + verdict text in Inter Bold, confidence on the right (Bold for >0.8 per Design System)
  - Middle: paper title (or arxiv ID + paper_section), function name in mono
  - Bottom: timestamp (relative — "5 min ago"), action button "View issue →" linking to `/trace/<trace_id>`
  - Hover: subtle elevation via `--secondary` background, no color shift
  - Click: navigates to detail page
- **Acceptance**: passing a trace summary to the component renders the card. Click navigates correctly. Hover shows subtle elevation.
- **Files touched**: `nocap-frontend/src/components/dashboard/TraceCard.tsx`.
- **Hours**: 1

### T3.30 — Trace detail page

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/app/trace/[id]/page.tsx`. Composes:
  - Header: verdict icon + headline ("Anomaly detected" / "Implementation matches paper" / "Inconclusive") + confidence
  - Inline summary: arxiv link + paper section + function name + trace_id (with copy button) + replay button
  - `<PaperCodeViewer />` (Devin's T3.25) — side-by-side
  - Anomaly residual block (only if verdict=anomaly): KaTeX-rendered residual + Critic feedback in italic
  - VIGIL audit panel: 3 role bullets with check/cross icons
  - `<TimingChart />` (Devin's T3.26)
  - Collapsible JSONL events log at the bottom
- **Acceptance**: visiting `/trace/<known-trace-id>` renders the full page. Replay button POSTs to `/api/traces/:id/replay` and navigates to the new trace_id on success.
- **Files touched**: `nocap-frontend/src/app/trace/[id]/page.tsx`, `nocap-frontend/src/components/trace/AnomalyPanel.tsx`, `nocap-frontend/src/components/trace/VigilAuditPanel.tsx`.
- **Hours**: 1.5

### T3.31 — API client (TanStack Query)

- [x] **@devin**
- **Deliverable**: `nocap-frontend/src/lib/api.ts` with TanStack Query hooks:
  - `useTraces(filters)` → `GET /api/traces` with server-side pagination
  - `useTrace(traceId)` → `GET /api/traces/:trace_id` with cache key
  - `useReplay()` → mutation that POSTs `/api/traces/:trace_id/replay`
  - `getPdfUrl(arxivId)` → returns the proxied PDF URL string for react-pdf
  - All point at `process.env.NEXT_PUBLIC_API_URL` (default `https://api.nocap.wiki`)
- **Acceptance**: dashboard page (T3.28) and trace detail page (T3.30) use these hooks and render real data when the gateway is up.
- **Files touched**: `nocap-frontend/src/lib/api.ts`, `nocap-frontend/src/app/layout.tsx` (QueryClient provider), `package.json` (`@tanstack/react-query`).
- **Hours**: 0.5

### T3.32 — Branding cleanup: drop `~`, lock cap-emoji wordmark

- [x] **@devin**
- **Deliverable**: 
  1. Find and delete every reference to the `~` (tilde) logo across `nocap-frontend/` — nav bar, favicon SVG, hero centerpiece, etc. Replace with the cap-emoji wordmark "NoCap🧢" (cap overlapping the `p`) consistently.
  2. Update `../../30 - Product/Design System.md` "Logo" section: replace `~` rules with cap-emoji wordmark rules. Document size/weight/color tokens for nav/hero/favicon.
  3. Update favicon SVG to render the cap emoji instead of the tilde character.
- **Acceptance**: grep `nocap-frontend/` for `'~'` returns no logo references; landing + dashboard + trace pages all use the cap-emoji wordmark; favicon shows the cap.
- **Files touched**: `nocap-frontend/src/components/Logo.tsx` (or wherever the wordmark lives), `nocap-frontend/public/favicon.ico` + `favicon.svg`, `30 - Product/Design System.md`.
- **Hours**: 0.5

### T3.33 — Slack "View Issue" button → trace detail page

- [x] **@devin**
- **Deliverable**: update `nocap-gateway/src/routes/slack.rs` Block Kit verdict rendering:
  - Rename the "Replay trace" button to "View Issue"
  - Set its `url` field to `https://nocap.wiki/trace/<trace_id>` (Slack opens external URLs natively when `url` is set on a button — no `action_id` dispatch needed)
  - Remove the old `view_trace` action handler in interactivity (now obsolete since the button is a direct link)
  - Keep "Approve anyway" button as-is
- **Acceptance**: a fresh `/nocap verify-impl` Slack run returns a verdict with a "View Issue" button; clicking it opens `nocap.wiki/trace/<trace_id>` in the browser, which renders the detail page.
- **Files touched**: `nocap-gateway/src/routes/slack.rs`.
- **Hours**: 0.3

### T3.34 — Final integration smoke

- [ ] **@user**
- **Deliverable**: end-to-end flow from a phone or laptop:
  1. Open `nocap.wiki` → landing renders
  2. Click "Try /nocap in our Slack" → joins workspace
  3. Run `/nocap verify-impl 1412.6980 https://github.com/.../adam_buggy.py` in Slack
  4. See verdict appear within 30s with "View Issue" button
  5. Click "View Issue" → `nocap.wiki/trace/<trace_id>` loads with side-by-side paper PDF + code + residual
  6. Open `nocap.wiki/dashboard` in another tab → see the new trace card
- **Acceptance**: all 6 steps work without intervention. Screen recording saved to `docs/screenshots/phase3-dashboard-demo.mp4`.
- **Hours**: 0.5

---

## Phase 3 — done when

- [x] T3.0–T3.19 all checked
- [ ] T3.21 (landing) ✅, T3.22 (deploy + DNS), T3.23–T3.33 (dashboard MVP) all checked
- [ ] T3.34 (final integration smoke) recording exists
- All sponsor tracks have at least one screenshot in `docs/screenshots/`

---

## ORIGINAL Phase 3 — done when (preserved for context, mostly superseded)

- [x] T3.0–T3.19 all checked
- `nocap.wiki` Lighthouse 95+ all categories
- 60-second frontend demo recording exists
- User signs off in T3.19
- All sponsor tracks have at least one screenshot in `docs/screenshots/`

---

## Sponsor signals captured this phase

- **Arista Networks**: polished web app at `nocap.wiki` (proof: live URL).
- **MLH × Gemma 4** (refresh): mention in About page or footer.
- **MLH × GoDaddy**: `nocap.wiki` (proof: any URL bar screenshot).

---

## Hours estimate

| Block | Hours | Notes |
|---|---|---|
| T3.0 (verify phase 2) | 0.1 | user, blocking |
| Block A (scaffold) | 1.5 | sequential |
| Block B (3 parallel primitives) | 4.5 if serial, **~2.5 if 2-way parallel** | |
| Block C (4 pages, sequential after A+B) | 9 | mostly Devin |
| Block D (3 components, parallel with C) | 5 if serial, **~2.5 if parallel** | |
| Block E (results page) | 1 | sequential |
| Block F (deploy + polish) | 3.5 | sequential |
| Block G (demo + retro) | 1.25 | mostly user |
| **Total** | **~25h serial / ~13h parallel** | aim parallel |

---

## Final submission checklist (after Phase 3)

The user runs through this once Phase 3 is complete:

- [ ] Devpost project page filled per `../30 - Product/Pitch Deck.md` + `Meta Patterns.md` 8-section template
- [ ] GitHub repo public
- [ ] `agents.md` exists in repo (per Cognition's process-eval criterion)
- [ ] `README.md` opens with the workshop validation quote
- [ ] Demo video < 2 min embedded
- [ ] Live URL `nocap.wiki` resolving + Lighthouse 95+
- [ ] MCP install command works for any judge with Cursor / Claude Code / Windsurf
- [ ] Slack workspace invite in writeup
- [ ] Dogfood screenshot in writeup
- [ ] Headline benchmark chart on slide + in README
- [ ] Limitations slide — 3 specific failure modes with measurements
- [ ] "Built With" lists every sponsor by name
- [ ] Cognition-language pitch: *"polygraph"*, *"single-writer three-judge"*, *"Verified not Lite"*

---

← Back to [`phase-2.md`](phase-2.md)
