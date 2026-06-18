"""Tests for the normalising CSV loader (qube_analysis.dataset)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from qube_analysis.dataset import (
    DRIVER_MIGRATION_DATE,
    infer_capture_date,
    infer_driver,
    load_run,
    load_session,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestDriverInference:
    """Driver/date inference from the capture path."""

    def test_before_migration_is_l298n(self) -> None:
        p = Path("experiments/2026-06-04_pid_tuning/data/x.csv")
        assert infer_capture_date(p) == date(2026, 6, 4)
        assert infer_driver(p) == "L298N"

    def test_on_migration_day_is_bts(self) -> None:
        p = Path(f"experiments/{DRIVER_MIGRATION_DATE.isoformat()}_swing/x.csv")
        assert infer_driver(p) == "BTS7960"

    def test_after_migration_is_bts(self) -> None:
        assert infer_driver(Path("experiments/2026-06-15_training/x.csv")) == "BTS7960"

    def test_unknown_date_is_none(self) -> None:
        assert infer_driver(Path("some/random/file.csv")) is None


class TestDelimiterAndAliases:
    """Delimiter detection and column canonicalisation."""

    def test_semicolon_delimiter(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-06-01_swing" / "s.csv",
            "time_s;mode;position_deg;pend_position_deg;pwm\n"
            + "\n".join(f"{i * 0.1};5;{i};{2 * i};10" for i in range(40)),
        )
        (runs,) = load_run(f)
        assert runs.columns and "theta_deg" in runs.data and "alpha_deg" in runs.data
        assert np.isclose(runs.data["theta_deg"][3], 3.0)
        assert np.isclose(runs.data["alpha_deg"][3], 6.0)

    def test_alias_variants_map_to_canonical(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-05-07_pid" / "s.csv",
            "t_s,servo_pos,current_ma,voltage_v\n"
            + "\n".join(f"{i},{i * 2},{i * 3},12.0" for i in range(40)),
        )
        (run,) = load_run(f)
        assert "theta_deg" in run.data  # servo_pos -> theta_deg
        assert "i_ma" in run.data  # current_ma -> i_ma
        assert "v_bus" in run.data  # voltage_v -> v_bus


class TestTimeNormalisation:
    """Time base conversion and zero-basing."""

    def test_milliseconds_converted_to_seconds(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-06-03_swing" / "s.csv",
            "t_ms,pwm,pend_deg\n" + "\n".join(f"{i * 100},0,{i}" for i in range(40)),
        )
        (run,) = load_run(f)
        # 100 ms steps -> 0.1 s, zero-based.
        assert np.isclose(run.data["t_s"][0], 0.0)
        assert np.isclose(run.data["t_s"][1], 0.1)
        assert np.isclose(run.dt_median, 0.1)

    def test_uptime_origin_is_zero_based(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-05-07_pid" / "s.csv",
            "t_s,pwm,position_deg\n" + "\n".join(f"{1225 + i},0,{i}" for i in range(40)),
        )
        (run,) = load_run(f)
        assert np.isclose(run.data["t_s"][0], 0.0)
        assert np.isclose(run.data["t_s"][-1], 39.0)

    def test_epoch_origin_is_zero_based(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-05-29_servo" / "s.csv",
            "t,servo_pos,pend_pos\n" + "\n".join(f"{1.78e9 + i},{i},{i}" for i in range(40)),
        )
        (run,) = load_run(f)
        assert np.isclose(run.data["t_s"][0], 0.0)
        assert run.data["t_s"][-1] > 0


class TestSegmentationAndFiltering:
    """Multi-attempt splitting and aborted-file filtering."""

    def test_multi_attempt_split_with_per_segment_zero_base(self, tmp_path: Path) -> None:
        rows = []
        for attempt in (1, 2):
            for i in range(40):
                rows.append(f"45,{attempt},{i * 0.1},{i},{i},6,0,12")
        f = _write(
            tmp_path / "2026-06-15_sweep" / "sweep_data.csv",
            "sp,attempt,t,servo_deg,pend_deg,mode,pwm,v_bus\n" + "\n".join(rows),
        )
        runs = load_run(f)
        assert len(runs) == 2
        for r in runs:
            assert np.isclose(r.data["t_s"][0], 0.0)  # each segment re-zeroed
            assert np.all(np.diff(r.data["t_s"]) >= 0)  # monotonic
            assert r.segment is not None and r.segment[0] == 45.0
        assert {r.segment[1] for r in runs} == {1.0, 2.0}
        # helper columns are not emitted as signals
        assert "attempt" not in runs[0].data

    def test_short_files_are_dropped(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "2026-06-08_swing" / "aborted.csv",
            "t,pwm,pend_deg\n" + "\n".join(f"{i * 0.1},0,{i}" for i in range(5)),
        )
        assert load_run(f, min_rows=30) == []
        assert len(load_run(f, min_rows=3)) == 1

    def test_missing_time_column_yields_nothing(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "x.csv", "pwm,pend_deg\n" + "\n".join("0,1" for _ in range(40)))
        assert load_run(f) == []


class TestSessionLoad:
    """Directory-level loading with driver filtering."""

    def test_load_session_filters_by_driver(self, tmp_path: Path) -> None:
        sess = tmp_path / "2026-06-08_swing"
        for k in range(2):
            _write(
                sess / f"run{k}.csv",
                "t,pwm,pend_deg\n" + "\n".join(f"{i * 0.1},0,{i}" for i in range(40)),
            )
        assert len(load_session(sess, driver="BTS7960")) == 2
        assert load_session(sess, driver="L298N") == []
