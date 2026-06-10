#!/usr/bin/env python3
"""Analyze all swing-up CSV data from BTS7960 session."""
import os
import csv
import glob

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def analyze_csv(path):
    try:
        with open(path) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    if not rows:
        return None
    max_pend = 0.0; lqr_catches = 0; lqr_start = None; max_hold = 0.0
    prev_mode = None; crash = False; servo_max = 0.0
    for row in rows:
        t = float(row.get("t", 0))
        pend = abs(float(row.get("pend_deg", 0)))
        servo = abs(float(row.get("servo_deg", 0)))
        mode = int(float(row.get("mode", 0)))
        if pend > max_pend: max_pend = pend
        if servo > servo_max: servo_max = servo
        if prev_mode == 5 and mode == 4:
            lqr_catches += 1; lqr_start = t
        elif mode == 4 and prev_mode == 4 and lqr_start:
            hold = t - lqr_start
            if hold > max_hold: max_hold = hold
        elif mode != 4: lqr_start = None
        if mode == 0 and t > 5: crash = True
        prev_mode = mode
    return {"max_pend": round(max_pend,1), "max_servo": round(servo_max,1),
            "lqr_catches": lqr_catches, "max_hold": round(max_hold,1),
            "crash": crash, "duration": round(float(rows[-1].get("t",0)),1)}

all_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
groups = {}
for f in all_files:
    bn = os.path.basename(f)
    key = bn.rsplit("_attempt",1)[0] if "_attempt" in bn else bn
    groups.setdefault(key, []).append(f)

print("=" * 80)
print("ANALISIS COMPLETO -- Swing-Up BTS7960 -- 2026-06-08")
print("=" * 80)
print("Total CSVs: %d, Grupos: %d" % (len(all_files), len(groups)))
print()

all_results = []
idx = 0
for key in sorted(groups.keys()):
    files = sorted(groups[key])
    gres = []
    for f in files:
        r = analyze_csv(f)
        if r: gres.append(r)
    if not gres: continue
    idx += 1
    config = key.replace("sweep_", "").replace("_20260608T", " @")
    if len(config) > 38: config = config[:35] + "..."
    best_max = max(r["max_pend"] for r in gres)
    catch_count = sum(1 for r in gres if r["lqr_catches"] > 0)
    avg_hold = 0
    holds = [r["max_hold"] for r in gres if r["max_hold"] > 0]
    if holds: avg_hold = sum(holds) / len(holds)
    crash_count = sum(1 for r in gres if r["crash"])
    avg_servo = sum(r["max_servo"] for r in gres) / len(gres)
    crash_s = "CRASH x%d" % crash_count if crash_count else ""
    print("%3d %-38s %5.1f %6.1f %2d/%d %5.1fs %s" % (
        idx, config, best_max, avg_servo, catch_count, len(gres), avg_hold, crash_s))
    for r in gres: r["config"] = key
    all_results.extend(gres)

print()
print("=" * 80)
print("RESUMEN ESTADISTICO")
print("=" * 80)
total = len(all_results)
catches = sum(1 for r in all_results if r["lqr_catches"] > 0)
crashes = sum(1 for r in all_results if r["crash"])
max_angles = [r["max_pend"] for r in all_results]
servo_angles = [r["max_servo"] for r in all_results]
holds = [r["max_hold"] for r in all_results if r["max_hold"] > 0]

print("Total ensayos:     %d" % total)
print("Catches totales:   %d/%d = %.1f%%" % (catches, total, catches/total*100))
print("Crashes:           %d/%d = %.1f%%" % (crashes, total, crashes/total*100))
print("Max angle promedio: %.1f deg" % (sum(max_angles)/len(max_angles)))
print("Max angle mejor:   %.1f deg" % max(max_angles))
print("Servo max promedio: %.1f deg" % (sum(servo_angles)/len(servo_angles)))
if holds:
    print("Hold promedio:     %.1fs" % (sum(holds)/len(holds)))
    print("Hold max:          %.1fs" % max(holds))
    print("Hold min (con catch): %.1fs" % min(holds))

print()
print("Distribucion de max angle:")
ranges = [(0, 50), (50, 100), (100, 150), (150, 200), (200, 500)]
for lo, hi in ranges:
    count = sum(1 for a in max_angles if lo <= a < hi)
    catch_in = sum(1 for r in all_results if lo <= r["max_pend"] < hi and r["lqr_catches"] > 0)
    if count > 0:
        print("  %3d-%3d: %3d ensayos, %2d catches (%d%% catch rate)" % (
            lo, hi, count, catch_in, catch_in*100//count))
    else:
        print("  %3d-%3d: %3d ensayos" % (lo, hi, count))

print()
print("=" * 80)
print("TOP 10 MEJORES INTENTOS")
print("=" * 80)
sorted_by_max = sorted(all_results, key=lambda r: r["max_pend"], reverse=True)[:10]
print("%3s %6s %7s %6s %7s %6s %s" % ("#", "Max", "Catches", "Hold", "Servo", "Crash", "Config"))
for i, r in enumerate(sorted_by_max, 1):
    config = os.path.basename(r["config"]).replace("sweep_", "").replace("_20260608T", "@")[:20]
    crash_s = "CRASH" if r["crash"] else ""
    print("%3d %5.1f  %4d    %5.1fs %5.1f  %-5s %s" % (
        i, r["max_pend"], r["lqr_catches"], r["max_hold"], r["max_servo"], crash_s, config))
