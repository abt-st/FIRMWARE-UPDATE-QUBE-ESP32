"""Normalising loader for QUBE experimental CSV captures.

The hardware was logged across ~12 sessions with **8 different column schemas**,
mixed delimiters (``,`` vs ``;``), inconsistent time units (relative seconds,
uptime seconds, Unix-epoch seconds, milliseconds) and several aborted/empty
files (see ``experiments/CATALOGO_DATOS.md``).  This module reads any of those
variants and returns a single canonical representation so downstream code
(system identification in Fase 1, plotting, metrics) never has to special-case
a session.

Canonical signals (all optional except ``t_s``; only those present in the
source file are populated), stored as float ``numpy`` arrays in :attr:`QubeRun.data`:

==================  ===========================================================
``t_s``             time, **zero-based per run**, seconds (monotonic)
``theta_deg``       rotary-arm / servo angle [deg]
``alpha_deg``       pendulum angle [deg]
``alpha_raw_deg``   pendulum angle without zero offset [deg]
``theta_count``     raw servo encoder count (X4)
``alpha_count``     raw pendulum encoder count (X4)
``pwm``             applied PWM command [-255, 255]
``setpoint_deg``    control setpoint [deg]
``error_deg``       control error [deg]
``mode``            firmware control mode (0..6)
``v_bus``           bus voltage [V] (INA219)
``i_ma``            current [mA] (INA219)
``p_mw``            power [mW] (INA219)
==================  ===========================================================

A key Fase-1 concern is *which motor driver* produced a capture: the project
migrated L298N -> BTS7960 on 2026-06-08, so actuator parameters must only be
identified from BTS7960 data.  :attr:`QubeRun.driver` is inferred from the
capture date in the path.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

# Motor driver migration: captures on/after this date used the BTS7960, before
# it the L298N.  See experiments/CATALOGO_DATOS.md (commit 78b4e7e).
DRIVER_MIGRATION_DATE = date(2026, 6, 8)

# Files with fewer than this many data rows are treated as aborted captures.
DEFAULT_MIN_ROWS = 30

# Map every raw column name seen across the sessions to a canonical signal.
# Lower-cased keys; the loader lower-cases headers before lookup.
_ALIASES: dict[str, str] = {
    # time
    "t": "t_s", "t_s": "t_s", "time_s": "t_s", "t_ms": "t_s",
    # rotary arm / servo angle (identity entries keep the canonical schema
    # written by experiments/capture.py loadable without translation)
    "theta_deg": "theta_deg", "position_deg": "theta_deg", "servo_deg": "theta_deg",
    "servo_pos": "theta_deg", "servo": "theta_deg",
    # pendulum angle
    "alpha_deg": "alpha_deg", "pend_deg": "alpha_deg", "pend_position_deg": "alpha_deg",
    "pend_pos": "alpha_deg", "pend": "alpha_deg",
    "alpha_raw_deg": "alpha_raw_deg", "pend_raw_deg": "alpha_raw_deg",
    # raw encoder counts
    "theta_count": "theta_count", "servo_count": "theta_count",
    "alpha_count": "alpha_count", "pend_count": "alpha_count",
    # actuator command
    "pwm": "pwm",
    # setpoint / error
    "setpoint_deg": "setpoint_deg", "servo_sp": "setpoint_deg",
    "pend_sp": "setpoint_deg", "sp": "setpoint_deg",
    "error_deg": "error_deg", "servo_err": "error_deg",
    # firmware mode / metadata
    "mode": "mode", "attempt": "attempt", "gain_mode": "gain_mode",
    "ina_ok": "ina_ok",
    # INA219 power telemetry
    "voltage_v": "v_bus", "v_bus": "v_bus", "v": "v_bus",
    "current_ma": "i_ma", "i_ma": "i_ma",
    "power_mw": "p_mw", "p_mw": "p_mw",
}

# Raw header names whose values are in milliseconds (converted to seconds).
_MILLISECOND_COLUMNS = frozenset({"t_ms"})

# Columns used only to split concatenated multi-attempt files, not emitted as data.
_SEGMENT_KEYS = ("setpoint_deg", "attempt")


@dataclass
class QubeRun:
    """A single normalised experimental run.

    Attributes:
        data: Canonical signal name -> float array (all the same length ``n``).
        path: Source CSV path.
        driver: ``"BTS7960"``, ``"L298N"`` or ``None`` if the date is unknown.
        capture_date: Date parsed from the path, or ``None``.
        segment: ``(setpoint, attempt)`` if this run came from a multi-attempt
            file, else ``None``.
    """

    data: dict[str, np.ndarray]
    path: Path
    driver: str | None = None
    capture_date: date | None = None
    segment: tuple[float | None, float | None] | None = None
    columns: tuple[str, ...] = field(default=())

    @property
    def n(self) -> int:
        """Number of samples."""
        return len(self.data["t_s"]) if "t_s" in self.data else 0

    @property
    def dt_median(self) -> float:
        """Median sample period [s] (NaN if fewer than 2 samples)."""
        t = self.data.get("t_s")
        if t is None or len(t) < 2:
            return float("nan")
        return float(np.median(np.diff(t)))

    @property
    def rate_hz(self) -> float:
        """Median logging rate [Hz] (NaN if undefined)."""
        dt = self.dt_median
        return float(1.0 / dt) if dt and np.isfinite(dt) and dt > 0 else float("nan")

    def __getattr__(self, name: str) -> np.ndarray:
        # Allow ``run.alpha_deg`` as sugar for ``run.data['alpha_deg']``.
        data = self.__dict__.get("data", {})
        if name in data:
            return data[name]
        raise AttributeError(name)

    def __repr__(self) -> str:
        sig = ",".join(self.columns)
        seg = f" seg={self.segment}" if self.segment else ""
        return (
            f"QubeRun({self.path.name}, n={self.n}, "
            f"{self.rate_hz:.0f}Hz, driver={self.driver}{seg}, [{sig}])"
        )


def infer_capture_date(path: Path) -> date | None:
    """Parse a ``YYYY-MM-DD`` capture date from any component of ``path``."""
    for part in path.parts:
        if len(part) >= 10 and part[4] == "-" and part[7] == "-":
            try:
                return date.fromisoformat(part[:10])
            except ValueError:
                continue
    return None


def infer_driver(path: Path) -> str | None:
    """Return ``"BTS7960"``/``"L298N"``/``None`` from the capture date in ``path``."""
    d = infer_capture_date(path)
    if d is None:
        return None
    return "BTS7960" if d >= DRIVER_MIGRATION_DATE else "L298N"


def _detect_delimiter(header_line: str) -> str:
    """Pick ``;`` or ``,`` based on the header line."""
    return ";" if header_line.count(";") > header_line.count(",") else ","


def _zero_base_time(t: np.ndarray) -> np.ndarray:
    """Shift a time vector so it starts at 0 (handles uptime/epoch origins)."""
    return t - t[0] if len(t) else t


def load_run(
    path: str | Path,
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
) -> list[QubeRun]:
    """Load and normalise one CSV file.

    Returns a *list* because multi-attempt aggregate files (``sweep_data.csv``,
    ``training_data.csv``) are split into one :class:`QubeRun` per contiguous
    ``(setpoint, attempt)`` segment.  A plain single-run file yields a 1-element
    list.  Aborted/short files (or segments) shorter than ``min_rows`` are
    dropped, so the list may be empty.

    Args:
        path: CSV file to load.
        min_rows: Minimum data rows for a run/segment to be kept.

    Returns:
        List of normalised runs (possibly empty).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) < 2:
        return []

    delim = _detect_delimiter(lines[0])
    reader = csv.reader(lines, delimiter=delim)
    raw_header = next(reader)
    # Canonicalise each column; keep raw name to know which need ms->s.
    raw_names = [h.strip() for h in raw_header]
    canon = [_ALIASES.get(h.lower()) for h in raw_names]

    # Collect columns by canonical name (first occurrence wins for duplicates).
    cols: dict[str, list[float]] = {}
    col_is_ms: dict[str, bool] = {}
    col_index: dict[str, int] = {}
    for idx, name in enumerate(canon):
        if name is None or name in col_index:
            continue
        col_index[name] = idx
        cols[name] = []
        col_is_ms[name] = raw_names[idx].lower() in _MILLISECOND_COLUMNS

    if "t_s" not in col_index:
        return []  # cannot normalise without a time base

    for row in reader:
        if not row or len(row) < len(raw_names):
            continue
        for name, idx in col_index.items():
            cell = row[idx].strip()
            try:
                cols[name].append(float(cell))
            except ValueError:
                cols[name].append(np.nan)

    arrays = {name: np.asarray(v, dtype=float) for name, v in cols.items()}
    if col_is_ms.get("t_s"):
        arrays["t_s"] = arrays["t_s"] / 1000.0

    capture_date = infer_capture_date(path)
    driver = infer_driver(path)

    runs = _split_segments(arrays, path, driver, capture_date)
    return [r for r in runs if r.n >= min_rows]


