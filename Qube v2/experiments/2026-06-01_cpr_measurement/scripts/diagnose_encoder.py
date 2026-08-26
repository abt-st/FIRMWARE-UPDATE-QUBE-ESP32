"""Diagnostico del encoder: lee estados crudos de enc_a/enc_b en tiempo real.

Muestra si los pines del encoder estan cambiando al rotar el eje manualmente.
Si enc_a y enc_b nunca cambian, el problema es hardware (senal, acondicionamiento, conexiones).
Si cambian pero el count es bajo, el problema es en las ISRs.

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/diagnose_encoder.py [--ip IP]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.request import urlopen

DEFAULT_IP = "192.168.4.1"
TIMEOUT = 3


def get_state(ip: str) -> dict:
    url = f"http://{ip}/state"
    with urlopen(url, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostico de encoder")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--samples", "-n", type=int, default=100, help="Muestras a tomar (default: 100)")
    args = parser.parse_args()

    try:
        state = get_state(args.ip)
        print(f"  [OK] Conectado a {args.ip}")
        print(f"     CPR configurado: {state.get('counts_per_rev')}")
        print(f"     Count actual: {state.get('count')}")
    except Exception as e:
        print(f"  [FAIL] No se puede conectar: {e}")
        sys.exit(1)

    # Reset encoder
    try:
        urlopen(f"http://{args.ip}/cmd?r", timeout=TIMEOUT)
        time.sleep(0.2)
    except Exception:
        pass

    print(f"\n  Rota el eje lentamente mientras se capturan {args.samples} muestras.")
    print("  Observa si enc_a y enc_b cambian.\n")

    print(f"  {'#':>4} | {'enc_a':>5} {'enc_b':>5} | {'count':>8} | {'pos_deg':>8}")
    print(f"  {'-' * 45}")

    prev_a: int | None = None
    prev_b: int | None = None
    transitions_a = 0
    transitions_b = 0

    for i in range(args.samples):
        try:
            state = get_state(args.ip)
        except Exception:
            print("  [!] Error de lectura, reintentando...")
            time.sleep(0.5)
            continue

        enc_a = state.get("enc_a", -1)
        enc_b = state.get("enc_b", -1)
        count = state.get("count", 0)
        pos = state.get("raw_position_deg", 0.0)

        if prev_a is not None and enc_a != prev_a:
            transitions_a += 1
        if prev_b is not None and enc_b != prev_b:
            transitions_b += 1

        changed = (enc_a != prev_a) or (enc_b != prev_b)
        if changed or i % 10 == 0:
            marker = " <- CAMBIO" if changed else ""
            print(f"  {i:>4} | {enc_a:>5} {enc_b:>5} | {count:>8} | {pos:>8.3f}{marker}")

        prev_a = enc_a
        prev_b = enc_b
        time.sleep(0.02)

    print(f"\n  {'-' * 45}")
    print("  Resumen:")
    print(f"    Transiciones en enc_a: {transitions_a}")
    print(f"    Transiciones en enc_b: {transitions_b}")
    print(f"    Count final: {state.get('count', 0)}")

    if transitions_a == 0 and transitions_b == 0:
        print("\n  [FAIL] PROBLEMA HARDWARE: Los pines del encoder NO cambian.")
        print("     Posibles causas:")
        print("       - Encoder no conectado o mal conexionado")
        print("       - Acondicionamiento de senal no funciona (Schmitt trigger)")
        print("       - Nivel de voltaje insuficiente en GPIO")
    elif transitions_a > 0 and transitions_b == 0:
        print("\n  [WARN] Solo enc_a cambia. Verificar conexion de canal B.")
    elif transitions_b > 0 and transitions_a == 0:
        print("\n  [WARN] Solo enc_b cambia. Verificar conexion de canal A.")
    else:
        ratio = max(transitions_a, transitions_b) / max(min(transitions_a, transitions_b), 1)
        print(f"\n  [OK] Ambos canales cambian (ratio A/B: {ratio:.1f})")
        if abs(state.get("count", 0)) < 5:
            print(f"     Pero el count es muy bajo ({state.get('count', 0)}).")
            print("     Posible problema en la logica de las ISRs o ruido excesivo.")
        else:
            print(f"     Count: {state.get('count', 0)} -- encoder funcional.")


if __name__ == "__main__":
    main()
