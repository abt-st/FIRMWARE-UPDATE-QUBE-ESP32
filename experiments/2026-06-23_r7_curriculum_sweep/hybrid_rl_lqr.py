"""Hybrid RL swing-up + LQR balance.

The R7 policy does swing-up (reaches ~178° on hardware) but can't balance.
The firmware's LQR (mode 4) handles balance natively. This script:

1. Starts mode 7 (RL on-device) for swing-up
2. Monitors /rl_state — when |alpha| > TRANSITION_DEG, switches to mode 4 (LQR)
3. Monitors mode 4 — if pendulum falls (|alpha| < FALLBACK_DEG), switches back to mode 7
4. Logs metrics throughout

Usage::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/hybrid_rl_lqr.py \\
        --ip 192.168.100.50 --seconds 120 --scale 0.85
"""
from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import time
from datetime import datetime

import requests

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

RAD2DEG = 180.0 / 3.141592653589793

# Transition thresholds
TRANSITION_DEG = 150.0   # switch to LQR when |alpha| >= this
FALLBACK_DEG = 120.0     # switch back to RL when |alpha| < this (hysteresis)
HOLD_THRESH_DEG = 12.0   # "upright" = within this of inverted (180°)
HOLD_VEL_THRESH = 1.0    # rad/s — must be slow to count as balance


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def get_state(ip: str) -> dict:
    """Read from /state endpoint (works in all modes, unlike /rl_state)."""
    d = requests.get(f"http://{ip}/state", timeout=3).json()
    return {
        "th": float(d["position_deg"]),
        "al": float(d["pend_position_deg"]),
        "ald": float(d.get("vel_alpha", 0.0)),
    }


def set_mode(ip: str, mode: int) -> None:
    requests.get(f"http://{ip}/cmd", params={"m": str(mode)}, timeout=3)


def set_scale(ip: str, scale: float) -> None:
    requests.get(f"http://{ip}/rl_cmd", params={"scale": str(scale)}, timeout=3)


def kill_motor(ip: str) -> None:
    with contextlib.suppress(Exception):
        requests.get(f"http://{ip}/cmd", params={"m": "0"}, timeout=3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid RL swing-up + LQR balance")
    parser.add_argument("--ip", type=str, default="192.168.100.50")
    parser.add_argument("--seconds", type=int, default=120, help="Total run time")
    parser.add_argument("--scale", type=float, default=0.85, help="RL torque scale")
    parser.add_argument("--reset", action="store_true", help="Reset encoders at start")
    args = parser.parse_args()

    ip = args.ip

    # Ctrl+C handler
    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -> emergency stop")
        kill_motor(ip)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # Reset encoders if requested
    if args.reset:
        log("Resetting encoders...")
        kill_motor(ip)
        time.sleep(0.3)
        requests.get(f"http://{ip}/rl_cmd", params={"r": "1"}, timeout=3)
        time.sleep(0.5)
        st = get_state(ip)
        log(f"  After reset: th={st['th']:+.1f} al={st['al']:+.1f}")

    # Set RL scale
    set_scale(ip, args.scale)
    log(f"RL scale={args.scale}")

    # Start in mode 7 (RL swing-up)
    log(f"Starting hybrid: RL swing-up -> LQR balance ({args.seconds}s)")
    log(f"  Transition at |alpha| >= {TRANSITION_DEG} deg")
    log(f"  Fallback at   |alpha| <  {FALLBACK_DEG} deg")

    set_mode(ip, 7)
    current_mode = "RL"
    log("Mode: RL (swing-up)")

    t0 = time.time()
    last_log = 0.0
    hold_steps = 0
    max_hold = 0
    transitions = 0

    while (time.time() - t0) < args.seconds:
        st = get_state(ip)
        al_deg = float(st["al"])  # already in degrees from /state
        abs_al_deg = abs(al_deg)
        th_deg = float(st["th"])  # already in degrees

        # Check for mode transition
        if current_mode == "RL" and abs_al_deg >= TRANSITION_DEG:
            set_mode(ip, 4)  # LQR
            current_mode = "LQR"
            transitions += 1
            log(f"  -> LQR (alpha={al_deg:+.1f} deg)")
        elif current_mode == "LQR" and abs_al_deg < FALLBACK_DEG:
            set_mode(ip, 7)  # RL
            current_mode = "RL"
            transitions += 1
            log(f"  -> RL  (alpha={al_deg:+.1f} deg)")

        # Track balance hold (in LQR mode, near inverted)
        if current_mode == "LQR":
            ang_to_top = 180.0 - abs_al_deg
            vel = float(st.get("ald", 0.0))
            if ang_to_top <= HOLD_THRESH_DEG and abs(vel) <= HOLD_VEL_THRESH:
                hold_steps += 1
                max_hold = max(max_hold, hold_steps)
            else:
                hold_steps = 0
        else:
            hold_steps = 0

        # Periodic log (every 2s)
        now = time.time() - t0
        if now - last_log >= 2.0:
            hold_s = max_hold / 50.0  # 50 Hz
            log(f"  t={now:.0f}s mode={current_mode:3s} "
                f"th={th_deg:+6.1f} al={al_deg:+7.1f} "
                f"transitions={transitions} max_hold={hold_s:.2f}s")
            last_log = now

        time.sleep(0.02)  # 50 Hz polling

    # Final report
    kill_motor(ip)
    elapsed = time.time() - t0
    hold_s = max_hold / 50.0

    log(f"\n{'='*60}")
    log("HYBRID RUN COMPLETE")
    log(f"  Duration:    {elapsed:.0f}s")
    log(f"  Transitions: {transitions}")
    log(f"  Max hold:    {hold_s:.2f}s (need >= 1.0s for balance)")
    log(f"  Scale:       {args.scale}")

    if hold_s >= 1.0:
        log(f"  *** BALANCE ACHIEVED! ({hold_s:.2f}s) ***")
    elif hold_s > 0:
        log(f"  Close! Hold was {hold_s:.2f}s but need >= 1.0s")
    else:
        log("  No balance detected. May need threshold tuning.")

    log("\nTo run again:")
    log(f"  uv run python experiments/2026-06-23_r7_curriculum_sweep/hybrid_rl_lqr.py "
        f"--ip {ip} --seconds {args.seconds} --scale {args.scale}")


if __name__ == "__main__":
    main()
