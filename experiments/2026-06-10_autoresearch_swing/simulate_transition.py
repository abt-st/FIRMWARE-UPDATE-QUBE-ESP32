#!/usr/bin/env python3
"""
Simulate the effect of widened transition window on existing data.

Models what WOULD have happened if the transition conditions were:
- vel < 120°/s (was 80°/s)
- peak detection dist < 40° (was 25°)
- forced transition at 150°+ (was 165°+)
"""

import os
import csv
import glob
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def simulate_csv(path, vel_threshold=120.0, peak_dist=40.0, forced_angle=150.0):
    """Simulate transition with new parameters."""
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            if "servo_deg" in headers:
                rows.append(
                    {
                        "t": float(row["t"]),
                        "servo_deg": float(row["servo_deg"]),
                        "pend_deg": float(row["pend_deg"]),
                        "pend_raw_deg": float(row["pend_raw_deg"]),
                        "pwm": int(row["pwm"]),
                        "mode": int(row["mode"]),
                        "v_bus": float(row["v_bus"]),
                    }
                )
            elif "servo" in headers:
                rows.append(
                    {
                        "t": float(row["t"]),
                        "servo_deg": float(row["servo"]),
                        "pend_deg": float(row["pend"]),
                        "pend_raw_deg": float(row["pend"]),
                        "pwm": int(row["pwm"]),
                        "mode": int(row["mode"]),
                        "v_bus": float(row["v"]),
                    }
                )
    if len(rows) < 3:
        return None

    # Find max pendulum angle
    max_pend = max(abs(r["pend_deg"]) for r in rows)

    # Check if original had a transition
    had_transition = any(rows[i - 1]["mode"] == 5 and rows[i]["mode"] == 4 for i in range(1, len(rows)))

    # Simulate new transition conditions
    prev_alpha_dot = 0.0
    simulated_transition = False
    for i in range(1, len(rows)):
        dt = rows[i]["t"] - rows[i - 1]["t"]
        if dt <= 0:
            dt = 0.001
        alpha_dot = (rows[i]["pend_deg"] - rows[i - 1]["pend_deg"]) / dt
        vel_dps = abs(alpha_dot)
        pend = abs(rows[i]["pend_deg"])

        in_upper = pend > 130.0
        nearly_stopped = vel_dps < vel_threshold
        can_transition = in_upper and nearly_stopped

        # Peak detection
        at_peak = (prev_alpha_dot > 0 and alpha_dot <= 0) or (prev_alpha_dot < 0 and alpha_dot >= 0)
        at_peak_transition = at_peak and in_upper and (180.0 - pend < peak_dist)

        forced = pend > forced_angle

        if can_transition or at_peak_transition or forced:
            dist_from_up = 180.0 - pend
            if forced or dist_from_up < peak_dist:
                simulated_transition = True
                break

        prev_alpha_dot = alpha_dot

    return {
        "max_pend": round(max_pend, 1),
        "had_transition": had_transition,
        "simulated_transition": simulated_transition,
        "would_improve": simulated_transition and not had_transition,
    }


# Run simulation
all_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))

print("=" * 90)
print("TRANSITION SIMULATION — Widened Window (vel<120, peak<40°, forced>150°)")
print("=" * 90)

results = []
for f in all_files:
    r = simulate_csv(f)
    if r:
        r["file"] = os.path.basename(f)
        results.append(r)

# Compare old vs new
old_transitions = sum(1 for r in results if r["had_transition"])
new_transitions = sum(1 for r in results if r["simulated_transition"])
improved = sum(1 for r in results if r["would_improve"])

print(f"\nTotal trials: {len(results)}")
print(f"Old transitions: {old_transitions}")
print(f"New transitions: {new_transitions}")
print(f"NEW transitions added: {improved}")

# Show which attempts would gain transitions
print(f"\n--- Attempts that WOULD NOW transition (but didn't before) ---")
for r in results:
    if r["would_improve"]:
        print(f"  {r['file'][:30]:30s} max_angle={r['max_pend']:6.1f}°")

# Show range breakdown
print(f"\n--- Range breakdown ---")
for lo, hi in [(0, 50), (50, 100), (100, 150), (150, 200), (200, 9999)]:
    subset = [r for r in results if lo <= r["max_pend"] < hi]
    if not subset:
        continue
    old_t = sum(1 for r in subset if r["had_transition"])
    new_t = sum(1 for r in subset if r["simulated_transition"])
    gain = new_t - old_t
    print(f"  {lo:>3}-{hi:<3}°: {len(subset):3d} trials, old_trans={old_t:2d}, new_trans={new_t:2d}, +{gain}")

# Estimate catch rate improvement
# From data: 150-200° with transitions has 28% catch rate (6/21)
# New transitions in 150-200° would get same catch rate
new_150_200 = sum(
    1 for r in results if 150 <= r["max_pend"] < 200 and r["simulated_transition"] and not r["had_transition"]
)
estimated_new_catches = int(new_150_200 * 0.28)  # 28% catch rate
total_trials = len(results)
current_catches = 12  # from baseline
estimated_new_catch_rate = (current_catches + estimated_new_catches) / total_trials * 100

print(f"\n--- Estimated catch rate improvement ---")
print(f"Current catches: {current_catches}/{total_trials} = {current_catches / total_trials * 100:.1f}%")
print(f"New transitions in 150-200°: {new_150_200}")
print(f"Estimated new catches: +{estimated_new_catches}")
print(
    f"Estimated new catch rate: {current_catches + estimated_new_catches}/{total_trials} = {estimated_new_catch_rate:.1f}%"
)
