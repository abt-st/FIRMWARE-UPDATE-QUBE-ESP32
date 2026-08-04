"""P3 — Diagnostico: que mide exactamente el homing cuando falla."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube

q = Qube("192.168.100.50")
res = []
for i in range(1, 9):
    # Agitar como un intento real, alternando para no sesgar el lado de arranque
    q.cmd(pl=0, sp=50, pc=0, pr=70); q.cmd(m=5); time.sleep(10.0); q.cmd(m=0)
    time.sleep(4.0)
    q.cmd(m=3)
    fases, t0 = [], time.monotonic()
    d = None
    while time.monotonic() - t0 < 40:
        d = q.state()
        ph = d.get("homing_phase")
        if not fases or fases[-1][0] != ph:
            fases.append((ph, round(float(d["raw_position_deg"]), 1)))
        if ph in ("DONE", "FAIL"): break
        time.sleep(0.15)
    r = {"n": i, "fase": d.get("homing_phase"), "fail": d.get("homing_fail"),
         "range": d.get("homing_range"), "stop_pos": d.get("homing_stop_pos"),
         "stop_neg": d.get("homing_stop_neg"),
         "traza": " ".join(f"{p}@{v}" for p, v in fases)}
    print(json.dumps({k: v for k, v in r.items() if k != "traza"}))
    print(f"    {r['traza']}")
    res.append(r)
q.cmd(m=0)
ok = [r for r in res if r["fase"] == "DONE"]
bad = [r for r in res if r["fase"] == "FAIL"]
print(f"\n{len(ok)}/{len(res)} exitos")
if bad:
    print("fallos:")
    for r in bad:
        print(f"  range={r['range']} stop+={r['stop_pos']} stop-={r['stop_neg']} code={r['fail']}")
if ok:
    print(f"exitos: stop+={[r['stop_pos'] for r in ok]}")
    print(f"        stop-={[r['stop_neg'] for r in ok]}")
