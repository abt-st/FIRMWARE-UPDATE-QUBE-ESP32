"""QUBE Analysis — Herramientas para análisis de datos experimentales."""

from .dataset import (
    DRIVER_MIGRATION_DATE,
    QubeRun,
    infer_driver,
    load_run,
    load_session,
)
from .metrics import compute_overshoot, compute_settling_time, compute_steady_state_error
from .sysid import (
    DampedFit,
    DeadzoneResult,
    PendulumParams,
    estimate_deadzone,
    fit_damped_oscillation,
    identify_pendulum,
    identify_pendulum_from_runs,
)

__all__ = [
    "DRIVER_MIGRATION_DATE",
    "DampedFit",
    "DeadzoneResult",
    "PendulumParams",
    "QubeRun",
    "compute_overshoot",
    "compute_settling_time",
    "compute_steady_state_error",
    "estimate_deadzone",
    "fit_damped_oscillation",
    "identify_pendulum",
    "identify_pendulum_from_runs",
    "infer_driver",
    "load_run",
    "load_session",
]


def plot_response(*args, **kwargs):
    """Lazy import for plot_response to avoid requiring matplotlib.

    See src/qube_analysis/plotter.py for full documentation.
    """
    from .plotter import plot_response as _plot_response

    return _plot_response(*args, **kwargs)
