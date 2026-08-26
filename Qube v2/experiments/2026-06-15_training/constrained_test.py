#!/usr/bin/env python3
"""
constrained_test.py — Test con restriccion ±45° en fase LQR

Regla: Si el pendulo sale de ±45° DESPUES de entrar en modo LQR (mode 4),
el intento se cuenta como fallo y se resetea inmediatamente.

Si el pendulo se mantiene dentro de ±45° hasta el final del intento (30s),
cuenta como CATCH exitoso.

Durante swing-up (mode 5) no hay restriccion — el pendulo puede oscilar libremente.
"""

import contextlib
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

IP = "192.168.100.50"
SP = 90
DURATION = 30
POLL_HZ = 5
PAUSE_BETWEEN = 5
TOTAL_TIME = 600  # 10 min
HTTP_TIMEOUT = 3
MAX_RETRIES = 5
MAX_ERRORS = 50  # fallos de lectura consecutivos antes de abortar
PEND_LIMIT = 90.0  # grados

OUT_DIR = Path(__file__).parent / "data" / f"constrained_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def _http_get(url: str) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.05)
            else:
                raise


def cmd(param: str) -> dict:
    return _http_get(f"http://{IP}/cmd?{param}")


def state() -> dict:
    return _http_get(f"http://{IP}/state")


def reset() -> None:
    """Stop motor and reset encoder. Pendulum must be at rest."""
    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(3.0)  # wait for pendulum to settle
    cmd("r=1")
    time.sleep(0.5)


