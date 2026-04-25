# Owner: CLAUDE — Phase 1 task T1.12
"""Numerical equivalence fallback for SymPy expressions.

When `simplify(a - b)` returns nonzero, that does NOT mean the expressions differ
— `simplify` is heuristic. Substitute random numerical values for every free
symbol, evaluate both sides, compare with numpy.isclose. With independent draws
from a continuous distribution, the probability that two non-equivalent rational
expressions agree at all 5 points is effectively zero (Schwartz-Zippel).

Sample from [0.1, 2.0] — avoid 0, ±1 and integer powers of 2 because many wrong
expressions accidentally agree there. See research.md [H3] §5.
"""
from __future__ import annotations

import numpy as np
import sympy as sp


def numeric_equal(a: sp.Expr, b: sp.Expr, n_samples: int = 5, rtol: float = 1e-9) -> bool:
    """Return True iff a and b agree at n_samples random points in [0.1, 2.0].

    Args:
        a: first SymPy expression.
        b: second SymPy expression.
        n_samples: number of random sample points (default 5).
        rtol: relative tolerance passed to numpy.isclose (default 1e-9).

    Returns:
        True if both expressions evaluate to (numerically) equal floats at every
        sampled point. False on the first disagreement.
    """
    syms = sorted((a.free_symbols | b.free_symbols), key=lambda s: s.name)
    rng = np.random.default_rng(0)
    for _ in range(n_samples):
        sub = {s: float(rng.uniform(0.1, 2.0)) for s in syms}
        try:
            if not np.isclose(float(a.subs(sub)), float(b.subs(sub)), rtol=rtol):
                return False
        except (TypeError, ZeroDivisionError):
            continue
    return True


if __name__ == "__main__":
    # Symbolically different but mathematically equal: (x+1)**2 vs x**2 + 2*x + 1.
    x = sp.Symbol("x")
    a1 = (x + 1) ** 2
    b1 = x**2 + 2 * x + 1
    print(f"(x+1)**2 vs x**2+2x+1 -> {numeric_equal(a1, b1)}  (expect True)")

    # Buggy Adam: paper m_hat = m / (1 - beta1**t); buggy code m_hat = m.
    m, beta1, t = sp.symbols("m beta1 t")
    paper = m / (1 - beta1**t)
    buggy = m
    print(f"Adam paper vs buggy m_hat -> {numeric_equal(paper, buggy)}  (expect False)")
