"""Scaled dot-product attention from Vaswani et al. 2017 (arXiv 1706.03762).

CLEAN variant — `scores` correctly scaled by `1/sqrt(d_k)` per equation 1
of §3.2.1:
    Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) V

Sibling fixture to attention_buggy.py (which omits the 1/sqrt(d_k) scaling).
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


def scaled_dot_product_attention(
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    mask: torch.Tensor | None = None,
) -> torch.Tensor:
    """Compute scaled dot-product attention per Vaswani et al. 2017 §3.2.1.

    Args:
        query: (B, n_heads, seq_len, d_k)
        key:   (B, n_heads, seq_len, d_k)
        value: (B, n_heads, seq_len, d_v)
        mask:  optional (seq_len, seq_len) bool tensor where False positions
               are masked out before softmax.

    Returns:
        attended: (B, n_heads, seq_len, d_v)
    """
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k)
    if mask is not None:
        scores = scores.masked_fill(mask == 0, float("-inf"))
    attention_weights = F.softmax(scores, dim=-1)
    return torch.matmul(attention_weights, value)


class MultiHeadAttention(nn.Module):
    """Multi-head wrapper; not the function under verification."""

    def __init__(self, d_model: int, n_heads: int):
        super().__init__()
        assert d_model % n_heads == 0
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        B, T, _ = x.shape
        q = self.W_q(x).reshape(B, T, self.n_heads, self.d_k).transpose(1, 2)
        k = self.W_k(x).reshape(B, T, self.n_heads, self.d_k).transpose(1, 2)
        v = self.W_v(x).reshape(B, T, self.n_heads, self.d_k).transpose(1, 2)
        out = scaled_dot_product_attention(q, k, v, mask)
        return self.W_o(out.transpose(1, 2).reshape(B, T, -1))
