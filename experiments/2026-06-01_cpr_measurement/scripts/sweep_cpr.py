"""Barrido de CPR no-interactivo: resetea el encoder, colecta datos continuos, y reporta.

El usuario rota el eje mientras el script graba. No requiere input interactivo.

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/sweep_cpr.py [--ip IP] [--encoder servo|pendulum]
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
    parser = argparse.ArgumentParser(description="Barrido de CPR")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--encoder", choices=["servo", "pendulum"], default="servo",
                        help="Encoder a medir: servo (GPIO34/35) o pendulum (GPIO32/33)")
    parser.add_argument("--duracion", "-t", type=float, default=20.0, help="Segundos de grabacion (default: 20)")
    parser.add_argument("--vueltas", "-n", type=int, default=1, help="Vueltas objetivo (default: 1)")
    args = parser.parse_args()
    reset_param = "r"  # r resetea ambos contadores PCNT
    is_pendulum = args.encoder == "pendulum"
    count_key = "pend_count" if is_pendulum else "count"
    pos_key = "pend_raw_position_deg" if is_pendulum else "raw_position_deg"
    cpr_key = "pend_counts_per_rev" if is_pendulum else "counts_per_rev"

    # Verificar conexion
    try:
        state = get_state(args.ip)
        print(f"[OK] Conectado a {args.ip}")
        print(f"     Encoder: {args.encoder}")
        print(f"     CPR configurado: {state.get(cpr_key, '?')}")
    except Exception as e:
        print(f"[FAIL] No se puede conectar: {e}")
        return

    # Reset encoder
    send_cmd(args.ip, {reset_param: ""})
    time.sleep(0.3)

    state = get_state(args.ip)
    baseline = state.get(count_key, 0)
    print(f"     Baseline post-reset: {baseline}")

    print(f"\n  >>> Rota el eje {args.vueltas} vuelta(s) en {args.duracion}s <<<")
    print(f"     Encoder: {args.encoder}, Grabando ahora...\n")

    # Grabar datos
    samples: list[tuple[float, int, float]] = []
    t_start = time.time()

    while (time.time() - t_start) < args.duracion:
        try:
            state = get_state(args.ip)
            elapsed = time.time() - t_start
            count = state.get(count_key, 0) - baseline
            pos = state.get(pos_key, 0.0)
            samples.append((elapsed, count, pos))
        except Exception:
            pass
        time.sleep(0.02)  # 50 Hz

    if not samples:
        print("[FAIL] No se capturaron datos.")
        return

    counts = [s[1] for s in samples]

    # Estadisticas
    max_count = max(counts)
    min_count = min(counts)
    final_count = counts[-1]
    total_range = max_count - min_count
    max_abs = max(abs(max_count), abs(min_count))

    print(f"\n{'=' * 60}")
    print(f"  RESULTADOS — Encoder: {args.encoder}")
    print(f"{'=' * 60}")
    print(f"  Duracion: {args.duracion}s, {len(samples)} muestras")
    print(f"  Count min: {min_count}")
    print(f"  Count max: {max_count}")
    print(f"  Count final: {final_count}")
    print(f"  Rango total: {total_range} counts")

    if max_abs > 0:
        print("\n  --- Estimacion de CPR ---")
        for n in [1, 2, 3, 5, 10]:
            cpr_est = max_abs / n
            print(f"  Si {n} vueltas: CPR = {cpr_est:.0f}")
        print(f"  Vueltas objetivo ({args.vueltas}): CPR = {max_abs / args.vueltas:.0f}")

        print("\n  CPRs estandar cercanos:")
        for std in [100, 200, 256, 300, 360, 500, 512, 600, 1000, 1024, 2048, 4096]:
            error_pct = abs(max_abs / args.vueltas - std) / std * 100
            if error_pct < 15:
                marker = " <- probable" if error_pct < 5 else ""
                print(f"    {std:>6}: {error_pct:>5.1f}% error{marker}")

    # Evolucion
    print("\n  Evolucion del count (cada 1s):")
    print(f"  {'t(s)':>6} | {'count':>8} | {'pos_deg':>8}")
    print(f"  {'-' * 30}")
    last_t = -1
    for t, c, p in samples:
        if t - last_t >= 1.0 or t == samples[0][0]:
            print(f"  {t:>6.1f} | {c:>8} | {p:>8.3f}")
            last_t = t

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
