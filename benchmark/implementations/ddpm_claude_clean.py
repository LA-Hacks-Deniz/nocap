"""DDPM (Ho, Jain, Abbeel 2020 — arXiv:2006.11239).

Variant of Claude-Code-generated DDPM implementation
(clean: as-shipped | buggy: planted bias-correction omission in q_sample's mean).
This file is the CLEAN variant — `q_sample` correctly uses `self.sqrt_bar_alphas`
in the mean per eq. (4).

Implements:
  * Forward process  q(x_t | x_0)              — eq. (4)
  * Reverse process  p_theta(x_{t-1} | x_t)    — eq. (1), (11)
  * Simplified loss  L_simple                  — eq. (14), §3.2
  * Sampling         Algorithm 2 (ancestral)
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Beta schedule + precomputed diffusion constants
# ---------------------------------------------------------------------------

def linear_beta_schedule(T: int, beta_start: float = 1e-4, beta_end: float = 0.02) -> torch.Tensor:
    """Linear schedule from §4 of the paper (T=1000, beta_1=1e-4, beta_T=0.02)."""
    return torch.linspace(beta_start, beta_end, T)


def _gather(a: torch.Tensor, t: torch.Tensor, x_shape) -> torch.Tensor:
    """Pick a[t] per-batch and broadcast to x_shape (B, 1, 1, ...)."""
    out = a.gather(0, t)
    return out.reshape(t.shape[0], *([1] * (len(x_shape) - 1)))


class GaussianDiffusion:
    """Holds the schedule and the closed-form q / p_theta math.

    Convention follows the paper:
        beta_t       : forward variance at step t
        alpha_t      : 1 - beta_t
        bar_alpha_t  : prod_{s<=t} alpha_s
    """

    def __init__(self, T: int = 1000, device: str | torch.device = "cpu"):
        self.T = T
        betas = linear_beta_schedule(T).to(device)
        alphas = 1.0 - betas
        bar_alphas = torch.cumprod(alphas, dim=0)
        bar_alphas_prev = F.pad(bar_alphas[:-1], (1, 0), value=1.0)  # bar_alpha_0 := 1

        self.betas = betas
        self.alphas = alphas
        self.bar_alphas = bar_alphas
        self.bar_alphas_prev = bar_alphas_prev

        # Forward: q(x_t | x_0) = N(sqrt(bar_alpha_t) x_0, (1 - bar_alpha_t) I)
        self.sqrt_bar_alphas = torch.sqrt(bar_alphas)
        self.sqrt_one_minus_bar_alphas = torch.sqrt(1.0 - bar_alphas)

        # Reverse: coefficients used to predict x_{t-1} from x_t and eps_theta — eq. (11)
        # mu_theta(x_t, t) = (1/sqrt(alpha_t)) (x_t - beta_t/sqrt(1-bar_alpha_t) * eps_theta)
        self.sqrt_recip_alphas = torch.sqrt(1.0 / alphas)
        self.eps_coef = betas / torch.sqrt(1.0 - bar_alphas)

        # Posterior variance  beta_tilde_t = (1 - bar_alpha_{t-1}) / (1 - bar_alpha_t) * beta_t — eq. (7)
        self.posterior_variance = betas * (1.0 - bar_alphas_prev) / (1.0 - bar_alphas)

    # ---- forward process ----------------------------------------------------

    def q_sample(self, x0: torch.Tensor, t: torch.Tensor, noise: torch.Tensor | None = None) -> torch.Tensor:
        """Sample x_t ~ q(x_t | x_0) using the reparameterization in eq. (4)."""
        if noise is None:
            noise = torch.randn_like(x0)
        sqrt_bar = _gather(self.sqrt_bar_alphas, t, x0.shape)
        sqrt_one_minus_bar = _gather(self.sqrt_one_minus_bar_alphas, t, x0.shape)
        return sqrt_bar * x0 + sqrt_one_minus_bar * noise

    # ---- training loss ------------------------------------------------------

    def loss_simple(self, model: nn.Module, x0: torch.Tensor) -> torch.Tensor:
        """L_simple from eq. (14): E_{t, x_0, eps} [ || eps - eps_theta(x_t, t) ||^2 ]."""
        B = x0.shape[0]
        t = torch.randint(0, self.T, (B,), device=x0.device, dtype=torch.long)
        noise = torch.randn_like(x0)
        x_t = self.q_sample(x0, t, noise)
        eps_pred = model(x_t, t)
        return F.mse_loss(eps_pred, noise)

    # ---- reverse process ----------------------------------------------------

    @torch.no_grad()
    def p_sample(self, model: nn.Module, x_t: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        """One reverse step: x_t -> x_{t-1} via Algorithm 2, line 4."""
        eps_pred = model(x_t, t)
        coef_eps = _gather(self.eps_coef, t, x_t.shape)
        coef_x = _gather(self.sqrt_recip_alphas, t, x_t.shape)
        mean = coef_x * (x_t - coef_eps * eps_pred)

        # No noise added at t=0 (Algorithm 2: z=0 when t=1, i.e. last reverse step).
        nonzero_mask = (t != 0).float().reshape(t.shape[0], *([1] * (len(x_t.shape) - 1)))
        var = _gather(self.posterior_variance, t, x_t.shape)
        noise = torch.randn_like(x_t)
        return mean + nonzero_mask * torch.sqrt(var) * noise

    @torch.no_grad()
    def sample(self, model: nn.Module, shape: tuple[int, ...], device: str | torch.device) -> torch.Tensor:
        """Algorithm 2: start at x_T ~ N(0, I), iterate p_sample down to x_0."""
        x = torch.randn(shape, device=device)
        for i in reversed(range(self.T)):
            t = torch.full((shape[0],), i, device=device, dtype=torch.long)
            x = self.p_sample(model, x, t)
        return x


# ---------------------------------------------------------------------------
# Noise predictor eps_theta(x_t, t)
# ---------------------------------------------------------------------------

class SinusoidalTimeEmbedding(nn.Module):
    """Transformer-style positional embedding for the diffusion timestep."""

    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        half = self.dim // 2
        freqs = torch.exp(-math.log(10000) * torch.arange(half, device=t.device) / (half - 1))
        args = t.float()[:, None] * freqs[None, :]
        return torch.cat([torch.sin(args), torch.cos(args)], dim=-1)


class ResBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, t_dim: int):
        super().__init__()
        self.norm1 = nn.GroupNorm(8, in_ch)
        self.conv1 = nn.Conv2d(in_ch, out_ch, 3, padding=1)
        self.t_proj = nn.Linear(t_dim, out_ch)
        self.norm2 = nn.GroupNorm(8, out_ch)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, padding=1)
        self.skip = nn.Conv2d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

    def forward(self, x: torch.Tensor, t_emb: torch.Tensor) -> torch.Tensor:
        h = self.conv1(F.silu(self.norm1(x)))
        h = h + self.t_proj(F.silu(t_emb))[:, :, None, None]
        h = self.conv2(F.silu(self.norm2(h)))
        return h + self.skip(x)


class TinyUNet(nn.Module):
    """Minimal UNet eps_theta(x_t, t). Two down/up stages, sized for e.g. 32x32 inputs."""

    def __init__(self, in_ch: int = 3, base: int = 64, t_dim: int = 128):
        super().__init__()
        self.time_mlp = nn.Sequential(
            SinusoidalTimeEmbedding(t_dim),
            nn.Linear(t_dim, t_dim),
            nn.SiLU(),
            nn.Linear(t_dim, t_dim),
        )
        self.in_conv = nn.Conv2d(in_ch, base, 3, padding=1)

        self.d1 = ResBlock(base, base, t_dim)
        self.d2 = ResBlock(base, base * 2, t_dim)
        self.down = nn.AvgPool2d(2)

        self.mid = ResBlock(base * 2, base * 2, t_dim)

        self.up = nn.Upsample(scale_factor=2, mode="nearest")
        self.u2 = ResBlock(base * 4, base, t_dim)
        self.u1 = ResBlock(base * 2, base, t_dim)

        self.out_norm = nn.GroupNorm(8, base)
        self.out_conv = nn.Conv2d(base, in_ch, 3, padding=1)

    def forward(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        t_emb = self.time_mlp(t)
        h0 = self.in_conv(x)
        h1 = self.d1(h0, t_emb)
        h2 = self.d2(self.down(h1), t_emb)
        m = self.mid(h2, t_emb)
        u2 = self.u2(torch.cat([self.up(m), h1], dim=1), t_emb)
        u1 = self.u1(torch.cat([u2, h0], dim=1), t_emb)
        return self.out_conv(F.silu(self.out_norm(u1)))


# ---------------------------------------------------------------------------
# Sanity check: shapes flow through, loss is scalar, sampling returns x_0.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    diffusion = GaussianDiffusion(T=1000, device=device)
    model = TinyUNet(in_ch=3).to(device)

    x0 = torch.randn(4, 3, 32, 32, device=device)
    loss = diffusion.loss_simple(model, x0)
    print(f"L_simple: {loss.item():.4f}")

    samples = diffusion.sample(model, shape=(2, 3, 32, 32), device=device)
    print(f"sample shape: {tuple(samples.shape)}")
