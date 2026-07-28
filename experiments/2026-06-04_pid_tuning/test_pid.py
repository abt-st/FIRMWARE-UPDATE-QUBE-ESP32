"""PID Servo & Pendulum test with CSV logging.

Tests the step response of both PID controllers via HTTP commands.
PID gains can be changed at runtime without reflashing firmware.

Usage:
    # Servo PID with default gains
    python test_pid.py --mode servo --duration 32

    # Servo PID with custom gains
    python test_pid.py --mode servo --duration 32 --kp 3.0 --ki 1.5 --kd 0.20

    # Pendulum PID with custom gains
    python test_pid.py --mode pendulum --duration 38 --kpp 15 --kip 0.5 --kdp 2.0

    # Both tests
    python test_pid.py --mode both --duration 70
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def get_state(ip: str, timeout: float = 2.0) -> dict | None:
    """Fetch JSON state from the ESP32."""
    try:
        with urllib.request.urlopen(f"http://{ip}/state", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def send_cmd(ip: str, timeout: float = 2.0, **params: object) -> None:
    """Send a command to the ESP32."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    try:
        with urllib.request.urlopen(f"http://{ip}/cmd?{qs}", timeout=timeout) as r:
            r.read()
    except Exception:
        pass


def wait_for_state(ip: str, retries: int = 5) -> dict | None:
    """Wait for the ESP32 to respond."""
    for _ in range(retries):
        s = get_state(ip)
        if s is not None:
            return s
        time.sleep(0.5)
    return None


def set_pid_gains(ip: str, mode: int, gains: dict[str, float]) -> None:
    """Set PID gains via HTTP command endpoint.

    Args:
        ip: ESP32 IP address.
        mode: 2 for servo, 3 for pendulum.
        gains: Dict of gain name to value.
    """
    params: dict[str, object] = {}
    if mode == 2:
        if "kp" in gains:
            params["kp"] = gains["kp"]
        if "ki" in gains:
            params["ki"] = gains["ki"]
        if "kd" in gains:
            params["kd"] = gains["kd"]
    elif mode == 3:
        if "kpp" in gains:
            params["kpp"] = gains["kpp"]
        if "kip" in gains:
            params["kip"] = gains["kip"]
        if "kdp" in gains:
            params["kdp"] = gains["kdp"]

    if params:
        send_cmd(ip, **params)
        print(f"  Gains set: {params}")


def run_test(
    ip: str,
    mode: int,
    duration: float,
    setpoints: list[tuple[float, float]],
    label: str = "",
) -> list[list]:
    """Run a PID test with scheduled setpoint changes.

    Args:
        ip: ESP32 IP address.
        mode: Control mode (2=servo, 3=pendulum).
        duration: Total test duration in seconds.
        setpoints: List of (time_offset_s, setpoint_deg) tuples.
        label: Label for this test run.

    Returns:
        Collected rows.
    """
    send_cmd(ip, m=mode)
    time.sleep(0.3)

    t_start = time.monotonic()
    sp_idx = 0
    rows: list[list] = []

    print(f"  Mode {mode} | Duration {duration}s | {len(setpoints)} setpoints | {label}")

    while (time.monotonic() - t_start) < duration:
        elapsed = time.monotonic() - t_start

        # Apply next setpoint if it's time
        while sp_idx < len(setpoints) and elapsed >= setpoints[sp_idx][0]:
            _, sp_val = setpoints[sp_idx]
            if mode == 2:
                send_cmd(ip, s=sp_val)
                print(f"  [{elapsed:6.1f}s] Servo setpoint -> {sp_val} deg")
            elif mode == 3:
                send_cmd(ip, sp=sp_val)
                print(f"  [{elapsed:6.1f}s] Pendulum setpoint -> {sp_val} deg")
            sp_idx += 1

        d = get_state(ip)
        if d is not None:
            t_ms = int(elapsed * 1000)
            if mode == 2:
                row = [
                    t_ms,
                    d.get("mode", 0),
                    d.get("pwm", 0),
                    d.get("count", 0),
                    d.get("position_deg", 0),
                    d.get("setpoint_deg", 0),
                    d.get("error_deg", 0),
                    d.get("gain_mode", 0),
                    d.get("pend_count", 0),
                    d.get("pend_position_deg", 0),
                    d.get("v_bus", 0),
                    d.get("i_ma", 0),
                    d.get("p_mw", 0),
                ]
            else:
                row = [
                    t_ms,
                    d.get("mode", 0),
                    d.get("pwm", 0),
                    d.get("pend_count", 0),
                    d.get("pend_position_deg", 0),
                    d.get("pend_setpoint_deg", 0),
                    d.get("pend_error_deg", 0),
                    d.get("count", 0),
                    d.get("position_deg", 0),
                    d.get("v_bus", 0),
                    d.get("i_ma", 0),
                    d.get("p_mw", 0),
                ]
            rows.append(row)
        time.sleep(0.1)

    return rows


SERVO_HEADER = [
    "t_ms",
    "mode",
    "pwm",
    "servo_count",
    "servo_deg",
    "setpoint_deg",
    "error_deg",
    "gain_mode",
    "pend_count",
    "pend_deg",
    "v_bus",
    "i_ma",
    "p_mw",
]

PEND_HEADER = [
    "t_ms",
    "mode",
    "pwm",
    "pend_count",
    "pend_deg",
    "pend_setpoint_deg",
    "pend_error_deg",
    "servo_count",
    "servo_deg",
    "v_bus",
    "i_ma",
    "p_mw",
]


SERVO_SETPOINTS = [
    (0.0, 0.0),
    (2.0, 30.0),
    (8.0, -30.0),
    (14.0, 60.0),
    (20.0, 0.0),
    (24.0, -60.0),
    (28.0, 0.0),
]

