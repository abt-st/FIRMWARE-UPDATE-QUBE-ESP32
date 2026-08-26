"""m7 medido por adquisicion en bloques, no sondeando /state.

Sucesor de `m7_balance.py`. El cambio no es cosmetico: sondear /state a 25 Hz **degrada
el lazo que se esta midiendo**. Medido el 2026-08-04 sobre el modo 7:

    sondeando a  4 Hz : inferencia max 11.065 us, 70 overruns en 20 s
    sin sondear       : inferencia max    702 us,  2 overruns en 20 s

`micros()` mide tiempo de reloj, asi que una inferencia "lenta" era una inferencia
DESALOJADA por la pila de WiFi. Con `m7_balance.py` (25 Hz) cada intento acumulaba ~300
overruns: el veredicto salia de un lazo roto por el propio instrumento.

`DaqStream` invierte la relacion: sondea cada 0,2 s (5 Hz de HTTP) y **cada sondeo vacia
un bloque de muestras a 500 Hz**. Cinco veces menos trafico y unas cien veces mas
resolucion temporal.

Ademas `al_deg` llega SIN ENVOLVER, asi que el hold se mide sin el salto de +-180 que
obliga a acotar desde el cliente.

Contrato del firmware: **un solo consumidor de /daq/read**. No correr esto con la GUI
abierta.

Criterio (el mismo de ../README.md, escrito antes de medir):
  1. alcanza |alpha - 180| < 15 en >= 3 de 5
  2. lo SOSTIENE >= 3 s continuos en >= 3 de 5
  3. loop_overruns bajo — y ahora la medicion no es la causa

Uso:
    uv run python m7_balance_daq.py --reps 5 --he 165
    uv run python m7_balance_daq.py --reps 5 --he 179
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

UPRIGHT_DEG = 180.0
TOL_DEG = 15.0
HOLD_S = 3.0


def wait_for_rest(link: QubeLink, timeout: float = 25.0, tol: float = 0.5) -> bool:
    """Reposo del pendulo antes del homing (ver el bring-up del 2026-08-03)."""
    link.send({"m": 0})
    end = time.perf_counter() + timeout
    prev, stable = None, 0
    while time.perf_counter() < end:
        a = float(link.state().get("pend_position_deg", 0.0))
        if prev is not None and abs(a - prev) < tol:
            stable += 1
            if stable >= 8:
                return True
        else:
            stable = 0
        prev = a
        time.sleep(0.15)
    return False


def homing(link: QubeLink, timeout: float = 30.0) -> dict:
    link.send({"m": 3})
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        d = link.state()
        if d.get("homing_phase") == "DONE":
            return d
        if d.get("homing_phase") == "FAIL":
            raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
        time.sleep(0.2)
    raise RuntimeError("homing timeout")


def longest_hold(t: np.ndarray, al: np.ndarray) -> tuple[float, bool, float]:
    """Tramo continuo mas largo dentro de la ventana vertical, en segundos.

    `al` viene sin envolver, asi que se acota aca a [-180, 180] para medir la distancia
    a la vertical. Se hace UNA vez sobre el array entero y no muestra a muestra, que es
    donde P14 encontro cuatro compuertas comparando un angulo sin acotar.
    """
    wrapped = (al + 180.0) % 360.0 - 180.0
    dist = np.abs(np.abs(wrapped) - UPRIGHT_DEG)
    inside = dist < TOL_DEG
    if not inside.any():
        return 0.0, False, float(dist.min())
    best = 0.0
    start = None
    for i, ok in enumerate(inside):
        if ok and start is None:
            start = t[i]
        elif not ok and start is not None:
            best = max(best, t[i] - start)
            start = None
    if start is not None:
        best = max(best, t[-1] - start)
    return float(best), True, float(dist.min())


def attempt(link: QubeLink, he: float, rep: int, max_s: float) -> dict | None:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    h = homing(link)
    link.send({"he": he})
    st = link.state()
    got = float(st.get("hybrid_enter_deg", -1))
    if abs(got - he) > 0.6:
        raise RuntimeError(f"la placa reporta he={got}, se pidio {he}")

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"daq_he{int(he)}_r{rep}.csv")
    rec.open()
    ts: list[np.ndarray] = []
    als: list[np.ndarray] = []
    ths: list[np.ndarray] = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for chunk in stream.drain():
                rec.write(chunk)
                ts.append(chunk.t_s)
                als.append(chunk.al_deg)
                ths.append(chunk.th_deg)

    link.reset_loop_metrics()
    stream.start()
    try:
        pump(0.5)
        link.send({"m": 7})
        pump(max_s)
    finally:
        link.send({"m": 0})
        stream.stop()
        for chunk in stream.drain():
            rec.write(chunk)
            ts.append(chunk.t_s)
            als.append(chunk.al_deg)
            ths.append(chunk.th_deg)
        rec.close()

    if not ts:
        print("    ERROR: no llego ninguna muestra")
        return None
    t = np.concatenate(ts)
    al = np.concatenate(als)
    th = np.concatenate(ths)
    hold, reached, min_dist = longest_hold(t, al)
    d = link.state()
    return {
        "rep": rep,
        "he": he,
        "homing_range": round(float(h.get("homing_range", 0.0)), 2),
        "samples": int(t.size),
        "rate_hz": round(float(t.size / max(t[-1] - t[0], 1e-9)), 1),
        "reached": bool(reached),
        "hold_s": round(hold, 3),
        "min_dist_deg": round(min_dist, 1),
        "alpha_peak_deg": round(float(np.abs((al + 180.0) % 360.0 - 180.0).max()), 1),
        "theta_abs_max_deg": round(float(np.abs(th).max()), 1),
        "loop_dt_max_us": d.get("loop_dt_max_us"),
        "loop_overruns": d.get("loop_overruns"),
        "rl_step_us_mean": d.get("rl_step_us_mean"),
        "rl_step_us_max": d.get("rl_step_us_max"),
        "rl_infer_count": d.get("rl_infer_count"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--he", type=float, default=165.0)
    ap.add_argument("--max-s", type=float, default=20.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if d.get("rl_step_us_mean") is None:
        raise SystemExit("Firmware sin los contadores de P21: hay que flashear >= v1.58.7.")

    DATA.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for rep in range(1, args.reps + 1):
            print(f"\n--- intento {rep}/{args.reps}  he={args.he} ---")
            try:
                r = attempt(link, args.he, rep, args.max_s)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                link.send({"m": 0})
                continue
            if r is None:
                continue
            print(
                f"  vertical={'si' if r['reached'] else 'NO'}  hold={r['hold_s']:.2f}s"
                f"  pico={r['alpha_peak_deg']:.1f}deg  [{r['rate_hz']:.0f} Hz]"
                f"  overruns={r['loop_overruns']}  infer_med={r['rl_step_us_mean']}us"
            )
            rows.append(r)
    finally:
        link.send({"m": 0, "he": 165.0})

    (DATA / f"daq_he{int(args.he)}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    if rows:
        n = len(rows)
        c1 = sum(r["reached"] for r in rows)
        c2 = sum(r["hold_s"] >= HOLD_S for r in rows)
        print(f"\n=== criterio (he={args.he}, n={n}) ===")
        print(f"  1. alcanza la vertical: {c1}/{n}  {'PASS' if c1 >= 3 else 'FAIL'}")
        print(f"  2. sostiene >= {HOLD_S:.0f}s:     {c2}/{n}  {'PASS' if c2 >= 3 else 'FAIL'}")
        print(f"  holds       : {sorted(r['hold_s'] for r in rows)}")
        print(f"  picos |alpha|: {sorted(r['alpha_peak_deg'] for r in rows)}  (vertical = 180)")
        print(f"  overruns    : {[r['loop_overruns'] for r in rows]}")
        print(f"  inferencia media: {[r['rl_step_us_mean'] for r in rows]} us")


if __name__ == "__main__":
    main()
