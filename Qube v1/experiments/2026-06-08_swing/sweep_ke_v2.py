#!/usr/bin/env python3
"""ke sweep via HTTP with robust error handling."""

import time
import json
import urllib.request

IP = "192.168.100.50"
N = 3
DUR = 45
PAUSE = 3
KES = [0.60, 0.70, 0.80, 0.90]


def cmd(params):
    url = f"http://{IP}/cmd?{params}"
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    return {"error": "failed"}


def state():
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(f"http://{IP}/state", timeout=5)
            return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    return {}


# Verify connection
s = state()
if not s or "mode" not in s:
    print("ERROR: Cannot connect to ESP32 at", IP)
    exit(1)
print(f"Connected. mode={s['mode']}, v={s['v_bus']}")
print(f"ke Sweep: {KES} x {N} attempts x {DUR}s")
print("=" * 60)

for ke in KES:
    print(f"\n--- ke={ke} ---")
    cmd("x=1")
    time.sleep(1)
    cmd(f"ke={ke}")
    time.sleep(0.3)
    for i in range(1, N + 1):
        cmd("r=1")
        time.sleep(1)
        cmd("m=5")
        time.sleep(0.5)
        s0 = state()
        if s0.get("mode") != 5:
            print(f"  #{i}: FAILED to start (mode={s0.get('mode')})")
            continue
        t0 = time.monotonic()
        mx = 0.0
        lqr = 0
        prev_m = 5
        while time.monotonic() - t0 < DUR:
            s = state()
            t = time.monotonic() - t0
            p = abs(s.get("pend_position_deg", 0))
            m = s.get("mode", 0)
            if p > mx:
                mx = p
            if prev_m == 5 and m == 4:
                lqr += 1
            if m == 0 and t > 5:
                break
            prev_m = m
            time.sleep(0.05)
        cmd("x=1")
        time.sleep(0.5)
        f = state()
        sv = f.get("position_deg", 0)
        print(f"  #{i}: max={mx:5.1f} LQR={lqr} servo={sv:6.1f}")
        if i < N:
            time.sleep(PAUSE)
