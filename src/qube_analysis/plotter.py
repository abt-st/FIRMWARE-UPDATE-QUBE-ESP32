"""Generación de gráficos para análisis de datos experimentales."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def plot_response(
    t: np.ndarray,
    position: np.ndarray,
    setpoint: np.ndarray,
    pwm: np.ndarray | None = None,
    current: np.ndarray | None = None,
    title: str = "QUBE Servo — Respuesta del Sistema",
    save_path: str | Path | None = None,
    show: bool = True,
) -> tuple:
    """Plot the system response with multiple subplots.

    Args:
        t: Time array in seconds.
        position: Position array in degrees.
        setpoint: Setpoint array in degrees.
        pwm: Optional PWM signal array.
        current: Optional current array in mA.
        title: Plot title.
        save_path: Optional path to save the figure.
        show: Whether to display the plot.

    Returns:
        Tuple of (figure, axes).
    """
    n_plots = 1 + (1 if pwm is not None else 0) + (1 if current is not None else 0)

    fig, axes = plt.subplots(n_plots, 1, figsize=(12, 3 * n_plots), sharex=True)
    axes_list = [axes] if n_plots == 1 else list(axes)

    fig.suptitle(title, fontsize=14, fontweight="bold")
    fig.patch.set_facecolor("#0d0d1a")

    colors = {
        "position": "#00c8ff",
        "setpoint": "#ffd700",
        "error": "#ff6060",
        "pwm": "#7fff7f",
        "current": "#ff9f40",
    }

    # Position subplot
    ax = axes_list[0]
    ax.plot(t, position, color=colors["position"], linewidth=1.5, label="Posición")
    ax.plot(t, setpoint, color=colors["setpoint"], linewidth=1.2, linestyle="--",
            label="Setpoint")
    ax.plot(t, setpoint - position, color=colors["error"], linewidth=1.0,
            alpha=0.6, label="Error")
    ax.set_ylabel("Ángulo (°)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_facecolor("#1a1a35")

    # PWM subplot
    plot_idx = 1
    if pwm is not None:
        ax = axes_list[plot_idx]
        ax.plot(t, pwm, color=colors["pwm"], linewidth=1.0)
        ax.set_ylabel("PWM")
        ax.grid(True, alpha=0.3)
        ax.set_facecolor("#1a1a35")
        plot_idx += 1

    # Current subplot
    if current is not None:
        ax = axes_list[plot_idx]
        ax.plot(t, current, color=colors["current"], linewidth=1.0)
        ax.set_ylabel("Corriente (mA)")
        ax.set_xlabel("Tiempo (s)")
        ax.grid(True, alpha=0.3)
        ax.set_facecolor("#1a1a35")

    plt.tight_layout()

    if save_path:
        fig.savefig(str(save_path), dpi=150, bbox_inches="tight")

    if show:
        plt.show()

    return fig, axes_list
