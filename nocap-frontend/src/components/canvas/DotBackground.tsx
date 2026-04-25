"use client";

// Owner: DEVIN — Phase 3 task T3.21
import { useEffect, useRef, useState } from "react";

const DOT_SPACING = 28;
const BASE_RADIUS = 0.8;
const MAX_RADIUS = 2.5;
const CURSOR_RADIUS = 150;
const LERP_SPEED = 0.08;
const BASE_COLOR = [229, 231, 235] as const;
const ACTIVE_COLOR = [156, 163, 175] as const;

type Dot = {
  x: number;
  y: number;
  radius: number;
  targetRadius: number;
  alpha: number;
  targetAlpha: number;
};

function lerp(start: number, end: number, amount: number) {
  return start + (end - start) * amount;
}

function mixColor(progress: number) {
  return BASE_COLOR.map((channel, index) =>
    Math.round(channel + (ACTIVE_COLOR[index] - channel) * progress),
  );
}

export function DotBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mobileQuery = window.matchMedia("(max-width: 767px)");
    const reducedMotionQuery = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );

    const sync = () => {
      setIsMobile(mobileQuery.matches);
      setReducedMotion(reducedMotionQuery.matches);
    };

    sync();
    mobileQuery.addEventListener("change", sync);
    reducedMotionQuery.addEventListener("change", sync);

    return () => {
      mobileQuery.removeEventListener("change", sync);
      reducedMotionQuery.removeEventListener("change", sync);
    };
  }, []);

  useEffect(() => {
    if (isMobile) {
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }

    let animationFrame = 0;
    let opacity = 0;
    let dots: Dot[] = [];
    let width = 0;
    let height = 0;
    let dpr = 1;
    const pointer = { x: -10_000, y: -10_000, active: false };

    const initializeDots = () => {
      dots = [];

      for (let y = DOT_SPACING / 2; y < height; y += DOT_SPACING) {
        for (let x = DOT_SPACING / 2; x < width; x += DOT_SPACING) {
          dots.push({
            x,
            y,
            radius: BASE_RADIUS,
            targetRadius: BASE_RADIUS,
            alpha: 0.45,
            targetAlpha: 0.45,
          });
        }
      }
    };

    const resize = () => {
      dpr = window.devicePixelRatio || 1;
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      initializeDots();
    };

    const updateTargets = (time: number) => {
      for (const dot of dots) {
        if (pointer.active && !reducedMotion) {
          const dx = dot.x - pointer.x;
          const dy = dot.y - pointer.y;
          const distance = Math.hypot(dx, dy);

          if (distance <= CURSOR_RADIUS) {
            const t = 1 - distance / CURSOR_RADIUS;
            const eased = t * t;
            dot.targetRadius = BASE_RADIUS + (MAX_RADIUS - BASE_RADIUS) * eased;
            dot.targetAlpha = 0.45 + 0.45 * eased;
            continue;
          }
        }

        if (!reducedMotion) {
          const ambient =
            0.07 *
            (Math.sin(dot.x * 0.01 + time * 0.0012) +
              Math.cos(dot.y * 0.012 + time * 0.0009));

          dot.targetRadius = BASE_RADIUS + ambient;
          dot.targetAlpha = 0.4 + Math.max(ambient, 0) * 0.7;
        } else {
          dot.targetRadius = BASE_RADIUS;
          dot.targetAlpha = 0.45;
        }
      }
    };

    const draw = (time: number) => {
      updateTargets(time);
      opacity = reducedMotion ? 1 : Math.min(opacity + 0.03, 1);
      context.clearRect(0, 0, width, height);

      for (const dot of dots) {
        dot.radius = lerp(dot.radius, dot.targetRadius, LERP_SPEED);
        dot.alpha = lerp(dot.alpha, dot.targetAlpha, LERP_SPEED);
        const colorProgress = Math.min(
          Math.max((dot.radius - BASE_RADIUS) / (MAX_RADIUS - BASE_RADIUS), 0),
          1,
        );
        const [r, g, b] = mixColor(colorProgress);

        context.beginPath();
        context.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2);
        context.fillStyle = `rgba(${r}, ${g}, ${b}, ${dot.alpha * opacity})`;
        context.fill();
      }

      if (!reducedMotion || pointer.active) {
        animationFrame = window.requestAnimationFrame(draw);
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;

      if (reducedMotion && animationFrame === 0) {
        animationFrame = window.requestAnimationFrame(draw);
      }
    };

    const onPointerLeave = () => {
      pointer.active = false;
      pointer.x = -10_000;
      pointer.y = -10_000;
    };

    resize();
    animationFrame = window.requestAnimationFrame(draw);
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerleave", onPointerLeave);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
    };
  }, [isMobile, reducedMotion]);

  if (isMobile) {
    return (
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 opacity-60"
        style={{
          backgroundColor: "transparent",
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(229,231,235,0.9) 1px, transparent 0)",
          backgroundPosition: "center",
          backgroundSize: "28px 28px",
        }}
      />
    );
  }

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 opacity-100"
    />
  );
}
