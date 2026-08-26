"""Distingue un pendulo trabado de un encoder trabado. Motor apagado.

La pregunta. El 2026-08-05 el pendulo, soltado desde ~50 grados, bajo al reposo SIN oscilar
ni una vez, con mesetas de hasta 4,25 s sin cambiar un solo conteo de encoder. Eso es
compatible con dos cosas muy distintas:

  friccion seca en el pivote  -> la lectura sigue el movimiento, pero la planta se traba
  encoder trabado o con fallo -> la lectura se pega aunque el pendulo se mueva

Se separan moviendo el pendulo A MANO, despacio, de un extremo al otro, y mirando si la
lectura acompana de forma continua. Con el motor apagado: hay una mano en el mecanismo.

Que se reporta:
  - conteos distintos vistos y rango recorrido: si el rango es amplio y los conteos pocos,
    el encoder pierde resolucion.
  - saltos: diferencias grandes entre muestras consecutivas a 500 Hz. Un movimiento lento
    de la mano no puede producirlos; un encoder que se despega, si.
  - mesetas: tramos sin cambiar un conteo mientras la mano se mueve.

Uso:
    uv run python encoder_probe.py --seconds 30
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--seconds", type=float, default=30.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    link.send({"m": 0})  # motor apagado: hay una mano en el mecanismo
    time.sleep(0.2)

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / "encoder_probe.csv")
    rec.open()
    parts = []
    stream.start()
    print(f"  grabando {args.seconds:.0f} s — mover el pendulo despacio de un extremo al otro")
    try:
        end = time.perf_counter() + args.seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for c in stream.drain():
                rec.write(c)
                parts.append((c.t_s, c.al_deg, c.th_deg, c.pwm))
    finally:
        stream.stop()
        for c in stream.drain():
            rec.write(c)
            parts.append((c.t_s, c.al_deg, c.th_deg, c.pwm))
        rec.close()
        link.send({"m": 0})

    t = np.concatenate([p[0] for p in parts])
    al = np.concatenate([p[1] for p in parts])
    th = np.concatenate([p[2] for p in parts])
    pwm = np.concatenate([p[3] for p in parts])
    t = t - t[0]

    rng = float(al.max() - al.min())
    uniq = np.unique(al)
    step = float(np.median(np.diff(uniq))) if uniq.size > 1 else float("nan")
    d = np.diff(al)
    moving = np.abs(d) > 0
    # mesetas: tramos consecutivos sin cambio alguno
    runs, n = [], 0
    for s in (~moving):
        if s:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    runs = np.array(runs) / 500.0 if runs else np.array([0.0])
    jumps = np.abs(d)[moving]

    print(f"\n  motor: |pwm| max {np.abs(pwm).max():.0f}   brazo: excursion {th.max() - th.min():.1f} deg")
    print(f"  alpha recorrido: {rng:.1f} deg   valores distintos: {uniq.size}")
    print(f"  paso mediano entre valores contiguos: {step:.3f} deg")
    print(f"  saltos entre muestras (500 Hz): mediana {np.median(jumps):.3f}  "
          f"p99 {np.percentile(jumps, 99):.3f}  max {jumps.max():.3f} deg")
    print(f"  mesetas sin cambiar un conteo: mediana {np.median(runs):.3f} s   "
          f"max {runs.max():.2f} s   (>0,5 s: {int((runs > 0.5).sum())})")

    print("\n  Lectura:")
    if rng < 20.0:
        print("    El pendulo casi no se movio; repetir recorriendo un rango amplio.")
        return
    sospecha_encoder = runs.max() > 0.5 or jumps.max() > 5.0
    if sospecha_encoder:
        print("    >> SOSPECHA DE ENCODER. Con la mano moviendo de forma continua no puede")
        print("       haber mesetas largas ni saltos grandes. Revisar el disco, el sensor y")
        print("       el cableado del acondicionador antes de tocar nada de control.")
    else:
        print("    >> El encoder SIGUE el movimiento sin mesetas ni saltos. Entonces lo que")
        print("       se trabo el 2026-08-05 es el PENDULO, no la medicion: friccion seca en")
        print("       el pivote. Es un problema mecanico y ningun ajuste de control lo tapa.")


if __name__ == "__main__":
    main()
