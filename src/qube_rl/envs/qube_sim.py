"""Gymnasium environment for the QUBE Servo rotary inverted pendulum (simulation).

Trains a SAC agent to swing up and balance the pendulum using the analytical
dynamics model from :class:`QubeDynamics`.  Domain randomisation is applied
automatically on every ``reset()``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import gymnasium as gym
import numpy as np
from gymnasium.spaces import Box

from qube_rl.config import MAX_VELOCITY
from qube_rl.envs.qube_dynamics import QubeDynamics
from qube_rl.rewards import REWARDS
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, Timing, VelocityFilter, observation_from_state


class QubeSimEnv(gym.Env):
    """Simulation environment for the QUBE Servo rotary inverted pendulum.

    Observation (see :func:`qube_rl.utils.observation_from_state`): 6-D when the
    angular range is unbounded, or 8-D when ``angle_limits`` are finite (raw
    ``theta``/``alpha`` prepended).  Training uses the bounded 8-D form so the
    layout matches :class:`~qube_rl.envs.qube_real.QubeRealEnv`::

        [theta, alpha, cos(theta), sin(theta), cos(alpha), sin(alpha), theta_dot, alpha_dot]

    Action space (1-D)::

        [-1.0, 1.0]  ->  mapped to [-V, +V] volts

    Termination:
        Episode ends when the state vector leaves ``state_space`` (angle or
        speed limits exceeded).
    """

    metadata: ClassVar[dict[str, Any]] = {"render_modes": ["rgb_array"], "render_fps": 50}

    def __init__(
        self,
        dyn: QubeDynamics | None = None,
        control_freq: int = 50,
        reward: str = "cos_alpha",
        angle_limits: list[float | None] | None = None,
        speed_limits: list[float | None] | None = None,
        encoders_cprs: list[float | None] | None = None,
        velocity_filter_order: int = 2,
        integration_dt: float = 1 / 500,
        render_mode: str = "rgb_array",
    ) -> None:
        super().__init__()
        self.dyn = dyn or QubeDynamics()
        self.timing = Timing(control_freq)
        self.integration_dt = integration_dt
        self.render_mode = render_mode

        # Reward function
        if reward not in REWARDS:
            raise ValueError(f"Unknown reward '{reward}'. Choose from {list(REWARDS)}")
        self._reward_name = reward
        self._reward_func = REWARDS[reward]

        # Encoder resolution (None = infinite / continuous)
        self.encoders_cprs = encoders_cprs  # [theta_CPR, alpha_CPR]

        # Velocity filter (matches firmware EMA)
        self.velocity_filter_order = velocity_filter_order
        self.vel_filt: VelocityFilter | None = None

        # --- Spaces ---
        angle_limits = angle_limits or [np.inf, np.inf]
        speed_limits = speed_limits or [50.0, 400.0]
        angle_limits = [np.inf if v is None else v for v in angle_limits]
        speed_limits = [np.inf if v is None else v for v in speed_limits]

        self.state_max = np.array(angle_limits + speed_limits, dtype=np.float32)

        # Observation: [cos_th, sin_th, cos_al, sin_al, th_d, al_d].
        # Velocity bound matches the integration clamp (MAX_VELOCITY) so the
        # declared observation box can never be exceeded by a produced state.
        obs_max = np.array([1.0, 1.0, 1.0, 1.0, MAX_VELOCITY, MAX_VELOCITY], dtype=np.float32)
        if not np.isinf(self.state_max[ALPHA]):
            obs_max = np.concatenate([[self.state_max[ALPHA]], obs_max])
        if not np.isinf(self.state_max[THETA]):
            obs_max = np.concatenate([[self.state_max[THETA]], obs_max])

        self.state_space = Box(low=-self.state_max, high=self.state_max, dtype=np.float32)
        self.observation_space = Box(low=-obs_max, high=obs_max, dtype=np.float32)
        self.action_space = Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)

        # Internal state
        self._sim_state: np.ndarray = np.zeros(4, dtype=np.float32)
        self._state: np.ndarray = np.zeros(4, dtype=np.float32)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        # Apply the action, then observe and reward the resulting state. The
        # observation and reward must describe the post-action state, otherwise
        # the agent receives the reward/observation of the state *before* its
        # action took effect (an off-by-one in the MDP).
        self._update_state(float(action[0]))
        obs = self._get_obs()
        rwd = float(self._reward_func(self._state))
        terminated = not self.state_space.contains(self._state)
        terminated = terminated or not np.all(np.isfinite(self._state))
        return obs, rwd, terminated, False, {}

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed, options=options)
        # Draw domain-randomisation and the initial state from the env's own
        # seeded generator so a given seed reproduces the same episode sequence.
        self.dyn.randomize(rng=self.np_random)
        self._init_state()
        self._init_vel_filt()
        return self._get_obs(), {}

    def render(self) -> None:
        """Rendering not implemented for headless simulation."""

    def close(self) -> None:
        """Nothing to clean up."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_state(self) -> None:
        """Initialise state near the unstable equilibrium (pendulum inverted)."""
        self._sim_state = (0.01 * self.np_random.standard_normal(4)).astype(np.float32)
        self._state = self._sim_state.copy()

    def _init_vel_filt(self) -> None:
        if self.velocity_filter_order:
            self.vel_filt = VelocityFilter(2, dt=self.timing.dt)
        else:
            self.vel_filt = None

    # Acceleration clamp [rad/s^2] — overflow protection against diverging dynamics.
    _MAX_ACCEL = 1000.0

    def _update_state(self, action: float) -> None:
        """Advance the true state, then derive the measured state.

        Pipeline: integrate the continuous dynamics, simulate encoder
        quantisation of the angles, then estimate velocities the same way the
        firmware does (filtered derivative).
        """
        self._integrate_euler(action)
        self._quantize_angles()
        self._estimate_velocities()

    def _integrate_euler(self, action: float) -> None:
        """Semi-implicit Euler integration of the true (unmeasured) state."""
        integration_steps = int(self.timing.dt / self.integration_dt)
        for _ in range(integration_steps):
            thdd, aldd = self.dyn(self._sim_state, action)
            thdd = float(np.clip(thdd, -self._MAX_ACCEL, self._MAX_ACCEL))
            aldd = float(np.clip(aldd, -self._MAX_ACCEL, self._MAX_ACCEL))
            if not np.isfinite(thdd) or not np.isfinite(aldd):
                break  # dynamics diverged — stop integrating
            self._sim_state[ALPHA_DOT] += self.integration_dt * aldd
            self._sim_state[THETA_DOT] += self.integration_dt * thdd
            self._sim_state[ALPHA] += self.integration_dt * self._sim_state[ALPHA_DOT]
            self._sim_state[THETA] += self.integration_dt * self._sim_state[THETA_DOT]
            # Clamp velocities to the physical range (shared with the obs bound)
            self._sim_state[THETA_DOT] = np.clip(self._sim_state[THETA_DOT], -MAX_VELOCITY, MAX_VELOCITY)
            self._sim_state[ALPHA_DOT] = np.clip(self._sim_state[ALPHA_DOT], -MAX_VELOCITY, MAX_VELOCITY)

    def _quantize_angles(self) -> None:
        """Copy true angles into the measured state, applying encoder quantisation."""
        cprs = self.encoders_cprs or [None, None]
        for idx, cpr in zip((THETA, ALPHA), cprs, strict=True):
            if cpr is not None:
                inc = 2 * np.pi / cpr
                self._state[idx] = np.round(self._sim_state[idx] / inc) * inc
            else:
                self._state[idx] = self._sim_state[idx]

    def _estimate_velocities(self) -> None:
        """Estimate velocities from measured angles (filtered, matches firmware).

        The filtered derivative can transiently overshoot, so clamp it to
        MAX_VELOCITY — the same bound declared by the observation space.
        """
        if self.vel_filt is not None:
            self._state[THETA_DOT : ALPHA_DOT + 1] = self.vel_filt(self._state[THETA : ALPHA + 1])
        else:
            self._state[THETA_DOT] = self._sim_state[THETA_DOT]
            self._state[ALPHA_DOT] = self._sim_state[ALPHA_DOT]
        self._state[THETA_DOT] = np.clip(self._state[THETA_DOT], -MAX_VELOCITY, MAX_VELOCITY)
        self._state[ALPHA_DOT] = np.clip(self._state[ALPHA_DOT], -MAX_VELOCITY, MAX_VELOCITY)

    def _get_obs(self) -> np.ndarray:
        """Build the observation vector from the current state.

        Raw angles are included only when the corresponding range is bounded,
        matching the observation-space construction in ``__init__``.
        """
        return observation_from_state(
            self._state,
            include_raw_theta=not np.isinf(self.state_max[THETA]),
            include_raw_alpha=not np.isinf(self.state_max[ALPHA]),
        )
