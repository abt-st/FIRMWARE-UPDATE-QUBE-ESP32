"""Reward functions for QUBE Servo RL environments.

All rewards assume the state vector layout:
    [theta, alpha, theta_dot, alpha_dot]

where alpha = 0 is the hanging-down position and alpha = π is the inverted position.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT


def alpha_theta_reward(state: np.ndarray) -> float:
    """Multiplicative reward: pendulum verticality * arm centring.

    - Pendulum component: ``(1 - cos(alpha)) / 2``  ->  0 when vertical (alpha=0), 1 when inverted (alpha=pi).
    - Arm component: penalises θ away from 0 (centre).
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi  # [-π, π]
    al_rew = (1 + -np.cos(al)) / 2
    th_rew = 1 - ((np.cos(state[THETA] + np.pi) + 1) / 2) ** 2
    return float(al_rew * th_rew)


def exp_alpha_reward(state: np.ndarray, exp: int = 2) -> float:
    """Exponential pendulum reward * arm centring.

    More aggressive near ±π — useful when the agent needs a stronger gradient
    to keep the pendulum inverted.
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_norm = np.abs(al) / np.pi  # 0 at vertical, 1 at hanging
    al_rew = (np.exp(al_norm * exp) - np.exp(0)) / np.exp(exp)
    th_rew = 1 - ((np.cos(state[THETA] + np.pi) + 1) / 2) ** 2
    return float(al_rew * th_rew)


def cos_alpha_centered(state: np.ndarray) -> float:
    """cos_alpha reward with strong additive theta centering penalty.

    - Pendulum: ``(1 - cos(alpha)) / 2`` -> 0 down, 1 inverted.
    - Centering: ``-0.5 * (theta / (pi/2))^2`` -> 0 at center, -1 at ±90°.
    The centering penalty is always active (additive, not multiplicative).
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_rew = (1 + -np.cos(al)) / 2
    # Strong quadratic penalty: -1.0 at ±90° (pi/2), 0 at center
    th_penalty = -0.5 * (state[THETA] / (np.pi / 2)) ** 2
    return float(al_rew + th_penalty)


def linear_alpha(state: np.ndarray) -> float:
    """Dense pendulum reward with strong gradient at every angle.

    Unlike ``(1 - cos(alpha)) / 2`` which has near-zero gradient when hanging,
    this uses ``|alpha| / pi`` for a **linear** gradient everywhere.
    Gives the agent clear signal even at small angles, enabling faster
    energy-building discovery during swing-up.

    - Pendulum: ``|alpha| / pi`` -> 0 at down, 1 at inverted.
    - Arm: additive quadratic penalty (light, -0.2 at ±90°).
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_rew = np.abs(al) / np.pi  # linear: 6x stronger gradient near 0 than cos_alpha
    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2
    return float(al_rew + th_penalty)


def linear_alpha_dense(state: np.ndarray) -> float:
    """Dense reward: linear_alpha + velocity shaping for energy awareness.

    Adds velocity term that rewards upward angular velocity when pendulum
    is in the lower half, and penalises it when in the upper half.
    Helps the agent discover pumping strategy faster.
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_abs = np.abs(al)
    al_rew = al_abs / np.pi

    # Velocity shaping: reward al_dot when pendulum is below horizontal
    # (pumping energy in), penalise when above (wasted energy)
    below = al_abs < np.pi / 2  # True when pendulum is in lower half
    al_dot = state[ALPHA_DOT]
    vel_shaping = 0.01 * al_dot if below else -0.005 * al_dot * al_dot

    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2
    return float(np.clip(al_rew + vel_shaping + th_penalty, -2.0, 1.0))


def swingup_balance(state: np.ndarray) -> float:
    """Phase-adaptive reward: swing-up progress + balance reward with cost.

    This reward is designed for the complete swing-up-and-balance task.
    It combines:
    - A smooth transition from swing-up (energy-building) to balance (precision).
    - Theta centering (arm stays near zero).
    - Control effort penalty to discourage chatter.

    The reward adapts based on how close the pendulum is to the inverted position:
    - Far from inverted (swing-up phase): light penalties, arm can move freely
    - Near inverted (balance phase): heavy penalties, arm must stay centered
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi  # [-pi, pi]

    # Pendulum upright: 0 at down (al=0), 1 at inverted (al=±pi)
    pendulum = (1.0 - np.cos(al)) / 2.0

    # Adaptive penalties: heavier when pendulum is near inverted (balance phase)
    # Lighter when pendulum is far (swing-up phase, arm must move freely)
    balance_weight = 0.1 + 0.4 * pendulum  # 0.1 when down, 0.5 when inverted
    th_penalty = -balance_weight * (state[THETA] / (np.pi / 2)) ** 2

    # Velocity penalty: adaptive — less when swinging, more when balancing
    vel_weight = 0.0005 + 0.002 * pendulum
    vel_penalty = -vel_weight * (state[THETA_DOT] ** 2 + state[ALPHA_DOT] ** 2)

    return float(np.clip(pendulum + th_penalty + vel_penalty, -2.0, 1.0))


REWARDS: dict[str, Callable[[np.ndarray], float]] = {
    "cos_alpha": alpha_theta_reward,
    "exp_alpha_2": lambda s: exp_alpha_reward(s, exp=2),
    "exp_alpha_3": lambda s: exp_alpha_reward(s, exp=3),
    "exp_alpha_4": lambda s: exp_alpha_reward(s, exp=4),
    "exp_alpha_6": lambda s: exp_alpha_reward(s, exp=6),
    "cos_alpha_centered": cos_alpha_centered,
    "swingup_balance": swingup_balance,
    "linear_alpha": linear_alpha,
    "linear_alpha_dense": linear_alpha_dense,
}
