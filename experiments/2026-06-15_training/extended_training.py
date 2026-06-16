#!/usr/bin/env python3
"""
extended_training.py — Entrenamiento extendido: estabilidad + fine-tuning SP

Fase 1: Estabilidad sp=60 x 20 minutos (~34 intentos)
Fase 2: Bracket sp=58, 62 x 10 intentos cada uno
Fase 3: Validacion con mejor SP x 15 minutos
"""

import contextlib
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

IP = "192.168.100.50"
DURATION = 30
POLL_HZ = 5
PAUSE_BETWEEN = 5
HTTP_TIMEOUT = 3
MAX_RETRIES = 5
MAX_ERRORS = 50

OUT_DIR = Path(__file__).parent / "data" / f"training_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


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


def run_attempt(sp: int, attempt: int, csvfile) -> dict:
    reset()
    time.sleep(0.5)
    cmd(f"sp={sp}")
    time.sleep(0.1)
    cmd("m=5")
    time.sleep(0.1)

    t0 = time.time()
    max_angle = 0.0
    lqr_catch_time = None
    lqr_losses = 0
    lqr_loss_times: list[float] = []
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
            lqr_loss_times.append(t)
            in_lqr = False

        csvfile.writerow([sp, attempt, f"{t:.3f}", f"{pend:.2f}", mode, pwm, f"{v_bus:.3f}"])
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
        "sp": sp,
        "attempt": attempt,
        "classification": cls,
        "max_angle": max_angle,
        "lqr_catch_time": lqr_catch_time,
        "lqr_losses": lqr_losses,
        "lqr_loss_times": lqr_loss_times,
        "samples": samples,
        "duration": time.time() - t0,
    }


