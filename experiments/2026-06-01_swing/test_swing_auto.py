"""
Automated swing-up test with crash detection and auto-retry.
Connects to ESP32 via HTTP, runs swing-up, records data,
detects motor crashes, stops and retries.

Usage: uv run python experiments/2026-06-01_swing/test_swing_auto.py
"""
import csv
import time
import urllib.request
import json
import math
from pathlib import Path
from datetime import datetime

ESP32_IP = "192.168.100.50"
BASE_URL = f"http://{ESP32_IP}"
POLL_S = 0.1
TEST_DURATION_S = 45
STABILIZE_WAIT_S = 8
MAX_ATTEMPTS = 6

OUTPUT_DIR = Path(__file__).parent
timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")


def http_get(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def send_cmd(params: str):
    return http_get(f"{BASE_URL}/cmd?{params}")


def get_state():
    return http_get(f"{BASE_URL}/state", timeout=1.0)


def norm_angle(deg: float) -> float:
    """Normalize to [-180, 180]."""
    deg = deg % 360
    if deg > 180:
        deg -= 360
    elif deg < -180:
        deg += 360
    return deg


def pend_upright_norm(pend_raw: float) -> float:
    """Normalize pendulum angle relative to upright (0=upright)."""
    return norm_angle(pend_raw - 180.0)


def detect_crash(history: list, current: dict):
    if len(history) < 20:
        return None

    recent = history[-20:]
    pwms = [r.get("pwm", 0) for r in recent]
    positions = [r.get("position_deg", 0) for r in recent]

    all_sat_pos = all(p > 95 for p in pwms)
    all_sat_neg = all(p < -95 for p in pwms)

    # Only flag if BOTH servo is stuck AND pendulum is NOT oscillating
    # (pendulum moving = normal swing-up, not a crash)
    pend_positions = [r.get("pend_position_deg", 0) for r in recent]
    pend_range = max(pend_positions) - min(pend_positions) if len(pend_positions) > 1 else 0

    if all_sat_pos or all_sat_neg:
        pos_range = max(positions) - min(positions)
        # Servo stuck AND pendulum also not moving = crash
        if pos_range < 2.0 and pend_range < 30.0:
            return f"CRASH: Servo stuck + pendulum stalled (srv_range={pos_range:.1f}, pend_range={pend_range:.1f})"

    servo = current.get("position_deg", 0)
    if servo is not None and abs(servo) > 170:
        return f"CRASH: Servo at {servo:.1f}deg (mechanical limit)"

    return None


def is_stabilized(history: list, window_s: float = 3.0) -> bool:
    """Check if pendulum stayed within 15deg of upright for window_s seconds."""
    if not history:
        return False
    window_samples = int(window_s / POLL_S)
    if len(history) < window_samples:
        return False
    recent = history[-window_samples:]
    for r in recent:
        if r.get("mode") != 4:
            return False
        p = r.get("pend_position_deg")
        if p is None:
            return False
        if abs(pend_upright_norm(p)) > 15:
            return False
    return True


def run_single_test(attempt: int):
    print(f"\n{'='*60}")
    print(f"  TEST {attempt}: Starting swing-up (m=5)")
    print(f"{'='*60}")

    resp = send_cmd("m=5")
    if resp is None:
        return [], "ERROR: Could not send m=5"
    actual_mode = resp.get("mode")
    print(f"  Response mode={actual_mode}")
    if actual_mode != 5:
        return [], f"ERROR: Mode is {actual_mode}, expected 5"

    history = []
    start = time.time()
    crash_reason = None
    lqr_seen = False

    while True:
        elapsed = time.time() - start
        if elapsed > TEST_DURATION_S:
            print(f"  Timeout after {TEST_DURATION_S}s")
            break

        state = get_state()
        if state is None:
            time.sleep(POLL_S)
            continue

        state["time_s"] = round(elapsed, 3)
        history.append(state)

        mode = state.get("mode", 0)
        pwm = state.get("pwm", 0)
        pend = state.get("pend_position_deg", 0)
        pos = state.get("position_deg", 0)

        if len(history) % 10 == 0:
            n = pend_upright_norm(pend) if pend is not None else 0
            print(f"  t={elapsed:5.1f}s M={mode} pend={pend:7.1f}(n={n:6.1f}) srv={pos:7.1f} PWM={pwm:4d}")

        if mode == 4 and not lqr_seen:
            lqr_seen = True
            print(f"  >> LQR active at t={elapsed:.1f}s")

        if is_stabilized(history):
            print(f"  >> STABILIZED! Within 15deg for 3s")
            for _ in range(30):
                s = get_state()
                if s:
                    s["time_s"] = round(time.time() - start, 3)
                    history.append(s)
                time.sleep(POLL_S)
            break

        crash_reason = detect_crash(history, state)
        if crash_reason:
            print(f"  !! {crash_reason}")
            send_cmd("x")
            print(f"  >> Emergency stop")
            time.sleep(1)
            break

        if mode == 0 and elapsed > 2 and len(history) > 5:
            print(f"  >> Mode back to 0 at t={elapsed:.1f}s")
            break

        time.sleep(POLL_S)

    if is_stabilized(history):
        result = "STABILIZED"
    elif crash_reason:
        result = crash_reason
    elif lqr_seen:
        result = "LQR active, not stabilized"
    else:
        result = "No swing-up"

    print(f"  Result: {result} ({len(history)} samples)")
    return history, result


def save_data(data: list, attempt: int) -> Path:
    filename = OUTPUT_DIR / f"test_{timestamp}_attempt{attempt}.csv"
    if not data:
        return filename
    fields = ["time_s", "mode", "position_deg", "setpoint_deg",
              "pend_position_deg", "pwm", "voltage_v", "current_mA", "power_mW"]
    with open(filename, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for r in data:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"  Saved: {filename.name}")
    return filename


def main():
    print(f"QUBE Swing-Up Automated Test")
    print(f"ESP32: {ESP32_IP}")
    print(f"Max attempts: {MAX_ATTEMPTS}, Duration: {TEST_DURATION_S}s each")

    state = get_state()
    if state is None:
        print("ERROR: Cannot connect to ESP32")
        return
    print(f"Connected. Mode={state.get('mode')}, Pend={state.get('pend_position_deg')}")

    send_cmd("x")
    time.sleep(1)

    results = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        data, result = run_single_test(attempt)
        save_data(data, attempt)
        results.append((attempt, result, len(data)))

        if "STABILIZED" in result:
            print(f"\n  SUCCESS on attempt {attempt}!")
            break

        if attempt < MAX_ATTEMPTS:
            print(f"\n  Reset + waiting {STABILIZE_WAIT_S}s to settle...")
            send_cmd("x")
            time.sleep(1)
            send_cmd("r")  # Reset encoders and offsets
            time.sleep(STABILIZE_WAIT_S)
            s = get_state()
            if s:
                print(f"  Settled. Pend={s.get('pend_position_deg')} Servo={s.get('position_deg')} PWM={s.get('pwm')}")

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    for a, r, n in results:
        ok = "+" if "STABILIZED" in r else "-"
        print(f"  [{ok}] Attempt {a}: {r} ({n} samples)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
