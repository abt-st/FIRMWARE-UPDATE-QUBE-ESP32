"""
sweep_swingup.py — Sweep swingupPwmMax to find the sweet spot.

For each sp value, runs N attempts of 30s each, measures:
- Catch rate (% of attempts that reach LQR)
- Time to catch
- Max angle achieved
- Final stability (stays in LQR)
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


IP = "192.168.100.50"
DURATION = 30        # seconds per attempt
POLL_HZ = 20        # HTTP poll rate
ATTEMPTS_PER_SP = 5 # attempts per sp value
SP_VALUES = [45, 50, 55, 60, 65]
PAUSE_BETWEEN = 3   # seconds between attempts
PAUSE_BETWEEN_SP = 5  # seconds between sp values

OUT_DIR = Path(__file__).parent / "data" / f"sweep_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def cmd(param: str) -> dict:
    r = requests.get(f"http://{IP}/cmd?{param}", timeout=3)
    return r.json()


def state() -> dict:
    r = requests.get(f"http://{IP}/state", timeout=3)
    return r.json()


def reset() -> None:
    cmd("r=1")
    time.sleep(0.3)


def run_attempt(sp: int, attempt: int, csvfile) -> dict:
    max_angle = 0.0
    reset()
    time.sleep(0.5)

    # Set sp and activate mode 5
    cmd(f"sp={sp}")
    time.sleep(0.1)
    cmd("m=5")
    time.sleep(0.1)

    t0 = time.time()
    samples = 0
    max_angle = 0.0
    max_angle_time = 0.0
    lqr_catch_time = None
    spin_events = 0
    lqr_transitions = 0
    prev_pend = 0.0

    while (time.time() - t0) < DURATION:
        try:
            s = state()
        except Exception:
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
            lqr_transitions += 1

        # Detect spin
        if abs(pend - prev_pend) > 200:
            spin_events += 1
        prev_pend = pend

        # Log sample
        csvfile.writerow([sp, attempt, f"{t:.3f}", f"{servo:.2f}", f"{pend:.2f}",
                          mode, pwm, f"{v_bus:.3f}"])

        time.sleep(1.0 / POLL_HZ)

    # Final state
    final = state()

    # Stop motor
    cmd("x=1")
    time.sleep(0.3)

    return {
        "sp": sp,
        "attempt": attempt,
        "max_angle": max_angle,
        "max_angle_time": max_angle_time,
        "lqr_catch_time": lqr_catch_time,
        "lqr_transitions": lqr_transitions,
        "spin_events": spin_events,
        "final_pend": final["pend_position_deg"],
        "final_servo": final["position_deg"],
        "final_mode": final["mode"],
        "stayed_in_lqr": final["mode"] == 4 and lqr_catch_time is not None,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "sweep_data.csv"
    summary_path = OUT_DIR / "summary.txt"

    print(f"=== Swing-Up PWM Sweep ===")
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
    except Exception as e:
        print(f"ERROR: Cannot reach ESP32 at {IP}: {e}")
        sys.exit(1)

    # CSV for all samples
    csv_file = open(csv_path, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(["sp", "attempt", "t", "servo_deg", "pend_deg", "mode", "pwm", "v_bus"])

    results = []

    for sp in SP_VALUES:
        print(f"\n--- sp={sp} ---")
        sp_results = []

        for i in range(1, ATTEMPTS_PER_SP + 1):
            print(f"  Attempt {i}/{ATTEMPTS_PER_SP}...", end=" ", flush=True)
            r = run_attempt(sp, i, writer)
            sp_results.append(r)

            # Print result
            status = "CATCH" if r["stayed_in_lqr"] else ("TRANS" if r["lqr_catch_time"] else "MISS")
            catch_str = f"t={r['lqr_catch_time']:.1f}s" if r["lqr_catch_time"] else "---"
            print(f"{status} max={r['max_angle']:.0f}° catch={catch_str} spins={r['spin_events']}")

            time.sleep(PAUSE_BETWEEN)

        results.extend(sp_results)

        # SP summary
        catches = sum(1 for r in sp_results if r["stayed_in_lqr"])
        transients = sum(1 for r in sp_results if r["lqr_catch_time"] is not None and not r["stayed_in_lqr"])
        misses = ATTEMPTS_PER_SP - catches - transients
        avg_max = sum(r["max_angle"] for r in sp_results) / len(sp_results)
        avg_catch = (sum(r["lqr_catch_time"] for r in sp_results if r["lqr_catch_time"]) / max(1, catches + transients))

        print(f"  Summary: {catches} catch, {transients} transient, {misses} miss | avg_max={avg_max:.0f}° avg_catch={avg_catch:.1f}s")

        time.sleep(PAUSE_BETWEEN_SP)

    csv_file.close()

    # Write summary
    with open(summary_path, "w") as f:
        f.write("=== Swing-Up PWM Sweep Results ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Duration: {DURATION}s per attempt, {ATTEMPTS_PER_SP} attempts per SP\n\n")

        f.write(f"{'SP':>4} | {'Catch':>5} | {'Trans':>5} | {'Miss':>4} | {'Rate':>5} | {'AvgMax':>7} | {'AvgCatch':>8} | {'AvgSpins':>8}\n")
        f.write("-" * 70 + "\n")

        best_sp = None
        best_rate = 0

        for sp in SP_VALUES:
            sp_results = [r for r in results if r["sp"] == sp]
            catches = sum(1 for r in sp_results if r["stayed_in_lqr"])
            transients = sum(1 for r in sp_results if r["lqr_catch_time"] is not None and not r["stayed_in_lqr"])
            misses = ATTEMPTS_PER_SP - catches - transients
            rate = catches / ATTEMPTS_PER_SP * 100
            avg_max = sum(r["max_angle"] for r in sp_results) / len(sp_results)
            catch_times = [r["lqr_catch_time"] for r in sp_results if r["lqr_catch_time"]]
            avg_catch = sum(catch_times) / max(1, len(catch_times))
            avg_spins = sum(r["spin_events"] for r in sp_results) / len(sp_results)

            f.write(f"{sp:>4} | {catches:>5} | {transients:>5} | {misses:>4} | {rate:>4.0f}% | {avg_max:>6.0f}° | {avg_catch:>7.1f}s | {avg_spins:>7.1f}\n")

            if rate > best_rate or (rate == best_rate and avg_catch < 10):
                best_rate = rate
                best_sp = sp

        f.write(f"\nSweet spot: sp={best_sp} ({best_rate:.0f}% catch rate)\n")

    print(f"\n{'='*60}")
    print(f"Results saved to: {OUT_DIR}")
    with open(summary_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()
