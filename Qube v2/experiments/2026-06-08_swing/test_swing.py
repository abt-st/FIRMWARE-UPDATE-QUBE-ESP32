"""Swing-up training session with CSV logging and auto-analysis.

Runs multiple swing-up attempts, logs telemetry, and reports stats.

Usage:
    python experiments/2026-06-08_swing/test_swing.py [--attempts 5] [--duration 60] [--ip 192.168.100.50]
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def get_state(ip: str, timeout: float = 2.0) -> dict | None:
    """Fetch JSON state from the ESP32."""
    try:
        with urllib.request.urlopen(f"http://{ip}/state", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def send_cmd(ip: str, timeout: float = 2.0, **params: object) -> None:
    """Send a command to the ESP32."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    with contextlib.suppress(Exception):
        urllib.request.urlopen(f"http://{ip}/cmd?{qs}", timeout=timeout)


def wait_for_state(ip: str, retries: int = 5) -> dict | None:
    """Wait for the ESP32 to respond."""
    for _ in range(retries):
        s = get_state(ip)
        if s is not None:
            return s
        time.sleep(0.5)
    return None


def run_swing_up(
    ip: str,
    duration: float,
    attempt: int,
) -> tuple[list[list], dict]:
    """Run one swing-up attempt and collect telemetry.

    Returns (rows, stats) where stats has max_angle, time_to_peak,
    lqr_transitions, spin_events, final_pend_pos.
    """

    # Start swing-up (mode 5)
    send_cmd(ip, m=5)
    t_start = time.monotonic()
    rows: list[list] = []

    # Stats tracking
    max_abs_angle = 0.0
    time_to_peak = 0.0
    lqr_transitions = 0
    spin_events = 0
    prev_mode = 5
    last_pend_raw = 0.0

    while (time.monotonic() - t_start) < duration:
        d = get_state(ip)
        if d is None:
            time.sleep(0.1)
            continue

        t = time.monotonic() - t_start
        servo = d.get("position_deg", 0)
        pend = d.get("pend_position_deg", 0)
        pend_raw = d.get("pend_raw_position_deg", 0)
        pwm = d.get("pwm", 0)
        mode = d.get("mode", 0)
        v_bus = d.get("v_bus", 0)
        i_ma = d.get("i_ma", 0)
        p_mw = d.get("p_mw", 0)

        rows.append(
            [
                round(t, 3),
                round(servo, 2),
                round(pend, 2),
                round(pend_raw, 2),
                pwm,
                mode,
                round(v_bus, 3),
                round(i_ma, 2),
                round(p_mw, 2),
            ]
        )

        # Track stats
        abs_pend = abs(pend)
        if abs_pend > max_abs_angle:
            max_abs_angle = abs_pend
            time_to_peak = t

        # Detect mode transitions (swing-up → LQR)
        if mode == 4 and prev_mode == 5:
            lqr_transitions += 1
        if mode == 5 and prev_mode == 4:
            pass  # LQR → swing-up fallback
        prev_mode = mode

        # Detect spin events (raw angle accumulating)
        if abs(pend_raw) > 360 and abs(last_pend_raw) <= 360:
            spin_events += 1
        last_pend_raw = pend_raw

        time.sleep(0.05)  # 20 Hz polling

    # Stop motor
    send_cmd(ip, x=1)

    stats = {
        "attempt": attempt,
        "duration_s": round(duration, 1),
        "samples": len(rows),
        "max_abs_angle_deg": round(max_abs_angle, 1),
        "time_to_peak_s": round(time_to_peak, 2),
        "lqr_transitions": lqr_transitions,
        "spin_events": spin_events,
        "final_pend_deg": round(rows[-1][2], 1) if rows else 0,
        "final_servo_deg": round(rows[-1][1], 1) if rows else 0,
    }
    return rows, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Swing-up training session")
    parser.add_argument("--ip", default="192.168.100.50", help="ESP32 IP address")
    parser.add_argument("--attempts", type=int, default=5, help="Number of attempts")
    parser.add_argument("--duration", type=float, default=60, help="Duration per attempt in seconds")
    parser.add_argument("--pause", type=float, default=5, help="Pause between attempts in seconds")
    args = parser.parse_args()

    ip = args.ip
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    # Verify connectivity
    state = wait_for_state(ip)
    if state is None:
        print(f"ERROR: Cannot reach ESP32 at {ip}")
        return

    print("QUBE Swing-Up Training Session")
    print(f"{'=' * 60}")
    print(f"  IP: {ip}")
    print(f"  Attempts: {args.attempts}")
    print(f"  Duration: {args.duration}s per attempt")
    print(f"  Pause: {args.pause}s between attempts")
    print(f"  Bus voltage: {state.get('v_bus', '?')}V")
    print(f"  INA219: {'OK' if state.get('ina_ok') else 'NOT DETECTED'}")
    print(f"{'=' * 60}")

    all_stats: list[dict] = []

    for attempt in range(1, args.attempts + 1):
        print(f"\n--- Attempt {attempt}/{args.attempts} ---")

        # Reset encoders for clean start
        send_cmd(ip, r=1)
        time.sleep(0.5)

        # Verify reset
        s = get_state(ip)
        if s:
            print(f"  Servo: {s.get('position_deg', '?')}°  Pend: {s.get('pend_position_deg', '?')}°")

        # Run swing-up
        rows, stats = run_swing_up(ip, args.duration, attempt)
        all_stats.append(stats)

        # Save CSV
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        csv_path = data_dir / f"swing_{ts}_attempt{attempt}.csv"
        header = ["t", "servo_deg", "pend_deg", "pend_raw_deg", "pwm", "mode", "v_bus", "i_ma", "p_mw"]
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

        print(f"  Saved: {csv_path.name} ({stats['samples']} samples)")
        print(f"  Max angle: {stats['max_abs_angle_deg']}° @ {stats['time_to_peak_s']}s")
        print(f"  LQR transitions: {stats['lqr_transitions']}")
        print(f"  Spin events: {stats['spin_events']}")
        print(f"  Final pend: {stats['final_pend_deg']}°  Servo: {stats['final_servo_deg']}°")

        # Pause between attempts
        if attempt < args.attempts:
            print(f"  Pausing {args.pause}s...")
            time.sleep(args.pause)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY — {len(all_stats)} attempts")
    print(f"{'=' * 60}")
    print(f"{'#':>3} {'MaxAng':>8} {'Peak@':>7} {'LQR':>5} {'Spins':>6} {'Final':>7}")
    print(f"{'-' * 6} {'-' * 7} {'-' * 6} {'-' * 4} {'-' * 5} {'-' * 6}")
    for s in all_stats:
        print(
            f"{s['attempt']:>3} {s['max_abs_angle_deg']:>7.1f}° "
            f"{s['time_to_peak_s']:>5.1f}s "
            f"{s['lqr_transitions']:>5} "
            f"{s['spin_events']:>6} "
            f"{s['final_pend_deg']:>6.1f}°"
        )

    best = max(all_stats, key=lambda x: x["max_abs_angle_deg"])
    stable = [s for s in all_stats if s["lqr_transitions"] > 0]
    print(f"\nBest max angle: {best['max_abs_angle_deg']}° (attempt {best['attempt']})")
    print(f"Attempts with LQR catch: {len(stable)}/{len(all_stats)}")
    if stable:
        longest_lqr = max(stable, key=lambda x: x["lqr_transitions"])
        print(f"Most LQR transitions: {longest_lqr['lqr_transitions']} (attempt {longest_lqr['attempt']})")


if __name__ == "__main__":
    main()
