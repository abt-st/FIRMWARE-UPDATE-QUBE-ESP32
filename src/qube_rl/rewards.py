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
    al_norm = np.abs(al) / np.pi  # 0 when hanging (alpha=0), 1 when inverted (alpha=±pi)
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


def linear_alpha_balance(state: np.ndarray) -> float:
    """Dense reward: linear_alpha + explicit balance incentive.

    Extends ``linear_alpha`` with:
    - **Velocity penalty** (quadratic on alpha_dot): always active, pushes the
      agent toward slower pendulum motion -- critical for stabilisation.
    - **Balance bonus** (additive, 2.0): awarded when the pendulum is both
      inverted (|alpha| > 150 deg) *and* slow (|alpha_dot| < 2 rad/s),
      giving a direct gradient toward the sustained-hold behaviour that
      ``evaluate_balance`` measures.

    The swing-up gradient from ``linear_alpha`` (``|alpha| / pi``) is
    preserved so the agent can still discover energy-pumping strategies.
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_abs = np.abs(al)
    al_rew = al_abs / np.pi  # linear: 0 at down, 1 at inverted

    # Balance zone: inverted (>150 deg) AND slow (|alpha_dot| < 2 rad/s)
    upright = al_abs > 5 * np.pi / 6
    slow = abs(state[ALPHA_DOT]) < 2.0
    balance_bonus = 2.0 if (upright and slow) else 0.0

    # Velocity penalty: quadratic, always active -- discourages fast swings
    vel_penalty = -0.01 * state[ALPHA_DOT] ** 2

    # Arm centering: light quadratic penalty
    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2

    return float(al_rew + vel_penalty + th_penalty + balance_bonus)


def linear_alpha_stabilise(state: np.ndarray) -> float:
    """``linear_alpha`` swing-up signal + gated damping + eval-aligned hold bonus.

    Designed to break the sustained-balance bottleneck (reach 100 %, but max
    continuous hold < 1 s) without re-introducing the two failure modes seen in
    earlier reward designs:

    - **R2's ``linear_alpha_balance``** applied a velocity penalty
      ``-c·alpha_dot**2`` over the *whole* state space, which made *hanging
      still* locally optimal and **killed the swing-up** (0 % reach). Here the
      damping is **gated to the upper half** (``|alpha| > pi/2``) so the agent
      is still free to pump energy when below horizontal.
    - **The planned R3 ``linear_alpha_adaptive``** awarded a *binary* +2.0 bonus
      over a wide zone (>150 deg, |alpha_dot|<2), giving no gradient to *tighten*
      toward the actual success criterion and inviting reward-hacking (orbiting
      the apex). Here the bonus is **continuous** — a Gaussian centred exactly on
      the ``evaluate_balance`` criterion (within 12 deg of inverted AND
      |alpha_dot| <= 1 rad/s) — so the gradient pulls the policy *into* the
      success region rather than merely near it.

    The swing-up gradient ``|alpha| / pi`` is preserved unchanged.

    Coefficients (``0.03`` damping, ``2.5`` bonus, ``sigma_alpha=0.21`` rad ~=
    12 deg, ``sigma_vel=1.0`` rad/s) are starting points; lower the damping if
    the swing-up slows, lower the bonus if the agent reward-hacks the apex.
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_abs = np.abs(al)
    al_rew = al_abs / np.pi  # swing-up: 0 at down, 1 at inverted (unchanged)

    d_top = np.pi - al_abs  # 0 at the apex (inverted), pi when hanging
    al_dot = state[ALPHA_DOT]

    # Velocity damping, GATED to the upper half: 0 below horizontal so the agent
    # can still pump energy; active above to encourage slowing for the catch.
    vel_penalty = -0.03 * al_dot * al_dot if al_abs > np.pi / 2 else 0.0

    # Continuous hold bonus, nested on the evaluate_balance success criterion
    # (within 12 deg of inverted AND |alpha_dot| <= 1 rad/s). Peaks at ~2.5 at
    # the exact target and decays smoothly, giving a gradient that tightens the
    # policy toward sustained balance instead of a flat reward-hackable plateau.
    bonus = 2.5 * np.exp(-((d_top / 0.21) ** 2) - (al_dot / 1.0) ** 2)

    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2

    return float(al_rew + vel_penalty + bonus + th_penalty)


def linear_alpha_apex_stabilise(state: np.ndarray) -> float:
    """``linear_alpha`` swing-up + balance bonus/damping gated **tightly to the apex**.

    Diagnosis from R2/R3: a velocity penalty is needed to make *slow, sustained*
    balance the reward optimum (``linear_alpha`` rewards being inverted equally
    whether held still or whipping through the top), **but** R3's
    ``linear_alpha_stabilise`` gated its damping at ``|alpha| > pi/2`` (horizontal)
    — which still hits the high-speed pass-through during swing-up and killed
    reach (0 %).

    Here the damping gate is tightened to within ``APEX_GATE`` (~30 deg) of the
    inverted apex (``pi - |alpha| < APEX_GATE``).  A *successful* swing-up only
    spends a brief instant that close to the top, so a small damping there aids
    the catch instead of starving the energy pump.  The continuous Gaussian hold
    bonus (nested exactly on the ``evaluate_balance`` criterion: within 12 deg of
    inverted AND ``|alpha_dot| <= 1`` rad/s) is kept so the gradient pulls the
    policy *into* sustained balance.

    Coefficients (``APEX_GATE=0.52`` rad ~= 30 deg, ``0.01`` damping, ``2.5``
    bonus) are starting points: widen the gate or raise the bonus if it still
    cannot hold; lower the damping if the swing-up reach drops.
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_abs = np.abs(al)
    al_rew = al_abs / np.pi  # swing-up: 0 at down, 1 at inverted (unchanged)

    d_top = np.pi - al_abs  # 0 at the apex (inverted), pi when hanging
    al_dot = state[ALPHA_DOT]

    # Damping GATED to within ~30 deg of the apex (not pi/2): off everywhere the
    # swing-up needs to pump energy, on only for the final catch.
    apex_gate = 0.52  # rad (~30 deg)
    vel_penalty = -0.01 * al_dot * al_dot if d_top < apex_gate else 0.0

    # Continuous hold bonus on the evaluate_balance success region.
    bonus = 2.5 * np.exp(-((d_top / 0.21) ** 2) - (al_dot / 1.0) ** 2)

    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2

    return float(al_rew + vel_penalty + bonus + th_penalty)


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
    "linear_alpha_balance": linear_alpha_balance,
    "linear_alpha_stabilise": linear_alpha_stabilise,
    "linear_alpha_apex_stabilise": linear_alpha_apex_stabilise,
    "linear_alpha_dense": linear_alpha_dense,
}