def _split_segments(
    arrays: dict[str, np.ndarray],
    path: Path,
    driver: str | None,
    capture_date: date | None,
) -> list[QubeRun]:
    """Split a multi-attempt file into per-segment runs; else return one run."""
    seg_keys = [k for k in _SEGMENT_KEYS if k in arrays]
    # Only treat as multi-attempt when an explicit ``attempt`` column exists.
    if "attempt" not in arrays:
        return [_make_run(arrays, path, driver, capture_date, segment=None)]

    key_stack = np.column_stack([arrays[k] for k in seg_keys])
    # Boundaries where any segment key changes between consecutive rows.
    change = np.any(key_stack[1:] != key_stack[:-1], axis=1)
    bounds = [0, *(np.flatnonzero(change) + 1).tolist(), len(key_stack)]

    runs: list[QubeRun] = []
    for start, stop in zip(bounds[:-1], bounds[1:], strict=True):
        sl = {k: v[start:stop] for k, v in arrays.items()}
        sp = float(sl["setpoint_deg"][0]) if "setpoint_deg" in sl else None
        at = float(sl["attempt"][0]) if "attempt" in sl else None
        runs.append(_make_run(sl, path, driver, capture_date, segment=(sp, at)))
    return runs


def _make_run(
    arrays: dict[str, np.ndarray],
    path: Path,
    driver: str | None,
    capture_date: date | None,
    *,
    segment: tuple[float | None, float | None] | None,
) -> QubeRun:
    """Build a :class:`QubeRun`, zero-basing time and dropping helper columns."""
    arrays = dict(arrays)
    if "t_s" in arrays:
        arrays["t_s"] = _zero_base_time(arrays["t_s"])
    # ``attempt``/``gain_mode``/``ina_ok`` are metadata, not physical signals.
    for helper in ("attempt", "gain_mode", "ina_ok"):
        arrays.pop(helper, None)
    columns = tuple(k for k in arrays if k != "t_s")
    return QubeRun(
        data=arrays,
        path=path,
        driver=driver,
        capture_date=capture_date,
        segment=segment,
        columns=columns,
    )


def load_session(
    directory: str | Path,
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
    driver: str | None = None,
) -> list[QubeRun]:
    """Load every CSV under ``directory`` (recursively), normalised.

    Args:
        directory: Experiment folder (e.g. ``experiments/2026-06-08_swing``).
        min_rows: Minimum rows per run/segment (aborted captures are dropped).
        driver: If given (``"BTS7960"``/``"L298N"``), keep only matching runs —
            convenient for Fase 1 actuator identification.

    Returns:
        Flat list of runs across all files, sorted by path.
    """
    directory = Path(directory)
    runs: list[QubeRun] = []
    for csv_path in sorted(directory.rglob("*.csv")):
        runs.extend(load_run(csv_path, min_rows=min_rows))
    if driver is not None:
        runs = [r for r in runs if r.driver == driver]
    return runs
