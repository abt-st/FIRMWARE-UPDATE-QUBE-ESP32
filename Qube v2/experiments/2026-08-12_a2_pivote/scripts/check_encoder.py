"""Comprueba si el canal del encoder del pendulo esta leyendo. Mueve el pendulo a mano.

**Por que hace falta.** El 2026-08-12, cinco corridas seguidas de la campana A2 salieron con
el angulo del pendulo tomando UN SOLO valor en 17.500 muestras, mientras el brazo seguia
leyendo. Antonio confirma que en esas cinco levanto y solto el pendulo normalmente, o sea que
el canal dejo de leer durante unos 6 minutos y volvio solo para la corrida 8.

Eso no se puede diagnosticar desde `pend_position_deg`: es un contador incremental, y con el
pendulo quieto da un valor exactamente constante, sin temblor. Una traza plana no distingue
"no se movio" de "no lee". Lo que si distingue es mirar los pines crudos, que `/state` publica
como `pend_a` y `pend_b` junto al conteo del PCNT:

    A/B conmutan  +  conteo cambia   ->  el canal esta sano
    A/B conmutan  +  conteo QUIETO   ->  llega senal y el PCNT no cuenta: firmware/PCNT
    A/B QUIETOS                      ->  no llega senal: cableado, Schmitt o alimentacion

El brazo va de control: si tampoco se mueve, el problema no es del canal del pendulo.

Uso:
    uv run python check_encoder.py
    (y mueve el pendulo a mano, de un lado a otro, durante toda la cuenta)
"""

from __future__ import annotations

import argparse
import sys
import time

import requests

C = {"ok": "\033[1;32m", "no": "\033[1;31m", "d": "\033[0;33m", "n": "\033[0m", "b": "\033[1m"}
if sys.platform == "win32":
    import os

    os.system("")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostico del encoder del pendulo")
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--seconds", type=float, default=20.0)
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"Connection": "keep-alive"})
    try:
        s.get(f"http://{args.ip}/cmd", params={"m": 0}, timeout=5)
    except requests.RequestException as exc:
        print(f"{C['no']}  sin conexion con {args.ip}: {type(exc).__name__}{C['n']}")
        return 1

    print(f"\n{C['b']}  MUEVE EL PENDULO A MANO, de un lado a otro, durante {args.seconds:.0f} s.{C['n']}")
    print(f"{C['d']}  Movelo bastante: media vuelta para cada lado alcanza y sobra.{C['n']}\n")
    for n in (3, 2, 1):
        print(f"    {n}...")
        time.sleep(1.0)
    print(f"  {C['b']}YA — move el pendulo{C['n']}\n")

    pend_counts: set[int] = set()
    pend_a: set[int] = set()
    pend_b: set[int] = set()
    arm_counts: set[float] = set()
    arm_a: set[int] = set()
    muestras = 0
    fallos = 0

    t0 = time.perf_counter()
    while (t := time.perf_counter() - t0) < args.seconds:
        try:
            d = s.get(f"http://{args.ip}/state", timeout=3).json()
        except (requests.RequestException, ValueError):
            fallos += 1
            continue
        muestras += 1
        pend_counts.add(int(d.get("pend_count", 0)))
        pend_a.add(int(d.get("pend_a", -1)))
        pend_b.add(int(d.get("pend_b", -1)))
        arm_counts.add(float(d.get("raw_position_deg", 0.0)))
        arm_a.add(int(d.get("enc_a", -1)))
        sys.stdout.write(
            f"\r    {args.seconds - t:4.1f} s   pend_count={d.get('pend_count'):>7}  "
            f"A={d.get('pend_a')} B={d.get('pend_b')}   valores vistos: "
            f"conteo {len(pend_counts)}, A {len(pend_a)}, B {len(pend_b)}    "
        )
        sys.stdout.flush()
        time.sleep(0.05)

    span = (max(pend_counts) - min(pend_counts)) if pend_counts else 0
    print("\n")
    print(f"  muestras {muestras}" + (f", {fallos} lecturas fallidas" if fallos else ""))
    print(f"  PENDULO   conteo: {len(pend_counts)} valores distintos, recorrido {span} cuentas "
          f"({span * 360 / 2048:.1f} deg)")
    print(f"            pines:  A tomo {len(pend_a)} estado(s), B tomo {len(pend_b)}")
    print(f"  BRAZO     angulo: {len(arm_counts)} valores distintos   pin A: {len(arm_a)} estado(s)")

    cuenta_cambia = len(pend_counts) > 2
    pines_conmutan = len(pend_a) > 1 or len(pend_b) > 1
    print()
    if cuenta_cambia and pines_conmutan:
        print(f"  {C['ok']}CANAL SANO{C['n']} — los pines conmutan y el PCNT cuenta.")
        print("  El fallo de las corridas 3 a 7 fue intermitente. Antes de repetir la campana")
        print("  conviene mover el mazo de cables del pendulo con la mano mientras corre esto:")
        print("  si el conteo se congela al tocarlo, es conexion floja y hay que resolverlo.")
        return 0
    if pines_conmutan and not cuenta_cambia:
        print(f"  {C['no']}LLEGA SENAL Y EL PCNT NO CUENTA{C['n']} — problema de firmware/PCNT,")
        print("  no de cableado. Un reinicio de la placa reinicializa el PCNT; si con eso vuelve,")
        print("  es que el contador se cuelga y hay que mirar `setupPendulumPcnt`.")
        return 2
    # Aca hay que tener cuidado con lo que se afirma. Que los pines no conmuten solo
    # significa "no llega senal" SI el pendulo se movio de verdad; si nadie lo toco, es
    # exactamente lo que se espera. La placa no puede distinguir esas dos cosas -por
    # construccion, es lo que se esta diagnosticando- asi que la respuesta la pone el
    # operador, y el script pregunta en vez de suponer.
    print(f"  {C['d']}Ni los pines ni el conteo cambiaron.{C['n']}")
    print("  Eso solo tiene una lectura si el pendulo se movio de verdad:")
    print()
    print(f"    {C['no']}si LO MOVISTE{C['n']}   -> no llega senal a la placa. Es cableado, el Schmitt")
    print("                      o la alimentacion del encoder. Comprobar:")
    print("                        - 5 V en el encoder, y la salida del Schmitt por debajo")
    print("                          de 3,3 V en el GPIO")
    print("                        - continuidad de A y B, y que no esten flojos")
    print("                        - que el conector no este medio salido")
    print(f"    {C['d']}si NO lo moviste{C['n']} -> no hay diagnostico. Corre esto otra vez y movelo.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
