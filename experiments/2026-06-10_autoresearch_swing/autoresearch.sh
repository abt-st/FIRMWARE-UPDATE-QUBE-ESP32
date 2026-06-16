#!/usr/bin/env bash
# autoresearch.sh — Benchmark harness for QUBE Servo swing-up + LQR controller
#
# Analyzes experimental CSV data from the latest session to compute baseline
# performance metrics. The iteration loop will modify firmware parameters and
# re-evaluate against this baseline.
#
# Primary metric: catch_rate (higher is better)
# Secondary metrics: avg_hold_time, crash_rate, max_angle

set -euo pipefail

DATA_DIR="experiments/2026-06-08_swing/data"

if [ ! -d "$DATA_DIR" ]; then
  echo "ERROR: Data directory not found: $DATA_DIR" >&2
  exit 1
fi

CSV_COUNT=$(find "$DATA_DIR" -name "*.csv" 2>/dev/null | wc -l)
if [ "$CSV_COUNT" -eq 0 ]; then
  echo "ERROR: No CSV files found in $DATA_DIR" >&2
  exit 1
fi

# Run the Python analysis script and capture output
RESULT=$(uv run python experiments/2026-06-08_swing/analyze_all.py 2>/dev/null || true)

if [ -z "$RESULT" ]; then
  echo "ERROR: Analysis script produced no output" >&2
  exit 1
fi

# Extract metrics from analysis output
# The analyze_all.py prints lines like:
#   "Catches totales:   12/173 = 6.9%"
#   "Crashes:           34/173 = 19.7%"
#   "Max angle mejor:   518.0 deg"
#   "Hold promedio:     82.0s"
#   "Hold max:          88.4s"

catch_pct=$(echo "$RESULT" | grep -oP 'Catches totales:\s+\d+/\d+\s+=\s+\K[0-9.]+' || echo "0")
crash_pct=$(echo "$RESULT" | grep -oP 'Crashes:\s+\d+/\d+\s+=\s+\K[0-9.]+' || echo "0")
max_angle=$(echo "$RESULT" | grep -oP 'Max angle mejor:\s+\K[0-9.]+' || echo "0")
hold_avg=$(echo "$RESULT" | grep -oP 'Hold promedio:\s+\K[0-9.]+' || echo "0")
hold_max=$(echo "$RESULT" | grep -oP 'Hold max:\s+\K[0-9.]+' || echo "0")
total_trials=$(echo "$RESULT" | grep -oP 'Total ensayos:\s+\K[0-9]+' || echo "0")
catches_total=$(echo "$RESULT" | grep -oP 'Catches totales:\s+\K\d+' || echo "0")
crashes_total=$(echo "$RESULT" | grep -oP 'Crashes:\s+\K\d+' || echo "0")

# Compute composite score: weighted combination
# catch_rate is primary (higher = better)
# crash_rate penalizes (lower = better)
# hold_time rewards longer holds
# Formula: score = catch_rate * (1 - crash_rate/100) * (hold_avg / 90)
# Normalized to 0-100 scale
composite=$(uv run python -c "
catch = float('${catch_pct}' or '0')
crash = float('${crash_pct}' or '0')
hold = float('${hold_avg}' or '0')
score = catch * (1 - crash / 100) * (hold / 90) * 100
print(f'{score:.2f}')
" 2>/dev/null || echo "0")

# Emit METRIC lines for autoresearch
echo "METRIC catch_rate=${catch_pct}"
echo "METRIC crash_rate=${crash_pct}"
echo "METRIC max_angle=${max_angle}"
echo "METRIC avg_hold_time=${hold_avg}"
echo "METRIC max_hold_time=${hold_max}"
echo "METRIC total_trials=${total_trials}"
echo "METRIC composite_score=${composite}"

# Summary to stderr for logging
echo "--- QUBE Swing-Up Benchmark Summary ---" >&2
echo "Total trials: $total_trials" >&2
echo "Catch rate: ${catch_pct}% ($catches_total catches)" >&2
echo "Crash rate: ${crash_pct}% ($crashes_total crashes)" >&2
echo "Max angle: ${max_angle}°" >&2
echo "Avg hold: ${hold_avg}s | Max hold: ${hold_max}s" >&2
echo "Composite score: ${composite}" >&2

exit 0
