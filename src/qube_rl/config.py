"""Centralised configuration for QUBE RL training, environments and wrappers.

Hyperparameters used to be hardcoded (and duplicated, with conflicting values)
across ``train.py`` and ``fast_train.py`` — e.g. a 1,000,000-step replay buffer
in one and 50,000 in the other.  Collecting them here gives a single source of
truth that every entry point shares, and documents the rationale behind values
that were previously magic numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Maximum angular velocity [rad/s].  Used BOTH as the simulator's integration
# clamp and as the observation-space velocity bound, so the declared
# observation box can never disagree with the states the simulator can produce.
MAX_VELOCITY: float = 50.0

# Default reproducibility seed.  ``None`` keeps the legacy non-deterministic
# behaviour; pass ``--seed`` on the CLI to make a run reproducible.
DEFAULT_SEED: int | None = None


@dataclass(frozen=True)
class EnvConfig:
    """Simulation environment configuration."""

    control_freq: int = 50  # Hz — must match the deployment/inference frequency
    reward: str = "swingup_balance"
    # State-space (termination) bounds.
    # theta = ±120°: the handoffs show the swing-up reach rate climbs from ~8-10%
    # at ±90° to ~38% at ±120° (the arm needs room to pump energy), so the
    # training env must not forbid the very maneuver the task requires.
    angle_limit_theta: float = 2 * math.pi / 3  # ±120°
    # alpha bound is kept for the observation-space scale only; the pendulum
    # angle is NOT a termination condition (see QubeSimEnv._is_terminal), so the
    # episode is no longer ended the instant the agent reaches the inverted goal.
    angle_limit_alpha: float = math.pi
    # Episode length cap (steps) applied via gymnasium.wrappers.TimeLimit in the
    # env factory; at 50 Hz, 500 steps = 10 s — long enough to swing up AND hold.
    max_episode_steps: int = 500
    # Speed termination bounds [rad/s] (separate from MAX_VELOCITY clamp).
    speed_limit_theta: float = 50.0
    speed_limit_alpha: float = 400.0
    velocity_filter_order: int = 2
    # Reverse-curriculum reset: fraction of episodes that start near the inverted
    # apex (alpha ~= pi) instead of hanging, giving the agent dense balance
    # experience.  0.0 = original hanging-only reset (Florensa et al., CoRL 2017).
    near_upright_prob: float = 0.0

    @property
    def angle_limits(self) -> list[float]:
        return [self.angle_limit_theta, self.angle_limit_alpha]

    @property
    def speed_limits(self) -> list[float]:
        return [self.speed_limit_theta, self.speed_limit_alpha]


@dataclass(frozen=True)
class WrapperConfig:
    """Observation/action wrapper configuration (shared sim ↔ real)."""

    deadzone: float = 0.2  # motor static-friction compensation
    deadzone_center: float = 0.01
    deadzone_max_act: float = 0.75
    history_steps: int = 4  # frame stacking for second-order dynamics
    use_continuity_cost: bool = True


@dataclass(frozen=True)
class SACConfig:
    """Stable-Baselines3 SAC hyperparameters."""

    learning_rate: float = 3e-4
    batch_size: int = 256
    buffer_size: int = 1_000_000
    tau: float = 0.005  # target-network soft-update rate
    gamma: float = 0.99  # discount factor
    use_sde: bool = True  # gSDE exploration (smoother for real hardware)
    use_sde_at_warmup: bool = True
    sde_sample_freq: int = 64
    train_freq: int = 1
    gradient_steps: int = 1
    learning_starts: int = 1000
    net_arch: int = 64  # hidden size; [64, 64] fits ESP32 flash/RAM budget


def set_global_seeds(seed: int | None) -> None:
    """Seed Python, NumPy and (if available) PyTorch for reproducible runs.

    No-op when ``seed`` is ``None``.  Environment seeding is handled separately
    via ``env.reset(seed=...)`` so the env's own ``np_random`` is used.
    """
    if seed is None:
        return
    import random

    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:  # torch is an optional dependency for non-training use
        pass
