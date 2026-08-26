"""Analyze PID test CSVs — computes step response metrics.

Metrics:
  - Rise time (10%→90% of step)
  - Settling time (within ±2% of setpoint)
  - Overshoot %
  - Steady-state error
  - PWM utilization

Usage:
    python experiments/2026-06-04_pid_tuning/analyze_pid.py data/servo_pid_*.csv
    python experiments/2026-06-04_pid_tuning/analyze_pid.py data/pend_pid_*.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def find_steps(
    setpoints: list[float],
    _times: list[int],
    tolerance: float = 0.5,
) -> list[dict]:
    """Find step transitions in the setpoint column.

    Returns list of dicts with keys: start_idx, end_idx, from_sp, to_sp, step_size.
    """
    steps = []
    i = 0
    while i < len(setpoints):
        # Find where setpoint changes
        current_sp = setpoints[i]
        j = i + 1
        while j < len(setpoints) and abs(setpoints[j] - current_sp) < tolerance:
            j += 1
        if j < len(setpoints):
            new_sp = setpoints[j]
            steps.append(
                {
                    "start_idx": j,
                    "from_sp": current_sp,
                    "to_sp": new_sp,
                    "step_size": new_sp - current_sp,
                }
            )
            i = j
        else:
            break
    return steps


def analyze_step_response(
    times: list[int],
    positions: list[float],
    setpoints: list[float],
    pwms: list[int],
    step: dict,
    settle_tolerance_pct: float = 2.0,
) -> dict | None:
    """Analyze one step response.

    Returns metrics dict or None if not enough data.
    """
    start = step["start_idx"]
    target = step["to_sp"]
    step_size = step["step_size"]

    if abs(step_size) < 0.1:
        return None

    # Extract the window after the step (up to next step or end)
    end = len(times)
    # Find next step
    for s2 in find_steps(setpoints[start:], times[start:], tolerance=0.5):
        end = start + s2["start_idx"]
        break

    window_pos = positions[start:end]
    window_t = times[start:end]
    window_pwm = pwms[start:end]

    if len(window_pos) < 5:
        return None

    # Compute metrics
    result = {
        "from_sp": step["from_sp"],
        "to_sp": target,
        "step_size": step_size,
        "n_samples": len(window_pos),
    }

    # Steady-state: average of last 20% of window
    n_ss = max(3, len(window_pos) // 5)
    ss_avg = sum(window_pos[-n_ss:]) / n_ss
    result["steady_state"] = ss_avg
    result["ss_error"] = target - ss_avg

    # Overshoot
    if step_size > 0:
        peak = max(window_pos)
        overshoot_pct = (peak - target) / abs(step_size) * 100 if abs(step_size) > 0 else 0
    else:
        peak = min(window_pos)
        overshoot_pct = (target - peak) / abs(step_size) * 100 if abs(step_size) > 0 else 0
    result["peak"] = peak
    result["overshoot_pct"] = max(0, overshoot_pct)

    # Rise time: time from 10% to 90% of step
    ten_pct = step["from_sp"] + 0.1 * step_size
    ninety_pct = step["from_sp"] + 0.9 * step_size
    t_10 = None
    t_90 = None
    for idx, pos in enumerate(window_pos):
        if t_10 is None and ((step_size > 0 and pos >= ten_pct) or (step_size < 0 and pos <= ten_pct)):
            t_10 = window_t[idx]
        if t_90 is None and ((step_size > 0 and pos >= ninety_pct) or (step_size < 0 and pos <= ninety_pct)):
            t_90 = window_t[idx]

    if t_10 is not None and t_90 is not None:
        result["rise_time_ms"] = t_90 - t_10
    else:
        result["rise_time_ms"] = None

    # Settling time: first time within ±tolerance% and stays there
    settle_band = abs(step_size) * settle_tolerance_pct / 100.0
    settle_time = None
    for idx in range(len(window_pos) - 1, -1, -1):
        if abs(window_pos[idx] - target) > settle_band:
            if idx + 1 < len(window_pos):
                settle_time = window_t[idx + 1] - window_t[0]
            break
    if settle_time is None and abs(window_pos[0] - target) <= settle_band:
        settle_time = 0
    result["settling_time_ms"] = settle_time

    # Average PWM during response
    avg_pwm = sum(abs(p) for p in window_pwm) / len(window_pwm) if window_pwm else 0
    result["avg_abs_pwm"] = avg_pwm

    return result


def analyze_csv(csv_path: Path, mode: str) -> None:
    """Analyze a PID test CSV."""
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"  Empty CSV: {csv_path}")
        return

    print(f"\n{'=' * 60}")
    print(f"ANALYSIS: {csv_path.name}")
    print(f"{'=' * 60}")
    print(f"  Samples: {len(rows)}")

    times = [int(r["t_ms"]) for r in rows]
    pwms = [int(r["pwm"]) for r in rows]

    if mode == "servo":
        positions = [float(r["servo_deg"]) for r in rows]
        setpoints = [float(r["setpoint_deg"]) for r in rows]
    else:
        positions = [float(r["pend_deg"]) for r in rows]
        setpoints = [float(r["pend_setpoint_deg"]) for r in rows]

    # Duration
    dur_s = (times[-1] - times[0]) / 1000.0
    print(f"  Duration: {dur_s:.1f}s")

    # Find and analyze steps
    steps = find_steps(setpoints, times)
    if not steps:
        print("  No step transitions found.")
        return

    print(f"  Steps found: {len(steps)}")
    print()

    # Table header
    print(
        f"  {'Step':>12} | {'Rise(ms)':>10} | {'Settle(ms)':>11} | {'Overshoot':>10} | {'SS Error':>10} | {'Avg PWM':>8}"
    )
    print(f"  {'-' * 12}-+-{'-' * 10}-+-{'-' * 11}-+-{'-' * 10}-+-{'-' * 10}-+-{'-' * 8}")

    total_overshoot = 0.0
    total_ss_error = 0.0
    n_valid = 0

    for step in steps:
        metrics = analyze_step_response(times, positions, setpoints, pwms, step)
        if metrics is None:
            print(f"  {step['from_sp']:>6.1f}→{step['to_sp']:<5.1f} | {'(insufficient data)':>30}")
            continue

        n_valid += 1
        total_overshoot += metrics["overshoot_pct"]
        total_ss_error += abs(metrics["ss_error"])

        rise = f"{metrics['rise_time_ms']}" if metrics["rise_time_ms"] is not None else "N/A"
        settle = f"{metrics['settling_time_ms']}" if metrics["settling_time_ms"] is not None else "N/A"

        print(
            f"  {step['from_sp']:>6.1f}->{step['to_sp']:<5.1f} | "
            f"{rise:>10} | "
            f"{settle:>11} | "
            f"{metrics['overshoot_pct']:>9.1f}% | "
            f"{metrics['ss_error']:>+10.2f} deg | "
            f"{metrics['avg_abs_pwm']:>8.1f}"
        )

    if n_valid > 0:
        print()
        avg_overshoot = total_overshoot / n_valid
        avg_ss_error = total_ss_error / n_valid
        print(f"  Avg overshoot:  {avg_overshoot:.1f}%")
        print(f"  Avg |SS error|: {avg_ss_error:.2f}°")

        # Quality assessment
        print()
        if avg_overshoot < 5 and avg_ss_error < 1.0:
            print("  ASSESSMENT: EXCELLENT — low overshoot, tight tracking")
        elif avg_overshoot < 15 and avg_ss_error < 2.0:
            print("  ASSESSMENT: GOOD — acceptable overshoot, decent tracking")
        elif avg_overshoot < 30 and avg_ss_error < 5.0:
            print("  ASSESSMENT: FAIR — moderate overshoot, consider reducing Kp or increasing Kd")
        else:
            print("  ASSESSMENT: POOR — high overshoot or large SS error, PID needs tuning")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_pid.py <csv_file> [csv_file ...]")
        return

    for path_str in sys.argv[1:]:
        csv_path = Path(path_str)
        if not csv_path.exists():
            print(f"  Not found: {csv_path}")
            continue

        # Detect mode from filename
        if "servo" in csv_path.name:
            mode = "servo"
        elif "pend" in csv_path.name:
            mode = "pendulum"
        else:
            # Try to detect from header
            with open(csv_path, newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            mode = "servo" if "servo_deg" in header else "pendulum"

        analyze_csv(csv_path, mode)


if __name__ == "__main__":
    main()
