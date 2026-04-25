# Owner: DEVIN — Phase 1 task T1.15
"""Reference Adam optimizer (Kingma & Ba 2014, arXiv:1412.6980).

Faithful single-step implementation used as a positive control for the
No Cap polygraph: ``nocap verify-impl 1412.6980 adam_clean.py`` should
return ``Pass``. Algorithm 1 of the paper, including the bias correction
``m_hat = m / (1 - beta1**t)`` and ``v_hat = v / (1 - beta2**t)``.
"""
from __future__ import annotations

import numpy as np


class Adam:
    """Adam optimizer with the canonical bias-correction (paper Algorithm 1)."""

    def __init__(
        self,
        theta: np.ndarray,
        lr: float = 1e-3,
        beta1: float = 0.9,
        beta2: float = 0.999,
        eps: float = 1e-8,
    ) -> None:
        """Initialize the optimizer state.

        Args:
            theta: initial parameter vector.
            lr: step size (paper default 1e-3).
            beta1: 1st-moment decay (paper default 0.9).
            beta2: 2nd-moment decay (paper default 0.999).
            eps: numerical stabilizer in the denominator (paper default 1e-8).
        """
        self.theta = np.asarray(theta, dtype=np.float64).copy()
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.m = np.zeros_like(self.theta)
        self.v = np.zeros_like(self.theta)

    def step(self, g: np.ndarray, t: int) -> np.ndarray:
        """Apply one Adam update step.

        Args:
            g: gradient of the objective at the current parameters.
            t: 1-indexed timestep (matches the paper's convention).

        Returns:
            The updated parameter vector ``theta``.
        """
        g = np.asarray(g, dtype=np.float64)
        self.m = self.beta1 * self.m + (1.0 - self.beta1) * g
        self.v = self.beta2 * self.v + (1.0 - self.beta2) * (g * g)
        m_hat = self.m / (1.0 - self.beta1 ** t)
        v_hat = self.v / (1.0 - self.beta2 ** t)
        self.theta = self.theta - self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
        return self.theta
