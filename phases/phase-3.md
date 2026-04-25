# Phase 3 — Frontend polish

*Active after Phase 2 ships. Goal: `nocap.wiki` live with landing + verify form + live WebSocket trace viewer + verdict modal. Notion/Vercel-grade polish per Design System.*

---

## Goal

End-to-end visual story:

1. Visitor lands at `nocap.wiki` — large `~` logo, tagline "does the code match the paper?", interactive cursor-reactive dot canvas, paper URL + code paste form.
2. Submit → redirect to `/trace/:id` — live WebSocket dashboard with 4 council cards (Spec / Plan / Code / Polygraph) animating in as the council progresses.
3. Side-by-side viewer: KaTeX-rendered paper math (left) ↔ syntax-highlighted code (right). Mismatched equations rendered in **bold weight** (no color — per Design System).
4. Final verdict modal: confidence band (Bold / Medium / Regular weight), per-equation pass/fail, voice playback button (ElevenLabs).
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
- **Deliverable**: `nocap-frontend/src/components/trace/VerdictModal.tsx`. Modal with `motion` AnimatePresence. Confidence band as **typographic weight** (Bold for >0.8, Medium for 0.5-0.8, Regular below) — never color (per Design System §"What NOT to do"). Per-equation pass/fail list. Voice playback button → POSTs to `/voice/:trace_id`, plays returned MP3 inline.
- **Acceptance**: passing a verdict object renders the modal with correct weight; voice button plays MP3.
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
- **Critical**: WebSockets cannot terminate on Vercel. Frontend connects directly to `wss://api.nocap.wiki/stream/:id` (the DO backend). Add `api.nocap.wiki` as an ALIAS domain on the DO App Platform spec, configure cert.

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
- **Deliverable**: 60-second screen recording of the landing → verify form → live trace animation → verdict modal → voice playback. Saved to `docs/screenshots/phase3-frontend-demo.mp4`.
- **Acceptance**: recording exists and shows the polished UI with smooth animations.
- **Hours**: 0.5

### T3.18 — Final integration smoke

- [ ] **@user**
- **Deliverable**: end-to-end run from a phone:
  1. Open `nocap.wiki` on phone.
  2. Paste arxiv ID + code.
  3. Watch trace page animate.
  4. See verdict modal.
  5. Tap Play Voice; hear voice in phone speaker.
- **Acceptance**: all 5 steps work without intervention.
- **Hours**: 0.25

### T3.19 — Phase 3 retrospective + Devpost prep

- [ ] **@user**
- **Deliverable**: 3-bullet summary in `docs/PRIVATE-phase3-retro.md`. Devpost draft started using `../30 - Product/Pitch Deck.md` and the `Meta Patterns.md` template.
- **Hours**: 0.5

---

## Phase 3 — done when

- [x] T3.0–T3.19 all checked
- `nocap.wiki` Lighthouse 95+ all categories
- 60-second frontend demo recording exists
- User signs off in T3.19
- All sponsor tracks have at least one screenshot in `docs/screenshots/`

---

## Sponsor signals captured this phase

- **Arista Networks**: polished web app at `nocap.wiki` (proof: live URL).
- **MLH × ElevenLabs**: voice button works in dashboard verdict modal (proof: phase3-frontend-demo.mp4).
- **MLH × Gemma 4** (refresh): mention in About page or footer.
- **MLH × DigitalOcean** (refresh): WebSocket connects to `api.nocap.wiki` on DO.
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
