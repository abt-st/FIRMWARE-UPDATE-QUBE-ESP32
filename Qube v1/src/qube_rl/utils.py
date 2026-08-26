"""Constants and utility classes for QUBE Servo RL."""

from __future__ import annotations

import numpy as np
from scipy import signal

# State vector indices — must match QubeDynamics.__call__ unpacking
THETA: int = 0  # Servo (rotary arm) angle [rad]
ALPHA: int = 1  # Pendulum angle [rad] — 0 = hanging down, π = inverted
THETA_DOT: int = 2  # Servo angular velocity [rad/s]
ALPHA_DOT: int = 3  # Pendulum angular velocity [rad/s]


def wrap_angle(angle: float) -> float:
    """Wrap an angle to the ``[-pi, pi]`` interval."""
    return float((angle + np.pi) % (2 * np.pi) - np.pi)


def observation_from_state(
    state: np.ndarray,
    include_raw_theta: bool = True,
    include_raw_alpha: bool = True,
) -> np.ndarray:
    """Build the policy observation vector from a 4-D state.

    Single source of truth for the observation layout shared by the simulation
    and real-hardware environments, so the two can never silently disagree
    (which would break sim-to-real transfer).  The full 8-D layout is::

        [theta, alpha, cos(theta), sin(theta), cos(alpha), sin(alpha), theta_dot, alpha_dot]

    The raw angles are optional so the simulator can emit a 6-D observation
    when its angular range is unbounded (no meaningful raw-angle scale).

    ``alpha`` is wrapped to ``[-pi, pi]`` before being emitted as a raw value so
    the observation always stays inside the declared ``observation_space`` even
    when the simulator lets the pendulum spin past +/-pi (the pendulum angle is
    no longer a termination condition — see ``QubeSimEnv.step``).  Wrapping is a
    no-op for ``cos``/``sin`` (they are periodic) and for the real hardware,
    whose firmware already reports alpha in ``[-180, 180]`` degrees.
    """
    th = float(state[THETA])
    al = wrap_angle(float(state[ALPHA]))
    obs: list[float] = [
        np.cos(th),
        np.sin(th),
        np.cos(al),
        np.sin(al),
        float(state[THETA_DOT]),
        float(state[ALPHA_DOT]),
    ]
    if include_raw_alpha:
        obs.insert(0, al)
    if include_raw_theta:
        obs.insert(0, th)
    return np.array(obs, dtype=np.float32)


class VelocityFilter:
    """Discrete velocity filter derived from a continuous one.

    Computes a filtered time-derivative of the input signal using a first-order
    low-pass filter discretised via ``scipy.signal.cont2discrete``.

    Ported from Quanser's common.py (used by Armandpl/furuta).
    """

    def __init__(
        self,
        x_len: int,
        dt: float,
        num: tuple[float, ...] = (50, 0),
        den: tuple[float, ...] = (1, 50),
        x_init: np.ndarray | None = None,
    ) -> None:
        derivative_filter = signal.cont2discrete((num, den), dt)
        self.b: np.ndarray = derivative_filter[0].ravel().astype(np.float32)
        self.a: np.ndarray = derivative_filter[1].astype(np.float32)
        if x_init is None:
            self.z: np.ndarray = np.zeros((max(len(self.a), len(self.b)) - 1, x_len), dtype=np.float32)
        else:
            self.set_initial_state(x_init)

    def set_initial_state(self, x_init: np.ndarray) -> None:
        """Set the filter state so that the first call returns zero velocity."""
        zi = signal.lfilter_zi(self.b, self.a)
        self.z = np.outer(zi, x_init).astype(np.float32)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """Filter one sample.  Returns filtered derivative."""
        xd, self.z = signal.lfilter(self.b, self.a, x[None, :], 0, self.z)
        return xd.ravel()


class Timing:
    """Simple timing helper that stores control frequency and dt."""

    def __init__(self, freq: int) -> None:
        self.f: int = freq
        self.dt: float = 1.0 / freq
