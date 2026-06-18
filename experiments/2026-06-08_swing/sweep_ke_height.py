#!/usr/bin/env python3
"""Fast ke sweep - measure how often pendulum reaches 150°+. 5 attempts x 45s."""

import time, json, urllib.request

IP = "192.168.100.50"
N = 5
DUR = 45
PAUSE = 2
KES = [0.60, 0.65, 0.70, 0.75, 0.80]


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
print(f"Connected. ke Sweep for height: {KES} x {N} x {DUR}s")
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
        heights.append(mx)
        if lqr > 0:
            catches += 1
        hit = "*" if mx >= 150 else " "
        print(f"  #{i}{hit}: max={mx:5.1f} LQR={lqr}")
        if i < N:
            time.sleep(PAUSE)
    pct_above = sum(1 for h in heights if h >= 150) / len(heights) * 100 if heights else 0
    avg_h = sum(heights) / len(heights) if heights else 0
    results[ke] = {"avg": avg_h, "pct150": pct_above, "catches": catches}
    print(f"  => avg={avg_h:.1f} >=150: {pct_above:.0f}% catches={catches}/{N}")

print("\n" + "=" * 60)
print(f"{'ke':>6} {'avg':>7} {'>=150':>7} {'catch':>7}")
print("-" * 30)
for ke in KES:
    r = results[ke]
    print(f"{ke:6.2f} {r['avg']:6.1f} {r['pct150']:6.0f}% {r['catches']:>3}/{N}")
