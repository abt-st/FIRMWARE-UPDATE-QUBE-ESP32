#!/usr/bin/env python3
"""ke sweep - 3 attempts x 45s per value, with delays."""

import time, json, urllib.request, os

IP = "192.168.100.50"
N = 3
DUR = 45
PAUSE = 3
KES = [0.60, 0.70, 0.80, 0.90]


def cmd(p):
    try:
        return json.loads(urllib.request.urlopen(f"http://{IP}/cmd?{p}", 3).read())
    except:
        return {}


def st():
    try:
        return json.loads(urllib.request.urlopen(f"http://{IP}/state", 2).read())
    except:
        return {}


print(f"ke Sweep: {KES} x {N} attempts x {DUR}s")
for ke in KES:
    print(f"\n--- ke={ke} ---")
    cmd("x=1")
    time.sleep(1)
    cmd(f"ke={ke}")
    time.sleep(0.2)
    for i in range(1, N + 1):
        cmd("r=1")
        time.sleep(1)
        cmd("m=5")
        time.sleep(0.5)
        # Verify it started
        s0 = st()
        if s0.get("mode") != 5:
            print(f"  #{i}: FAILED to start mode 5 (got mode={s0.get('mode')})")
            continue
        t0 = time.monotonic()
        mx = 0.0
        lqr = 0
        prev_m = 5
        while time.monotonic() - t0 < DUR:
            s = st()
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
        f = st()
        sv = f.get("position_deg", 0)
        print(f"  #{i}: max={mx:5.1f} LQR={lqr} servo={sv:6.1f}")
        if i < N:
            time.sleep(PAUSE)
