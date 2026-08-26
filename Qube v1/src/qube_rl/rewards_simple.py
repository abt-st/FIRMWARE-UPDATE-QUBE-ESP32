"""Simplified reward functions designed for small [64,64] networks.

The key insight: large networks (128,128) can learn complex reward landscapes,
but small networks need simpler, more direct gradient signals.
"""

from __future__ import annotations

import numpy as np


def swingup_simple(state: np.ndarray) -> float:
    """Ultra-simple swing-up reward: just maximize |alpha| with energy bonus.

    State: [theta, alpha, theta_dot, alpha_dot]
    alpha=0 is hanging, alpha=±π is inverted.
    """
    al = state[1]
    ald = state[3]

    # Primary: how close to inverted (0 at hanging, 1 at inverted)
    al_rew = 1.0 - abs(al) / np.pi

    # Bonus: reward angular velocity when pendulum is moving upward
    # This encourages energy injection
    if abs(al) < np.pi / 2:  # noqa: SIM108 — kept as if/else for readability of the two regimes
        # In lower half: reward upward velocity
        vel_bonus = 0.3 * abs(ald) * (1.0 if al * ald > 0 else 0.0)
    else:
        # In upper half: reward low velocity (stabilizing)
        vel_bonus = -0.1 * abs(ald)

    # Small penalty for arm angle
    th = state[0]
    th_penalty = -0.1 * (th / (np.pi / 2)) ** 2

    return float(np.clip(al_rew + vel_bonus + th_penalty, -1.0, 1.0))
