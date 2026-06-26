"""Tests for the bench capture toolkit (src/firmware/capture.py).

Hardware I/O is not exercised; the tests cover the pure logic (schedules, PWM
clamp, state->row mapping), the safety guard, the command sequencing against a
fake client, and the round-trip of a written CSV back through the real
``qube_analysis.dataset`` loader (proving the canonical schema is loadable).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# capture.py lives next to the firmware, not in an importable package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "firmware"))

import capture

from qube_analysis.dataset import load_run


class FakeClient:
    """Records every command; returns a fixed /state dict."""

    def __init__(self, state: dict | None = None, fail_stop: bool = False) -> None:
        self._state = state or {
            "position_deg": 12.0,
            "pend_position_deg": -3.0,
            "pend_raw_position_deg": 177.0,
            "pwm": 0,
            "mode": 1,
            "v_bus": 14.8,
            "i_ma": 50.0,
        }
        self.modes: list[int] = []
        self.pwms: list[int] = []
        self.stops = 0
        self._fail_stop = fail_stop

    def state(self) -> dict:
        return dict(self._state)

    def set_mode(self, m: int) -> None:
        self.modes.append(int(m))

    def set_pwm(self, p: int) -> None:
        self.pwms.append(int(p))

    def stop(self) -> None:
        self.stops += 1
        if self._fail_stop:
            raise RuntimeError("stop failed")


class TestPureHelpers:
    def test_clamp_pwm(self) -> None:
        assert capture.clamp_pwm(300, 120) == 120
        assert capture.clamp_pwm(-300, 120) == -120
        assert capture.clamp_pwm(50, 120) == 50

    def test_row_from_state_maps_canonical(self) -> None:
        row = capture.row_from_state({"position_deg": 10.0, "pend_position_deg": 2.0, "pwm": 5}, 1.234567)
        assert row["t_s"] == 1.2346
        assert row["theta_deg"] == 10.0 and row["alpha_deg"] == 2.0 and row["pwm"] == 5
        assert "v_bus" not in row  # absent source field is not invented

    def test_staircase_visits_both_signs_with_rest(self) -> None:
        plan = capture.staircase([40, 80], dwell=1.0)
        pwms = [p for _, p in plan]
        assert 40 in pwms and -80 in pwms
        assert pwms.count(0) >= 4  # a rest step before each level + trailing
        assert all(h == 1.0 for h, _ in plan)

    def test_deadzone_ramp_monotonic(self) -> None:
        plan = capture.deadzone_ramp(step=10, dwell=0.3, max_pwm=50, sign=1)
        assert [p for _, p in plan] == [0, 10, 20, 30, 40, 50]
        neg = capture.deadzone_ramp(step=25, dwell=0.3, max_pwm=50, sign=-1)
        assert [p for _, p in neg] == [0, -25, -50]


class TestSafetyGuard:
    def test_motor_safe_stops_on_success(self) -> None:
        c = FakeClient()
        with capture.motor_safe(c):
            pass
        assert c.stops == 1

    def test_motor_safe_stops_on_exception(self) -> None:
        c = FakeClient()
        with pytest.raises(ValueError), capture.motor_safe(c):
            raise ValueError("boom")
        assert c.stops == 1  # stopped despite the error

    def test_motor_safe_swallows_failed_stop(self) -> None:
        c = FakeClient(fail_stop=True)
        with capture.motor_safe(c):  # must not raise from the failing stop
            pass
        assert c.stops == 1


class TestRunSchedule:
    def test_commands_mode_clamps_and_stops(self) -> None:
        c = FakeClient()
        plan = [(0.0, 40), (0.0, 300), (0.0, -300)]  # 0 hold => no polling, just commands
        capture.run_schedule(c, plan, max_pwm=120)
        assert c.modes == [1]
        assert c.pwms == [40, 120, -120]  # clamped to +/-max_pwm
        assert c.stops == 1  # guard fired


class TestCsvRoundTrip:
    def test_written_csv_loads_through_dataset(self, tmp_path: Path) -> None:
        rows = [
            capture.row_from_state(
                {
                    "position_deg": float(i),
                    "pend_position_deg": float(2 * i),
                    "pwm": 0,
                    "mode": 0,
                    "v_bus": 14.8,
                    "i_ma": 40.0,
                },
                t_s=i * 0.03,
            )
            for i in range(40)
        ]
        # Dated path so infer_driver tags it BTS7960.
        out = capture.write_csv(tmp_path / "2026-06-20_freedecay" / "freedecay_01.csv", rows)
        (run,) = load_run(out)
        assert run.driver == "BTS7960"
        assert "theta_deg" in run.data and "alpha_deg" in run.data
        assert run.data["theta_deg"][3] == 3.0 and run.data["alpha_deg"][3] == 6.0
        assert run.n == 40
