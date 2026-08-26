#!/usr/bin/env python3
"""Sweep ke_gain via HTTP — no recompile needed."""

import time
import json
import urllib.request
import csv
import os

IP = "192.168.100.50"
ATTEMPTS = 5
DURATION = 60
PAUSE = 3
KE_VALUES = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def cmd(params: str) -> dict:
    url = f"http://{IP}/cmd?{params}"
    try:
        resp = urllib.request.urlopen(url, timeout=3)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def state() -> dict:
    try:
        resp = urllib.request.urlopen(f"http://{IP}/state", timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}


def run_attempts(ke: float, num: int) -> list[dict]:
    results = []
    ts = time.strftime("%Y%m%dT%H%M%S")
    for i in range(1, num + 1):
        cmd("r=1")
        time.sleep(0.3)
        cmd(f"ke={ke}")
        cmd("m=5")
        t0 = time.monotonic()
        max_ang = 0.0
        max_ang_t = 0.0
        lqr_transitions = 0
        spins = 0
        samples = []
        prev_mode = 5
        servo_start = state().get("servo_raw", 0)
        while time.monotonic() - t0 < DURATION:
            s = state()
            t = time.monotonic() - t0
            p = abs(s.get("pend_position_deg", 0))
            m = s.get("mode", 0)
            pwm = s.get("pwm", 0)
            if p > max_ang:
                max_ang = p
                max_ang_t = t
            if prev_mode == 5 and m == 4:
                lqr_transitions += 1
            if m == 0 and t > 5:
                # stopped unexpectedly — brownout?
                break
            prev_mode = m
            samples.append(
                {
                    "t": round(t, 3),
                    "pend": round(s.get("pend_position_deg", 0), 2),
                    "servo": round(s.get("position_deg", 0), 2),
                    "mode": m,
                    "pwm": pwm,
                    "v": round(s.get("v_bus", 0), 2),
                }
            )
            time.sleep(0.05)
        cmd("x=1")
        time.sleep(0.3)
        final = state()
        r = {
            "attempt": i,
            "ke": ke,
            "max_angle": round(max_ang, 1),
            "peak_at": round(max_ang_t, 1),
            "lqr_transitions": lqr_transitions,
            "final_pend": round(final.get("pend_position_deg", 0), 1),
            "final_servo": round(final.get("position_deg", 0), 1),
            "samples": len(samples),
            "servo_range": round(abs(final.get("position_deg", 0) - servo_start), 1),
        }
        print(f"  #{i}: max={max_ang:5.1f}° @{max_ang_t:4.1f}s LQR={lqr_transitions} servo_final={r['final_servo']}")
        results.append(r)
        # Save CSV
        csv_path = os.path.join(DATA_DIR, f"sweep_ke{ke}_{ts}_attempt{i}.csv")
        if samples:
            with open(csv_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=samples[0].keys())
                w.writeheader()
                w.writerows(samples)
        if i < num:
            time.sleep(PAUSE)
    return results


print(f"QUBE ke Sweep — {len(KE_VALUES)} values × {ATTEMPTS} attempts")
print(f"  IP: {IP}, Duration: {DURATION}s, Pause: {PAUSE}s")
print(f"  Current ke: {state().get('ke', '?')}")
print("=" * 60)

all_results = []
for ke in KE_VALUES:
    print(f"\n--- ke={ke:.2f} ---")
    cmd("x=1")
    time.sleep(0.2)
    results = run_attempts(ke, ATTEMPTS)
    all_results.extend(results)
    # Print summary for this ke
    max_angles = [r["max_angle"] for r in results]
    lqr_counts = [r["lqr_transitions"] for r in results]
    avg_max = sum(max_angles) / len(max_angles)
    catch_count = sum(1 for c in lqr_counts if c > 0)
    print(f"  Summary ke={ke:.2f}: avg_max={avg_max:.1f}° catches={catch_count}/{ATTEMPTS}")

print("\n" + "=" * 60)
print("FINAL RESULTS")
print(f"{'ke':>6} {'avg_max':>8} {'best':>8} {'catches':>8}")
print("-" * 40)
for ke in KE_VALUES:
    ke_results = [r for r in all_results if r["ke"] == ke]
    if ke_results:
        maxes = [r["max_angle"] for r in ke_results]
        catches = sum(1 for r in ke_results if r["lqr_transitions"] > 0)
        print(f"{ke:6.2f} {sum(maxes) / len(maxes):8.1f} {max(maxes):8.1f} {catches:>4}/{ATTEMPTS}")
