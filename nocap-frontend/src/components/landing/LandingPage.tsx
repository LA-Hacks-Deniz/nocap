"use client";

// Owner: DEVIN — Phase 3 task T3.21
import Link from "next/link";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import { DotBackground } from "@/components/canvas/DotBackground";
import { Button } from "@/components/ui/button";

const NAV_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
];

const FOOTER_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
];

const SPONSORS = [
  "Cognition",
  "MLH × Gemma",
  "MLH × MongoDB Atlas",
  "MLH × GoDaddy",
  "Figma Flicker to Flow",
  "Cloudflare",
];

const BULLETS = [
  "Catches what humans take hours to find: missing math terms, faulty algorithm implementations, dropped normalization constants",
  "Four checks running in parallel: does the math symbolically match? Does it match when you plug in real numbers? Does the algorithm have the right number of steps? Are the hyperparameters the same as the paper's defaults?",
  "Accessible from inside the Slack with a single command, so the engineers will not need to adapt to a new dashboard.",
];

function FadeIn({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className={className}
      initial={{ opacity: 0, y: 20 }}
      transition={{ delay, duration: 0.5, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

function Wordmark() {
  return (
    <span className="inline-flex items-end justify-center tracking-[-0.065em]">
      <span>NoCap.wiki</span>
    </span>
  );
}

export function LandingPage() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="relative min-h-dvh overflow-x-hidden bg-background text-foreground">
      <DotBackground />

      <header
        className={[
          "sticky top-0 z-30 transition-all duration-300",
          scrolled
            ? "border-b border-border bg-background/92 backdrop-blur-md"
            : "bg-transparent",
        ].join(" ")}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 sm:px-8">
          <Link
            aria-label="NoCap home"
            className="select-none text-2xl leading-none"
            href="#top"
          >
            🧢
          </Link>
          <nav className="flex items-center gap-5 text-sm text-muted-foreground">
            {NAV_LINKS.map((link) => (
              <Link
                className="transition-colors hover:text-foreground"
                href={link.href}
                key={link.label}
                rel="noreferrer"
                target="_blank"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main className="relative z-10" id="top">
        <section className="flex min-h-[calc(100dvh-5.5rem)] items-center justify-center px-6 pb-20 pt-12 sm:px-8">
          <div className="mx-auto flex max-w-5xl flex-col items-center text-center">
            <FadeIn className="mb-8">
              <p className="select-none text-5xl font-bold sm:text-6xl lg:text-7xl">
                <Wordmark />
              </p>
            </FadeIn>
            <FadeIn className="max-w-2xl" delay={0.2}>
              <h1 className="text-balance text-2xl font-normal tracking-[-0.03em] text-muted-foreground sm:text-3xl">
                AI agent polygraph for research-grade code.
              </h1>
            </FadeIn>
            <FadeIn className="mt-10" delay={0.6}>
              <Button
                asChild
                className="h-11 rounded-full px-6 text-sm font-medium"
                size="lg"
              >
                <Link href="#what-it-does">See how it works ↓</Link>
              </Button>
            </FadeIn>
          </div>
        </section>

        <section className="px-6 py-24 sm:px-8 lg:py-32" id="what-it-does">
          <div className="mx-auto grid max-w-6xl gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:items-start">
            <div className="max-w-2xl">
              <FadeIn>
                <h2 className="text-3xl font-bold tracking-[-0.04em] sm:text-4xl">
                  What it does
                </h2>
              </FadeIn>
              <FadeIn delay={0.15}>
                <p className="mt-6 text-lg leading-relaxed text-muted-foreground">
                  After an agent writes the implementation for a paper, the
                  researchers will activate No Cap within their Slack. Give it
                  the paper (arXiv ID or a PDF) and the implementation of an
                  agent (Python file or PR diff). It will return a verdict: pass
                  or an anomaly, including confidence and per-equation evidence.
                </p>
              </FadeIn>
              <FadeIn delay={0.3}>
                <ul className="mt-8 space-y-5 text-left text-base leading-relaxed text-foreground/92">
                  {BULLETS.map((bullet) => (
                    <li className="flex gap-3" key={bullet}>
                      <span
                        aria-hidden="true"
                        className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"
                      />
                      <span>{bullet}</span>
                    </li>
                  ))}
                </ul>
              </FadeIn>
            </div>

            <FadeIn className="lg:sticky lg:top-28" delay={0.2}>
              <div className="overflow-hidden rounded-[2rem] border border-border bg-[#1a1a1a] text-left text-sm text-[#FAFAFA] shadow-[0_18px_60px_rgba(26,26,26,0.16)]">
                <div className="flex items-center justify-between border-b border-[#2a2a2a] px-5 py-4 sm:px-6">
                  <div>
                    <p className="text-sm font-bold"># nocap-verifications</p>
                    <p className="mt-1 text-xs text-[#9CA3AF]">
                      No Cap app · research implementation checks
                    </p>
                  </div>
                  <span className="rounded-full border border-[#3a3a3a] px-2 py-1 text-xs text-[#9CA3AF]">
                    Slack
                  </span>
                </div>
                <div className="space-y-5 p-5 sm:p-6">
                  <div className="flex gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#FAFAFA] text-lg">
                      🧢
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm">
                        <span className="font-bold">Deniz</span>
                        <span className="ml-2 text-xs text-[#9CA3AF]">
                          10:42 AM
                        </span>
                      </p>
                      <p className="mt-2 rounded-xl bg-[#242424] px-3 py-2 font-mono text-xs leading-6 text-[#FAFAFA]">
                        /nocap verify-impl 1412.6980
                        https://github.com/LA-Hacks-Deniz/nocap/blob/main/benchmark/implementations/adam_clean.py
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#3a3a3a] text-lg">
                      🧢
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm">
                        <span className="font-bold">No Cap</span>
                        <span className="ml-2 rounded bg-[#2f2f2f] px-1.5 py-0.5 text-[10px] uppercase tracking-[0.16em] text-[#D1D5DB]">
                          app
                        </span>
                      </p>
                      <div className="mt-3 rounded-2xl border border-[#3a3a3a] bg-[#202020] p-4">
                        <p className="text-[#D1D5DB]">
                          🔍 Verifying paper 1412.6980... (&lt;30s)
                        </p>
                        <p className="mt-4 font-bold text-[#FAFAFA]">
                          🟢 No Cap — Implementation matches paper
                        </p>
                        <dl className="mt-5 grid gap-x-8 gap-y-4 text-sm leading-6 text-[#D1D5DB] sm:grid-cols-2">
                          <div>
                            <dt className="font-bold text-[#FAFAFA]">
                              Confidence
                            </dt>
                            <dd className="mt-1 font-mono text-[#FAFAFA]">
                              0.95
                            </dd>
                          </div>
                          <div>
                            <dt className="font-bold text-[#FAFAFA]">
                              Paper
                            </dt>
                            <dd className="mt-1 font-mono text-[#FAFAFA]">
                              arxiv:1412.6980 §Algorithm 1
                            </dd>
                          </div>
                          <div>
                            <dt className="font-bold text-[#FAFAFA]">
                              Function
                            </dt>
                            <dd className="mt-1">
                              <code className="rounded border border-[#3a3a3a] bg-[#FAFAFA] px-1.5 py-0.5 font-mono text-[#1a1a1a]">
                                step
                              </code>
                            </dd>
                          </div>
                          <div>
                            <dt className="font-bold text-[#FAFAFA]">Trace</dt>
                            <dd className="mt-1">
                              <code className="rounded border border-[#3a3a3a] bg-[#FAFAFA] px-1.5 py-0.5 font-mono text-[#1a1a1a]">
                                16405808-09be-4a3f-9e78-327029d17556
                              </code>
                            </dd>
                          </div>
                        </dl>
                        <div className="mt-5 flex flex-wrap gap-2">
                          <button
                            className="rounded-lg border border-[#3a3a3a] bg-[#FAFAFA] px-3 py-2 text-xs font-bold text-[#1a1a1a]"
                            type="button"
                          >
                            Replay trace
                          </button>
                          <button
                            className="rounded-lg bg-[#FAFAFA] px-3 py-2 text-xs font-bold text-[#1a1a1a]"
                            type="button"
                          >
                            Approve anyway
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </FadeIn>
          </div>
        </section>

        <section className="border-y border-border/80 px-6 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <FadeIn>
              <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-4 text-center text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {SPONSORS.map((sponsor) => (
                  <span key={sponsor}>{sponsor}</span>
                ))}
              </div>
            </FadeIn>
          </div>
        </section>
      </main>

      <footer className="relative z-10 px-6 py-8 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 border-t border-border pt-6 text-sm text-muted-foreground sm:flex-row sm:items-start sm:justify-between">
          <p className="max-w-2xl leading-relaxed">
            Built at LA Hacks 2026 by Deniz Lapsekili. Validated by Cognition
            (Apr 24, Apr 25 workshops).
          </p>
          <div className="flex flex-wrap gap-4">
            {FOOTER_LINKS.map((link) => (
              <Link
                className="transition-colors hover:text-foreground"
                href={link.href}
                key={link.label}
                rel="noreferrer"
                target="_blank"
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}