def run_attempt(attempt: int, csvfile) -> dict:
    reset()
    time.sleep(0.5)
    cmd(f"sp={SP}")
    time.sleep(0.1)
    cmd("m=5")
    time.sleep(0.1)

    t0 = time.time()
    max_angle = 0.0
    lqr_catch_time = None
    lqr_losses = 0
    in_lqr = False
    samples = 0
    errors = 0
    constraint_violated = False
    constraint_time = None
    lqr_stable_time = None  # tiempo que LQR mantuvo dentro de ±45°
    pend_settled = False  # True cuando el pendulo entra en ±45° por primera vez
    settled_time = None

    while (time.time() - t0) < DURATION:
        try:
            s = state()
            errors = 0
        except Exception:
            errors += 1
            if errors > MAX_ERRORS:
                break
            time.sleep(0.1)
            continue

        t = time.time() - t0
        pend = s["pend_position_deg"]
        mode = s["mode"]
        pwm = s["pwm"]
        v_bus = s["v_bus"]
        abs_pend = abs(pend)
        if abs_pend > max_angle:
            max_angle = abs_pend

        # Track LQR transitions
        if mode == 4:
            if lqr_catch_time is None:
                lqr_catch_time = t
            in_lqr = True

            # FASE 1: Convergencia — LQR acaba de entrar, pendulo esta en ~155°
            # Todavia no aplicamos la restriccion.
            if not pend_settled:
                if abs_pend <= PEND_LIMIT:
                    # El pendulo entro en ±45° por primera vez
                    pend_settled = True
                    settled_time = t
                # else: todavia convergiendo, no contar como escape

            # FASE 2: Establecido — el pendulo ya estuvo en ±45°
            # Ahora SI aplicamos la restriccion
            elif abs_pend > PEND_LIMIT:
                constraint_violated = True
                constraint_time = t
                lqr_stable_time = t - settled_time
                break
        elif in_lqr and mode != 4:
            lqr_losses += 1
            in_lqr = False

        csvfile.writerow([attempt, f"{t:.3f}", f"{pend:.2f}", mode, pwm, f"{v_bus:.3f}"])
        samples += 1
        time.sleep(1.0 / POLL_HZ)

    # Si no se rompio por constraint y LQR estaba activo, calcular tiempo estable
    if in_lqr and not constraint_violated and lqr_catch_time is not None:
        if pend_settled and settled_time is not None:
            lqr_stable_time = (time.time() - t0) - settled_time
        else:
            lqr_stable_time = 0  # LQR activo pero pendulo nunca llego a ±45°

    try:
        final = state()
    except Exception:
        final = {"mode": -1}

    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(0.3)

    has_lqr = lqr_catch_time is not None
    final_mode = final["mode"]

    # Clasificacion considerando constraint
    if not has_lqr:
        cls = "MISS"
    elif constraint_violated:
        cls = "ESCAPE"  # LQR entro pero pendulo se escapo de ±45°
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
        "constraint_time": constraint_time,
        "lqr_stable_time": lqr_stable_time,
        "samples": samples,
        "duration": time.time() - t0,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "constrained_data.csv"
    summary_path = OUT_DIR / "summary.txt"

    print(f"=== Constrained Test sp={SP} (±{PEND_LIMIT}°) ===")
    print(f"  IP: {IP}")
    print(f"  Pendulum limit: ±{PEND_LIMIT}° during LQR")
    print(f"  Duration: {TOTAL_TIME // 60}min")
    print(f"  Output: {OUT_DIR}")
    print()

    try:
        s = state()
        print(f"  ESP32 online: v={s['v_bus']:.1f}V mode={s['mode']}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    csv_file = open(csv_path, "w", newline="")  # noqa: SIM115
    writer = csv.writer(csv_file)
    writer.writerow(["attempt", "t", "pend_deg", "mode", "pwm", "v_bus"])

    results: list[dict] = []
    t_start = time.time()
    attempt = 0

    while (time.time() - t_start) < TOTAL_TIME:
        attempt += 1
        elapsed = time.time() - t_start
        print(f"[{elapsed / 60:.1f}m] Att {attempt}...", end=" ", flush=True)

        try:
            r = run_attempt(attempt, writer)
            results.append(r)

            cls = r["classification"]
            catch_str = f"t={r['lqr_catch_time']:.1f}s" if r["lqr_catch_time"] else "---"
            stable_str = f" stable={r['lqr_stable_time']:.1f}s" if r["lqr_stable_time"] is not None else ""
            escape_str = f" ESCAPED@{r['constraint_time']:.1f}s" if r["constraint_violated"] else ""
            print(f"{cls} max={r['max_angle']:.0f}° catch={catch_str}{stable_str}{escape_str}")

        except Exception as e:
            print(f"ERROR: {e}")

        # Running stats
        if len(results) >= 5:
            recent = results[-5:]
            catches = sum(1 for r in recent if r["classification"] == "CATCH")
            escapes = sum(1 for r in recent if r["classification"] == "ESCAPE")
            print(f"  Last 5: {catches}C {escapes}E ({catches / len(recent) * 100:.0f}% constrained catch)")

        time.sleep(PAUSE_BETWEEN)

    csv_file.close()

    # Summary
    total = len(results)
    catches = sum(1 for r in results if r["classification"] == "CATCH")
    chatters = sum(1 for r in results if r["classification"] == "CHATTER")
    escapes = sum(1 for r in results if r["classification"] == "ESCAPE")
    transients = sum(1 for r in results if r["classification"] == "TRANSIENT")
    misses = sum(1 for r in results if r["classification"] == "MISS")

    # Tiempos de estabilidad LQR dentro de ±45°
    stable_times = [r["lqr_stable_time"] for r in results if r["lqr_stable_time"] is not None]
    avg_stable = sum(stable_times) / max(1, len(stable_times))

    with open(summary_path, "w") as f:
        f.write(f"=== Constrained Test sp={SP} (±{PEND_LIMIT}°) ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Attempts: {total}\n\n")

        f.write(f"CATCH (dentro ±{PEND_LIMIT}°): {catches}/{total} ({catches / total * 100:.0f}%)\n")
        f.write(f"CHATTER: {chatters}/{total}\n")
        f.write(f"ESCAPE (salió de ±{PEND_LIMIT}°): {escapes}/{total} ({escapes / total * 100:.0f}%)\n")
        f.write(f"TRANSIENT: {transients}/{total}\n")
        f.write(f"MISS: {misses}/{total}\n\n")

        f.write(f"Avg LQR stable time (within ±{PEND_LIMIT}°): {avg_stable:.1f}s\n")

    print(f"\n{'=' * 60}")
    print(f"CONSTRAINED RESULTS — sp={SP} (±{PEND_LIMIT}°)")
    print(f"{'=' * 60}")
    print(f"CATCH (±{PEND_LIMIT}°): {catches} ({catches / total * 100:.0f}%)")
    print(f"ESCAPE: {escapes} ({escapes / total * 100:.0f}%)")
    print(f"CHATTER: {chatters}")
    print(f"MISS: {misses}")
    print(f"Avg LQR stable time: {avg_stable:.1f}s")
    print(f"\nResults: {OUT_DIR}")


if __name__ == "__main__":
    main()
