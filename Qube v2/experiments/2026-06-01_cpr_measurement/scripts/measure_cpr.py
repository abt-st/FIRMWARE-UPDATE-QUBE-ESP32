"""Medición experimental de CPR (Counts Per Revolution) del encoder.

Método:
  1. Parada segura del motor
  2. Reset del encoder a 0
  3. Rotación manual del eje exactamente 1 vuelta completa (marcar el eje)
  4. Leer el conteo crudo del encoder
  5. Repetir N veces para promediar
  6. CPR = promedio(|count| / 1_vuelta)

El firmware expone el conteo crudo en /state como "count", independiente
del countsPerRev configurado. Esto permite medir el CPR real sin supuestos.

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/measure_cpr.py [--ip IP] [--vueltas N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.request import urlopen

DEFAULT_IP = "192.168.4.1"
DEFAULT_PORT = 80
TIMEOUT = 5


def get_state(ip: str, port: int = DEFAULT_PORT) -> dict:
    """Obtiene el estado actual del ESP32 (/state)."""
    url = f"http://{ip}:{port}/state"
    with urlopen(url, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def send_cmd(ip: str, params: dict[str, str | int], port: int = DEFAULT_PORT) -> None:
    """Envía un comando al ESP32 (/cmd?...)."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"http://{ip}:{port}/cmd?{query}"
    with urlopen(url, timeout=TIMEOUT) as resp:
        resp.read()


def measure_cpr_interactive(ip: str, vueltas: int, port: int = DEFAULT_PORT) -> list[int]:
    """Mide CPR mediante rotación manual. Retorna lista de conteos (1 por vuelta)."""
    print(f"\n{'=' * 60}")
    print("  MEDICIÓN DE CPR — Encoder Servo")
    print(f"{'=' * 60}")
    print(f"  ESP32: {ip}:{port}")
    print(f"  Vueltas a medir: {vueltas}")
    print(f"{'=' * 60}\n")

    # Verificar conexión
    try:
        state = get_state(ip, port)
        print(f"  [OK] Conexion OK. CPR configurado: {state.get('counts_per_rev', '?')}")
        print(f"     Count actual: {state.get('count', '?')}")
        print(f"     Modo actual: {state.get('mode', '?')}")
    except Exception as e:
        print(f"  [FAIL] No se puede conectar al ESP32 en {ip}: {e}")
        sys.exit(1)

    # Parar motor antes de medir (x = safeStop)
    print("\n  [!] Parando motor (safeStop)...")
    send_cmd(ip, {"x": ""}, port)
    time.sleep(0.2)

    # Verificar que el motor está parado
    state = get_state(ip, port)
    if state.get("mode", 0) != 0:
        print(f"  [!] Motor aun en modo {state.get('mode')}. Intentando reset completo...")
        send_cmd(ip, {"m": 0, "x": ""}, port)
        time.sleep(0.2)

    print("  [OK] Motor parado.\n")

    counts: list[int] = []

    for i in range(1, vueltas + 1):
        print(f"--- Vuelta {i}/{vueltas} ---")

        # Reset encoder a 0
        print("  Reseteando encoder a 0...")
        send_cmd(ip, {"r": ""}, port)
        time.sleep(0.3)

        state = get_state(ip, port)
        baseline = state.get("count", 0)
        if baseline != 0:
            print(f"  [!] Count post-reset: {baseline} (ruido normal, se restara del resultado)")
        else:
            print("  [OK] Count: 0")

        # Instrucciones
        if i == 1:
            print("\n  INSTRUCCIONES:")
            print("     1. Marca el eje con cinta/marcador en una posición de referencia.")
            print("     2. Rota el eje EXACTAMENTE 1 vuelta completa en sentido horario.")
            print("        (la marca debe volver a la posición original)")
            print("     3. NO muevas el eje mas de lo necesario para la vuelta.\n")
        else:
            print(f"\n  Rota 1 vuelta completa más (vuelta {i}).")

        input(f"  Presiona ENTER cuando hayas completado la vuelta {i}...")

        # Leer conteo crudo y restar baseline (ruido post-reset)
        state = get_state(ip, port)
        raw_count = state.get("count", 0) - baseline

        cpr_this = abs(raw_count)
        print(f"  Count crudo: {raw_count}  ->  CPR vuelta {i}: {cpr_this}")

        counts.append(raw_count)
        print()

    return counts


def print_results(counts: list[int]) -> None:
    """Imprime estadísticas de la medición."""
    print(f"\n{'=' * 60}")
    print("  RESULTADOS")
    print(f"{'=' * 60}\n")

    if not counts:
        print("  No hay datos para analizar.")
        return

    # CPR por vuelta individual
    print("  Vuelta | Count crudo | CPR")
    print("  -------|-------------|--------")
    for i, c in enumerate(counts, 1):
        print(f"  {i:>6} | {c:>11} | {abs(c)}")

    print(f"\n  {'─' * 45}")

    # Estadísticas
    cprs = [abs(c) for c in counts]
    n = len(cprs)

    if n == 1:
        print(f"\n  CPR medido: {cprs[0]}")
        print("  (1 sola vuelta — no hay estadísticas disponibles)")
    else:
        avg = sum(cprs) / n
        variance = sum((x - avg) ** 2 for x in cprs) / n
        std = variance**0.5
        min_cpr = min(cprs)
        max_cpr = max(cprs)

        print(f"\n  CPR promedio:  {avg:.1f}")
        print(f"  Desviación:    ±{std:.1f} ({std / avg * 100:.2f}%)")
        print(f"  Rango:         [{min_cpr}, {max_cpr}]")
        print(f"  Vueltas:       {n}")

        # Detección de cuántos CPRs por vuelta de encoder real
        # (si el encoder tiene un gearbox, el CPR del motor ≠ CPR del eje)
        print(f"\n  {'─' * 45}")
        print("  Posibles CPR estándar:")
        for standard in [100, 200, 256, 360, 500, 512, 600, 1000, 1024, 2048, 4096]:
            error_pct = abs(avg - standard) / standard * 100
            if error_pct < 10:
                marker = "  ← probable" if error_pct < 3 else ""
                print(f"    {standard:>6}: {error_pct:>5.1f}% error{marker}")

    print(f"\n{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mide CPR del encoder del QUBE Servo")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Puerto (default: {DEFAULT_PORT})")
    parser.add_argument("--vueltas", "-n", type=int, default=5, help="Número de vueltas a medir (default: 5)")
    args = parser.parse_args()

    counts = measure_cpr_interactive(args.ip, args.vueltas, args.port)
    print_results(counts)


if __name__ == "__main__":
    main()
