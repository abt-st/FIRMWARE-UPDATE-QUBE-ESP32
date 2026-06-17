"""Constants and utility classes for QUBE Servo RL."""

from __future__ import annotations

import numpy as np
from scipy import signal

# State vector indices — must match QubeDynamics.__call__ unpacking
THETA: int = 0  # Servo (rotary arm) angle [rad]
ALPHA: int = 1  # Pendulum angle [rad] — 0 = hanging down, π = inverted
THETA_DOT: int = 2  # Servo angular velocity [rad/s]
ALPHA_DOT: int = 3  # Pendulum angular velocity [rad/s]


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
