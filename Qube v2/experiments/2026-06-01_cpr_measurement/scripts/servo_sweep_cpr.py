"""Medicion de CPR del encoder del servo usando el rango mecanico ±90°.

El servo solo tiene ±90° desde el centro. El script:
1. Usa PWM para llevar el motor al tope mecanico
2. Cuenta los ticks del encoder durante el recorrido
3. Calcula CPR = ticks / (grados_recorridos / 360)

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/servo_sweep_cpr.py [--ip IP] [--pwm N]
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.request import urlopen

DEFAULT_IP = "192.168.4.1"
TIMEOUT = 3


def get_state(ip: str) -> dict:
    url = f"http://{ip}/state"
    with urlopen(url, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def send_cmd(ip: str, params: dict[str, str | int]) -> None:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"http://{ip}/cmd?{query}"
    with urlopen(url, timeout=TIMEOUT) as resp:
        resp.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="CPR encoder servo via rango mecanico")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--pwm", type=int, default=60, help="Valor PWM para mover (default: 60)")
    parser.add_argument("--vueltas", "-n", type=int, default=3, help="Vueltas objetivo para estimar CPR (default: 3)")
    args = parser.parse_args()

    # Verificar conexion
    try:
        state = get_state(args.ip)
        print(f"[OK] Conectado a {args.ip}")
        print(f"     CPR configurado: {state.get('counts_per_rev')}")
    except Exception as e:
        print(f"[FAIL] No se puede conectar: {e}")
        return

    # Parar motor + reset encoder
    send_cmd(args.ip, {"x": ""})
    time.sleep(0.3)
    send_cmd(args.ip, {"r": ""})
    time.sleep(0.3)

    state = get_state(args.ip)
    baseline = state.get("count", 0)
    pos_initial = state.get("raw_position_deg", 0.0)
    print(f"     Baseline: {baseline}, Posicion inicial: {pos_initial:.1f} deg")

    # Fase 1: Mover motor al tope con PWM
    print(f"\n  Fase 1: Moviendo motor con PWM {args.pwm}...")
    send_cmd(args.ip, {"p": args.pwm, "m": 1})

    # Grabar hasta que el motor se estanque (count deja de cambiar)
    samples: list[tuple[float, int, float]] = []
    t_start = time.time()
    stale_count = 0
    prev_count = baseline

    while (time.time() - t_start) < 8.0:
        try:
            state = get_state(args.ip)
            elapsed = time.time() - t_start
            count = state.get("count", 0) - baseline
            pos = state.get("raw_position_deg", 0.0)
            samples.append((elapsed, count, pos))

            # Detectar si el motor se estanco (count sin cambio por 1s)
            if count == prev_count:
                stale_count += 1
            else:
                stale_count = 0
            prev_count = count

            if stale_count > 50:  # 1 segundo sin cambio
                print(f"     Motor estancado en t={elapsed:.1f}s, count={count}")
                break
        except Exception:
            pass
        time.sleep(0.02)

    # Parar motor
    send_cmd(args.ip, {"x": ""})
    time.sleep(0.2)

    if not samples:
        print("[FAIL] No se capturaron datos.")
        return

    # Analizar fase 1
    counts = [s[1] for s in samples]
    posiciones = [s[2] for s in samples]
    final_count = counts[-1]
    final_pos = posiciones[-1]

    print("\n  Fase 1 resultado:")
    print(f"    Count: {baseline} -> {final_count + baseline} (delta: {final_count})")
    print(f"    Posicion: {pos_initial:.1f} -> {final_pos:.1f} deg")

    # Fase 2: Mover en la otra direccion
    print("\n  Fase 2: Moviendo en direccion opuesta...")
    send_cmd(args.ip, {"r": ""})
    time.sleep(0.3)
    state = get_state(args.ip)
    baseline2 = state.get("count", 0)

    send_cmd(args.ip, {"p": -args.pwm, "m": 1})

    samples2: list[tuple[float, int, float]] = []
    t_start2 = time.time()
    stale_count2 = 0
    prev_count2 = baseline2

    while (time.time() - t_start2) < 8.0:
        try:
            state = get_state(args.ip)
            elapsed = time.time() - t_start2
            count = state.get("count", 0) - baseline2
            pos = state.get("raw_position_deg", 0.0)
            samples2.append((elapsed, count, pos))

            if count == prev_count2:
                stale_count2 += 1
            else:
                stale_count2 = 0
            prev_count2 = count

            if stale_count2 > 50:
                print(f"     Motor estancado en t={elapsed:.1f}s, count={count}")
                break
        except Exception:
            pass
        time.sleep(0.02)

    send_cmd(args.ip, {"x": ""})
    time.sleep(0.2)

    if samples2:
        counts2 = [s[1] for s in samples2]
        posiciones2 = [s[2] for s in samples2]
        final_count2 = counts2[-1]
        final_pos2 = posiciones2[-1]

        print("\n  Fase 2 resultado:")
        print(f"    Count: {baseline2} -> {final_count2 + baseline2} (delta: {final_count2})")
        print(f"    Posicion: {pos_initial:.1f} -> {final_pos2:.1f} deg")

        # Calcular CPR usando el recorrido total
        total_range_count = abs(final_count) + abs(final_count2)
        total_range_deg = abs(final_pos - pos_initial) + abs(final_pos2 - pos_initial)

        print(f"\n{'=' * 60}")
        print("  RESULTADOS FINALES")
        print(f"{'=' * 60}")
        print(f"  Recorrido total: {total_range_count} counts, {total_range_deg:.1f} grados")
        print(f"  Fase 1 (+): {abs(final_count)} counts, {abs(final_pos - pos_initial):.1f} deg")
        print(f"  Fase 2 (-): {abs(final_count2)} counts, {abs(final_pos2 - pos_initial):.1f} deg")

        if total_range_deg > 10:
            cpr = total_range_count / (total_range_deg / 360.0)
            print(f"\n  CPR calculado: {cpr:.1f}")
            print("  CPR configurado actualmente: 2048.0")

            print("\n  CPRs estandar cercanos:")
            for std in [100, 200, 256, 300, 360, 500, 512, 600, 1000, 1024, 2048, 4096]:
                error_pct = abs(cpr - std) / std * 100
                if error_pct < 15:
                    marker = " <- probable" if error_pct < 5 else ""
                    print(f"    {std:>6}: {error_pct:>5.1f}% error{marker}")
        else:
            print(f"\n  [!] Recorrido muy corto ({total_range_deg:.1f} deg) para calcular CPR.")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
