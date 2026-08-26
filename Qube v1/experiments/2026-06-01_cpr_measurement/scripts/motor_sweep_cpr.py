"""Barrido de CPR con motor: mueve el motor a PWM constante y graba el encoder.

Elimina el error humano: el motor gira a velocidad constante y el PCNT
cuenta cada transicion. Se calcula CPR comparando el count con la
velocidad angular medida por el encoder.

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/motor_sweep_cpr.py [--ip IP] [--pwm N] [--duracion S]
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
    parser = argparse.ArgumentParser(description="Barrido CPR con motor")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--pwm", type=int, default=40, help="Valor PWM (0-255, default: 40 = lento)")
    parser.add_argument("--duracion", "-t", type=float, default=10.0, help="Segundos (default: 10)")
    parser.add_argument("--vueltas", "-n", type=int, default=5, help="Vueltas objetivo (default: 5)")
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
    time.sleep(0.2)
    send_cmd(args.ip, {"r": ""})
    time.sleep(0.3)

    state = get_state(args.ip)
    baseline = state.get("count", 0)
    print(f"     Baseline: {baseline}")

    # Confirmar que el motor puede girar
    print(f"\n  PWM: {args.pwm}, Duracion: {args.duracion}s")
    print(f"  Velocidad estimada: ~{args.pwm * 100 / 255:.0f}% del maximo")

    # Arrancar motor
    print("\n  Arrancando motor...")
    send_cmd(args.ip, {"p": args.pwm, "m": 1})

    # Grabar datos
    samples: list[tuple[float, int]] = []
    t_start = time.time()

    while (time.time() - t_start) < args.duracion:
        try:
            state = get_state(args.ip)
            elapsed = time.time() - t_start
            count = state.get("count", 0) - baseline
            samples.append((elapsed, count))
        except Exception:
            pass
        time.sleep(0.02)  # 50 Hz

    # Parar motor
    send_cmd(args.ip, {"x": ""})
    time.sleep(0.1)

    if not samples:
        print("[FAIL] No se capturaron datos.")
        return

    # Analizar
    counts = [s[1] for s in samples]

    # Calcular rango total de counts (maneja ambas direcciones)
    total_range = max(counts) - min(counts)
    # Tomar tramo central 80% (descartar arranque/frenado)
    trim = len(counts) // 10
    central = counts[trim:-trim] if trim > 0 and len(counts) > 20 else counts

    c1 = central[0]
    c2 = central[-1]
    dc = abs(c2 - c1)
    dt = len(central) * 0.02  # 50 Hz

    print(f"\n{'=' * 60}")
    print("  RESULTADOS")
    print(f"{'=' * 60}")
    print(f"  Duracion: {args.duracion}s, {len(samples)} muestras")
    print(f"  Rango total: {total_range} counts")
    print(f"  Tramo central: delta = {dc} counts en {dt:.2f}s")
    print(f"  Velocidad: {dc / dt:.1f} counts/s")

    # Evolucion completa
    print("\n  Evolucion del count:")
    print(f"  {'t(s)':>6} | {'count':>8}")
    print(f"  {'-' * 18}")
    last_t = -1
    for t, c in samples:
        if t - last_t >= 0.5 or t == samples[0][0]:
            print(f"  {t:>6.2f} | {c:>8}")
            last_t = t

    # Estimacion de CPR
    print("\n  --- Estimacion de CPR ---")
    print("  (Necesitamos saber las vueltas reales del eje del MOTOR)")
    print(f"  Si el motor hizo 1 vuelta: CPR = {abs(dc)}")
    print(f"  Si el motor hizo 2 vueltas: CPR = {abs(dc) / 2:.0f}")
    print(f"  Si el motor hizo 3 vueltas: CPR = {abs(dc) / 3:.0f}")
    print(f"  Si el motor hizo 5 vueltas: CPR = {abs(dc) / 5:.0f}")
    print(f"  Si el motor hizo 10 vueltas: CPR = {abs(dc) / 10:.0f}")
    print(f"  Vueltas objetivo: {args.vueltas} -> CPR = {abs(dc) / args.vueltas:.0f}")

    print("\n  CPRs estandar cercanos:")
    for std in [100, 200, 256, 360, 500, 512, 600, 1000, 1024, 2048, 4096]:
        error_pct = abs(abs(dc) / args.vueltas - std) / std * 100
        if error_pct < 10:
            marker = " <- probable" if error_pct < 3 else ""
            print(f"    {std:>6}: {error_pct:>5.1f}% error{marker}")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
