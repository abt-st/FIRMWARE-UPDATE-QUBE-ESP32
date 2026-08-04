"""Banco de latencia del enlace PC↔ESP32 — A/B entre SoftAP puro y AP+STA.

Implementa el protocolo de docs/research/softap_app_escritorio.md §9. El criterio de
decisión está PRE-REGISTRADO en el README de esta carpeta: se escribió antes de correr
la primera medición, para que el resultado no se pueda reinterpretar después.

Qué mide: el round-trip completo de ``GET /rl_step?a=0`` desde Python, que es el mismo
camino que recorre ``QubeRealEnv.step()``. Reutiliza la ``requests.Session`` con
keep-alive de ``qube_real.py`` (una sola conexión TCP reutilizada), porque medir sin
keep-alive mediría el handshake, no el enlace.

Seguridad: por defecto corre en **modo 0** (motor deshabilitado), así que la acción
``a=0`` no llega al motor y el banco puede quedar desatendido. ``--mode 6`` mide el
camino real del lazo RL, pero deja el motor habilitado: sólo con el brazo despejado.

Uso
---
    # Corrida A — placa con firmware AP+STA (pio run -e esp32dev_apsta)
    python measure_link_latency.py run --label apsta --ip 192.168.100.50

    # Corrida B — placa con firmware SoftAP puro (PC asociado a QUBE-ESP32)
    python measure_link_latency.py run --label softap

    # Tabla comparativa de todas las corridas guardadas
    python measure_link_latency.py report
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import socket
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_IP = os.environ.get("QUBE_IP", "192.168.4.1")
# Período del modo 6. La fracción de muestras por encima de este valor es,
# literalmente, la fracción de pasos que no cierran a 50 Hz.
PERIOD_MS = 20.0


# ── Medición ──────────────────────────────────────────────────────────────────


def _get(session: requests.Session, url: str, timeout: float) -> dict | None:
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def measure(ip: str, n: int, mode: int, timeout: float) -> dict:
    """Lanza N round-trips y devuelve el resumen + la serie completa de latencias."""
    base = f"http://{ip}"
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=4)
    session.mount("http://", adapter)
    session.headers.update({"Connection": "keep-alive"})

    state = _get(session, f"{base}/state", timeout)
    if state is None:
        print(f"ERROR: {ip} no responde. ¿Está el PC asociado a la red correcta?")
        sys.exit(1)

    probe = _get(session, f"{base}/rl_step", timeout)
    if probe is None or "pv" not in probe:
        print("ERROR: /rl_step no responde o no reporta 'pv'. Firmware desactualizado.")
        sys.exit(1)

    if mode != state.get("mode"):
        _get(session, f"{base}/cmd?m={mode}", timeout)
        time.sleep(0.2)

    # Resetear las métricas de salud del lazo AL ARRANQUE: si no, el peor caso del
    # arranque del firmware domina loop_dt_max_us y la corrida no dice nada.
    _get(session, f"{base}/cmd?rj=1", timeout)

    print(f"Midiendo {n} round-trips contra {ip} (modo {mode}, pv={probe['pv']})...")
    latencies_ms: list[float] = []
    failures = 0
    t_start = time.perf_counter()
    for i in range(n):
        t0 = time.perf_counter()
        ok = _get(session, f"{base}/rl_step?a=0.0", timeout)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if ok is None:
            failures += 1
        else:
            latencies_ms.append(dt_ms)
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{n}  (fallos: {failures})")
    elapsed_s = time.perf_counter() - t_start

    final = _get(session, f"{base}/state", timeout) or {}
    if mode != 0:  # dejar el motor detenido pase lo que pase
        _get(session, f"{base}/cmd?x=1", timeout)
    session.close()

    if not latencies_ms:
        print("ERROR: ninguna petición tuvo éxito.")
        sys.exit(1)

    ordered = sorted(latencies_ms)
    over = sum(1 for v in latencies_ms if v > PERIOD_MS)
    return {
        "n_ok": len(latencies_ms),
        "n_fail": failures,
        "mean_ms": statistics.fmean(latencies_ms),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[min(int(0.95 * len(ordered)), len(ordered) - 1)],
        "max_ms": ordered[-1],
        "frac_over_period": over / len(latencies_ms),
        "throughput_hz": len(latencies_ms) / elapsed_s,
        "loop_dt_max_us": final.get("loop_dt_max_us"),
        "loop_overruns": final.get("loop_overruns"),
        "proto_version": probe.get("pv"),
        "latencies_ms": [round(v, 3) for v in latencies_ms],
    }


# ── Persistencia y reporte ────────────────────────────────────────────────────


def save(summary: dict, label: str, ip: str, mode: int) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DATA_DIR / f"{stamp}_{label}.json"
    record = {
        "label": label,
        "ip": ip,
        "mode": mode,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        **summary,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def print_summary(s: dict) -> None:
    print()
    print(f"  muestras OK / fallidas : {s['n_ok']} / {s['n_fail']}")
    print(f"  media                  : {s['mean_ms']:.1f} ms")
    print(f"  p50                    : {s['p50_ms']:.1f} ms")
    print(f"  p95                    : {s['p95_ms']:.1f} ms   <- la cola es lo que decide")
    print(f"  máximo                 : {s['max_ms']:.1f} ms")
    print(f"  fracción > {PERIOD_MS:.0f} ms       : {s['frac_over_period'] * 100:.1f} %")
    print(f"  throughput             : {s['throughput_hz']:.1f} Hz")
    print(f"  loop_dt_max_us         : {s['loop_dt_max_us']}  (nominal 2000)")
    print(f"  loop_overruns          : {s['loop_overruns']}")
    print()


def report() -> None:
    runs = sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []
    if not runs:
        print(f"No hay corridas guardadas en {DATA_DIR}")
        return

    print(f"\n{'corrida':<22} {'label':<10} {'media':>8} {'p50':>8} {'p95':>8} {'máx':>8} {'>20ms':>8} {'Hz':>6} {'dt_max':>8}")
    print("-" * 96)
    by_label: dict[str, list[dict]] = {}
    for path in runs:
        r = json.loads(path.read_text(encoding="utf-8"))
        by_label.setdefault(r["label"], []).append(r)
        print(
            f"{path.stem:<22} {r['label']:<10} {r['mean_ms']:>7.1f}m {r['p50_ms']:>7.1f}m "
            f"{r['p95_ms']:>7.1f}m {r['max_ms']:>7.1f}m {r['frac_over_period'] * 100:>7.1f}% "
            f"{r['throughput_hz']:>5.1f} {r['loop_dt_max_us']!s:>8}"
        )

    print("\nMedianas por configuración (sobre las corridas de cada label):")
    for label, rs in by_label.items():
        print(
            f"  {label:<10} media {statistics.median([r['mean_ms'] for r in rs]):>6.1f} ms  |  "
            f"p95 {statistics.median([r['p95_ms'] for r in rs]):>6.1f} ms  |  "
            f">20ms {statistics.median([r['frac_over_period'] for r in rs]) * 100:>5.1f} %  "
            f"({len(rs)} corridas)"
        )
    print("\nCriterio pre-registrado (README §criterio): se adopta SoftAP puro si la media")
    print("baja >=20 % Y el p95 NO empeora Y la fracción >20 ms NO aumenta.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Correr una medición")
    run.add_argument("--label", required=True, help="Etiqueta de la configuración: softap | apsta")
    run.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default {DEFAULT_IP})")
    run.add_argument("--n", type=int, default=2000, help="Número de round-trips (default 2000)")
    run.add_argument("--mode", type=int, default=0, help="Modo del firmware durante la medición (default 0 = motor OFF)")
    run.add_argument("--timeout", type=float, default=0.4, help="Timeout HTTP [s], igual al de QubeRealEnv")
    sub.add_parser("report", help="Tabla comparativa de las corridas guardadas")

    args = ap.parse_args()
    if args.cmd == "report":
        report()
        return

    if args.mode != 0:
        print(f"\n  AVISO: modo {args.mode} deja el MOTOR HABILITADO. Brazo despejado.")
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("  ENTER para continuar, Ctrl-C para abortar... ")

    summary = measure(args.ip, args.n, args.mode, args.timeout)
    path = save(summary, args.label, args.ip, args.mode)
    print_summary(summary)
    print(f"Guardado en {path}")


if __name__ == "__main__":
    main()
