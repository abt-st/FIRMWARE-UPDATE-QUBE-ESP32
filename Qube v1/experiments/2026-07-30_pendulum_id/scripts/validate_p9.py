"""P9 — Validacion empirica de la ganancia del estimador de velocidad.

Independiente del analisis del filtro: en oscilacion libre, la conservacion de
energia liga la amplitud del apice con la velocidad al pasar por cero,
    alpha_dot(0) = wn * sqrt(2 (1 - cos A))
con wn = 14.34 rad/s medida por el periodo (2026-07-30_pendulum_id).

Se compara esa prediccion contra lo que REPORTA el firmware (`ald` de /rl_state, el
mismo rl_vf_alVel). El cociente deberia dar ~1.52, la ganancia calculada del filtro.

Se muestrea en modo 6 con accion 0: es el unico modo que tickea updateRlObservation
sin aplicar par (en modo 0 la observacion queda vieja).
"""
import json, math, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "2026-07-30_swingup" / "scripts"))
from sweep_pumpref import Qube

WN = 14.34
q = Qube("192.168.100.50")

def rl(): 
    return q.s.get("http://192.168.100.50/rl_state", timeout=2).json()

def rest():
    t0, win = time.monotonic(), []
    while time.monotonic() - t0 < 40:
        win.append((time.monotonic(), float(q.state()["pend_position_deg"])))
        win = [(t,a) for t,a in win if time.monotonic()-t <= 2.5]
        if len(win) >= 12 and max(a for _,a in win)-min(a for _,a in win) < 1.5: return True
        time.sleep(0.1)
    return False

out=[]
for k in (1,2,3):
    q.homing(); rest(); q.cmd(zp=1)
    q.cmd(m=1); q.cmd(p=70); time.sleep(0.18); q.cmd(p=-70); time.sleep(0.18)
    q.cmd(m=6)
    q.s.get("http://192.168.100.50/rl_cmd", params={"a":"0.0"}, timeout=2)
    tr=[]; t0=time.monotonic()
    while time.monotonic()-t0 < 12:
        d=rl(); tr.append((math.degrees(abs(float(d["al"]))), abs(float(d["ald"]))))
        time.sleep(0.03)
    q.cmd(m=0)
    # amplitud: mayor |alpha| visto en el primer tercio (antes de amortiguarse)
    A_deg = max(a for a,_ in tr[:len(tr)//3])
    # alpha_dot reportado cerca del paso por cero, en el mismo tramo
    cerca = [v for a,v in tr[:len(tr)//3] if a < 8.0]
    if not cerca: 
        print(f"  corrida {k}: sin muestras cerca de cero"); continue
    v_rep = max(cerca)
    # alpha medido desde colgando; A_deg es el apice respecto de colgando
    A = math.radians(A_deg)
    v_pred = WN*math.sqrt(max(2*(1-math.cos(A)),0))
    out.append(v_rep/v_pred)
    print(f"  corrida {k}: A={A_deg:5.1f} deg  alpha_dot predicho={v_pred:6.2f} rad/s  "
          f"reportado={v_rep:6.2f}  cociente={v_rep/v_pred:.3f}")
q.cmd(m=0)
if out:
    m=sum(out)/len(out)
    print(f"\ncociente medio: {m:.3f}   (ganancia calculada del filtro: 1.520)")
    print("VEREDICTO:", "coherente" if abs(m-1.52)<0.25 else f"NO coincide (dif {abs(m-1.52):.2f})")
