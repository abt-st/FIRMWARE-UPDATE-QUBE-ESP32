"""P13 — Verificacion: el cero del pendulo debe sobrevivir a un swing-up con giro.

Protocolo: cerar con el pendulo colgando en reposo, correr swing-up fuerte hasta que
gire (que es cuando se dispara el acotado), volver al reposo, y comprobar que
`pend_position_deg` vuelve cerca de 0.

Antes del arreglo esto fallaba: el acotado ponia el cero donde estuviera el pendulo,
asi que colgando podia leer 98 deg. Ahora deberia restar vueltas enteras y conservar
la referencia. `pend_wraps` dice cuantas veces se acoto — si es 0 la prueba no probo
nada, porque el camino que fallaba no se ejercito.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube

REST_PP, HOLD, TMO = 1.5, 2.5, 45.0

def wait_rest(q):
    q.cmd(m=0); t0, win = time.monotonic(), []
    while time.monotonic() - t0 < TMO:
        win.append((time.monotonic(), float(q.state()["pend_position_deg"])))
        win = [(t,a) for t,a in win if time.monotonic()-t <= HOLD]
        if len(win) >= 12 and max(a for _,a in win)-min(a for _,a in win) < REST_PP:
            return True
        time.sleep(0.1)
    return False

q = Qube("192.168.100.50")
res = []
for i in (1, 2, 3):
    q.homing()
    if not wait_rest(q):
        print(f"  intento {i}: no llego a reposo, se salta"); continue
    q.cmd(zp=1)
    a0 = float(q.state()["pend_position_deg"])

    # Swing-up fuerte para forzar giro y por lo tanto el acotado
    q.cmd(pl=0, pc=0, pr=70, sp=80); q.cmd(m=5)
    t0, amax = time.monotonic(), 0.0
    while time.monotonic() - t0 < 22:
        d = q.state(); amax = max(amax, abs(float(d["pend_position_deg"])))
        if d.get("mode") == 0: break
        time.sleep(0.05)
    q.cmd(m=0)

    ok_rest = wait_rest(q)
    d = q.state()
    a1 = float(d["pend_position_deg"])
    r = {"intento": i, "alpha_al_cerar": round(a0,2), "alpha_max_durante": round(amax,1),
         "pend_wraps": d.get("pend_wraps"), "alpha_final_colgando": round(a1,2),
         "deriva_del_cero": round(abs(a1-a0),2), "reposo_final": ok_rest}
    print(json.dumps(r)); res.append(r)

q.cmd(m=0, sp=60)
print()
usados = [r for r in res if (r["pend_wraps"] or 0) > 0]
print(f"corridas que ejercitaron el acotado: {len(usados)}/{len(res)}")
if usados:
    d = [r["deriva_del_cero"] for r in usados]
    print(f"deriva del cero tras girar: {min(d):.2f}–{max(d):.2f} deg")
    print("VEREDICTO:", "PASA (el cero sobrevive)" if max(d) < 10 else "FALLA (el cero se corrio)")
