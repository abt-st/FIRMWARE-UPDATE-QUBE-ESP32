#!/usr/bin/env python3
"""
Session Prep — Verificación de hardware + búsqueda de parámetros para constrained catch.

Este script:
  1. Verifica que los encoders estén conectados y respondan
  2. Confirma firmware actual (parámetros LQR, swing-up, transición)
  3. Ejecuta grid search de parámetros para maximizar constrained catch rate
  4. Genera reporte con las mejores configuraciones encontradas

Uso:
  uv run python experiments/2026-06-15_training/session_prep.py

Requisitos:
  - ESP32 encendido y conectado a 192.168.100.50
  - Péndulo libre (sin obstrucciones)
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Force UTF-8 on Windows to avoid cp1252 encoding errors
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

IP = "192.168.100.50"
HTTP_TIMEOUT = 3
MAX_RETRIES = 5

OUT_DIR = Path(__file__).parent / "data" / f"grid_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

# ── Grid search parameters ─────────────────────────────────────────────────
# Each tuple: (sp, ke_override_or_None, label)
# ke_override: None = use firmware default (adaptive), float = force specific value
GRID: list[tuple[int, float | None, str]] = [
    # Baseline (mejor resultado anterior)
    (80, None, "sp80_baseline"),
    (80, 0.80, "sp80_ke080"),
    (80, 0.90, "sp80_ke090"),
    # Más energía
    (85, None, "sp85_baseline"),
    (85, 0.80, "sp85_ke080"),
    (85, 0.90, "sp85_ke090"),
    # sp=90 (primer intento anterior dio CATCH)
    (90, None, "90_baseline"),
    (90, 0.80, "sp90_ke080"),
    (90, 0.90, "sp90_ke090"),
    # sp=95 (agresivo)
    (95, None, "sp95_baseline"),
    (95, 0.85, "sp95_ke085"),
]

ATTEMPTS_PER_CONFIG = 10
DURATION = 30  # seconds per attempt
POLL_HZ = 5
PEND_LIMIT = 90.0
PAUSE_BETWEEN = 5


def _http_get(url: str) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, json.JSONDecodeError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(0.2 * (attempt + 1))
    return {}


def cmd(param: str) -> dict:
    return _http_get(f"http://{IP}/cmd?{param}")


def state() -> dict:
    return _http_get(f"http://{IP}/state")


# ═══════════════════════════════════════════════════════════════════════════
# FASE 1: Verificación de hardware
# ═══════════════════════════════════════════════════════════════════════════


def verify_encoders() -> bool:
    """Verifica que los encoders respondan al mover el péndulo manualmente."""
    print("\n" + "=" * 60)
    print("FASE 1: Verificación de hardware")
    print("=" * 60)

    # Stop motor
    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(0.5)

    # Check basic connectivity
    try:
        s = state()
    except Exception as e:
        print(f"  ✗ No se puede conectar al ESP32: {e}")
        return False

    print(f"  ✓ Conectado al ESP32 ({IP})")
    print(f"    Firmware mode: {s.get('mode', '?')}")
    print(f"    INA219: {'OK' if s.get('ina_ok') else 'DESCONECTADO'}")
    print(f"    V_bus: {s.get('v_bus', 0):.1f}V")

    # Reset encoders
    cmd("r=1")
    time.sleep(0.5)
    s1 = state()
    pend1 = s1.get("pend_count", 0)

    print("\n  >>> MUEVE EL PÉNDULO MANUALMENTE (10 segundos) <<<")
    print("  >>> El péndulo debe oscilar libremente              <<<")
    for i in range(10, 0, -1):
        print(f"  ... {i}s restantes", end="\r")
        time.sleep(1)

    s2 = state()
    pend2 = s2.get("pend_count", 0)
    delta = abs(pend2 - pend1)

    print()
    if delta < 10:
        print(f"  ✗ Encoder péndulo NO responde (delta={delta})")
        print("    Verificar conexiones GPIO32/33 y Schmitt Trigger")
        return False

    print(f"  ✓ Encoder péndulo OK (delta={delta} counts)")
    print(f"    pend_position_deg: {s2.get('pend_position_deg', 0):.1f}°")
    return True


def show_firmware_params() -> None:
    """Muestra los parámetros actuales del firmware."""
    print("\n" + "=" * 60)
    print("FASE 2: Parámetros del firmware")
    print("=" * 60)

    s = state()
    print(f"  swingupPwmMax (sp):  {s.get('mode', '?')} (se lee al ejecutar)")
    print(f"  pend_position_deg:   {s.get('pend_position_deg', 0):.1f}°")
    print(f"  pend_count:          {s.get('pend_count', 0)}")
    print()

    # Read current sp by setting it and reading back
    # (firmware doesn't expose sp/ke in /state, so we note defaults)
    print("  Parámetros por defecto del firmware:")
    print("    ke_gain:     0.65 (base) / 0.75 (boost, x1.5)")
    print("    sp (PWM):    configurable via HTTP sp=<val>")
    print("    LQR trans:   |pendPos| > 120°")
    print("    Forced:      |pendPos| > 125°")
    print("    Catch mode:  400ms, gain=0.10, limit ±25")
    print("    LQR K2:      22.0 (base), 30.0 (near), 55.0 (very near)")
    print("    LQR K4:      9.0 (base), 15.0 (near), 20.0 (very near)")


# ═══════════════════════════════════════════════════════════════════════════
# FASE 3: Grid search
# ═══════════════════════════════════════════════════════════════════════════


def reset_pendulum() -> None:
    """Reset seguro: parar motor, esperar reposo, resetear encoder."""
    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(3.0)
    cmd("r=1")
    time.sleep(0.5)


def run_attempt(sp: int, ke: float | None, attempt: int, csvfile) -> dict:
    """Ejecuta un intento de swing-up + constrained catch."""
    reset_pendulum()

    # Configurar parámetros
    cmd(f"sp={sp}")
    time.sleep(0.05)
    if ke is not None:
        cmd(f"ke={ke:.2f}")
        time.sleep(0.05)

    # Iniciar swing-up
    cmd("m=5")
    time.sleep(0.1)

    t0 = time.time()
    max_angle = 0.0
    lqr_catch_time = None
    lqr_losses = 0
    in_lqr = False
    constraint_violated = False
    lqr_stable_time = None
    pend_settled = False
    settled_time = None
    samples = 0
    errors = 0

    while (time.time() - t0) < DURATION:
        try:
            s = state()
            errors = 0
        except Exception:
            errors += 1
            if errors > 20:
                break
            time.sleep(0.1)
            continue

        t = time.time() - t0
        pend = s.get("pend_position_deg", 0.0)
        mode = s.get("mode", 0)
        pwm = s.get("pwm", 0)
        v_bus = s.get("v_bus", 0.0)
        abs_pend = abs(pend)

        if abs_pend > max_angle:
            max_angle = abs_pend

        # Track LQR
        if mode == 4:
            if lqr_catch_time is None:
                lqr_catch_time = t
            in_lqr = True

            if not pend_settled:
                if abs_pend <= PEND_LIMIT:
                    pend_settled = True
                    settled_time = t
            elif abs_pend > PEND_LIMIT:
                constraint_violated = True
                lqr_stable_time = t - settled_time
                break
        elif in_lqr and mode != 4:
            lqr_losses += 1
            in_lqr = False

        csvfile.writerow([attempt, f"{t:.3f}", f"{pend:.2f}", mode, pwm, f"{v_bus:.3f}"])
        samples += 1
        time.sleep(1.0 / POLL_HZ)

    # Calcular tiempo estable si LQR sigue activo
    if in_lqr and not constraint_violated and lqr_catch_time is not None:
        lqr_stable_time = (time.time() - t0) - settled_time if pend_settled and settled_time is not None else 0

    try:
        final = state()
    except Exception:
        final = {"mode": -1}

    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(0.3)

    has_lqr = lqr_catch_time is not None
    final_mode = final.get("mode", -1)

    if not has_lqr:
        cls = "MISS"
    elif constraint_violated:
        cls = "ESCAPE"
    elif final_mode == 4 and lqr_losses == 0:
        cls = "CATCH"
    elif final_mode == 4 and lqr_losses > 0:
        cls = "CHATTER"
    else:
        cls = "TRANSIENT"

    return {
        "attempt": attempt,
        "classification": cls,
        "max_angle": max_angle,
        "lqr_catch_time": lqr_catch_time,
        "lqr_losses": lqr_losses,
        "constraint_violated": constraint_violated,
        "lqr_stable_time": lqr_stable_time,
        "samples": samples,
    }


def run_config(sp: int, ke: float | None, label: str) -> dict:
    """Ejecuta N intentos para una configuración y devuelve resumen."""
    cfg_dir = OUT_DIR / label
    cfg_dir.mkdir(parents=True, exist_ok=True)

    csv_path = cfg_dir / "data.csv"
    results: list[dict] = []

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["attempt", "t", "pend_deg", "mode", "pwm", "v_bus"])

        for i in range(1, ATTEMPTS_PER_CONFIG + 1):
            print(f"    [{i}/{ATTEMPTS_PER_CONFIG}] ", end="", flush=True)
            r = run_attempt(sp, ke, i, writer)
            results.append(r)
            print(f"{r['classification']:>10}  max={r['max_angle']:.0f}°", end="")
            if r["lqr_stable_time"] is not None:
                print(f"  stable={r['lqr_stable_time']:.1f}s", end="")
            print()
            time.sleep(PAUSE_BETWEEN)

    # Calcular estadísticas
    catches = sum(1 for r in results if r["classification"] == "CATCH")
    escapes = sum(1 for r in results if r["classification"] == "ESCAPE")
    chatters = sum(1 for r in results if r["classification"] == "CHATTER")
    misses = sum(1 for r in results if r["classification"] == "MISS")
    transients = sum(1 for r in results if r["classification"] == "TRANSIENT")
    n = len(results)

    stable_times = [
        r["lqr_stable_time"] for r in results if r["lqr_stable_time"] is not None and r["lqr_stable_time"] > 0
    ]
    avg_stable = sum(stable_times) / len(stable_times) if stable_times else 0.0

    summary = {
        "label": label,
        "sp": sp,
        "ke": ke,
        "n": n,
        "catch": catches,
        "catch_pct": catches / n * 100 if n else 0,
        "escape": escapes,
        "chatter": chatters,
        "miss": misses,
        "transient": transients,
        "avg_stable_time": avg_stable,
    }

    # Guardar summary
    summary_path = cfg_dir / "summary.txt"
    with open(summary_path, "w") as f:
        f.write(f"=== Grid Config: {label} ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"sp={sp}, ke={'default' if ke is None else f'{ke:.2f}'}\n")
        f.write(f"Attempts: {n}\n\n")
        f.write(f"CATCH:   {catches}/{n} ({catches / n * 100:.0f}%)\n")
        f.write(f"ESCAPE:  {escapes}/{n} ({escapes / n * 100:.0f}%)\n")
        f.write(f"CHATTER: {chatters}/{n} ({chatters / n * 100:.0f}%)\n")
        f.write(f"MISS:    {misses}/{n} ({misses / n * 100:.0f}%)\n")
        f.write(f"TRANS:   {transients}/{n} ({transients / n * 100:.0f}%)\n\n")
        if stable_times:
            f.write(f"Avg stable time (catches only): {avg_stable:.1f}s\n")

    return summary


def run_grid_search() -> list[dict]:
    """Ejecuta el grid search completo."""
    print("\n" + "=" * 60)
    print("FASE 3: Grid Search")
    print("=" * 60)
    print(f"  Configuraciones: {len(GRID)}")
    print(f"  Intentos por config: {ATTEMPTS_PER_CONFIG}")
    print(f"  Duración por intento: {DURATION}s")
    print(f"  Tiempo estimado: {len(GRID) * ATTEMPTS_PER_CONFIG * (DURATION + PAUSE_BETWEEN) / 60:.0f} min")
    print()

    summaries: list[dict] = []
    for idx, (sp, ke, label) in enumerate(GRID, 1):
        ke_str = "default" if ke is None else f"{ke:.2f}"
        print(f"\n  [{idx}/{len(GRID)}] sp={sp}, ke={ke_str} ({label})")
        print("  " + "-" * 40)
        summary = run_config(sp, ke, label)
        summaries.append(summary)
        print(
            f"    → CATCH: {summary['catch']}/{summary['n']} "
            f"({summary['catch_pct']:.0f}%) "
            f"avg_stable={summary['avg_stable_time']:.1f}s"
        )

    return summaries


# ═══════════════════════════════════════════════════════════════════════════
# FASE 4: Reporte
# ═══════════════════════════════════════════════════════════════════════════


def generate_report(summaries: list[dict]) -> None:
    """Genera reporte final con ranking de configuraciones."""
    print("\n" + "=" * 60)
    print("FASE 4: Resultados")
    print("=" * 60)

    # Ordenar por catch rate, luego por avg stable time
    ranked = sorted(summaries, key=lambda s: (s["catch_pct"], s["avg_stable_time"]), reverse=True)

    print(f"\n  {'Config':<20} {'SP':>3} {'KE':>6} {'Catch':>6} {'Esc':>4} {'Chat':>5} {'Miss':>5} {'AvgSt':>6}")
    print("  " + "-" * 60)
    for s in ranked:
        ke_str = "def" if s["ke"] is None else f"{s['ke']:.2f}"
        print(
            f"  {s['label']:<20} {s['sp']:>3} {ke_str:>6} "
            f"{s['catch']:>3}/{s['n']:<2} {s['escape']:>4} {s['chatter']:>5} "
            f"{s['miss']:>5} {s['avg_stable_time']:>5.1f}s"
        )

    best = ranked[0]
    print(f"\n  >>> MEJOR: {best['label']} — CATCH {best['catch_pct']:.0f}%, avg_stable={best['avg_stable_time']:.1f}s")

    if best["catch_pct"] >= 30:
        print("  >>> ¡META ALCANZADA! (>30% constrained catch rate)")
    else:
        print(f"  >>> Meta no alcanzada (target >30%). Mejor: {best['catch_pct']:.0f}%")

    # Guardar reporte
    report_path = OUT_DIR / "report.md"
    with open(report_path, "w") as f:
        f.write("# Grid Search Report\n\n")
        f.write(f"**Date:** {datetime.now().isoformat()}\n")
        f.write("**Target:** >30% constrained catch rate (±90°)\n")
        f.write(f"**Configs tested:** {len(summaries)}\n")
        f.write(f"**Attempts per config:** {ATTEMPTS_PER_CONFIG}\n\n")

        f.write("## Results (ranked by catch rate)\n\n")
        f.write("| Config | SP | KE | Catch | Escape | Chatter | Miss | Avg Stable |\n")
        f.write("|--------|-----|------|-------|--------|---------|------|------------|\n")
        for s in ranked:
            ke_str = "default" if s["ke"] is None else f"{s['ke']:.2f}"
            f.write(
                f"| {s['label']} | {s['sp']} | {ke_str} | "
                f"{s['catch']}/{s['n']} ({s['catch_pct']:.0f}%) | "
                f"{s['escape']} | {s['chatter']} | {s['miss']} | "
                f"{s['avg_stable_time']:.1f}s |\n"
            )

        f.write("\n## Best Configuration\n\n")
        f.write(f"- **Label:** {best['label']}\n")
        f.write(f"- **sp:** {best['sp']}\n")
        f.write(f"- **ke:** {'default (adaptive)' if best['ke'] is None else best['ke']}\n")
        f.write(f"- **Catch rate:** {best['catch_pct']:.0f}%\n")
        f.write(f"- **Avg stable time:** {best['avg_stable_time']:.1f}s\n")

        if best["catch_pct"] >= 30:
            f.write("\n**Target achieved!** (>30% constrained catch rate)\n")
        else:
            f.write(f"\n**Target not reached.** Best: {best['catch_pct']:.0f}%. ")
            f.write("Consider: longer attempts, firmware tuning, or different transition threshold.\n")

    print(f"\n  Reporte: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="QUBE Constrained Catch Grid Search")
    parser.add_argument("--skip-verify", action="store_true", help="Skip encoder verification")
    parser.add_argument("--skip-confirm", action="store_true", help="Skip interactive confirmation")
    args = parser.parse_args()

    print("=" * 60)
    print("QUBE Constrained Catch - Session Prep & Grid Search")
    print(f"Target: >30% catch rate within +/-{PEND_LIMIT:.0f} deg")
    print(f"ESP32: {IP}")
    print("=" * 60)

    # Fase 1: Verificar hardware
    if not args.skip_verify:
        if not verify_encoders():
            print("\n  X Hardware check FAILED. No continuar sin encoders.")
            print("  Comandos de verificacion:")
            print(f'    curl "http://{IP}/state"')
            print(f'    curl "http://{IP}/cmd?r=1"')
            return
    else:
        try:
            s = state()
            print(f"  [OK] Conectado al ESP32 ({IP})")
            ina_str = "OK" if s.get("ina_ok") else "DESCONECTADO"
            print(f"    INA219: {ina_str}")
        except Exception as e:
            print(f"  [FAIL] No se puede conectar: {e}")
            return

    # Fase 2: Mostrar parametros
    show_firmware_params()

    # Confirmar antes de grid search
    if not args.skip_confirm:
        print("\n  >>> Presiona ENTER para iniciar grid search (Ctrl+C para cancelar) <<<")
        try:
            input()
        except KeyboardInterrupt:
            print("\n  Cancelado.")
            return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fase 3: Grid search
    summaries = run_grid_search()

    # Fase 4: Reporte
    generate_report(summaries)

    print(f"\n  Datos completos: {OUT_DIR}")


if __name__ == "__main__":
    main()
