#!/usr/bin/env python3
"""
sweep_swingup.py — Sweep de PWM setpoint para swing-up + LQR

Prueba valores de sp para encontrar el sweet spot que maximiza el catch rate.
Basado en la sesión 2026-06-10 con firmware:
  - catch mode: gain=0.25, limit ±50
  - centering gain: 0.5
  - transiciones: >155°, vel <30°/s
"""

import contextlib
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

IP = "192.168.100.50"
DURATION = 30  # seconds per attempt
POLL_HZ = 20  # HTTP poll rate
ATTEMPTS_PER_SP = 5  # attempts per sp value
SP_VALUES = [45, 50, 55, 60, 65]
PAUSE_BETWEEN = 3  # seconds between attempts
PAUSE_BETWEEN_SP = 5  # seconds between sp values
HTTP_TIMEOUT = 3  # seconds per HTTP request
MAX_RETRIES = 3  # retries on HTTP failure

OUT_DIR = Path(__file__).parent / "data" / f"sweep_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def _http_get(url: str, retries: int = MAX_RETRIES) -> dict:
    """HTTP GET with retry logic."""
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException, ValueError:
            if attempt < retries - 1:
                time.sleep(0.2)
            else:
                raise


def cmd(param: str) -> dict:
    return _http_get(f"http://{IP}/cmd?{param}")


def state() -> dict:
    return _http_get(f"http://{IP}/state")


def reset() -> None:
    cmd("r=1")
    time.sleep(0.3)


