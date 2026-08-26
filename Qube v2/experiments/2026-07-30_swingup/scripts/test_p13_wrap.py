"""P13 — Prueba discriminante del acotado por vueltas.

Se fuerza un offset artificial para que `pend_position_deg` lea ~400 deg y se entra
brevemente a m4, donde la proteccion del LQR corta el motor (pwm=0) ANTES del
fallback — asi la rama del acotado se ejercita sin mover el mecanismo.

Prediccion que separa las dos implementaciones:
  - viejo (cero donde este)   -> 0 deg   (pierde la referencia)
  - nuevo (resta una vuelta)  -> 40 deg  (400 - 360, conserva la referencia)
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube

q = Qube("192.168.100.50")
q.homing()                      # brazo dentro de limites, si no m4 se auto-mata
time.sleep(1.0)

d = q.state()
raw = float(d["pend_raw_position_deg"]); w0 = int(d["pend_wraps"])
print(f"antes: raw={raw:.2f} offset={float(d['pend_offset_deg']):.2f} "
      f"pos={float(d['pend_position_deg']):.2f} wraps={w0}")

q.cmd(op=raw - 400.0)           # ahora pos = raw - (raw-400) = 400
d = q.state()
print(f"tras forzar offset: pos={float(d['pend_position_deg']):.2f} (se busca ~400)")

q.cmd(m=4); time.sleep(0.6); q.cmd(m=0); time.sleep(0.4)

d = q.state()
pos = float(d["pend_position_deg"]); w1 = int(d["pend_wraps"])
print(f"despues: pos={pos:.2f}  wraps={w1} (delta {w1-w0})")
print()
if w1 == w0:
    print("INCONCLUSO: el acotado no se ejercito")
elif abs(pos - 40.0) < 15:
    print("PASA: resto una vuelta entera y conservo la referencia fisica")
elif abs(pos) < 15:
    print("FALLA: puso el cero donde estaba (comportamiento viejo)")
else:
    print(f"INESPERADO: pos={pos:.2f}")
q.cmd(m=0)
