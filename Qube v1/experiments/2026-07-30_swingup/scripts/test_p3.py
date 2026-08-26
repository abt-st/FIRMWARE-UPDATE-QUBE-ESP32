"""P3 — Verificacion del arreglo: homing inmediatamente despues de un swing-up.

Es el caso que fallaba. Se compara A/B en la MISMA tanda:
  - settle=0  : disparar el homing al instante (comportamiento viejo)
  - settle=8  : esperar a que el mecanismo se aquiete

Con el firmware nuevo, settle=0 deberia FALLAR con codigo 5 ("no se aquieto") en vez
de arrancar a ciegas y aceptar un cero corrido, que era el peligro real.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube

def agitar(q):
    """Deja el mecanismo como queda tras un intento real: swing-up 12 s y corte."""
    q.cmd(pl=0, sp=50, pc=0, pr=70)
    q.cmd(m=5); time.sleep(12.0); q.cmd(m=0)

def probar(q, settle):
    agitar(q)
    try:
        d = q.homing(settle=settle)
        return {"settle": settle, "ok": True, "range": d["homing_range"],
                "center": d["homing_center"], "fail": 0}
    except RuntimeError as e:
        return {"settle": settle, "ok": False, "error": str(e)}

q = Qube("192.168.100.50")
res = []
for settle in (0, 0, 8, 8):
    print(f"--- homing con settle={settle}s tras swing-up ---")
    r = probar(q, settle); print(f"    {json.dumps(r)}"); res.append(r)
    time.sleep(1)
q.cmd(m=0)
print()
for s in (0, 8):
    g = [r for r in res if r["settle"] == s]
    ok = sum(r["ok"] for r in g)
    rangos = [r["range"] for r in g if r.get("range")]
    extra = f"  recorridos={rangos}" if rangos else ""
    print(f"  settle={s}s -> {ok}/{len(g)} exitos{extra}")
