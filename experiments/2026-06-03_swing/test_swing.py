"""Swing-up test with CSV logging.

Usage:
    python experiments/2026-06-03_swing/test_swing.py [--duration 30] [--ip 192.168.100.50]
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def get_state(ip: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{ip}/state", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def send_cmd(ip: str, **params: object) -> None:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    try:
        urllib.request.urlopen(f"http://{ip}/cmd?{qs}", timeout=2)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Swing-up test with logging")
    parser.add_argument("--ip", default="192.168.100.50")
    parser.add_argument("--duration", type=float, default=30, help="Duration in seconds")
    parser.add_argument("--mode", type=int, default=5, help="Mode to set (5=swing-up)")
    args = parser.parse_args()

    ip = args.ip
    duration = args.duration
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    csv_path = data_dir / f"swing_{ts}.csv"

    header = [
        "t_ms", "mode", "pwm",
        "servo_count", "servo_deg",
        "pend_count", "pend_raw_deg", "pend_deg",
        "ina_ok", "v_bus", "i_ma", "p_mw",
    ]

    # Start mode
    send_cmd(ip, m=args.mode)
    print(f"Mode {args.mode} started. Logging to {csv_path}")
    print(f"Duration: {duration}s | IP: {ip}")
    print()

    t_start = time.monotonic()
    rows: list[list] = []

    while (time.monotonic() - t_start) < duration:
        d = get_state(ip)
        t_ms = int((time.monotonic() - t_start) * 1000)
        if d:
            row = [
                t_ms, d.get("mode", 0), d.get("pwm", 0),
                d.get("count", 0), d.get("position_deg", 0),
                d.get("pend_count", 0), d.get("pend_raw_position_deg", 0),
                d.get("pend_position_deg", 0),
                d.get("ina_ok", False), d.get("v_bus", 0), d.get("i_ma", 0), d.get("p_mw", 0),
            ]
            rows.append(row)
            # Print summary
            print(
                f"{t_ms:>6}ms  m={d['mode']}  pwm={d['pwm']:>+4d}  "
                f"serv={d['position_deg']:>+7.1f}  "
                f"pend={d['pend_position_deg']:>+7.1f}  "
                f"pend_raw={d['pend_raw_position_deg']:>+8.1f}  "
                f"pend_cnt={d['pend_count']:>+6d}"
            )
        else:
            rows.append([t_ms, -1, 0, 0, 0, 0, 0, 0, False, 0, 0, 0])
            print(f"{t_ms:>6}ms  -- no response --")
        time.sleep(0.1)

    # Stop
    send_cmd(ip, x=1)
    print(f"\nMotor stopped. {len(rows)} samples collected.")

    # Write CSV
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
