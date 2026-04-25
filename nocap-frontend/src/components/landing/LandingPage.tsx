"use client";

// Owner: DEVIN — Phase 3 task T3.21
import Link from "next/link";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

import { DotBackground } from "@/components/canvas/DotBackground";
import { Button } from "@/components/ui/button";

const NAV_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
  { href: "#", label: "Devpost" },
];

const FOOTER_LINKS = [
  { href: "https://github.com/LA-Hacks-Deniz/nocap", label: "GitHub" },
  { href: "#", label: "Devpost" },
  {
    href: "#",
    label: "Slack workspace",
  },
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
  "Accessible from inside Slack via a single command, so engineers don't context-switch to a dashboard",
];

const slackLines = [
  "@deniz /nocap verify-impl 1412.6980 ./adam.py",
  "",
  "🔴 No Cap — Anomaly detected (confidence 0.95)",
  "  Paper Algorithm 1, equation 3:",
  "      m̂_t = m_t / (1 - β₁ᵗ)",
  "  Code line 23:",
  "      m_hat = self.m",
  "  Residual: m·β₁ᵗ / (1 - β₁ᵗ)   (bias correction missing)",
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
    <span className="inline-flex items-end justify-center tracking-[-0.06em]">
      <span>NoCa</span>
      <span className="relative inline-block">
        <span>p</span>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -top-[0.72em] left-[0.05em] rotate-[-14deg] text-[0.62em]"
        >
          🧢
        </span>
      </span>
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
            className="select-none text-2xl font-bold tracking-[-0.08em]"
            href="#top"
          >
            ~
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
            <FadeIn className="mt-6 max-w-xl" delay={0.4}>
              <blockquote className="text-base italic leading-relaxed text-muted-foreground sm:text-lg">
                &quot;polygraphs what the LLM has produced.&quot;
              </blockquote>
              <p className="mt-3 text-sm text-muted-foreground">
                — founder pitch to Cognition, Apr 25 2026
              </p>
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
                  researcher activates No Cap from inside Slack. Give it the
                  paper (arXiv ID or PDF) and the agent&apos;s implementation
                  (Python file or PR diff). It returns a verdict — Pass or
                  Anomaly — with confidence and per-equation evidence.
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
              <FadeIn delay={0.45}>
                <div className="mt-10 space-y-5 text-lg leading-relaxed text-muted-foreground">
                  <p>
                    From our tests, out-of-the-box agents miss subtle math bugs
                    every time. Without No Cap, a faulty job runs on the cluster
                    for ~6 hours of cluster CPU time. The engineer then bisects
                    between code and paper, hour by hour, to find why the loss
                    diverged. Hundreds of cluster CPU hours wasted.
                  </p>
                  <p>
                    With No Cap, within ~20 seconds, the polygraph flags the
                    bias-correction omission with the exact residual
                    m·β₁ᵗ/(1-β₁ᵗ). The engineer reads the residual, fixes the
                    bug, ships the correct code. Zero cluster CPU hours wasted.
                  </p>
                </div>
              </FadeIn>
            </div>

            <FadeIn className="lg:sticky lg:top-28" delay={0.2}>
              <div className="rounded-[2rem] border border-border bg-[#1a1a1a] p-6 text-left text-sm text-[#FAFAFA] shadow-[0_18px_60px_rgba(26,26,26,0.16)] sm:p-8">
                <p className="mb-5 text-xs uppercase tracking-[0.28em] text-[#9CA3AF]">
                  Slack mockup
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-sm leading-7">
                  {slackLines.join("\n")}
                </pre>
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
