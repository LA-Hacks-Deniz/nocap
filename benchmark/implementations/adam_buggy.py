# Owner: DEVIN — Phase 1 task T1.15
"""Buggy Adam optimizer — intentional bias-correction omission.

Used as a negative control for the No Cap polygraph: ``nocap verify-impl
1412.6980 adam_buggy.py`` should return ``Anomaly`` because ``m_hat`` and
``v_hat`` in :meth:`Adam.step` are NOT divided by ``(1 - beta**t)`` as
required by Kingma & Ba 2014, Algorithm 1, eq. (3).
"""
from __future__ import annotations

import numpy as np


class Adam:
    """Adam optimizer with bias correction omitted (intentional bug)."""

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
        """Apply one Adam update step (without bias correction).

        Args:
            g: gradient of the objective at the current parameters.
            t: 1-indexed timestep. Accepted for signature parity with
                :class:`adam_clean.Adam`; intentionally unused here.

        Returns:
            The updated parameter vector ``theta``.
        """
        g = np.asarray(g, dtype=np.float64)
        self.m = self.beta1 * self.m + (1.0 - self.beta1) * g
        self.v = self.beta2 * self.v + (1.0 - self.beta2) * (g * g)
        m_hat = self.m
        v_hat = self.v
        self.theta = self.theta - self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
        return self.theta
