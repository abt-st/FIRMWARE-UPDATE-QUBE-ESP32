"""Tests for PID metrics computation."""

from __future__ import annotations

import numpy as np

from qube_analysis.metrics import compute_overshoot, compute_settling_time, compute_steady_state_error


class TestComputeOvershoot:
    """Tests for compute_overshoot."""

    def test_no_overshoot(self) -> None:
        """Test with no overshoot."""
        response = np.array([0.0, 0.2, 0.5, 0.8, 0.95, 1.0, 1.0, 1.0])
        assert compute_overshoot(response, setpoint=1.0) == 0.0

    def test_with_overshoot(self) -> None:
        """Test with overshoot."""
        response = np.array([0.0, 0.5, 1.2, 1.1, 1.0, 1.0])
        result = compute_overshoot(response, setpoint=1.0)
        assert abs(result - 20.0) < 0.01  # 20% overshoot

    def test_empty(self) -> None:
        """Test with empty array."""
        assert compute_overshoot(np.array([])) == 0.0


class TestComputeSettlingTime:
    """Tests for compute_settling_time."""

    def test_settles_quickly(self) -> None:
        """Test with a quickly settling response."""
        response = np.array([0.0, 0.5, 0.8, 0.95, 0.98, 1.0, 1.0])
        # All samples after index 0 are within 2% of 1.0
        t = compute_settling_time(response, setpoint=1.0, dt=0.1)
        assert t > 0

    def test_never_settles(self) -> None:
        """Test with a response that never settles."""
        response = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
        t = compute_settling_time(response, setpoint=1.0, dt=0.1)
        assert abs(t - 0.6) < 1e-9  # len=6, dt=0.1


class TestComputeSteadyStateError:
    """Tests for compute_steady_state_error."""

    def test_zero_error(self) -> None:
        """Test with zero steady-state error."""
        response = np.array([0.0, 0.5, 0.8, 1.0, 1.0, 1.0, 1.0])
        err = compute_steady_state_error(response, setpoint=1.0)
        assert abs(err) < 0.01

    def test_small_error(self) -> None:
        """Test with a small steady-state error."""
        response = np.array([0.0, 0.5, 0.9, 0.92, 0.93, 0.91, 0.92])
        err = compute_steady_state_error(response, setpoint=1.0, window_ratio=0.3)
        assert abs(err - 0.08) < 0.01  # ~0.08 error

    def test_empty(self) -> None:
        """Test with empty array."""
        assert compute_steady_state_error(np.array([])) == 0.0
