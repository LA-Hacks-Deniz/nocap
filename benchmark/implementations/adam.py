from __future__ import annotations

import numpy as np


class Adam:
    def __init__(
        self,
        theta: np.ndarray,
        lr: float = 1e-3,
        beta1: float = 0.9,
        beta2: float = 0.999,
        eps: float = 1e-8,
    ) -> None:
        self.theta = np.asarray(theta, dtype=np.float64).copy()
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.m = np.zeros_like(self.theta)
        self.v = np.zeros_like(self.theta)

    def step(self, g: np.ndarray, t: int) -> np.ndarray:
        g = np.asarray(g, dtype=np.float64)
        self.m = self.beta1 * self.m + (1.0 - self.beta1) * g
        self.v = self.beta2 * self.v + (1.0 - self.beta2) * (g * g)
        m_hat = self.m
        v_hat = self.v
        self.theta = self.theta - self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
        return self.theta
