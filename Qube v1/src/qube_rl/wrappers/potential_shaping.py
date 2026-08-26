"""Potential-based reward shaping (PBRS).

Adds a shaping term ``F(s, s') = gamma * Phi(s') - Phi(s)`` to the environment
reward.  Ng, Harada & Russell (1999) proved that any shaping of this exact form
leaves the set of optimal policies **unchanged** (policy invariance), so it can
guide learning toward the inverted goal without distorting the task — unlike the
ad-hoc reward variants in :mod:`qube_rl.rewards`, where swapping rewards changes
the optimum and can invite reward hacking (e.g. spinning).

The potential is computed from the underlying 4-D physical state
``[theta, alpha, theta_dot, alpha_dot]`` (``env.unwrapped._state``), so this
wrapper can sit at the outermost position of the stack (after ``HistoryWrapper``)
without caring about the stacked-observation layout.

Reference: A. Y. Ng, D. Harada, S. Russell, "Policy Invariance Under Reward
Transformations", ICML 1999.
"""

from __future__ import annotations

from collections.abc import Callable

import gymnasium as gym
import numpy as np

from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, wrap_angle


def _phi_upright(state: np.ndarray, theta_weight: float = 0.0) -> float:
    """Potential that increases as the pendulum approaches the inverted goal.

    ``(1 - cos(alpha)) / 2`` is 0 when hanging (alpha=0) and 1 when inverted
    (alpha=±pi).  An optional quadratic arm-centering term can be subtracted.
    """
    al = wrap_angle(float(state[ALPHA]))
    phi = (1.0 - np.cos(al)) / 2.0
    if theta_weight:
        phi -= theta_weight * (float(state[THETA]) / np.pi) ** 2
    return float(phi)


POTENTIALS: dict[str, Callable[[np.ndarray, float], float]] = {
    "upright": _phi_upright,
}

# The "energy" potential needs the (randomised) dynamics constants, so it is
# computed as a method of the wrapper rather than a pure state function — see
# ``PotentialShaping._phi_energy``.  Listed here so it passes name validation.
ENERGY_POTENTIAL = "energy"


class PotentialShaping(gym.Wrapper):
    """Add a policy-invariant potential-based shaping term to the reward.

    Parameters
    ----------
    env : gym.Env
        Environment to wrap (must expose ``unwrapped._state`` as a 4-D state).
    potential : str
        Name of the potential function from :data:`POTENTIALS`.
    gamma : float
        Discount factor — **must match the agent's** ``gamma`` for the
        invariance guarantee to hold.
    scale : float
        Multiplier on the potential (tunes how strong the shaping is).
    theta_weight : float
        Weight of the optional arm-centering term inside the potential.
    energy_weight : float
        Weight of the quadratic energy-error term in the ``"energy"`` potential
        (ignored by other potentials).
    """

    def __init__(
        self,
        env: gym.Env,
        potential: str = "upright",
        gamma: float = 0.99,
        scale: float = 1.0,
        theta_weight: float = 0.0,
        energy_weight: float = 1.0,
    ) -> None:
        super().__init__(env)
        valid = set(POTENTIALS) | {ENERGY_POTENTIAL}
        if potential not in valid:
            raise ValueError(f"Unknown potential '{potential}'. Choose from {sorted(valid)}")
        self._potential_name = potential
        self._phi_fn = POTENTIALS.get(potential)
        self.gamma = gamma
        self.scale = scale
        self.theta_weight = theta_weight
        self.energy_weight = energy_weight
        self._prev_phi = 0.0

    def _phi_energy(self, state: np.ndarray) -> float:
        """Energy-based potential (EBERL/Astrom-style), policy-invariant via PBRS.

        Combines upright-closeness with a penalty on the deviation of the total
        mechanical energy from the upright-equilibrium energy, so the shaping
        guides the agent onto the energy manifold of the goal (the basis of
        energy-shaping swing-up) while remaining policy-invariant.

        Uses the *current* (domain-randomised) dynamics constants from the
        wrapped env, where the EOM gravity term ``c[4] = 0.5*Mp*Lp*g`` gives the
        pendulum potential energy ``PE(alpha) = -c[4]*cos(alpha)`` (``-c[4]`` when
        hanging, ``+c[4]`` inverted) and the mass matrix gives the kinetic energy.
        """
        dyn = self.unwrapped.dyn
        c = dyn._c
        al = wrap_angle(float(state[ALPHA]))
        thd = float(state[THETA_DOT])
        ald = float(state[ALPHA_DOT])
        sin_al = np.sin(al)
        cos_al = np.cos(al)

        a = c[0] + c[1] * sin_al**2
        b = c[2] * cos_al
        cc = c[3]
        ke = 0.5 * (a * thd * thd + 2.0 * b * thd * ald + cc * ald * ald)
        pe = -c[4] * cos_al  # -c4 hanging, +c4 inverted
        energy = ke + pe

        e_top = c[4]  # PE at the upright equilibrium, at rest
        e_scale = 2.0 * c[4] + 1e-9  # bottom->top potential swing
        upright = (1.0 - cos_al) / 2.0
        e_err = (energy - e_top) / e_scale
        return float(upright - self.energy_weight * e_err * e_err)

    def _potential(self) -> float:
        state = self.unwrapped._state
        if self._potential_name == ENERGY_POTENTIAL:
            return self.scale * self._phi_energy(state)
        return self.scale * self._phi_fn(state, self.theta_weight)

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self._prev_phi = self._potential()
        return obs, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        phi = self._potential()
        # Policy-invariance convention: Phi(terminal) = 0 for a true terminal
        # state, but a time-limit *truncation* is NOT terminal — use Phi(s') so
        # the shaping telescopes correctly across the (non-terminal) cutoff.
        phi_next = 0.0 if terminated else phi
        shaping = self.gamma * phi_next - self._prev_phi
        self._prev_phi = phi
        info["shaping_reward"] = shaping
        return obs, reward + shaping, terminated, truncated, info
