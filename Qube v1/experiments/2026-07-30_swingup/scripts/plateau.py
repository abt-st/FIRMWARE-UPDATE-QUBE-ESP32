"""P2 — Donde plafona REALMENTE el bombeo, con el traspaso desactivado.

Motivo: a sp=50 la meseta (145 deg) se midio sobre 25 s sin traspaso. A sp=60 el
traspaso dispara a ~155 y la corrida TERMINA ahi, asi que solo sabemos que el bombeo
PASA por 155, no donde se detiene. Con `tr=0` el modo 5 bombea indefinidamente.

Metrica: mediana del ultimo tercio de los picos (la meseta), y ademas el pico maximo.
Se registra `pend_wraps` para saber si el pendulo llego a girar — si gira, el bombeo
ya supero la energia de la vertical y la meseta deja de tener sentido como techo.
"""
import json, math, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube, peaks_of, DATA, SAMPLE_DT

def rest(q):
    t0, win = time.monotonic(), []
    while time.monotonic() - t0 < 40:
        win.append((time.monotonic(), float(q.state()["pend_position_deg"])))
        win = [(t,a) for t,a in win if time.monotonic()-t <= 2.5]
        if len(win) >= 12 and max(a for _,a in win)-min(a for _,a in win) < 1.5: return True
        time.sleep(0.1)
    return False

def run(q, sp, secs):
    q.homing(); rest(q); q.cmd(zp=1)
    w0 = int(q.state()["pend_wraps"])
    q.cmd(pl=0, pc=0, pr=70, sp=sp, tr=0)      # traspaso DESACTIVADO
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic()-t0) < secs:
        try: d = q.state()
        except Exception: time.sleep(SAMPLE_DT); continue
        rows.append({"t_s": round(t,4), "mode": d.get("mode"),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"), "pwm": d.get("pwm")})
        if d.get("mode") == 0: break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)
    w1 = int(q.state()["pend_wraps"])
    inm = [r for r in rows if r["mode"] == 5]
    pk = peaks_of(inm)
    tail = [v for _,v in pk[len(pk)*2//3:]] if len(pk) >= 9 else [v for _,v in pk]
    mes = statistics.median(tail) if tail else 0.0
    return {"sp": sp, "picos": len(pk), "meseta": round(mes,1),
            "E_meseta": round((1-math.cos(math.radians(min(mes,180))))/2, 4),
            "pico_max": round(max((v for _,v in pk), default=0.0),1),
            "wraps": w1-w0,
            "theta_max": round(max(abs(float(r["theta_deg"])) for r in inm),1) if inm else 0,
            "t_bombeo": round(inm[-1]["t_s"],1) if inm else 0,
            "murio": any(r["mode"]==0 for r in rows)}, rows

q = Qube("192.168.100.50")
out=[]
for sp in (60,):
    for rep in (1,2,3):
        print(f"\n--- sp={sp} rep{rep}  (traspaso OFF, 30 s) ---")
        try: r,rows = run(q, sp, 30.0)
        except Exception as e:
            print(f"    ERROR: {e}"); q.cmd(m=0, tr=1); continue
        r["rep"]=rep; print("    "+json.dumps(r)); out.append(r)
        with (DATA/f"plateau_sp{sp}_r{rep}.csv").open("w",newline="",encoding="utf-8") as fh:
            import csv; w=csv.DictWriter(fh,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
q.cmd(m=0, tr=1, sp=60)     # restaurar
(DATA/"plateau.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("\n=== meseta real con traspaso desactivado ===")
for sp in (50,60):
    g=[r for r in out if r["sp"]==sp]
    if not g: continue
    print(f"  sp={sp}: meseta {statistics.mean(r['meseta'] for r in g):.1f} deg  "
          f"E/E*={statistics.mean(r['E_meseta'] for r in g):.3f}  "
          f"pico max {max(r['pico_max'] for r in g):.1f}  "
          f"wraps={[r['wraps'] for r in g]}  ciclos={[r['picos'] for r in g]}")
