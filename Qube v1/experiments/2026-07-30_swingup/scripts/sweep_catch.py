"""P2 — Barrido del angulo de captura (`tn`): donde conviene entregar al LQR.

Medido el 2026-07-31: el bombeo llega a 179.8 deg. Traspasar en 155 entregaba el
pendulo a 25 deg de la vertical, muy fuera de la region donde un LQR linealizado
arriba tiene sentido. Aca se barre tn para ver donde el LQR realmente sostiene.

METRICA: no "traspaso" sino CAPTURA — cuanto tiempo se mantiene en m4 con |alpha|
cerca de 180. Un traspaso que dura 1 s no capturo nada.
"""
import csv, json, math, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube, DATA, SAMPLE_DT

UP_TOL = 25.0   # |180-|alpha|| por debajo de esto cuenta como "arriba"

def rest(q):
    t0, win = time.monotonic(), []
    while time.monotonic()-t0 < 40:
        win.append((time.monotonic(), float(q.state()["pend_position_deg"])))
        win=[(t,a) for t,a in win if time.monotonic()-t<=2.5]
        if len(win)>=12 and max(a for _,a in win)-min(a for _,a in win)<1.5: return True
        time.sleep(0.1)
    return False

def run(q, tn, secs=30.0):
    q.homing(); rest(q); q.cmd(zp=1)
    q.cmd(pl=0, pc=0, pr=70, sp=60, tr=1, tn=tn)
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic()-t0) < secs:
        try: d=q.state()
        except Exception: time.sleep(SAMPLE_DT); continue
        rows.append({"t_s":round(t,4),"mode":d.get("mode"),
                     "alpha_deg":d.get("pend_position_deg"),
                     "theta_deg":d.get("position_deg"),"pwm":d.get("pwm")})
        if d.get("mode")==0: break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)
    d=q.state()
    m4=[r for r in rows if r["mode"]==4]
    up=[r for r in m4 if abs(180.0-abs(float(r["alpha_deg"])))<UP_TOL]
    dt = (rows[1]["t_s"]-rows[0]["t_s"]) if len(rows)>1 else 0.08
    return {"tn":tn,
            "traspaso": len(m4)>0,
            "t_en_lqr_s": round(len(m4)*dt,2),
            "t_arriba_s": round(len(up)*dt,2),
            "alpha_al_traspasar": round(float(d.get("swing_trans_alpha",0)),1),
            "vel_al_traspasar": round(float(d.get("swing_trans_vel",0)),1),
            "E_al_traspasar": round(float(d.get("swing_trans_energy",0)),3),
            "alpha_max": round(max(abs(float(r["alpha_deg"])) for r in rows),1),
            "theta_max": round(max(abs(float(r["theta_deg"])) for r in rows),1),
            "murio": any(r["mode"]==0 for r in rows)}, rows

q=Qube("192.168.100.50"); out=[]
for tn in (175,):
    for rep in (1,2,3,4):
        print(f"\n--- tn={tn} rep{rep} ---")
        try: r,rows = run(q, tn)
        except Exception as e:
            print(f"    ERROR: {e}"); q.cmd(m=0, tn=155); continue
        r["rep"]=rep; print("    "+json.dumps(r)); out.append(r)
        with (DATA/f"catch_tn{tn}_r{rep}.csv").open("w",newline="",encoding="utf-8") as fh:
            w=csv.DictWriter(fh,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
q.cmd(m=0, tn=155)
(DATA/"sweep_catch.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("\n=== captura por angulo de traspaso ===")
print(f"{'tn':>5} {'traspasos':>10} {'t en LQR':>10} {'t ARRIBA':>10} {'alpha trasp':>12} {'E/E*':>7}")
for tn in (155,165,170,175):
    g=[r for r in out if r["tn"]==tn]
    if not g: continue
    print(f"{tn:>5} {sum(r['traspaso'] for r in g):>4}/{len(g):<5} "
          f"{statistics.mean(r['t_en_lqr_s'] for r in g):>10.2f} "
          f"{statistics.mean(r['t_arriba_s'] for r in g):>10.2f} "
          f"{statistics.mean(abs(r['alpha_al_traspasar']) for r in g):>12.1f} "
          f"{statistics.mean(r['E_al_traspasar'] for r in g):>7.3f}")
