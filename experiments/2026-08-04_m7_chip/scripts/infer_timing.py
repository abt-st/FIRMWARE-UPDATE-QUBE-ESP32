"""P21 — cuanto tarda UNA inferencia en el chip, y donde se va el tiempo.

La campana del 2026-08-04 dejo medido que la inferencia rompe el lazo de 500 Hz
(corr(segundos en rama politica, loop_overruns) = +0,996, n=10), pero no CUANTO tarda
ni POR QUE. Eso es lo que mide esto, y es el dato que decide el arreglo: optimizar sin
el numero es adivinar.

Cronometra las dos mitades por separado, porque son sospechosos distintos:

    fwd  = solo la red (6.464 MACs, pesos `constexpr` leidos desde flash)
    step = fwd + armado de la observacion (4 transcendentales por llamada)

Lectura del resultado:
  - fwd ~ step  y ambos grandes  -> el problema es la RED (accesos a flash, o el
    bucle de multiplicaciones). Arreglo: pesos a RAM, o achicar la red.
  - fwd chico, step >> fwd       -> el problema es el ARMADO (cosf/sinf). Arreglo:
    tablas o aproximaciones; la red no se toca.
  - los dos chicos               -> no es la inferencia: el atraso viene de otra
    cosa dentro de la rama del modo 7 y hay que seguir buscando.

**NO necesita el pendulo ni energizar el motor.** La inferencia corre en cada tick del
modo 7 pase lo que pase con la mecanica, asi que se mide con el brazo quieto. Aun asi
se aborta si el INA219 esta caido: el modo 7 puede accionar el motor.

Referencia para juzgar los numeros: 6.464 MACs en un ESP32 a 240 MHz con FPU de un
ciclo son decenas de microsegundos. El presupuesto por tick del lazo es 2.000 us, y el
de una decision a 50 Hz es 20.000 us.

Uso:
    uv run python infer_timing.py --seconds 20
    uv run python infer_timing.py --seconds 20 --hold-arm   # sin swing-up (he=90)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MACS = 36 * 64 + 64 * 64 + 64  # 6464
LOOP_BUDGET_US = 2000  # periodo del lazo de control
TICK_BUDGET_US = 20000  # periodo de una decision a 50 Hz


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--sample-dt", type=float, default=0.25)
    ap.add_argument(
        "--hold-arm",
        action="store_true",
        help="he=90: entra a la rama LQR enseguida, para contrastar el costo de la rama "
        "de la politica contra el de la del LQR dentro del MISMO modo",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="NO sondear /state durante la ventana; leer una sola vez al final. Discrimina "
        "si los picos los causa la inferencia o la pila de WiFi atendiendo el sondeo: "
        "micros() mide tiempo de reloj, asi que un forward 'lento' puede ser un forward "
        "DESALOJADO",
    )
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"Connection": "keep-alive"})
    base = f"http://{args.ip}"

    def cmd(**p):
        return s.get(f"{base}/cmd", params=p, timeout=3).json()

    def state():
        return s.get(f"{base}/state", timeout=3).json()

    d = state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if d.get("rl_step_us_mean") is None:
        raise SystemExit("Firmware sin los contadores de P21: hay que flashear >= v1.58.7.")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")

    cmd(m=0)
    time.sleep(0.3)
    cmd(he=90.0 if args.hold_arm else 179.0)
    cmd(rj=1)  # reinicia los contadores del lazo Y los de P21, en la misma ventana
    cmd(m=7)
    print(f"Midiendo {args.seconds:.0f}s en modo 7 (he={90 if args.hold_arm else 179})...")

    rows = []
    t0 = time.monotonic()
    try:
        if args.quiet:
            # Ni un request durante la ventana: el unico trafico WiFi es el del SoftAP.
            time.sleep(args.seconds)
            d = state()
            rows.append({"t_s": round(time.monotonic() - t0, 2), **{k: d.get(k) for k in (
                "hybrid_lqr", "rl_infer_count", "rl_fwd_us_last", "rl_fwd_us_max",
                "rl_fwd_us_mean", "rl_step_us_last", "rl_step_us_max", "rl_step_us_mean",
                "loop_dt_max_us", "loop_overruns")}})
        while not args.quiet and (t := time.monotonic() - t0) < args.seconds:
            try:
                d = state()
            except requests.RequestException:
                time.sleep(args.sample_dt)
                continue
            rows.append(
                {
                    "t_s": round(t, 2),
                    "hybrid_lqr": d.get("hybrid_lqr"),
                    "rl_infer_count": d.get("rl_infer_count"),
                    "rl_fwd_us_last": d.get("rl_fwd_us_last"),
                    "rl_fwd_us_max": d.get("rl_fwd_us_max"),
                    "rl_fwd_us_mean": d.get("rl_fwd_us_mean"),
                    "rl_step_us_last": d.get("rl_step_us_last"),
                    "rl_step_us_max": d.get("rl_step_us_max"),
                    "rl_step_us_mean": d.get("rl_step_us_mean"),
                    "loop_dt_max_us": d.get("loop_dt_max_us"),
                    "loop_overruns": d.get("loop_overruns"),
                }
            )
            if d.get("mode") == 0:
                print("  la placa volvio a modo 0 (limite o proteccion); se corta")
                break
            time.sleep(args.sample_dt)
    finally:
        cmd(m=0, he=165.0)  # restaurar el default del firmware

    if not rows:
        raise SystemExit("sin muestras")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tag = "holdarm" if args.hold_arm else "policy"
    (DATA_DIR / f"infer_timing_{tag}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    f = rows[-1]
    n = f["rl_infer_count"] or 0
    fwd_max = f["rl_fwd_us_max"] or 0
    fwd_mean = f["rl_fwd_us_mean"] or 0
    step_max = f["rl_step_us_max"] or 0
    step_mean = f["rl_step_us_mean"] or 0
    # media contra media: restarle un maximo a una media no significa nada.
    armado = max(step_mean - fwd_mean, 0)

    print("\n=== P21 — costo de una inferencia ===")
    print(f"  inferencias contadas      : {n}  en {f['t_s']:.1f}s  ({n / max(f['t_s'], 1e-9):.1f}/s)")
    print(f"  step (total)  media / max : {step_mean} / {step_max} us")
    print(f"  fwd  (red)    media / max : {fwd_mean} / {fwd_max} us")
    print(f"  armado de observacion     : {armado} us  ({armado / max(step_mean, 1):.0%} del total)")
    print()
    print(f"  presupuesto del lazo      : {LOOP_BUDGET_US} us   -> la inferencia usa {step_mean / LOOP_BUDGET_US:.1%}")
    print(f"  presupuesto de un tick    : {TICK_BUDGET_US} us  -> la inferencia usa {step_mean / TICK_BUDGET_US:.1%}")
    print(f"  us/MAC ({MACS} MACs)      : {step_mean / MACS:.3f}  (referencia sana: ~0.005 a 240 MHz)")
    print()
    print(f"  loop_dt_max_us            : {f['loop_dt_max_us']}")
    print(f"  loop_overruns             : {f['loop_overruns']}")
    print()
    if step_mean > LOOP_BUDGET_US:
        print("  >> La inferencia SOLA excede el periodo del lazo. Ese es el defecto.")
    if step_max and step_mean and step_max > 4 * step_mean:
        print(f"  >> Muy a PICOS (max/media = {step_max / max(step_mean, 1):.1f}x): firma de fallos de cache")
        print("     de flash. Los pesos son `constexpr` en .rodata; moverlos a RAM es el arreglo.")
    if fwd_mean and step_mean and fwd_mean > 0.7 * step_mean:
        print("  >> El grueso esta en la RED, no en el armado de la observacion.")
    elif armado > 0.5 * step_mean:
        print("  >> El grueso esta en el ARMADO de la observacion: los cosf/sinf.")
    else:
        print("  >> Ni la red ni el armado dominan: el atraso viene de otra parte del modo 7.")


if __name__ == "__main__":
    main()
