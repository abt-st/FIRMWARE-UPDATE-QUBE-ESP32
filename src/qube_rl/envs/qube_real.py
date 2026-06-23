"""Gymnasium environment that controls the physical QUBE Servo via HTTP.

Talks to the ESP32's ``/rl_state`` and ``/rl_cmd`` endpoints at 50 Hz.
Compatible with concurrent MCP usage (separate HTTP connections, no shared state).

Concurrency contract:
    - The ESP32 async web server handles concurrent HTTP requests natively.
    - ``QubeRealEnv`` uses its own ``requests.Session`` (connection pooling).
    - MCP tools use separate ``requests.get()`` calls (no session).
    - Both can read ``/state`` or ``/rl_state`` simultaneously without conflict.
    - **Writing** (``/cmd``, ``/rl_cmd``) from both simultaneously is undefined:
      last-write-wins. The RL agent should be the sole writer when active.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, ClassVar

import gymnasium as gym
import numpy as np
import requests
from gymnasium.spaces import Box

from qube_rl.config import MAX_VELOCITY
from qube_rl.rewards import REWARDS
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, Timing, observation_from_state, wrap_angle

logger = logging.getLogger(__name__)


class QubeRealEnv(gym.Env):
    """Gymnasium environment for the real QUBE Servo (ESP32 over WiFi).

    Observation space (8-D, see :func:`qube_rl.utils.observation_from_state`)::

        [theta, alpha, cos(theta), sin(theta), cos(alpha), sin(alpha), theta_dot, alpha_dot]

    Action space (1-D)::

        [-1.0, 1.0]  ->  sent to ESP32 as ``/rl_cmd?a=<value>``

    Endpoints used:
        - ``GET /rl_state`` -> ``{th, al, thd, ald}`` (rad, rad/s)
        - ``GET /rl_cmd?a=X`` -> apply action
        - ``GET /rl_cmd?r=1`` -> reset encoders + state
        - ``GET /cmd?m=6`` -> switch to RL mode
    """

    metadata: ClassVar[dict[str, Any]] = {"render_modes": [], "render_fps": 50}

    def __init__(
        self,
        esp32_ip: str = "192.168.4.1",
        control_freq: int = 50,
        reward: str = "cos_alpha",
        http_timeout: float = 5.0,
        reset_settle_time: float = 3.0,
        auto_set_mode: bool = True,
        invert_action: bool = True,
        invert_alpha: bool = True,
    ) -> None:
        super().__init__()
        self.esp32_ip = esp32_ip
        self.timing = Timing(control_freq)
        self.http_timeout = http_timeout
        self.reset_settle_time = reset_settle_time
        self.auto_set_mode = auto_set_mode
        # Bench bring-up (2026-06-22) found the real motor torque is sign-flipped
        # vs the simulator: a +action drove theta NEGATIVE on hardware but POSITIVE
        # in sim, while theta/alpha encoders matched sim convention (the alpha
        # coupling -theta<->+alpha held on both).  So only the motor is mirrored;
        # negate the command at the hardware boundary (AFTER the wrappers, so the
        # action history the policy sees stays in sim convention).
        self._action_sign = -1.0 if invert_action else 1.0
        # The pendulum encoder also reads with the opposite sign vs sim: with the
        # action corrected, a sim-negative theta pairs with sim-POSITIVE alpha,
        # but the raw hardware reported alpha NEGATIVE (clear -56deg under a real
        # swing pump on 2026-06-22).  Flip alpha + alpha_dot so the (theta, alpha)
        # coupling the policy sees matches sim (theta and alpha opposite signs).
        self._alpha_sign = -1.0 if invert_alpha else 1.0

        # Reward
        if reward not in REWARDS:
            raise ValueError(f"Unknown reward '{reward}'. Choose from {list(REWARDS)}")
        self._reward_func = REWARDS[reward]

        # Spaces — bounds mirror the 8-D observation layout; the theta bound
        # (±120°) and velocity bound (MAX_VELOCITY) match the simulator so the
        # sim and real observation spaces agree (see EnvConfig.angle_limit_theta).
        th_max = np.float32(2 * np.pi / 3)  # ±120°, matches EnvConfig
        pi = np.float32(np.pi)
        v = np.float32(MAX_VELOCITY)
        self.observation_space = Box(
            low=np.array([-th_max, -pi, -1, -1, -1, -1, -v, -v], dtype=np.float32),
            high=np.array([th_max, pi, 1, 1, 1, 1, v, v], dtype=np.float32),
            dtype=np.float32,
        )
        self.action_space = Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)

        # HTTP session (connection pooling for 50Hz)
        self._session = requests.Session()
        self._base_url = f"http://{esp32_ip}"

        # Internal state
        self._state = np.zeros(4, dtype=np.float32)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get_rl_state(self) -> dict[str, Any]:
        """Read state from ``/rl_state`` endpoint with retry."""
        for attempt in range(3):
            try:
                resp = self._session.get(
                    f"{self._base_url}/rl_state",
                    timeout=self.http_timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        raise RuntimeError("unreachable")  # pragma: no cover

    def _send_rl_action(self, action: float) -> None:
        """Send action to ``/rl_cmd?a=<value>`` with retry."""
        for attempt in range(3):
            try:
                self._session.get(
                    f"{self._base_url}/rl_cmd",
                    params={"a": f"{action:.4f}"},
                    timeout=self.http_timeout,
                )
                return
            except requests.RequestException:
                if attempt == 2:
                    logger.warning("rl_cmd failed after 3 attempts")
                    return  # best-effort, don't crash training
                time.sleep(0.05)

    def _send_rl_reset(self) -> None:
        """Reset encoders and state via ``/rl_cmd?r=1``."""
        self._session.get(
            f"{self._base_url}/rl_cmd",
            params={"r": "1"},
            timeout=self.http_timeout,
        )

    def _set_mode(self, mode: int) -> None:
        """Switch ESP32 mode via ``/cmd?m=<mode>``."""
        self._session.get(
            f"{self._base_url}/cmd",
            params={"m": str(mode)},
            timeout=self.http_timeout,
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        # Send action (sign-corrected for the mirrored real motor), then a small
        # delay for the ESP32 to apply PWM.
        self._send_rl_action(self._action_sign * float(action[0]))
        time.sleep(0.01)  # 10ms — give ESP32 time to apply PWM

        # Read state with fallback to last known.
        # NOTE: ``/rl_state`` already returns RADIANS / rad·s⁻¹ (firmware
        # ``handleRlState`` applies ``DEG_TO_RAD``).  Do NOT call ``np.radians``
        # here — that double-conversion shrank every angle ~57× and was the root
        # cause of the r4_real failure (policy saw a near-zero state forever).
        # ``al`` accumulates unbounded across turns, so wrap it to [-π, π].
        try:
            data = self._get_rl_state()
            self._state[THETA] = float(data["th"])
            self._state[ALPHA] = wrap_angle(self._alpha_sign * float(data["al"]))
            self._state[THETA_DOT] = float(data["thd"])
            self._state[ALPHA_DOT] = self._alpha_sign * float(data["ald"])
        except requests.RequestException:
            logger.warning("rl_state read failed, using last known state")

        # Build observation
        obs = self._get_obs()
        rwd = float(self._reward_func(self._state))

        # Termination: only the servo (arm) hitting its mechanical limit ends an
        # episode.  We deliberately do NOT terminate on the pendulum angle: the
        # inverted goal is alpha = ±pi, so terminating near ±pi (the previous
        # ``abs(alpha) > 0.95*pi`` check, ~171°) ended the episode exactly when
        # the agent reached the target — making balancing impossible.  Episode
        # length is instead bounded by the ``TimeLimit`` wrapper (env factory).
        terminated = bool(abs(self._state[THETA]) > np.radians(100.0))  # servo ±100° (matches sim)
        if terminated:
            logger.info("Episode terminated: servo limit, theta=%.1f", np.degrees(self._state[THETA]))

        return obs, rwd, terminated, False, {}

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed, options=options)

        # Switch to RL mode if requested
        if self.auto_set_mode:
            self._set_mode(6)
            time.sleep(0.1)

        # Kill motor, wait for pendulum to settle (NO encoder reset — keeps physical reference)
        self._send_rl_action(0.0)
        logger.info("Reset: waiting %.1fs for pendulum to settle...", self.reset_settle_time)
        time.sleep(self.reset_settle_time)

        # Read initial state (radians already — see note in ``step``).
        data = self._get_rl_state()
        self._state[THETA] = float(data["th"])
        self._state[ALPHA] = wrap_angle(self._alpha_sign * float(data["al"]))
        self._state[THETA_DOT] = float(data["thd"])
        self._state[ALPHA_DOT] = self._alpha_sign * float(data["ald"])

        return self._get_obs(), {}

    def close(self) -> None:
        """Kill motor and close HTTP session."""
        with contextlib.suppress(Exception):
            self._send_rl_action(0.0)
        self._session.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_obs(self) -> np.ndarray:
        return observation_from_state(self._state, include_raw_theta=True, include_raw_alpha=True)
