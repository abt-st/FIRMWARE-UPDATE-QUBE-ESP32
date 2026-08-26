"""Barrido con ambos encoders: compara servo vs pendulum para calcular CPR del servo.

El encoder del pendulo ya tiene CPR=2048 confirmado. Al mover el motor,
grabamos ambos counts y calculamos la relacion.

Uso:
  uv run python experiments/2026-06-01_cpr_measurement/scripts/dual_encoder_sweep.py [--ip IP] [--pwm N]
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
    parser = argparse.ArgumentParser(description="Barrido dual encoder")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default: {DEFAULT_IP})")
    parser.add_argument("--pwm", type=int, default=50, help="Valor PWM (default: 50)")
    args = parser.parse_args()

    try:
        state = get_state(args.ip)
        print(f"[OK] Conectado a {args.ip}")
    except Exception as e:
        print(f"[FAIL] No se puede conectar: {e}")
        return

    # Parar + reset ambos encoders
    send_cmd(args.ip, {"x": ""})
    time.sleep(0.3)
    send_cmd(args.ip, {"r": ""})
    time.sleep(0.3)

    state = get_state(args.ip)
    print(f"     Servo count: {state.get('count')}, Pend count: {state.get('pend_count')}")

    # Fase 1: motor en una direccion
    print(f"\n  Fase 1: PWM +{args.pwm}...")
    send_cmd(args.ip, {"p": args.pwm, "m": 1})

    samples: list[tuple[float, int, int]] = []
    t_start = time.time()
    stale = 0
    prev_servo = 0

    while (time.time() - t_start) < 8.0:
        try:
            state = get_state(args.ip)
            t = time.time() - t_start
            servo = state.get("count", 0)
            pend = state.get("pend_count", 0)
            samples.append((t, servo, pend))

            if servo == prev_servo:
                stale += 1
            else:
                stale = 0
            prev_servo = servo
            if stale > 50:
                break
        except Exception:
            pass
        time.sleep(0.02)

    send_cmd(args.ip, {"x": ""})
    time.sleep(0.3)

    # Fase 2: motor en la otra direccion
    print(f"  Fase 2: PWM -{args.pwm}...")
    send_cmd(args.ip, {"r": ""})
    time.sleep(0.3)

    samples2: list[tuple[float, int, int]] = []
    t_start2 = time.time()
    stale2 = 0
    prev_servo2 = 0

    send_cmd(args.ip, {"p": -args.pwm, "m": 1})

    while (time.time() - t_start2) < 8.0:
        try:
            state = get_state(args.ip)
            t = time.time() - t_start2
            servo = state.get("count", 0)
            pend = state.get("pend_count", 0)
            samples2.append((t, servo, pend))

            if servo == prev_servo2:
                stale2 += 1
            else:
                stale2 = 0
            prev_servo2 = servo
            if stale2 > 50:
                break
        except Exception:
            pass
        time.sleep(0.02)

    send_cmd(args.ip, {"x": ""})

    # Analizar
    print(f"\n{'=' * 60}")
    print("  COMPARACION SERVO vs PENDULUM")
    print(f"{'=' * 60}")

    for label, samps in [("Fase 1 (+)", samples), ("Fase 2 (-)", samples2)]:
        if not samps:
            print(f"\n  {label}: sin datos")
            continue

        servo_start = samps[0][1]
        servo_end = samps[-1][1]
        pend_start = samps[0][2]
        pend_end = samps[-1][2]

        d_servo = servo_end - servo_start
        d_pend = pend_end - pend_start

        print(f"\n  {label}:")
        print(f"    Servo: {servo_start} -> {servo_end} (delta: {d_servo})")
        print(f"    Pend:  {pend_start} -> {pend_end} (delta: {d_pend})")

        if abs(d_pend) > 10:
            # Con CPR_pend = 2048, calcular grados reales del pendulo
            pend_deg = d_pend * (360.0 / 2048.0)
            # CPR_servo = d_servo / (pend_deg / 360)
            cpr_servo = d_servo / (pend_deg / 360.0)
            ratio = abs(d_servo) / abs(d_pend)
            print(f"    Pend grados reales: {pend_deg:.1f} deg")
            print(f"    CPR servo estimado: {cpr_servo:.1f}")
            print(f"    Ratio servo/pend: {ratio:.4f}")

    # Estimacion final
    all_servo = [s[1] for s in samples + samples2]
    all_pend = [s[2] for s in samples + samples2]

    if len(all_servo) > 2:
        servo_range = max(all_servo) - min(all_servo)
        pend_range = max(all_pend) - min(all_pend)

        if abs(pend_range) > 10:
            pend_deg = pend_range * (360.0 / 2048.0)
            cpr_final = servo_range / (pend_deg / 360.0)
            ratio_final = servo_range / pend_range

            print(f"\n  {'-' * 50}")
            print("  ESTIMACION FINAL:")
            print(f"    Rango servo: {servo_range} counts")
            print(f"    Rango pend:  {pend_range} counts ({pend_deg:.1f} deg)")
            print(f"    Ratio servo/pend: {ratio_final:.4f}")
            print(f"    CPR servo: {cpr_final:.1f}")
            print("    CPR pend confirmado: 2048")

            print("\n  CPRs estandar cercanos:")
            for std in [100, 200, 256, 360, 500, 512, 600, 1024, 1500, 2048, 3000, 4096]:
                error_pct = abs(cpr_final - std) / std * 100
                if error_pct < 15:
                    marker = " <- probable" if error_pct < 5 else ""
                    print(f"    {std:>6}: {error_pct:>5.1f}% error{marker}")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
