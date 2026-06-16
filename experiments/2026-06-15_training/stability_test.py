#!/usr/bin/env python3
"""
stability_test.py — Test de estabilidad a largo plazo para sp=60

Ejecuta intentos de swing-up repetidos durante 10 minutos.
Monitorea si el catch rate se degrada con el tiempo (fatiga, calentamiento, etc.).
Audita cada intento en tiempo real con clasificación CHATTER.
"""

import contextlib
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

IP = "192.168.100.50"
SP = 60
DURATION = 30  # seconds per attempt
POLL_HZ = 5  # realistic rate
PAUSE_BETWEEN = 5  # seconds between attempts
TOTAL_TIME = 600  # 10 minutes total
HTTP_TIMEOUT = 3
MAX_RETRIES = 5
MAX_ERRORS = 50

OUT_DIR = Path(__file__).parent / "data" / f"stability_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


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
    cmd("r=1")
    time.sleep(0.3)


def run_attempt(attempt: int, csvfile) -> dict:
    """Run one swing-up attempt and return classification."""
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

        if mode == 4:
            if lqr_catch_time is None:
                lqr_catch_time = t
            in_lqr = True
        elif in_lqr and mode != 4:
            lqr_losses += 1
            in_lqr = False

        csvfile.writerow([attempt, f"{t:.3f}", f"{pend:.2f}", mode, pwm, f"{v_bus:.3f}"])
        samples += 1
        time.sleep(1.0 / POLL_HZ)

    try:
        final = state()
    except Exception:
        final = {"mode": -1}

    with contextlib.suppress(Exception):
        cmd("x=1")
    time.sleep(0.3)

    has_lqr = lqr_catch_time is not None
    final_mode = final["mode"]

    if not has_lqr:
        cls = "MISS"
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
        "samples": samples,
        "duration": time.time() - t0,
        "wall_time": time.time(),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "stability_data.csv"
    summary_path = OUT_DIR / "summary.txt"

    print(f"=== Stability Test sp={SP} ({TOTAL_TIME // 60}min) ===")
    print(f"  IP: {IP}")
    print(f"  SP: {SP}")
    print(f"  Duration per attempt: {DURATION}s")
    print(f"  Pause between: {PAUSE_BETWEEN}s")
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
        remaining = TOTAL_TIME - elapsed
        print(f"[{elapsed / 60:.1f}m] Attempt {attempt} (remaining {remaining / 60:.1f}m)...", end=" ", flush=True)

        try:
            r = run_attempt(attempt, writer)
            results.append(r)

            cls = r["classification"]
            catch_str = f"t={r['lqr_catch_time']:.1f}s" if r["lqr_catch_time"] else "---"
            loss_str = f" losses={r['lqr_losses']}" if r["lqr_losses"] > 0 else ""
            print(f"{cls} max={r['max_angle']:.0f}° catch={catch_str}{loss_str} samples={r['samples']}")
        except Exception as e:
            print(f"ERROR: {e}")

        # Running stats
        if len(results) >= 3:
            recent = results[-5:]
            catches = sum(1 for r in recent if r["classification"] == "CATCH")
            chatters = sum(1 for r in recent if r["classification"] == "CHATTER")
            print(f"  Running (last {len(recent)}): {catches}C + {chatters}CH = {(catches + chatters) / len(recent) * 100:.0f}% catch")

        time.sleep(PAUSE_BETWEEN)

    csv_file.close()

    # Final summary
    total = len(results)
    catches = sum(1 for r in results if r["classification"] == "CATCH")
    chatters = sum(1 for r in results if r["classification"] == "CHATTER")
    transients = sum(1 for r in results if r["classification"] == "TRANSIENT")
    misses = sum(1 for r in results if r["classification"] == "MISS")

    catch_times = [r["lqr_catch_time"] for r in results if r["lqr_catch_time"]]
    avg_catch = sum(catch_times) / max(1, len(catch_times))
    max_angles = [r["max_angle"] for r in results]
    avg_max = sum(max_angles) / max(1, len(max_angles))

    # Degradation check: compare first half vs second half
    mid = len(results) // 2
    first_half = results[:mid]
    second_half = results[mid:]
    first_rate = sum(1 for r in first_half if r["classification"] == "CATCH") / max(1, len(first_half)) * 100
    second_rate = sum(1 for r in second_half if r["classification"] == "CATCH") / max(1, len(second_half)) * 100
    degradation = first_rate - second_rate

    with open(summary_path, "w") as f:
        f.write(f"=== Stability Test sp={SP} ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Total time: {TOTAL_TIME // 60}min\n")
        f.write(f"Attempts: {total}\n\n")

        f.write(f"Catches: {catches}/{total} ({catches / total * 100:.0f}%)\n")
        f.write(f"Chatters: {chatters}/{total} ({chatters / total * 100:.0f}%)\n")
        f.write(f"Transients: {transients}/{total}\n")
        f.write(f"Misses: {misses}/{total}\n\n")

        f.write(f"Avg catch time: {avg_catch:.1f}s\n")
        f.write(f"Avg max angle: {avg_max:.0f}°\n\n")

        f.write("=== Degradation Check ===\n")
        f.write(f"First half catch rate: {first_rate:.0f}%\n")
        f.write(f"Second half catch rate: {second_rate:.0f}%\n")
        f.write(f"Degradation: {degradation:+.0f}%\n")

        if degradation > 20:
            f.write("WARNING: Significant degradation detected!\n")
        elif degradation > 10:
            f.write("NOTICE: Mild degradation detected.\n")
        else:
            f.write("OK: No significant degradation.\n")

    print(f"\n{'=' * 60}")
    print(f"STABILITY RESULTS — sp={SP} ({TOTAL_TIME // 60}min)")
    print(f"{'=' * 60}")
    print(f"Attempts: {total}")
    print(f"Catches: {catches} ({catches / total * 100:.0f}%)")
    print(f"Chatters: {chatters} ({chatters / total * 100:.0f}%)")
    print(f"Misses: {misses}")
    print(f"Avg catch time: {avg_catch:.1f}s")
    print(f"Degradation: {degradation:+.0f}%")
    print(f"\nResults: {OUT_DIR}")


if __name__ == "__main__":
    main()
