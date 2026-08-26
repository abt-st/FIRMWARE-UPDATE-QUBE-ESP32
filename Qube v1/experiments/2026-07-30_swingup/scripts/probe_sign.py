"""Sondeo corto y de baja potencia para determinar el signo de la ley de energia.

Se hace aparte y con PWM reducido porque el primer intento a PWM 50 dejo la placa sin
responder: con el signo invertido la ley no bombea, empuja el brazo en un solo sentido
contra el tope, y el calado del motor tira la tension (mismo mecanismo que el brownout
ya documentado). Aborta desde el cliente en cuanto |theta| pasa de 70.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube

ABORT_THETA = 70.0

def homing_retry(q, n=3):
    # El homing falla ~1 de cada 4 veces tras modos energeticos (P3: calado falso con
    # el pendulo agitado). Reintentar es la mitigacion practica mientras la causa raiz
    # siga abierta; se deja pausa para que el pendulo se aquiete.
    for i in range(n):
        try:
            return q.homing()
        except RuntimeError as e:
            if i == n-1: raise
            print(f"    homing fallo ({e}); reintento {i+2}/{n}")
            time.sleep(3.0)

def probe(q, pn, secs=6.0, cap=35):
    homing_retry(q)
    q.cmd(pl=1, sp=cap, pc=0, pn=pn, pg=8000)
    q.cmd(m=5)
    t0, amax, tmax, abortado = time.monotonic(), 0.0, 0.0, False
    while time.monotonic() - t0 < secs:
        try: d = q.state()
        except Exception: time.sleep(0.05); continue
        a, th = abs(float(d["pend_position_deg"])), abs(float(d["position_deg"]))
        amax, tmax = max(amax, a), max(tmax, th)
        if th > ABORT_THETA:
            abortado = True; break
        if d.get("mode") == 0: break
        time.sleep(0.04)
    q.cmd(m=0)
    return {"pn": pn, "alpha_max": round(amax,1), "theta_max": round(tmax,1),
            "abortado": abortado}

q = Qube("192.168.100.50")
res = []
for pn in (1, -1, 1):
    print(f"--- sondeo pn={pn:+d} (PWM tope 35, {6}s) ---")
    try:
        r = probe(q, pn); print(f"    {json.dumps(r)}"); res.append(r)
    except Exception as e:
        print(f"    ERROR: {e}")
        try: q.cmd(m=0)
        except Exception: pass
    time.sleep(1.5)
q.cmd(m=0, pl=0, sp=50, pc=0, pr=70)
print("\nEl signo correcto es el que hace crecer alpha sin llevarse el brazo al tope.")
print(json.dumps(res))
