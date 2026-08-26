#!/usr/bin/env bash
# autoresearch.sh — Benchmark harness for QUBE Servo swing-up + LQR controller
#
# Analyzes experimental CSV data from the latest sweep to compute baseline
# performance metrics. The iteration loop will modify firmware parameters and
# re-evaluate against this baseline.
#
# Primary metric: catch_rate (higher is better)
# Secondary metrics: avg_hold_time, crash_rate, max_angle

set -euo pipefail

DATA_DIR="experiments/2026-06-15_sweep_v2/data"

if [ ! -d "$DATA_DIR" ]; then
  echo "ERROR: Data directory not found: $DATA_DIR" >&2
  exit 1
fi

# Find the latest sweep directory
LATEST_SWEEP=$(find "$DATA_DIR" -maxdepth 1 -type d -name "sweep_*" 2>/dev/null | sort -r | head -1)

if [ -z "$LATEST_SWEEP" ]; then
  echo "ERROR: No sweep directories found in $DATA_DIR" >&2
  exit 1
fi

SWEEP_CSV="$LATEST_SWEEP/sweep_data.csv"

if [ ! -f "$SWEEP_CSV" ]; then
  echo "ERROR: No sweep_data.csv found in $LATEST_SWEEP" >&2
  exit 1
fi

echo "--- QUBE Swing-Up Benchmark ---" >&2
echo "Sweep: $LATEST_SWEEP" >&2

# Analyze sweep CSV with Python
RESULT=$(uv run python -c "
import csv
import sys
from collections import defaultdict

results = defaultdict(lambda: {'catch': 0, 'transient': 0, 'miss': 0, 'max_angles': [], 'catch_times': []})

with open('$SWEEP_CSV') as f:
    reader = csv.DictReader(f)
    current_sp = None
    attempt_data = {}

    for row in reader:
        sp = int(row['sp'])
        attempt = int(row['attempt'])
        mode = int(row['mode'])
        pend = abs(float(row['pend_deg']))
        t = float(row['t'])

        key = (sp, attempt)
        if key not in attempt_data:
            attempt_data[key] = {'sp': sp, 'max_angle': 0, 'lqr_time': None, 'final_mode': mode}

        d = attempt_data[key]
        if pend > d['max_angle']:
            d['max_angle'] = pend
        if mode == 4 and d['lqr_time'] is None:
            d['lqr_time'] = t
        d['final_mode'] = mode

    # Classify each attempt
    for (sp, attempt), d in attempt_data.items():
        r = results[sp]
        r['max_angles'].append(d['max_angle'])
        if d['final_mode'] == 4 and d['lqr_time'] is not None:
            r['catch'] += 1
            r['catch_times'].append(d['lqr_time'])
        elif d['lqr_time'] is not None:
            r['transient'] += 1
        else:
            r['miss'] += 1

# Print summary
total_attempts = sum(r['catch'] + r['transient'] + r['miss'] for r in results.values())
total_catches = sum(r['catch'] for r in results.values())
total_transients = sum(r['transient'] for r in results.values())
total_misses = sum(r['miss'] for r in results.values())

catch_pct = total_catches / max(1, total_attempts) * 100
trans_pct = total_transients / max(1, total_attempts) * 100
miss_pct = total_misses / max(1, total_attempts) * 100

# Max angle stats
all_max = []
for r in results.values():
    all_max.extend(r['max_angles'])
max_angle = max(all_max) if all_max else 0
avg_max = sum(all_max) / max(1, len(all_max))

# Catch time stats
all_catch_times = []
for r in results.values():
    all_catch_times.extend(r['catch_times'])
avg_hold = sum(all_catch_times) / max(1, len(all_catch_times))
max_hold = max(all_catch_times) if all_catch_times else 0

# Best SP
best_sp = max(results.keys(), key=lambda sp: results[sp]['catch']) if results else None
best_rate = results[best_sp]['catch'] / max(1, results[best_sp]['catch'] + results[best_sp]['transient'] + results[best_sp]['miss']) * 100 if best_sp else 0

print(f'Total trials: {total_attempts}')
print(f'Catches: {total_catches}/{total_attempts} = {catch_pct:.1f}%')
print(f'Transients: {total_transients}/{total_attempts} = {trans_pct:.1f}%')
print(f'Misses: {total_misses}/{total_attempts} = {miss_pct:.1f}%')
print(f'Max angle: {max_angle:.1f}°')
print(f'Avg max angle: {avg_max:.1f}°')
print(f'Avg hold time: {avg_hold:.1f}s')
print(f'Max hold time: {max_hold:.1f}s')
print(f'Best SP: {best_sp} ({best_rate:.0f}% catch)')

# Per-SP breakdown
for sp in sorted(results.keys()):
    r = results[sp]
    total = r['catch'] + r['transient'] + r['miss']
    rate = r['catch'] / max(1, total) * 100
    avg_m = sum(r['max_angles']) / max(1, len(r['max_angles']))
    ct = r['catch_times']
    avg_ct = sum(ct) / max(1, len(ct))
    print(f'SP {sp}: {r[\"catch\"]}C/{r[\"transient\"]}T/{r[\"miss\"]}M ({rate:.0f}%) avg_max={avg_m:.0f}° avg_catch={avg_ct:.1f}s')
" 2>/dev/null || echo "ERROR: Analysis failed")

if [ -z "$RESULT" ] || echo "$RESULT" | grep -q "ERROR"; then
  echo "ERROR: Analysis produced no valid output" >&2
  echo "$RESULT" >&2
  exit 1
fi

# Extract metrics
catch_pct=$(echo "$RESULT" | grep -oP 'Catches:\s+\d+/\d+\s+=\s+\K[0-9.]+' || echo "0")
total_trials=$(echo "$RESULT" | grep -oP 'Total trials:\s+\K[0-9]+' || echo "0")
max_angle=$(echo "$RESULT" | grep -oP 'Max angle:\s+\K[0-9.]+' || echo "0")
avg_hold=$(echo "$RESULT" | grep -oP 'Avg hold time:\s+\K[0-9.]+' || echo "0")
max_hold=$(echo "$RESULT" | grep -oP 'Max hold time:\s+\K[0-9.]+' || echo "0")
best_sp=$(echo "$RESULT" | grep -oP 'Best SP:\s+\K[0-9]+' || echo "0")

# Compute composite score
composite=$(uv run python -c "
catch = float('${catch_pct}' or '0')
hold = float('${avg_hold}' or '0')
score = catch * (hold / 30) * 100
print(f'{score:.2f}')
" 2>/dev/null || echo "0")

# Emit METRIC lines
echo "METRIC catch_rate=${catch_pct}"
echo "METRIC total_trials=${total_trials}"
echo "METRIC max_angle=${max_angle}"
echo "METRIC avg_hold_time=${avg_hold}"
echo "METRIC max_hold_time=${max_hold}"
echo "METRIC best_sp=${best_sp}"
echo "METRIC composite_score=${composite}"

# Full output to stderr
echo "---" >&2
echo "$RESULT" >&2
echo "---" >&2
echo "Composite score: ${composite}" >&2

exit 0
