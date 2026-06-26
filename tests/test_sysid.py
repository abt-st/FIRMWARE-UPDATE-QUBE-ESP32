"""Tests for the gray-box system-identification toolkit (qube_analysis.sysid).

The strategy is ground-truth recovery: synthesise signals from known physical
parameters, sampled at the ~30 Hz the real hardware logs at, and check the
estimators recover them within tolerance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qube_analysis.dataset import QubeRun
from qube_analysis.sysid import (
    G,
    estimate_deadzone,
    fit_damped_oscillation,
    identify_pendulum,
    identify_pendulum_from_runs,
)


def _damped(t: np.ndarray, amp: float, zeta: float, wn: float, off: float = 0.0) -> np.ndarray:
    wd = wn * np.sqrt(1.0 - zeta**2)
    return amp * np.exp(-zeta * wn * t) * np.cos(wd * t) + off


def _run(data: dict[str, np.ndarray]) -> QubeRun:
    return QubeRun(data=data, path=Path("synthetic.csv"), driver="BTS7960")


class TestDampedFit:
    """Recovery of modal parameters from a decaying sinusoid."""

    def test_recovers_frequency_and_damping(self) -> None:
        wn, zeta = 10.5, 0.03
        t = np.linspace(0, 3.0, 90)  # 30 Hz, 3 s
        x = _damped(t, amp=1.2, zeta=zeta, wn=wn, off=0.4)
        fit = fit_damped_oscillation(t, x)
        assert fit.r2 > 0.98
        assert np.isclose(fit.omega_n, wn, rtol=0.05)
        assert np.isclose(fit.zeta, zeta, atol=0.01)
        assert np.isclose(fit.offset, 0.4, atol=0.05)

    def test_period_property(self) -> None:
        t = np.linspace(0, 4.0, 120)
        fit = fit_damped_oscillation(t, _damped(t, 1.0, 0.02, 2 * np.pi))  # 1 Hz
        assert np.isclose(fit.period, 1.0, rtol=0.05)
        assert np.isclose(fit.freq_hz, 1.0, rtol=0.05)

    def test_survives_measurement_noise(self) -> None:
        rng = np.random.default_rng(0)
        t = np.linspace(0, 3.0, 90)
        x = _damped(t, 1.0, 0.04, 11.0) + rng.normal(0, 0.02, t.size)
        fit = fit_damped_oscillation(t, x)
        assert np.isclose(fit.omega_n, 11.0, rtol=0.08)

    def test_too_few_samples_raises(self) -> None:
        with pytest.raises(ValueError):
            fit_damped_oscillation(np.arange(4.0), np.arange(4.0))


class TestPendulumMapping:
    """Mapping a fit to Lp/Dp must match the QubeDynamics relations."""

    def test_lp_from_natural_frequency(self) -> None:
        # Build a signal whose wn corresponds exactly to Lp = 0.129 m.
        Lp_true = 0.129
        wn = np.sqrt(3 * G / (2 * Lp_true))
        t = np.linspace(0, 3.0, 120)
        fit = fit_damped_oscillation(t, _damped(t, np.deg2rad(20), 0.02, wn))
        params = identify_pendulum(fit, Mp=0.024)
        assert np.isclose(params.Lp, Lp_true, rtol=0.05)
        assert params.Dp > 0

    def test_dp_scales_with_mass(self) -> None:
        t = np.linspace(0, 3.0, 120)
        fit = fit_damped_oscillation(t, _damped(t, np.deg2rad(20), 0.05, 10.0))
        p1 = identify_pendulum(fit, Mp=0.02)
        p2 = identify_pendulum(fit, Mp=0.04)
        # Dp = 2 zeta (Mp Lp^2/3) wn  -> linear in Mp at fixed fit.
        assert np.isclose(p2.Dp / p1.Dp, 2.0, rtol=1e-6)


class TestAggregateAcrossRuns:
    """Multi-run aggregation and quality filtering."""

    def test_aggregates_and_filters(self) -> None:
        Lp_true = 0.12
        wn = np.sqrt(3 * G / (2 * Lp_true))
        t = np.linspace(0, 3.0, 100)
        good = [_run({"t_s": t, "alpha_deg": np.rad2deg(_damped(t, np.deg2rad(15), 0.03, wn))}) for _ in range(3)]
        junk = _run({"t_s": t, "alpha_deg": np.zeros_like(t)})  # flat -> bad fit, dropped
        agg, per_run = identify_pendulum_from_runs([*good, junk], Mp=0.024)
        assert agg is not None
        assert len(per_run) == 3  # junk filtered out
        assert np.isclose(agg.Lp, Lp_true, rtol=0.05)

    def test_returns_none_when_nothing_qualifies(self) -> None:
        t = np.linspace(0, 2.0, 60)
        flat = _run({"t_s": t, "alpha_deg": np.zeros_like(t)})
        agg, per_run = identify_pendulum_from_runs([flat], Mp=0.024)
        assert agg is None and per_run == []


class TestDeadzone:
    """Dead-zone threshold from a PWM staircase."""

    def test_finds_threshold(self) -> None:
        # PWM ramps 0..40; motion only once |pwm| > 25 (the dead-zone).
        pwm = np.repeat(np.arange(0, 42, 2), 5).astype(float)
        t = np.arange(pwm.size) * 0.03
        speed = np.where(pwm > 25, (pwm - 25) * 2.0, 0.0)  # deg/s once moving
        pos = np.cumsum(speed) * 0.03
        run = _run({"t_s": t, "pwm": pwm, "theta_deg": pos})
        res = estimate_deadzone(run)
        assert 24 <= res.pwm_threshold <= 26
        assert res.pwm_moving <= 28

    def test_missing_columns_raise(self) -> None:
        run = _run({"t_s": np.arange(10.0)})
        with pytest.raises(ValueError):
            estimate_deadzone(run)
