#!/usr/bin/env python3
"""LQR stability test - configurable ke, 10 attempts x 90s.
Usage: python test_lqr.py [ke] [attempts] [duration]
"""

import sys
import time
import json
import urllib.request

IP = "192.168.100.50"
KE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.70
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
DUR = int(sys.argv[3]) if len(sys.argv) > 3 else 90
PAUSE = 3


def cmd(params):
    url = f"http://{IP}/cmd?{params}"
    for _ in range(3):
        try:
            urllib.request.urlopen(url, timeout=5)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def state():
    for _ in range(3):
        try:
            resp = urllib.request.urlopen(f"http://{IP}/state", timeout=5)
            return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    return {}


s = state()
if not s or "mode" not in s:
    print("ERROR: No ESP32")
    exit(1)

print(f"Setting ke={KE}, bt=1")
cmd(f"ke={KE}")
cmd("bt=1")
time.sleep(0.3)

print(f"LQR Test: {N} attempts x {DUR}s (ke={KE})")
print("=" * 60)

for i in range(1, N + 1):
    cmd("x=1")
    time.sleep(1)
    cmd("r=1")
    time.sleep(1)
    cmd("m=5")
    time.sleep(0.5)

    s0 = state()
    if s0.get("mode") != 5:
        print(f"  #{i}: FAILED (mode={s0.get('mode')})")
        time.sleep(2)
        continue

    t0 = time.monotonic()
    mx = 0.0
    lqr = 0
    max_hold = 0.0
    prev_m = 5
    lqr_start = 0.0

    while time.monotonic() - t0 < DUR:
        s = state()
        t = time.monotonic() - t0
        p = abs(s.get("pend_position_deg", 0))
        m = s.get("mode", 0)

        if p > mx:
            mx = p

        if prev_m == 5 and m == 4:
            lqr += 1
            lqr_start = t
        elif m == 4 and prev_m == 4:
            hold = t - lqr_start
            if hold > max_hold:
                max_hold = hold

        if m == 0 and t > 5:
            print(f"  #{i}: CRASH at {t:.1f}s")
            break
        prev_m = m
        time.sleep(0.05)

    cmd("x=1")
    time.sleep(0.5)
    f = state()
    sv = f.get("position_deg", 0)
    print(f"  #{i}: max={mx:5.1f} catches={lqr} hold={max_hold:.1f}s servo={sv:6.1f}")
    if i < N:
        time.sleep(PAUSE)
