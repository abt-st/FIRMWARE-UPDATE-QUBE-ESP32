#!/usr/bin/env python3
"""
Deep analysis of swing-up transitions: WHY do catches fail in 150-200° range?

Analyzes per-attempt:
1. Energy at transition point
2. Velocity at transition point
3. Servo position at transition
4. Time to reach max angle
5. Voltage drop (brownout indicator)
"""
import os
import csv
import glob
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def analyze_csv(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            # Handle two CSV formats
            if "servo_deg" in headers:
                rows.append({
                    "t": float(row["t"]),
                    "servo_deg": float(row["servo_deg"]),
                    "pend_deg": float(row["pend_deg"]),
                    "pend_raw_deg": float(row["pend_raw_deg"]),
                    "pwm": int(row["pwm"]),
                    "mode": int(row["mode"]),
                    "v_bus": float(row["v_bus"]),
                    "i_ma": float(row["i_ma"]),
                    "p_mw": float(row["p_mw"]),
                })
            elif "servo" in headers:
                rows.append({
                    "t": float(row["t"]),
                    "servo_deg": float(row["servo"]),
                    "pend_deg": float(row["pend"]),
                    "pend_raw_deg": float(row["pend"]),
                    "pwm": int(row["pwm"]),
                    "mode": int(row["mode"]),
                    "v_bus": float(row["v"]),
                    "i_ma": 0.0,
                    "p_mw": 0.0,
                })
    if len(rows) < 3:
        return None
        return None

    # Physics constants (from firmware)
    PEND_MASS = 0.025   # kg
    GRAVITY = 9.81      # m/s^2
    PEND_LENGTH = 0.065  # m (pivot to CM)
    PEND_INERTIA = 2.0e-5  # kg*m^2
    mgl = PEND_MASS * GRAVITY * PEND_LENGTH

    # Find max pendulum angle and transition point
    max_pend = 0
    max_pend_time = 0
    max_pend_idx = 0
    transition_idx = None
    transition_pend = 0
    transition_servo = 0
    transition_vel = 0
    transition_energy = 0
    transition_voltage = 0
    voltage_min = 999
    voltage_min_time = 0
    v_bus_start = rows[0]["v_bus"]
    crash = False
    catches = 0
    hold_start = None
    max_hold = 0

    prev_pend = rows[0]["pend_deg"]
    prev_t = rows[0]["t"]

    for i, r in enumerate(rows):
        # Track max angle
        if abs(r["pend_deg"]) > abs(max_pend):
            max_pend = r["pend_deg"]
            max_pend_time = r["t"]
            max_pend_idx = i

        # Track voltage drops (brownout indicator)
        if r["v_bus"] < voltage_min:
            voltage_min = r["v_bus"]
            voltage_min_time = r["t"]

        # Detect LQR transition (mode change from 5 to 4)
        if i > 0 and rows[i-1]["mode"] == 5 and r["mode"] == 4:
            transition_idx = i
            transition_pend = r["pend_deg"]
            transition_servo = r["servo_deg"]
            # Velocity at transition
            dt = r["t"] - prev_t if r["t"] - prev_t > 0 else 0.001
            transition_vel = (r["pend_deg"] - prev_pend) / dt
            # Energy at transition (kinetic + potential)
            alpha_rad = r["pend_deg"] * math.pi / 180.0
            E_kin = 0.5 * PEND_INERTIA * (transition_vel * math.pi / 180.0) ** 2
            E_pot = mgl * (1 - math.cos(alpha_rad))
            transition_energy = E_kin + E_pot
            transition_voltage = r["v_bus"]
            catches += 1
            if hold_start is None:
                hold_start = r["t"]

        # Detect LQR loss (mode change from 4 to something else, or crash)
        if i > 0 and rows[i-1]["mode"] == 4 and r["mode"] != 4:
            if hold_start is not None:
                hold_time = r["t"] - hold_start
                if hold_time > max_hold:
                    max_hold = hold_time
                hold_start = None

        # Detect crash (voltage drop > 2V or data ends abruptly)
        if r["v_bus"] < 12.0 and v_bus_start > 13.0:
            crash = True

        prev_pend = r["pend_deg"]
        prev_t = r["t"]

    # Final hold time
    if hold_start is not None:
        hold_time = rows[-1]["t"] - hold_start
        if hold_time > max_hold:
            max_hold = hold_time

    # Energy at max angle (should be mostly potential)
    alpha_max_rad = max_pend * math.pi / 180.0
    E_pot_max = mgl * (1 - math.cos(alpha_max_rad))

    # Compute energy ratio (actual / target)
    E_target = 2 * mgl  # Energy needed to reach vertical
    energy_ratio = E_pot_max / E_target if E_target > 0 else 0

    return {
        "max_pend": round(abs(max_pend), 1),
        "max_pend_time": round(max_pend_time, 2),
        "catches": catches,
        "max_hold": round(max_hold, 1),
        "crash": crash,
        "voltage_drop": round(v_bus_start - voltage_min, 2),
        "voltage_min": round(voltage_min, 2),
        "transition_pend": round(transition_pend, 1) if transition_pend else 0,
        "transition_servo": round(transition_servo, 1) if transition_servo else 0,
        "transition_vel": round(transition_vel, 1) if transition_vel else 0,
        "transition_energy": round(transition_energy * 1000, 3) if transition_energy else 0,  # mJ
        "energy_ratio": round(energy_ratio, 3),
        "E_pot_max_mJ": round(E_pot_max * 1000, 3),
        "E_target_mJ": round(E_target * 1000, 3),
        "duration": round(float(rows[-1]["t"]), 1),
    }

# Analyze all files
all_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
results = []
for f in all_files:
    r = analyze_csv(f)
    if r:
        r["file"] = os.path.basename(f)
        results.append(r)

# Categorize by max angle range
ranges = {
    "0-50": (0, 50),
    "50-100": (50, 100),
    "100-150": (100, 150),
    "150-200": (150, 200),
    "200+": (200, 9999),
}

print("=" * 100)
print("DEEP TRANSITION ANALYSIS — QUBE Swing-Up")
print("=" * 100)

for range_name, (lo, hi) in ranges.items():
    subset = [r for r in results if lo <= r["max_pend"] < hi]
    if not subset:
        continue

    catches = sum(1 for r in subset if r["catches"] > 0)
    crashes = sum(1 for r in subset if r["crash"])
    avg_vdrop = sum(r["voltage_drop"] for r in subset) / len(subset)
    avg_energy_ratio = sum(r["energy_ratio"] for r in subset) / len(subset)
    avg_transition_vel = [r["transition_vel"] for r in subset if r["transition_vel"] != 0]
    avg_transition_energy = [r["transition_energy"] for r in subset if r["transition_energy"] != 0]

    print(f"\n--- Range {range_name}° ({len(subset)} trials) ---")
    print(f"  Catches: {catches}/{len(subset)} = {100*catches/len(subset):.0f}%")
    print(f"  Crashes: {crashes}/{len(subset)} = {100*crashes/len(subset):.0f}%")
    print(f"  Avg voltage drop: {avg_vdrop:.2f}V")
    print(f"  Avg energy ratio (E/Etarget): {avg_energy_ratio:.3f}")
    if avg_transition_vel:
        print(f"  Avg transition velocity: {sum(avg_transition_vel)/len(avg_transition_vel):.1f}°/s")
    if avg_transition_energy:
        print(f"  Avg transition energy: {sum(avg_transition_energy)/len(avg_transition_energy):.2f}mJ")
    print(f"  E_target: {results[0]['E_target_mJ']:.2f}mJ")

# Specific: analyze the 150-200° range failures in detail
print("\n" + "=" * 100)
print("DETAILED: 150-200° RANGE (the critical transition zone)")
print("=" * 100)
critical = [r for r in results if 150 <= r["max_pend"] < 200]
for r in sorted(critical, key=lambda x: x["max_pend"], reverse=True):
    status = "CATCH" if r["catches"] > 0 else "MISS"
    crash_s = " CRASH" if r["crash"] else ""
    print(f"  {r['file'][:25]:25s} max={r['max_pend']:6.1f}° "
          f"e_ratio={r['energy_ratio']:.3f} "
          f"v_drop={r['voltage_drop']:.1f}V "
          f"t_vel={r['transition_vel']:6.1f}°/s "
          f"t_energy={r['transition_energy']:5.1f}mJ "
          f"hold={r['max_hold']:5.1f}s "
          f"{status}{crash_s}")

# The successful catches for comparison
print("\n" + "=" * 100)
print("SUCCESSFUL CATCHES (all ranges)")
print("=" * 100)
caught = [r for r in results if r["catches"] > 0]
for r in sorted(caught, key=lambda x: x["max_hold"], reverse=True):
    print(f"  {r['file'][:25]:25s} max={r['max_pend']:6.1f}° "
          f"e_ratio={r['energy_ratio']:.3f} "
          f"v_drop={r['voltage_drop']:.1f}V "
          f"t_vel={r['transition_vel']:6.1f}°/s "
          f"t_energy={r['transition_energy']:5.1f}mJ "
          f"hold={r['max_hold']:5.1f}s")

# Key insight: what distinguishes successful catches?
print("\n" + "=" * 100)
print("KEY INSIGHT: What separates catches from misses?")
print("=" * 100)
if caught:
    avg_caught_energy = sum(r["energy_ratio"] for r in caught) / len(caught)
    avg_caught_vdrop = sum(r["voltage_drop"] for r in caught) / len(caught)
    avg_caught_max = sum(r["max_pend"] for r in caught) / len(caught)
    print(f"Successful catches: avg energy_ratio={avg_caught_energy:.3f}, avg v_drop={avg_caught_vdrop:.1f}V, avg max_angle={avg_caught_max:.1f}°")

missed = [r for r in results if r["catches"] == 0 and r["max_pend"] > 100]
if missed:
    avg_missed_energy = sum(r["energy_ratio"] for r in missed) / len(missed)
    avg_missed_vdrop = sum(r["voltage_drop"] for r in missed) / len(missed)
    avg_missed_max = sum(r["max_pend"] for r in missed) / len(missed)
    print(f"Misses (>100°):    avg energy_ratio={avg_missed_energy:.3f}, avg v_drop={avg_missed_vdrop:.1f}V, avg max_angle={avg_missed_max:.1f}°")

print(f"\nDelta energy_ratio (catch vs miss): {avg_caught_energy - avg_missed_energy:.3f}")
