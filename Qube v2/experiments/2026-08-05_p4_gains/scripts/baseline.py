"""Linea base del swing-up: 3 intentos que dicen si el banco sirve como instrumento.

Por que existe. El 2026-08-05 el swing-up se degrado a lo largo de la jornada —bombeo
mediano de 5,5 a 13,6 s, theta en bombeo de 69 a 94,7 grados, traspasos de 15/15 a 2/5— y
eso invalido comparaciones entre tandas y obligo a abortar un barrido en la rep 1. Correr
esto ANTES de cada tanda cuesta tres minutos y ese dia habria ahorrado dos barridos.

No mide el LQR: mide si el swing-up esta en condiciones de alimentarlo.

Referencias de la jornada del 2026-08-05, para comparar:

    banco sano      bombeo ~5,5 s   theta en bombeo ~69 deg   3/3 traspasos
    banco degradado bombeo ~13,6 s  theta en bombeo ~94,7 deg  2/5 traspasos

Uso:
    uv run python baseline.py            # 3 intentos con el tn del firmware
    uv run python baseline.py --tn 162
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m4_daq import BROWNOUT_CUT_V, BROWNOUT_DERATE_V, homing, wait_for_rest

from qube_app.link import QubeLink
from qube_app.stream import DaqStream

# Umbrales de decision, de la jornada del 2026-08-05.
PUMP_WARN_S = 10.0  # bombeo mediano por encima de esto: el banco ya no es instrumento
THETA_WARN_DEG = 90.0  # theta en bombeo por encima de esto: el brazo vive contra el tope


def one(link: QubeLink, max_s: float) -> dict:
    wait_for_rest(link)
    homing(link)
    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    parts: list[tuple[np.ndarray, ...]] = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for c in stream.drain():
                parts.append((c.th_deg, c.al_deg, c.mode))

    stream.start()
    try:
        pump(0.5)
        link.send({"m": 5})
        pump(max_s)
    finally:
        link.send({"m": 0})
        stream.stop()
        for c in stream.drain():
            parts.append((c.th_deg, c.al_deg, c.mode))

    th = np.concatenate([p[0] for p in parts])
    al = np.concatenate([p[1] for p in parts])
    mode = np.concatenate([p[2] for p in parts])
    in5 = mode == 5
    alw = np.abs((al[in5] + 180.0) % 360.0 - 180.0)
    return {
        "pump_s": round(float(in5.sum()) / 500.0, 1),
        "theta_max": round(float(np.abs(th[in5]).max()), 1) if in5.any() else 0.0,
        "alpha_peak": round(float(alw.max()), 1) if in5.any() else 0.0,
        "handed_off": bool((mode == 4).any()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tn", type=float, default=None, help="por defecto, el del firmware")
    ap.add_argument("--max-s", type=float, default=20.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    v = float(d.get("v_bus") or 0.0)
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={v:.2f}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: no se energiza el motor.")
    if v < BROWNOUT_CUT_V:
        raise SystemExit(f"v_bus = {v:.2f} V: el firmware anula todo comando de motor.")
    if v < BROWNOUT_DERATE_V:
        raise SystemExit(f"v_bus = {v:.2f} V: el PWM se escala por tension.")
    if args.tn is not None:
        link.send({"tn": args.tn})

    rows = []
    try:
        for i in range(1, args.reps + 1):
            r = one(link, args.max_s)
            rows.append(r)
            print(f"  {i}/{args.reps}  bombeo {r['pump_s']:>5.1f} s   theta max "
                  f"{r['theta_max']:>5.1f}   pico alpha {r['alpha_peak']:>5.1f}   "
                  f"{'traspasa' if r['handed_off'] else 'SIN TRASPASO'}")
    finally:
        link.send({"m": 0})

    if not rows:
        return
    p = statistics.median(r["pump_s"] for r in rows)
    t = statistics.median(r["theta_max"] for r in rows)
    ho = sum(r["handed_off"] for r in rows)
    print(f"\n  bombeo mediano {p:.1f} s   theta max mediano {t:.1f}   traspasos {ho}/{len(rows)}")
    print(f"  referencia sana: ~5,5 s / ~69 deg / {len(rows)}/{len(rows)}")
    malo = p > PUMP_WARN_S or t > THETA_WARN_DEG or ho < len(rows)
    if malo:
        print("\n  >> BANCO DEGRADADO. No arrancar una tanda: los resultados no seran")
        print("     comparables y es probable que el control no produzca dato.")
    else:
        print("\n  >> Banco en condiciones. Se puede arrancar la tanda.")
    raise SystemExit(1 if malo else 0)


if __name__ == "__main__":
    main()
