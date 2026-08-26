"""Tests for plotter module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")  # Non-interactive backend for testing
import matplotlib.pyplot as plt

from qube_analysis.plotter import plot_response


class TestPlotResponse:
    """Tests for plot_response function."""

    def test_basic_plot(self) -> None:
        """Test basic plot with position and setpoint only."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)

        fig, axes = plot_response(t, position, setpoint, show=False)

        assert fig is not None
        assert axes is not None
        assert len(axes) >= 1
        plt.close(fig)

    def test_plot_with_pwm(self) -> None:
        """Test plot with PWM signal."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)
        pwm = np.sin(t) * 100

        fig, axes = plot_response(t, position, setpoint, pwm=pwm, show=False)

        assert fig is not None
        assert axes is not None
        assert len(axes) >= 2
        plt.close(fig)

    def test_plot_with_current(self) -> None:
        """Test plot with current signal."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)
        current = np.abs(np.sin(t)) * 500

        fig, axes = plot_response(t, position, setpoint, current=current, show=False)

        assert fig is not None
        assert axes is not None
        assert len(axes) >= 2
        plt.close(fig)

    def test_plot_with_all_signals(self) -> None:
        """Test plot with all optional signals."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)
        pwm = np.sin(t) * 100
        current = np.abs(np.sin(t)) * 500

        fig, axes = plot_response(t, position, setpoint, pwm=pwm, current=current, show=False)

        assert fig is not None
        assert axes is not None
        assert len(axes) == 3
        plt.close(fig)

    def test_save_plot(self) -> None:
        """Test saving plot to file."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            save_path = Path(f.name)

        try:
            fig, _axes = plot_response(t, position, setpoint, save_path=save_path, show=False)

            assert save_path.exists()
            assert save_path.stat().st_size > 0
            plt.close(fig)
        finally:
            save_path.unlink(missing_ok=True)

    def test_custom_title(self) -> None:
        """Test custom title."""
        t = np.linspace(0, 10, 100)
        position = np.sin(t)
        setpoint = np.ones_like(t)
        title = "Custom Test Title"

        fig, _axes = plot_response(t, position, setpoint, title=title, show=False)

        assert fig is not None
        assert title in fig.get_suptitle()
        plt.close(fig)
