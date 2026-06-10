#!/usr/bin/env python3
"""Fast ke sweep via HTTP — 3 attempts x 30s per ke."""
import time
import json
import urllib.request
import csv
import os

IP = "192.168.100.50"
ATTEMPTS = 3
DURATION = 30
PAUSE = 2
KE_VALUES = [0.40, 0.50, 0.55, 0.60, 0.70]
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def cmd(params: str) -> dict:
    try:
        resp = urllib.request.urlopen(f"http://{IP}/cmd?{params}", timeout=3)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def state() -> dict:
    try:
        resp = urllib.request.urlopen(f"http://{IP}/state", timeout=2)
        return json.loads(resp.read())
    except Exception:
        return {}


print(f"QUBE Fast ke Sweep - {len(KE_VALUES)} values x {ATTEMPTS} attempts x {DURATION}s")
print("=" * 60)

all_results = []
for ke in KE_VALUES:
    print(f"\n--- ke={ke:.2f} ---")
    cmd("x=1")
    time.sleep(0.2)
    cmd(f"ke={ke}")
    results = []
    for i in range(1, ATTEMPTS + 1):
        cmd("r=1")
        time.sleep(0.2)
        cmd("m=5")
        t0 = time.monotonic()
        max_ang = 0.0
        lqr = 0
        prev_m = 5
        n_samples = 0
        while time.monotonic() - t0 < DURATION:
            s = state()
            t = time.monotonic() - t0
            p = abs(s.get("pend_position_deg", 0))
            m = s.get("mode", 0)
            if p > max_ang:
                max_ang = p
            if prev_m == 5 and m == 4:
                lqr += 1
            if m == 0 and t > 3:
                break
            prev_m = m
            n_samples += 1
            time.sleep(0.05)
        cmd("x=1")
        time.sleep(0.3)
        fin = state()
        r = {"ke": ke, "i": i, "max": round(max_ang, 1), "lqr": lqr,
             "servo": round(fin.get("position_deg", 0), 1),
             "pend": round(fin.get("pend_position_deg", 0), 1)}
        results.append(r)
        print(f"  #{i}: max={max_ang:5.1f} LQR={lqr} servo={r['servo']}")
        if i < ATTEMPTS:
            time.sleep(PAUSE)
    all_results.extend(results)

print("\n" + "=" * 60)
print(f"{'ke':>6} {'avg':>7} {'best':>7} {'catch':>7}")
print("-" * 30)
for ke in KE_VALUES:
    kr = [r for r in all_results if r["ke"] == ke]
    if kr:
        mx = [r["max"] for r in kr]
        c = sum(1 for r in kr if r["lqr"] > 0)
        print(f"{ke:6.2f} {sum(mx)/len(mx):7.1f} {max(mx):7.1f} {c:>3}/{ATTEMPTS}")
