#!/usr/bin/env python3
"""bt sweep via HTTP with ke=0.70."""
import time
import json
import urllib.request

IP = "192.168.100.50"
N = 5
DUR = 45
PAUSE = 3
BT_VALS = [1, 3, 5, 8, 10]
KE = 0.70


def cmd(params):
    url = f"http://{IP}/cmd?{params}"
    for _ in range(3):
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    return {"error": "failed"}


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
    print("ERROR: Cannot connect to ESP32")
    exit(1)
print(f"Connected. Setting ke={KE}")
cmd(f"ke={KE}")
time.sleep(0.3)
print(f"bt Sweep: {BT_VALS} x {N} attempts x {DUR}s (ke={KE})")
print("=" * 60)

all_results = []
for bt in BT_VALS:
    print(f"\n--- bt={bt} ---")
    cmd("x=1")
    time.sleep(1)
    cmd(f"bt={bt}")
    time.sleep(0.3)
    catches = 0
    for i in range(1, N + 1):
        cmd("r=1")
        time.sleep(1)
        cmd("m=5")
        time.sleep(0.5)
        s0 = state()
        if s0.get("mode") != 5:
            print(f"  #{i}: FAILED (mode={s0.get('mode')})")
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
        hit = "*" if lqr > 0 else " "
        if lqr > 0:
            catches += 1
        print(f"  #{i}{hit}: max={mx:5.1f} LQR={lqr} servo={sv:6.1f}")
        if i < N:
            time.sleep(PAUSE)
    all_results.append({"bt": bt, "catches": catches, "total": N})
    print(f"  => catch rate: {catches}/{N}")

print("\n" + "=" * 60)
print(f"{'bt':>4} {'catch':>8}")
print("-" * 15)
for r in all_results:
    print(f"{r['bt']:4d} {r['catches']:>4}/{r['total']}")
