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

from qube_rl.envs.qube_dynamics import QubeDynamics
from qube_rl.rewards import REWARDS
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, Timing, VelocityFilter


class QubeSimEnv(gym.Env):
    """Simulation environment for the QUBE Servo rotary inverted pendulum.

    Observation space (6-D)::

        [cos(theta), sin(theta), cos(alpha), sin(alpha), theta_dot, alpha_dot]

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

        # Observation: [cos_th, sin_th, cos_al, sin_al, th_d, al_d]
        obs_max = np.array([1.0, 1.0, 1.0, 1.0, 30.0, 30.0], dtype=np.float32)
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
        rwd = float(self._reward_func(self._state))
        obs = self._get_obs()
        self._update_state(float(action[0]))
        terminated = not self.state_space.contains(self._state)
        terminated = terminated or not np.all(np.isfinite(self._state))
        return obs, rwd, terminated, False, {}

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed, options=options)
        self.dyn.randomize()
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
        self._sim_state = (0.01 * np.random.randn(4)).astype(np.float32)
        self._state = self._sim_state.copy()

    def _init_vel_filt(self) -> None:
        if self.velocity_filter_order:
            self.vel_filt = VelocityFilter(2, dt=self.timing.dt)
        else:
            self.vel_filt = None

    def _update_state(self, action: float) -> None:
        """Integrate dynamics and simulate encoder measurements."""
        integration_steps = int(self.timing.dt / self.integration_dt)
        for _ in range(integration_steps):
            thdd, aldd = self.dyn(self._sim_state, action)
            # Overflow protection: clamp accelerations
            max_acc = 1000.0  # rad/s^2 — physical limit
            thdd = float(np.clip(thdd, -max_acc, max_acc))
            aldd = float(np.clip(aldd, -max_acc, max_acc))
            if not np.isfinite(thdd) or not np.isfinite(aldd):
                break  # dynamics diverged — stop integrating
            self._sim_state[ALPHA_DOT] += self.integration_dt * aldd
            self._sim_state[THETA_DOT] += self.integration_dt * thdd
            self._sim_state[ALPHA] += self.integration_dt * self._sim_state[ALPHA_DOT]
            self._sim_state[THETA] += self.integration_dt * self._sim_state[THETA_DOT]
            # Clamp velocities to physical range
            self._sim_state[THETA_DOT] = np.clip(self._sim_state[THETA_DOT], -50.0, 50.0)
            self._sim_state[ALPHA_DOT] = np.clip(self._sim_state[ALPHA_DOT], -50.0, 50.0)

        # Simulate encoder quantisation
        if self.encoders_cprs:
            th_cpr, al_cpr = self.encoders_cprs
            if th_cpr is not None:
                inc = 2 * np.pi / th_cpr
                self._state[THETA] = np.round(self._sim_state[THETA] / inc) * inc
            else:
                self._state[THETA] = self._sim_state[THETA]
            if al_cpr is not None:
                inc = 2 * np.pi / al_cpr
                self._state[ALPHA] = np.round(self._sim_state[ALPHA] / inc) * inc
            else:
                self._state[ALPHA] = self._sim_state[ALPHA]
        else:
            self._state[THETA] = self._sim_state[THETA]
            self._state[ALPHA] = self._sim_state[ALPHA]

        # Velocity estimation (filtered derivative, matches firmware)
        if self.vel_filt is not None:
            self._state[THETA_DOT : ALPHA_DOT + 1] = self.vel_filt(self._state[THETA : ALPHA + 1])
        else:
            self._state[THETA_DOT] = self._sim_state[THETA_DOT]
            self._state[ALPHA_DOT] = self._sim_state[ALPHA_DOT]

    def _get_obs(self) -> np.ndarray:
        """Build the observation vector from the current state."""
        obs = np.array(
            [
                np.cos(self._state[THETA]),
                np.sin(self._state[THETA]),
                np.cos(self._state[ALPHA]),
                np.sin(self._state[ALPHA]),
                self._state[THETA_DOT],
                self._state[ALPHA_DOT],
            ],
            dtype=np.float32,
        )
        # Append raw angles if limits are set (gives the agent direct access)
        if not np.isinf(self.state_max[ALPHA]):
            obs = np.concatenate([[self._state[ALPHA]], obs])
        if not np.isinf(self.state_max[THETA]):
            obs = np.concatenate([[self._state[THETA]], obs])
        return obs