def run_attempt(sp: int, attempt: int, csvfile) -> dict:
    """Run a single swing-up attempt and log data."""
    reset()
    time.sleep(0.5)

    # Set sp and activate mode 5 (swing-up)
    cmd(f"sp={sp}")
    time.sleep(0.1)
    cmd("m=5")
    time.sleep(0.1)

    t0 = time.time()
    max_angle = 0.0
    max_angle_time = 0.0
    lqr_catch_time = None
    spin_events = 0
    prev_pend = 0.0
    samples = 0
    errors = 0

    while (time.time() - t0) < DURATION:
        try:
            s = state()
            errors = 0  # reset on success
        except Exception:
            errors += 1
            if errors > 10:
                print(f"    [WARN] {errors} consecutive errors, aborting attempt")
                break
            time.sleep(0.1)
            continue

        t = time.time() - t0
        pend = s["pend_position_deg"]
        servo = s["position_deg"]
        mode = s["mode"]
        pwm = s["pwm"]
        v_bus = s["v_bus"]

        # Track max angle
        abs_pend = abs(pend)
        if abs_pend > max_angle:
            max_angle = abs_pend
            max_angle_time = t

        # Detect LQR transition (mode 5 -> mode 4)
        if mode == 4 and lqr_catch_time is None:
            lqr_catch_time = t

        # Detect spin (large angle jump)
        if abs(pend - prev_pend) > 200:
            spin_events += 1
        prev_pend = pend

        # Log sample
        csvfile.writerow([sp, attempt, f"{t:.3f}", f"{servo:.2f}", f"{pend:.2f}", mode, pwm, f"{v_bus:.3f}"])
        samples += 1

        time.sleep(1.0 / POLL_HZ)

    # Final state
    try:
        final = state()
    except Exception:
        final = {"pend_position_deg": 0, "position_deg": 0, "mode": -1}

    # Stop motor
    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(0.3)

    return {
        "sp": sp,
        "attempt": attempt,
        "max_angle": max_angle,
        "max_angle_time": max_angle_time,
        "lqr_catch_time": lqr_catch_time,
        "spin_events": spin_events,
        "final_pend": final["pend_position_deg"],
        "final_servo": final["position_deg"],
        "final_mode": final["mode"],
        "stayed_in_lqr": final["mode"] == 4 and lqr_catch_time is not None,
        "samples": samples,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "sweep_data.csv"
    summary_path = OUT_DIR / "summary.txt"

    print("=== Swing-Up PWM Sweep v2 ===")
    print(f"  IP: {IP}")
    print(f"  SP values: {SP_VALUES}")
    print(f"  Attempts per SP: {ATTEMPTS_PER_SP}")
    print(f"  Duration: {DURATION}s each")
    print(f"  Output: {OUT_DIR}")
    print()

    # Verify connectivity
    try:
        s = state()
        print(f"  ESP32 online: v={s['v_bus']:.1f}V mode={s['mode']}")
        if s["mode"] != 0:
            print(f"  WARNING: mode={s['mode']} (expected 0). Sending stop...")
            cmd("x=1")
            time.sleep(0.5)
    except Exception as e:
        print(f"ERROR: Cannot reach ESP32 at {IP}: {e}")
        sys.exit(1)

    # CSV for all samples
    csv_file = open(csv_path, "w", newline="")  # noqa: SIM115 — closed explicitly below
    writer = csv.writer(csv_file)
    writer.writerow(["sp", "attempt", "t", "servo_deg", "pend_deg", "mode", "pwm", "v_bus"])

    results = []

    for sp in SP_VALUES:
        print(f"\n--- sp={sp} ---")
        sp_results = []

        for i in range(1, ATTEMPTS_PER_SP + 1):
            print(f"  Attempt {i}/{ATTEMPTS_PER_SP}...", end=" ", flush=True)
            try:
                r = run_attempt(sp, i, writer)
                sp_results.append(r)

                status = "CATCH" if r["stayed_in_lqr"] else ("TRANS" if r["lqr_catch_time"] else "MISS")
                catch_str = f"t={r['lqr_catch_time']:.1f}s" if r["lqr_catch_time"] else "---"
                print(
                    f"{status} max={r['max_angle']:.0f}° catch={catch_str} spins={r['spin_events']} samples={r['samples']}"
                )
            except Exception as e:
                print(f"ERROR: {e}")
                sp_results.append(
                    {
                        "sp": sp,
                        "attempt": i,
                        "max_angle": 0,
                        "max_angle_time": 0,
                        "lqr_catch_time": None,
                        "spin_events": 0,
                        "final_pend": 0,
                        "final_servo": 0,
                        "final_mode": -1,
                        "stayed_in_lqr": False,
                        "samples": 0,
                    }
                )

            time.sleep(PAUSE_BETWEEN)

        results.extend(sp_results)

        # SP summary
        valid = [r for r in sp_results if r["samples"] > 0]
        catches = sum(1 for r in valid if r["stayed_in_lqr"])
        transients = sum(1 for r in valid if r["lqr_catch_time"] is not None and not r["stayed_in_lqr"])
        misses = len(valid) - catches - transients
        avg_max = sum(r["max_angle"] for r in valid) / max(1, len(valid))
        catch_times = [r["lqr_catch_time"] for r in valid if r["lqr_catch_time"]]
        avg_catch = sum(catch_times) / max(1, len(catch_times))

        print(
            f"  Summary: {catches} catch, {transients} transient, {misses} miss | avg_max={avg_max:.0f}° avg_catch={avg_catch:.1f}s"
        )

        time.sleep(PAUSE_BETWEEN_SP)

    csv_file.close()

    # Write summary
    with open(summary_path, "w") as f:
        f.write("=== Swing-Up PWM Sweep v2 Results ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write("Firmware: catch gain=0.25, centering=0.5, trans >155°\n")
        f.write(f"Duration: {DURATION}s per attempt, {ATTEMPTS_PER_SP} attempts per SP\n\n")

        f.write(
            f"{'SP':>4} | {'Catch':>5} | {'Trans':>5} | {'Miss':>4} | {'Rate':>5} | {'AvgMax':>7} | {'AvgCatch':>8}\n"
        )
        f.write("-" * 65 + "\n")

        best_sp = None
        best_rate = 0

        for sp in SP_VALUES:
            sp_results = [r for r in results if r["sp"] == sp and r["samples"] > 0]
            if not sp_results:
                f.write(f"{sp:>4} | {'N/A':>5} | {'N/A':>5} | {'N/A':>4} | {'N/A':>5} | {'N/A':>7} | {'N/A':>8}\n")
                continue

            catches = sum(1 for r in sp_results if r["stayed_in_lqr"])
            transients = sum(1 for r in sp_results if r["lqr_catch_time"] is not None and not r["stayed_in_lqr"])
            misses = len(sp_results) - catches - transients
            rate = catches / len(sp_results) * 100
            avg_max = sum(r["max_angle"] for r in sp_results) / len(sp_results)
            catch_times = [r["lqr_catch_time"] for r in sp_results if r["lqr_catch_time"]]
            avg_catch = sum(catch_times) / max(1, len(catch_times))

            f.write(
                f"{sp:>4} | {catches:>5} | {transients:>5} | {misses:>4} | {rate:>4.0f}% | {avg_max:>6.0f}° | {avg_catch:>7.1f}s\n"
            )

            if rate > best_rate or (rate == best_rate and avg_catch < 10):
                best_rate = rate
                best_sp = sp

        f.write(f"\nSweet spot: sp={best_sp} ({best_rate:.0f}% catch rate)\n")

    print(f"\n{'=' * 60}")
    print(f"Results saved to: {OUT_DIR}")
    with open(summary_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()
