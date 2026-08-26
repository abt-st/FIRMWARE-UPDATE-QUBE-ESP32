"""Task-level evaluation metrics for the swing-up + balance problem.

The old success proxy — *peak* ``|alpha| > 120 deg`` reached once
(``distill.py``) — measures *reaching* the top, not *balancing* there, and is
fooled by a pendulum that simply spins through the top (reward hacking).  This
module is the single source of truth for a correct, balance-aware metric:

- **reach**: did the pendulum get near inverted at all?
- **upright_fraction**: fraction of steps held genuinely inverted *and* slow.
- **max_hold_s**: longest *continuous* time spent inverted-and-slow.
- **balance**: was ``max_hold_s`` at least ``hold_seconds`` (true stabilisation)?

A step counts as "upright" only when the pendulum is within ``upright_tol`` of
the inverted position **and** its angular speed is below ``vel_tol`` — i.e. up
*and* not just whipping past the top.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from qube_rl.utils import ALPHA, ALPHA_DOT, wrap_angle

logger = logging.getLogger(__name__)


def _physical_state(env: Any) -> np.ndarray:
    """Return the underlying 4-D physical state regardless of wrappers."""
    return np.asarray(env.unwrapped._state, dtype=np.float32)


def evaluate_balance(
    model: Any,
    env: Any,
    n_episodes: int = 20,
    *,
    upright_tol_deg: float = 12.0,
    vel_tol: float = 1.0,
    reach_deg: float = 150.0,
    hold_seconds: float = 1.0,
    control_freq: int = 50,
    deterministic: bool = True,
    max_steps: int | None = None,
    reset_options: dict | None = None,
) -> dict[str, float]:
    """Roll out a policy and compute balance-aware success metrics.

    Parameters
    ----------
    model
        Anything with ``predict(obs, deterministic=...) -> (action, _)`` (an SB3
        model) — or ``None`` to evaluate a zero policy (sanity baseline).
    env
        A (wrapped) environment exposing ``unwrapped._state`` as a 4-D state.
    n_episodes
        Number of evaluation episodes.
    upright_tol_deg
        Angular tolerance around the inverted position to count as "upright".
    vel_tol
        Max ``|alpha_dot|`` [rad/s] to count a step as a genuine hold.
    reach_deg
        ``|alpha|`` threshold (deg) counting as "reached the top".
    hold_seconds
        Continuous upright time required to count an episode as "balanced".
    control_freq
        Control rate [Hz]; ``dt = 1 / control_freq`` converts steps to seconds.
    reset_options
        Passed straight to ``env.reset(options=...)`` for every episode.  Use
        ``{"near_upright": True}`` to roll out from the inverted apex — a
        diagnostic that isolates the policy's *stabilisation* ability from its
        swing-up, independent of the env's training reset distribution.

    Returns
    -------
    dict
        Aggregated metrics (means across episodes): ``reach_rate``,
        ``balance_rate``, ``upright_fraction``, ``max_hold_s``, ``return_mean``.
    """
    dt = 1.0 / control_freq
    upright_tol = np.radians(upright_tol_deg)
    reach_tol = np.radians(reach_deg)

    reach_flags: list[bool] = []
    balance_flags: list[bool] = []
    upright_fracs: list[float] = []
    max_holds: list[float] = []
    returns: list[float] = []

    for _ep in range(n_episodes):
        obs, _info = env.reset(options=reset_options)
        ep_return = 0.0
        n_steps = 0
        n_upright = 0
        reached = False
        cur_hold = 0
        best_hold = 0

        while True:
            if model is None:
                action = np.zeros(env.action_space.shape, dtype=np.float32)
            else:
                action, _ = model.predict(obs, deterministic=deterministic)
            obs, reward, terminated, truncated, _info = env.step(action)
            ep_return += float(reward)
            n_steps += 1

            state = _physical_state(env)
            al = wrap_angle(float(state[ALPHA]))
            ang_to_top = np.pi - abs(al)  # 0 at inverted, pi at hanging
            if abs(al) >= reach_tol:
                reached = True
            if ang_to_top <= upright_tol and abs(float(state[ALPHA_DOT])) <= vel_tol:
                n_upright += 1
                cur_hold += 1
                best_hold = max(best_hold, cur_hold)
            else:
                cur_hold = 0

            if terminated or truncated:
                break
            if max_steps is not None and n_steps >= max_steps:
                break

        reach_flags.append(reached)
        balance_flags.append(best_hold * dt >= hold_seconds)
        upright_fracs.append(n_upright / n_steps if n_steps else 0.0)
        max_holds.append(best_hold * dt)
        returns.append(ep_return)

    return {
        "episodes": float(n_episodes),
        "reach_rate": float(np.mean(reach_flags)),
        "balance_rate": float(np.mean(balance_flags)),
        "upright_fraction": float(np.mean(upright_fracs)),
        "max_hold_s": float(np.mean(max_holds)),
        "max_hold_s_best": float(np.max(max_holds)) if max_holds else 0.0,
        "return_mean": float(np.mean(returns)),
    }


def format_balance_metrics(m: dict[str, float]) -> str:
    """One-line human-readable summary of :func:`evaluate_balance` output."""
    return (
        f"reach={m['reach_rate'] * 100:.0f}% | balance={m['balance_rate'] * 100:.0f}% | "
        f"upright={m['upright_fraction'] * 100:.0f}% | hold_avg={m['max_hold_s']:.2f}s "
        f"(best {m['max_hold_s_best']:.2f}s) | return={m['return_mean']:.1f}"
    )
