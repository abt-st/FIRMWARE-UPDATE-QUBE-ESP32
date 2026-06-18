#!/usr/bin/env python3
"""Fast ke sweep high values - 5 attempts x 45s."""

import time
import json
import urllib.request
import os

IP = "192.168.100.50"
ATTEMPTS = 5
DURATION = 45
PAUSE = 2
KE_VALUES = [0.60, 0.70, 0.80, 0.90]


def cmd(p):
    try:
        return json.loads(urllib.request.urlopen(f"http://{IP}/cmd?{p}", 3).read())
    except:
        return {}


def state():
    try:
        return json.loads(urllib.request.urlopen(f"http://{IP}/state", 2).read())
    except:
        return {}


print(f"High ke Sweep - {len(KE_VALUES)} values x {ATTEMPTS} attempts x {DURATION}s")
print("=" * 60)

for ke in KE_VALUES:
    print(f"\n--- ke={ke:.2f} ---")
    cmd("x=1")
    time.sleep(0.2)
    cmd(f"ke={ke}")
    for i in range(1, ATTEMPTS + 1):
        cmd("r=1")
        time.sleep(0.2)
        cmd("m=5")
        t0 = time.monotonic()
        mx = 0.0
        lqr = 0
        prev_m = 5
        while time.monotonic() - t0 < DURATION:
            s = state()
            t = time.monotonic() - t0
            p = abs(s.get("pend_position_deg", 0))
            m = s.get("mode", 0)
            if p > mx:
                mx = p
            if prev_m == 5 and m == 4:
                lqr += 1
            if m == 0 and t > 3:
                break
            prev_m = m
            time.sleep(0.05)
        cmd("x=1")
        time.sleep(0.3)
        f = state()
        print(f"  #{i}: max={mx:5.1f} LQR={lqr} servo={f.get('position_deg', 0):6.1f}")
        if i < ATTEMPTS:
            time.sleep(PAUSE)
