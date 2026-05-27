"""QUBE Analysis — Herramientas para análisis de datos experimentales."""

from .metrics import compute_overshoot, compute_settling_time, compute_steady_state_error

__all__ = [
    "compute_overshoot",
    "compute_settling_time",
    "compute_steady_state_error",
]


def plot_response(*args, **kwargs):
    """Lazy import for plot_response to avoid requiring matplotlib.

    See src/qube_analysis/plotter.py for full documentation.
    """
    from .plotter import plot_response as _plot_response

    return _plot_response(*args, **kwargs)
