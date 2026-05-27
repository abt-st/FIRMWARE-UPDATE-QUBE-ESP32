"""Métricas de desempeño para sistemas de control."""

from __future__ import annotations

import numpy as np


def compute_overshoot(
    response: np.ndarray,
    setpoint: float = 1.0,
) -> float:
    """Compute the percentage overshoot of a step response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.

    Returns:
        Overshoot percentage (0 if none).
    """
    if len(response) == 0:
        return 0.0
    peak = np.max(response)
    if peak <= setpoint:
        return 0.0
    return float(((peak - setpoint) / setpoint) * 100.0)


def compute_settling_time(
    response: np.ndarray,
    setpoint: float = 1.0,
    tolerance: float = 0.02,
    dt: float = 0.1,
) -> float:
    """Compute the 2% settling time of a step response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.
        tolerance: Fraction of setpoint for settling band (default 0.02).
        dt: Time step between samples in seconds.

    Returns:
        Settling time in seconds. Returns len(response) * dt if never settles.
    """
    band = tolerance * abs(setpoint)
    t_settle = len(response) * dt
    for i in range(len(response) - 1, -1, -1):
        if abs(response[i] - setpoint) > band:
            t_settle = (i + 1) * dt
            break
    return float(t_settle)


def compute_steady_state_error(
    response: np.ndarray,
    setpoint: float = 1.0,
    window_ratio: float = 0.1,
) -> float:
    """Compute the steady-state error from the last portion of the response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.
        window_ratio: Fraction of the response to use for steady-state (default 0.1).

    Returns:
        Steady-state error as absolute value.
    """
    if len(response) == 0:
        return 0.0
    n_samples = max(1, int(len(response) * window_ratio))
    final_segment = response[-n_samples:]
    return float(abs(np.mean(final_segment) - setpoint))