PEND_SETPOINTS = [
    (0.0, 0.0),
    (3.0, 30.0),
    (9.0, 60.0),
    (15.0, 90.0),
    (21.0, 45.0),
    (27.0, -30.0),
    (33.0, 0.0),
]


def test_servo_pid(
    ip: str,
    duration: float,
    csv_path: Path,
    gains: dict[str, float] | None,
) -> None:
    """Test servo PID with multi-step response."""
    print(f"\n{'=' * 60}")
    print("SERVO PID TEST (Mode 2)")
    print(f"{'=' * 60}")

    if gains:
        set_pid_gains(ip, 2, gains)

    # Zero encoder first
    send_cmd(ip, z=1)
    time.sleep(0.3)

    label = (
        f"Kp={gains.get('kp', 'def')}, Ki={gains.get('ki', 'def')}, Kd={gains.get('kd', 'def')}"
        if gains
        else "defaults"
    )
    rows = run_test(ip, 2, duration, SERVO_SETPOINTS, label)

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SERVO_HEADER)
        w.writerows(rows)

    print(f"\n  Saved: {csv_path} ({len(rows)} samples)")


def test_pendulum_pid(
    ip: str,
    duration: float,
    csv_path: Path,
    gains: dict[str, float] | None,
) -> None:
    """Test pendulum PID with angle tracking."""
    print(f"\n{'=' * 60}")
    print("PENDULUM PID TEST (Mode 3)")
    print(f"{'=' * 60}")

    if gains:
        set_pid_gains(ip, 3, gains)

    # Zero pendulum encoder first
    send_cmd(ip, zp=1)
    time.sleep(0.3)

    label = (
        f"Kp={gains.get('kpp', 'def')}, Ki={gains.get('kip', 'def')}, Kd={gains.get('kdp', 'def')}"
        if gains
        else "defaults"
    )
    rows = run_test(ip, 3, duration, PEND_SETPOINTS, label)

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(PEND_HEADER)
        w.writerows(rows)

    print(f"\n  Saved: {csv_path} ({len(rows)} samples)")


def main() -> None:
    parser = argparse.ArgumentParser(description="PID Servo & Pendulum test")
    parser.add_argument("--ip", default="192.168.100.50", help="ESP32 IP")
    parser.add_argument("--mode", choices=["servo", "pendulum", "both"], default="servo")
    parser.add_argument("--duration", type=float, default=0, help="Override test duration (0=auto)")
    parser.add_argument("--no-stop", action="store_true", help="Don't stop motor at end")
    parser.add_argument("--ff", type=float, default=None, help="Servo feedforward PWM")
    # Servo PID gains
    parser.add_argument("--kp", type=float, default=None, help="Servo Kp")
    parser.add_argument("--ki", type=float, default=None, help="Servo Ki")
    parser.add_argument("--kd", type=float, default=None, help="Servo Kd")
    # Pendulum PID gains
    parser.add_argument("--kpp", type=float, default=None, help="Pendulum Kp")
    parser.add_argument("--kip", type=float, default=None, help="Pendulum Ki")
    parser.add_argument("--kdp", type=float, default=None, help="Pendulum Kd")
    args = parser.parse_args()

    # The pendulum-PID path drives firmware mode 3. That mode was removed in v1.34
    # (the pendulum is a passive underactuated link) and the ID has since been
    # reassigned to homing, so running it would send the arm into both mechanical
    # stops instead of doing nothing. Refuse before touching the hardware.
    if args.mode in ("pendulum", "both"):
        raise SystemExit(
            "--mode pendulum/both is retired: firmware m3 was the pendulum PID and "
            "is now the homing routine. Running it would drive the arm into the "
            "mechanical stops. Use --mode servo."
        )

    ip = args.ip
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    # Check connection
    s = wait_for_state(ip)
    if s is None:
        print(f"ERROR: Cannot reach ESP32 at {ip}")
        return
    print(f"Connected to {ip} | Mode={s.get('mode')} | Pos={s.get('position_deg')} deg")

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    servo_gains: dict[str, float] = {}
    if args.kp is not None:
        servo_gains["kp"] = args.kp
    if args.ki is not None:
        servo_gains["ki"] = args.ki
    if args.kd is not None:
        servo_gains["kd"] = args.kd

    pend_gains: dict[str, float] = {}
    if args.kpp is not None:
        pend_gains["kpp"] = args.kpp
    if args.kip is not None:
        pend_gains["kip"] = args.kip
    if args.kdp is not None:
        pend_gains["kdp"] = args.kdp

    # Set feedforward if provided
    if args.ff is not None:
        send_cmd(ip, ff=args.ff)
        print(f"  Feedforward: ff={args.ff}")
    try:
        if args.mode in ("servo", "both"):
            dur = args.duration if args.duration > 0 else 32.0
            ff_tag = f"_ff{args.ff:.0f}" if args.ff is not None else ""
            csv_path = data_dir / f"servo_pid_{ts}{ff_tag}.csv"
            test_servo_pid(ip, dur, csv_path, servo_gains or None)

        if args.mode in ("pendulum", "both"):
            if args.mode == "both":
                print("\nWaiting 2s between tests...")
                time.sleep(2)
            dur = args.duration if args.duration > 0 else 38.0
            csv_path = data_dir / f"pend_pid_{ts}.csv"
            test_pendulum_pid(ip, dur, csv_path, pend_gains or None)

    finally:
        if not args.no_stop:
            send_cmd(ip, x=1)
            print("\nMotor stopped.")


if __name__ == "__main__":
    main()
