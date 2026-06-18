#!/usr/bin/env python3
"""Test different ke/centering combos. 5 attempts x 60s each."""

import time, json, urllib.request

IP = "192.168.100.50"
N = 5
DUR = 60
PAUSE = 3
# (ke, centering_kp_via_http_not_available) - centering requires recompile
# So test ke only: 0.65, 0.70, 0.75 with current centering=0.15
# Then we'll know if ke matters more
KES = [0.60, 0.65, 0.70]


def cmd(p):
    try:
        urllib.request.urlopen(f"http://{IP}/cmd?{p}", timeout=5)
    except:
        pass


def st():
    try:
        return json.loads(urllib.request.urlopen(f"http://{IP}/state", timeout=5).read())
    except:
        return {}


s = st()
if not s or "mode" not in s:
    print("ERROR: No ESP32")
    exit(1)
print(f"Connected. ke Sweep: {KES} x {N} x {DUR}s")
print("=" * 60)

results = {}
for ke in KES:
    print(f"\n--- ke={ke} ---")
    cmd("x=1")
    time.sleep(1)
    cmd(f"ke={ke}")
    time.sleep(0.3)
    heights = []
    catches = 0
    crashes = 0
    for i in range(1, N + 1):
        cmd("r=1")
        time.sleep(1)
        cmd("m=5")
        time.sleep(0.5)
        s0 = st()
        if s0.get("mode") != 5:
            print(f"  #{i}: FAILED")
            time.sleep(2)
            continue
        t0 = time.monotonic()
        mx = 0.0
        lqr = 0
        prev_m = 5
        crash = False
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
                crash = True
                break
            prev_m = m
            time.sleep(0.05)
        cmd("x=1")
        time.sleep(0.5)
        heights.append(mx)
        if lqr > 0:
            catches += 1
        if crash:
            crashes += 1
        marker = "*" if mx >= 150 else " "
        crash_s = " CRASH" if crash else ""
        print(f"  #{i}{marker}: max={mx:5.1f} LQR={lqr}{crash_s}")
        if i < N:
            time.sleep(PAUSE)
    above = sum(1 for h in heights if h >= 150)
    avg = sum(heights) / len(heights) if heights else 0
    results[ke] = {"avg": avg, "above150": above, "catches": catches, "crashes": crashes}
    print(f"  => avg={avg:.1f} >=150: {above}/{N} catches={catches}/{N} crashes={crashes}/{N}")

print("\n" + "=" * 60)
print(f"{'ke':>6} {'avg':>7} {'>=150':>7} {'catch':>7} {'crash':>7}")
print("-" * 37)
for ke in KES:
    r = results[ke]
    print(f"{ke:6.2f} {r['avg']:6.1f} {r['above150']:>3}/{N} {r['catches']:>3}/{N} {r['crashes']:>3}/{N}")
