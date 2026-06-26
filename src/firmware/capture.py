"""Bench data-acquisition tool for QUBE system identification (Fase 1).

Drives the ESP32 over its HTTP API (same endpoints as ``mcp/esp32_qube_server.py``
and ``qube_rl/envs/qube_real.py``) and logs telemetry to the **canonical CSV
schema** that ``qube_analysis.dataset`` / ``.sysid`` consume directly, dropped
into ``experiments/<YYYY-MM-DD>_<exp>/`` (the dated path makes the loader tag the
capture as BTS7960 automatically).

Why a local script and not MCP tool calls
==========================================
System identification needs telemetry sampled as fast as the WiFi link allows
(tens of Hz).  MCP tools round-trip through the agent (seconds per call), so they
are right for *discrete* control and supervision, but cannot poll a time series.
This script runs the fast loop locally.  Workflow: the agent uses MCP to connect
and to abort if needed; this tool performs the actual timed captures.

Subcommands
-----------
* ``bench``         measure achievable poll rate + HTTP latency (run FIRST).
* ``monitor``       print live state at a human rate (debug, reusable).
* ``encoder-check`` read encoder counts / CPR / offsets (sanity, reusable).
* ``freedecay``     Exp. A -> ``Lp``, ``Dp``  (motor off; arm clamped; release pendulum).
* ``pwm-step``      Exp. B -> ``km``, ``Rm``, ``Dr`` (mode 1; arm free; PWM staircase).
* ``deadzone``      Exp. C -> dead-zone (mode 1; slow PWM ramp to motion onset).

Safety
------
Every capture runs inside :func:`motor_safe`, which ALWAYS sends the kill switch
(``/cmd?x=1``) on normal exit, exception or Ctrl-C.  Commanded PWM is clamped to
``--max-pwm`` (default 120) so a wiring/units mistake cannot drive full power.

Examples
--------
    python src/firmware/capture.py bench --ip 192.168.4.1
    python src/firmware/capture.py freedecay --ip 192.168.4.1 --reps 8 --duration 8
    python src/firmware/capture.py deadzone  --ip 192.168.4.1 --max-pwm 90
"""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import date
from pathlib import Path
from typing import Any

# --- Canonical output schema (matches qube_analysis.dataset aliases) ----------

# /state JSON field -> canonical CSV column.
_STATE_MAP: dict[str, str] = {
    "position_deg": "theta_deg",
    "pend_position_deg": "alpha_deg",
    "pend_raw_position_deg": "alpha_raw_deg",
    "pwm": "pwm",
    "mode": "mode",
    "v_bus": "v_bus",
    "i_ma": "i_ma",
}
CSV_FIELDS: tuple[str, ...] = (
    "t_s",
    "theta_deg",
    "alpha_deg",
    "alpha_raw_deg",
    "pwm",
    "mode",
    "v_bus",
    "i_ma",
)

DEFAULT_IP = "192.168.4.1"  # ESP32 SoftAP; pass --ip for the STA address.
DEFAULT_MAX_PWM = 120  # safety clamp on |PWM| for actuator experiments.


# --- HTTP client --------------------------------------------------------------


class QubeClient:
    """Thin HTTP client over the ESP32 ``/state`` and ``/cmd`` endpoints."""

    def __init__(self, ip: str = DEFAULT_IP, timeout: float = 2.0) -> None:
        import requests  # lazy: keeps the module importable without the dep

        self._session = requests.Session()
        self._base = f"http://{ip}"
        self._timeout = timeout

    def state(self) -> dict[str, Any]:
        """Return the parsed ``/state`` JSON."""
        r = self._session.get(f"{self._base}/state", timeout=self._timeout)
        r.raise_for_status()
        return r.json()

    def cmd(self, **params: Any) -> None:
        """Issue ``/cmd`` with the given query parameters."""
        r = self._session.get(f"{self._base}/cmd", params=params, timeout=self._timeout)
        r.raise_for_status()

    def set_mode(self, mode: int) -> None:
        self.cmd(m=int(mode))

    def set_pwm(self, pwm: int) -> None:
        self.cmd(p=int(pwm))

    def stop(self) -> None:
        """Kill switch (``/cmd?x=1``)."""
        self.cmd(x=1)


@contextmanager
def motor_safe(client: Any) -> Iterator[None]:
    """Guarantee the motor is stopped on any exit (normal, error, Ctrl-C)."""
    try:
        yield
    finally:
        with suppress(Exception):
            client.stop()


# --- Pure helpers (unit-tested without hardware) ------------------------------


def clamp_pwm(pwm: int, max_pwm: int) -> int:
    """Clamp a PWM command to +/- ``max_pwm``."""
    return int(max(-max_pwm, min(max_pwm, pwm)))


def row_from_state(state: dict[str, Any], t_s: float) -> dict[str, Any]:
    """Project a ``/state`` JSON dict onto the canonical CSV row."""
    row: dict[str, Any] = {"t_s": round(t_s, 4)}
    for src, dst in _STATE_MAP.items():
        if src in state:
            row[dst] = state[src]
    return row