def run_phase(phase_name: str, sp: int, num_attempts: int, csvfile, results: list[dict]) -> dict:
    """Run a training phase and return summary stats."""
    print(f"\n{'=' * 60}")
    print(f"PHASE: {phase_name} — sp={sp} x {num_attempts} attempts")
    print(f"{'=' * 60}")

    catches = 0
    chatters = 0
    misses = 0
    t_start = time.time()

    for i in range(1, num_attempts + 1):
        elapsed = time.time() - t_start
        print(f"  [{elapsed / 60:.1f}m] Attempt {i}/{num_attempts}...", end=" ", flush=True)

        try:
            r = run_attempt(sp, i, csvfile)
            results.append(r)

            cls = r["classification"]
            catch_str = f"t={r['lqr_catch_time']:.1f}s" if r["lqr_catch_time"] else "---"
            loss_str = f" losses={r['lqr_losses']}" if r["lqr_losses"] > 0 else ""
            print(f"{cls} max={r['max_angle']:.0f}° catch={catch_str}{loss_str}")

            if cls == "CATCH":
                catches += 1
            elif cls == "CHATTER":
                chatters += 1
            else:
                misses += 1

            # Running stats every 5 attempts
            if i % 5 == 0:
                total = catches + chatters + misses
                print(f"  Running: {catches}C + {chatters}CH + {misses}M = {(catches + chatters) / total * 100:.0f}% catch")

        except Exception as e:
            print(f"ERROR: {e}")
            misses += 1

        time.sleep(PAUSE_BETWEEN)

    total = catches + chatters + misses
    duration = time.time() - t_start

    summary = {
        "phase": phase_name,
        "sp": sp,
        "attempts": total,
        "catches": catches,
        "chatters": chatters,
        "misses": misses,
        "catch_rate": catches / max(1, total) * 100,
        "effective_rate": (catches + chatters) / max(1, total) * 100,
        "duration_min": duration / 60,
    }

    print(f"\n  RESULT: {catches}C + {chatters}CH + {misses}M")
    print(f"  Clean rate: {summary['catch_rate']:.0f}%")
    print(f"  Effective rate: {summary['effective_rate']:.0f}%")

    return summary


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "training_data.csv"
    summary_path = OUT_DIR / "summary.txt"

    print("=== Extended Training Session ===")
    print(f"  IP: {IP}")
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
    writer.writerow(["sp", "attempt", "t", "pend_deg", "mode", "pwm", "v_bus"])

    results: list[dict] = []
    phase_summaries: list[dict] = []

    # Phase 1: Stability sp=60 x 20 min (~34 attempts)
    s1 = run_phase("Stability sp=60", sp=60, num_attempts=34, csvfile=writer, results=results)
    phase_summaries.append(s1)

    # Phase 2a: Bracket sp=58 x 10 attempts
    s2a = run_phase("Bracket sp=58", sp=58, num_attempts=10, csvfile=writer, results=results)
    phase_summaries.append(s2a)

    # Phase 2b: Bracket sp=62 x 10 attempts
    s2b = run_phase("Bracket sp=62", sp=62, num_attempts=10, csvfile=writer, results=results)
    phase_summaries.append(s2b)

    csv_file.close()

    # Find best SP
    sp_stats: dict[int, dict] = {}
    for sp in [58, 60, 62]:
        sp_r = [r for r in results if r["sp"] == sp]
        catches = sum(1 for r in sp_r if r["classification"] == "CATCH")
        chatters = sum(1 for r in sp_r if r["classification"] == "CHATTER")
        total = len(sp_r)
        sp_stats[sp] = {
            "catches": catches,
            "chatters": chatters,
            "misses": total - catches - chatters,
            "total": total,
            "clean_rate": catches / max(1, total) * 100,
            "effective_rate": (catches + chatters) / max(1, total) * 100,
        }

    # Best = highest clean rate, ties broken by effective rate
    best_sp = max(sp_stats.keys(), key=lambda sp: (sp_stats[sp]["clean_rate"], sp_stats[sp]["effective_rate"]))

    # Phase 3: Validation with best SP x 15 min (~26 attempts)
    print(f"\n{'#' * 60}")
    print(f"BEST SP: {best_sp} (clean rate: {sp_stats[best_sp]['clean_rate']:.0f}%)")
    print(f"{'#' * 60}")

    csv_file = open(csv_path, "a", newline="")  # noqa: SIM115
    writer = csv.writer(csv_file)

    s3 = run_phase("Validation", sp=best_sp, num_attempts=26, csvfile=writer, results=results)
    phase_summaries.append(s3)

    csv_file.close()

    # Write summary
    with open(summary_path, "w") as f:
        f.write("=== Extended Training Session Results ===\n\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Total attempts: {len(results)}\n\n")

        f.write("=== Phase Results ===\n\n")
        for s in phase_summaries:
            f.write(f"{s['phase']} (sp={s['sp']}):\n")
            f.write(f"  {s['catches']}C + {s['chatters']}CH + {s['misses']}M "
                    f"| clean={s['catch_rate']:.0f}% effective={s['effective_rate']:.0f}% "
                    f"| {s['duration_min']:.1f}min\n\n")

        f.write("=== SP Comparison ===\n\n")
        f.write(f"{'SP':>4} | {'Catch':>5} | {'Chat':>5} | {'Miss':>4} | {'Clean%':>6} | {'Eff%':>6}\n")
        f.write("-" * 45 + "\n")
        for sp in sorted(sp_stats.keys()):
            st = sp_stats[sp]
            marker = " <-- BEST" if sp == best_sp else ""
            f.write(f"{sp:>4} | {st['catches']:>5} | {st['chatters']:>5} | {st['misses']:>4} | "
                    f"{st['clean_rate']:>5.0f}% | {st['effective_rate']:>5.0f}%{marker}\n")

        f.write(f"\nBest SP: {best_sp}\n")

        # Overshoot analysis
        f.write("\n=== Overshoot Analysis ===\n\n")
        overshoot = [r for r in results if r["max_angle"] > 200]
        clean = [r for r in results if r["max_angle"] <= 200]
        if overshoot:
            overshoot_chatter = sum(1 for r in overshoot if r["classification"] == "CHATTER")
            f.write(f"Attempts with overshoot (>200°): {len(overshoot)}\n")
            f.write(f"  Of which CHATTER: {overshoot_chatter} ({overshoot_chatter / len(overshoot) * 100:.0f}%)\n")
        if clean:
            clean_catch = sum(1 for r in clean if r["classification"] == "CATCH")
            f.write(f"Attempts without overshoot (≤200°): {len(clean)}\n")
            f.write(f"  Of which CATCH: {clean_catch} ({clean_catch / len(clean) * 100:.0f}%)\n")

    print(f"\n{'=' * 60}")
    print("TRAINING COMPLETE")
    print(f"{'=' * 60}")
    print(f"Best SP: {best_sp}")
    print(f"Total attempts: {len(results)}")
    print(f"Results: {OUT_DIR}")

    with open(summary_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()
