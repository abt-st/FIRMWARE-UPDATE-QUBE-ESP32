"""Log LQR behavior while user holds pendulum near vertical.

Starts mode 4 (LQR) and logs state at 30 Hz for analysis.
The user manually holds the pendulum near inverted (~160-180 deg).

Usage::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/log_lqr_hold.py \\
        --ip 192.168.100.50 --seconds 30
"""
from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

RAD2DEG = 180.0 / 3.141592653589793

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.100.50")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--out", default=None, help="CSV output path")
    args = parser.parse_args()

    ip = args.ip
    out_path = Path(args.out) if args.out else Path(
        f"experiments/2026-06-23_r7_curriculum_sweep/log_lqr_{datetime.now():%Y%m%dT%H%M%S}.csv"
    )

    def _kill(*_: object) -> None:
        requests.get(f"http://{ip}/cmd", params={"m": "0"}, timeout=3)
        sys.exit(0)
    signal.signal(signal.SIGINT, _kill)

    # Start LQR mode
    print(f"Starting LQR mode 4 on {ip} for {args.seconds}s")
    print(f"Output: {out_path}")
    requests.get(f"http://{ip}/cmd", params={"m": "4"}, timeout=3)
    time.sleep(0.2)

    rows = []
    t0 = time.time()
    while (time.time() - t0) < args.seconds:
        r = requests.get(f"http://{ip}/state", timeout=3)
        d = r.json()
        t = time.time() - t0
        rows.append({
            "t": round(t, 4),
            "th_deg": round(float(d.get("position_deg", 0)), 2),
            "al_deg": round(float(d.get("pend_position_deg", 0)), 2),
            "pwm": int(d.get("pwm", 0)),
            "i_ma": round(float(d.get("i_ma", 0)), 1),
            "mode": int(d.get("mode", 0)),
        })
        time.sleep(0.033)  # ~30 Hz

    # Kill motor
    requests.get(f"http://{ip}/cmd", params={"m": "0"}, timeout=3)

    # Save CSV
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} samples to {out_path}")

    # Quick analysis
    ths = [r["th_deg"] for r in rows]
    als = [r["al_deg"] for r in rows]
    pwms = [r["pwm"] for r in rows]
    print(f"  theta:  min={min(ths):+.1f}  max={max(ths):+.1f}  mean={sum(ths)/len(ths):+.1f}")
    print(f"  alpha:  min={min(als):+.1f}  max={max(als):+.1f}  mean={sum(als)/len(als):+.1f}")
    print(f"  pwm:    min={min(pwms)}  max={max(pwms)}  mean={sum(pwms)/len(pwms):+.1f}")

if __name__ == "__main__":
    main()