def staircase(levels: list[int], dwell: float, signs: tuple[int, ...] = (1, -1)) -> list[tuple[float, int]]:
    """Build a ``[(hold_s, pwm), ...]`` plan visiting each signed level.

    A 0-PWM settling step precedes every level so the analysis has a clean rest
    reference and the arm decelerates between levels.
    """
    plan: list[tuple[float, int]] = []
    for sign in signs:
        for lvl in levels:
            plan.append((dwell, 0))
            plan.append((dwell, sign * abs(lvl)))
    plan.append((dwell, 0))
    return plan


def deadzone_ramp(step: int, dwell: float, max_pwm: int, sign: int = 1) -> list[tuple[float, int]]:
    """Build a slow ``[(dwell, pwm), ...]`` ramp from 0 to ``sign*max_pwm``."""
    return [(dwell, sign * p) for p in range(0, max_pwm + 1, step)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write canonical-schema rows to ``path`` (creating parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    return path


def session_dir(exp: str, today: date) -> Path:
    """Return ``experiments/<date>_<exp>`` for a capture session."""
    root = Path(__file__).resolve().parent.parent.parent / "experiments"
    return root / f"{today.isoformat()}_{exp}"


# --- Timed capture primitives -------------------------------------------------


def poll(client: Any, duration: float, *, on_tick: Callable[[dict], None] | None = None) -> list[dict[str, Any]]:
    """Poll ``/state`` as fast as the link allows for ``duration`` seconds."""
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    while True:
        t = time.perf_counter() - t0
        if t >= duration:
            break
        try:
            st = client.state()
        except Exception:
            continue
        rows.append(row_from_state(st, t))
        if on_tick is not None:
            on_tick(st)
    return rows


def run_schedule(client: Any, plan: list[tuple[float, int]], *, max_pwm: int) -> list[dict[str, Any]]:
    """Drive mode-1 PWM through ``plan`` while logging, then stop.

    Each ``(hold, pwm)`` segment commands the (clamped) PWM and polls for
    ``hold`` seconds; timestamps are continuous across the whole plan.
    """
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    with motor_safe(client):
        client.set_mode(1)
        for hold, pwm in plan:
            client.set_pwm(clamp_pwm(pwm, max_pwm))
            seg_end = time.perf_counter() + hold
            while time.perf_counter() < seg_end:
                try:
                    st = client.state()
                except Exception:
                    continue
                rows.append(row_from_state(st, time.perf_counter() - t0))
    return rows


def _countdown(lead: float, message: str) -> None:
    """Print ``message`` then count down ``lead`` whole seconds."""
    print(message)
    for k in range(int(lead), 0, -1):
        print(f"  {k}...", flush=True)
        time.sleep(1.0)
    print("  CAPTURING", flush=True)


# --- Experiment routines ------------------------------------------------------


def cmd_bench(client: QubeClient, args: argparse.Namespace) -> None:
    """Measure the real poll-rate ceiling and per-request latency."""
    n, t0 = 0, time.perf_counter()
    lat: list[float] = []
    while time.perf_counter() - t0 < args.duration:
        a = time.perf_counter()
        try:
            client.state()
        except Exception as e:
            print(f"  poll error: {e}")
            continue
        lat.append(time.perf_counter() - a)
        n += 1
    elapsed = time.perf_counter() - t0
    lat.sort()
    p50 = lat[len(lat) // 2] * 1e3 if lat else float("nan")
    p95 = lat[int(len(lat) * 0.95)] * 1e3 if lat else float("nan")
    print(f"\nPolled {n} samples in {elapsed:.1f}s -> {n / elapsed:.1f} Hz")
    print(f"HTTP latency: p50={p50:.1f} ms  p95={p95:.1f} ms")
    print("Use this rate when judging whether on-device buffering is needed (>100 Hz).")


def cmd_monitor(client: QubeClient, args: argparse.Namespace) -> None:
    """Print live state at ~4 Hz (debug)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < args.duration:
        try:
            s = client.state()
            print(
                f"  mode={s.get('mode')} pwm={s.get('pwm'):>+4} "
                f"theta={s.get('position_deg', 0):>7.1f} alpha={s.get('pend_position_deg', 0):>7.1f} "
                f"V={s.get('v_bus', 0):.2f} I={s.get('i_ma', 0):.0f}mA"
            )
        except Exception as e:
            print(f"  no response: {e}")
        time.sleep(0.25)


def cmd_encoder_check(client: QubeClient, _args: argparse.Namespace) -> None:
    """One-shot encoder/INA sanity dump."""
    s = client.state()
    keys = [
        "count",
        "counts_per_rev",
        "raw_position_deg",
        "position_deg",
        "offset_deg",
        "pend_count",
        "pend_raw_position_deg",
        "pend_position_deg",
        "pend_offset_deg",
        "ina_ok",
        "v_bus",
        "i_ma",
    ]
    print("Encoder / INA snapshot:")
    for k in keys:
        if k in s:
            print(f"  {k:24s} = {s[k]}")


def cmd_freedecay(client: QubeClient, args: argparse.Namespace) -> None:
    """Exp. A: pendulum free-decay -> Lp, Dp. Arm must be clamped."""
    outdir = session_dir("freedecay", date.today())
    print(f"Free-decay capture -> {outdir}")
    print("CLAMP THE ARM so theta cannot move (fixed-base assumption).\n")
    with motor_safe(client):
        client.set_mode(0)
        client.stop()
        for rep in range(1, args.reps + 1):
            _countdown(args.lead, f"Rep {rep}/{args.reps}: lift pendulum ~{args.angle:.0f} deg and release on 0")
            rows = poll(client, args.duration)
            p = write_csv(outdir / f"freedecay_{rep:02d}.csv", rows)
            rate = (len(rows) / args.duration) if args.duration else 0.0
            print(f"  saved {p.name}: {len(rows)} samples (~{rate:.0f} Hz)\n")


def cmd_pwm_step(client: QubeClient, args: argparse.Namespace) -> None:
    """Exp. B: PWM staircase, arm free -> km, Rm, Dr."""
    outdir = session_dir("pwm_step", date.today())
    print(f"PWM-step capture -> {outdir}")
    print("Arm FREE, pendulum removed/fixed. Keep the work area clear.\n")
    plan = staircase(args.levels, args.settle)
    for rep in range(1, args.reps + 1):
        rows = run_schedule(client, plan, max_pwm=args.max_pwm)
        p = write_csv(outdir / f"pwm_step_{rep:02d}.csv", rows)
        print(f"  saved {p.name}: {len(rows)} samples")


def cmd_deadzone(client: QubeClient, args: argparse.Namespace) -> None:
    """Exp. C: slow PWM ramp -> dead-zone threshold."""
    outdir = session_dir("deadzone", date.today())
    print(f"Dead-zone capture -> {outdir}")
    print("Arm FREE, pendulum removed/fixed.\n")
    for rep in range(1, args.reps + 1):
        plan = deadzone_ramp(args.step, args.dwell, args.max_pwm, sign=1) + deadzone_ramp(
            args.step, args.dwell, args.max_pwm, sign=-1
        )
        rows = run_schedule(client, plan, max_pwm=args.max_pwm)
        p = write_csv(outdir / f"deadzone_{rep:02d}.csv", rows)
        print(f"  saved {p.name}: {len(rows)} samples")


# --- CLI ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # Shared connection/safety options, accepted after the subcommand so that
    # e.g. `capture.py bench --ip 192.168.100.50` works.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ip", default=DEFAULT_IP, help=f"ESP32 IP (default {DEFAULT_IP})")
    common.add_argument("--timeout", type=float, default=2.0, help="HTTP timeout [s]")
    common.add_argument("--max-pwm", type=int, default=DEFAULT_MAX_PWM, help="Safety clamp on |PWM|")

    p = argparse.ArgumentParser(description="QUBE bench capture for system identification (Fase 1).")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bench", parents=[common], help="measure poll rate + latency")
    b.add_argument("--duration", type=float, default=5.0)
    b.set_defaults(func=cmd_bench)

    m = sub.add_parser("monitor", parents=[common], help="print live state")
    m.add_argument("--duration", type=float, default=20.0)
    m.set_defaults(func=cmd_monitor)

    e = sub.add_parser("encoder-check", parents=[common], help="encoder/INA sanity dump")
    e.set_defaults(func=cmd_encoder_check)

    f = sub.add_parser("freedecay", parents=[common], help="Exp. A -> Lp, Dp")
    f.add_argument("--reps", type=int, default=8)
    f.add_argument("--duration", type=float, default=8.0)
    f.add_argument("--lead", type=float, default=3.0, help="countdown seconds before each rep")
    f.add_argument("--angle", type=float, default=40.0, help="release angle hint [deg]")
    f.set_defaults(func=cmd_freedecay)

    s = sub.add_parser("pwm-step", parents=[common], help="Exp. B -> km, Rm, Dr")
    s.add_argument("--levels", type=int, nargs="+", default=[40, 80, 120, 160])
    s.add_argument("--settle", type=float, default=2.0, help="hold per level [s]")
    s.add_argument("--reps", type=int, default=3)
    s.set_defaults(func=cmd_pwm_step)

    d = sub.add_parser("deadzone", parents=[common], help="Exp. C -> dead-zone")
    d.add_argument("--step", type=int, default=2, help="PWM increment")
    d.add_argument("--dwell", type=float, default=0.3, help="hold per step [s]")
    d.add_argument("--reps", type=int, default=3)
    d.set_defaults(func=cmd_deadzone)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    client = QubeClient(ip=args.ip, timeout=args.timeout)
    try:
        client.state()  # fail fast if the ESP32 is unreachable
    except Exception as e:
        raise SystemExit(f"Cannot reach ESP32 at {args.ip}: {e}") from e
    args.func(client, args)


if __name__ == "__main__":
    main()
