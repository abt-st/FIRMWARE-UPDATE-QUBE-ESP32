"""Intentos de swing-up (m5) instrumentados, con homing entre intentos.

Cada intento: homing -> m5 -> muestreo hasta que la placa vuelva a m0 (safeStop o
fin del swing-up) o se agote el tiempo -> m0.

Convencion del pendulo: colgando = 0 deg, VERTICAL = 180 deg. El firmware habilita
el traspaso a LQR con |alpha| > SWINGUP_TRANS_NEAR_DEG = 120 (60 deg de la vertical),
asi que "llego a 130" NO significa que se paro: significa que entro a la ventana.

Se muestrea lo mas rapido que deje el HTTP (sin sleep). A 2048 CPR cada conteo son
0.176 deg, asi que la velocidad por diferencias finitas es ruidosa: se reporta como
referencia, no como medida fina.

Uso:
    python swingup_attempt.py --ip 192.168.100.50 --attempts 5
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

UPRIGHT_DEG = 180.0
TRANS_NEAR_DEG = 120.0   # SWINGUP_TRANS_NEAR_DEG en el firmware
SERVO_LIMIT_DEG = 95.0

# Bitmask de `swing_trans_reason` (firmware >= v1.55.0). Los 4 criterios exigen
# |pendPos| > 120, asi que un alpha de traspaso menor solo puede ser retraso de
# muestreo: por eso el firmware latchea el valor y no se infiere desde el cliente.
REASON_BITS = {0x01: "near+slow", 0x02: "peak", 0x04: "forced", 0x08: "energy"}


def decode_reason(mask: int) -> str:
    if not mask:
        return "-"
    # Puede haber varios a la vez: el firmware evalua los 4 antes de cortocircuitar.
    return "+".join(name for bit, name in REASON_BITS.items() if mask & bit)


# Pausa entre muestras. NO es cosmetica: el AsyncTCP del ESP32 es sensible a la
# rotacion de conexiones (ver el contrato de concurrencia en qube_rl/envs/qube_real.py)
# y muestrear sin pausa alguna llego a dejar la placa sin responder. 25 Hz sobra para
# ver el bombeo y deja respirar al lazo de 500 Hz.
SAMPLE_DT = 0.04


class Qube:
    def __init__(self, ip: str) -> None:
        self.base = f"http://{ip}"
        self.s = requests.Session()
        # Keep-alive: se paga el handshake una vez y no por muestra.
        self.s.headers.update({"Connection": "keep-alive"})
        self.s.mount("http://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=4))

    def cmd(self, **p) -> dict:
        r = self.s.get(f"{self.base}/cmd", params=p, timeout=3)
        r.raise_for_status()
        return r.json()

    def state(self, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                r = self.s.get(f"{self.base}/state", timeout=2)
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(0.15)
        raise RuntimeError("unreachable")

    def homing(self, timeout=30.0, settle=0.0):
        # Espera opcional antes de disparar. Por defecto 0: el firmware ya espera
        # quietud en la fase WAIT_QUIET. Se midio que esperar desde el cliente NO
        # cambia la tasa de fallo — la causa del fallo intermitente era un punto duro
        # mecanico, no inercia residual (ver docs/REGISTRO_PROBLEMAS.md, P3).
        if settle > 0:
            self.cmd(m=0)
            time.sleep(settle)
        self.cmd(m=3)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self.state()
            if d.get("homing_phase") == "DONE":
                return d
            if d.get("homing_phase") == "FAIL":
                raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
            time.sleep(0.2)
        raise RuntimeError("homing timeout")


def attempt(q: Qube, idx: int, max_s: float) -> tuple[dict, list[dict]]:
    h = q.homing()
    print(f"\n--- intento {idx}  (homing: recorrido={h['homing_range']:.2f}) ---")

    q.cmd(m=5)
    rows: list[dict] = []
    t0 = time.monotonic()
    prev_mode = 5
    handoff_t = None
    while (t := time.monotonic() - t0) < max_s:
        try:
            d = q.state()
        except requests.RequestException:
            time.sleep(SAMPLE_DT)
            continue
        mode = d.get("mode")
        rows.append(
            {
                "t_s": round(t, 4),
                "mode": mode,
                "alpha_deg": d.get("pend_position_deg"),
                "theta_deg": d.get("position_deg"),
                "pwm": d.get("pwm"),
                "i_ma": d.get("i_ma"),
            }
        )
        if mode != prev_mode:
            print(f"  t={t:6.2f}s  modo {prev_mode} -> {mode}   alpha={d.get('pend_position_deg')}  theta={d.get('position_deg')}")
            if prev_mode == 5 and mode == 4:
                handoff_t = t
            prev_mode = mode
            if mode == 0:
                break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    # Telemetria latcheada del traspaso: es el dato fiable, medido por el firmware
    # EN el instante de la transicion y no por muestreo del modo desde afuera.
    trans = {}
    try:
        d = q.state()
        if d.get("swing_trans_reason") is not None:
            trans = {
                "reason_mask": int(d["swing_trans_reason"]),
                "reason": decode_reason(int(d["swing_trans_reason"])),
                "alpha_deg": float(d["swing_trans_alpha"]),
                "vel_dps": float(d["swing_trans_vel"]),
                "energy_ratio": float(d["swing_trans_energy"]),
            }
            if trans["reason_mask"]:
                print(
                    f"  traspaso latcheado: criterio={trans['reason']}"
                    f"  alpha={trans['alpha_deg']:.2f}  vel={trans['vel_dps']:.2f} deg/s"
                    f"  E/E*={trans['energy_ratio']:.3f}"
                )
    except requests.RequestException:
        pass

    alphas = [abs(float(r["alpha_deg"])) for r in rows if r["alpha_deg"] is not None]
    thetas = [abs(float(r["theta_deg"])) for r in rows if r["theta_deg"] is not None]
    peak = max(alphas, default=0.0)
    modes_seen = sorted({r["mode"] for r in rows if r["mode"] is not None})
    # Tiempo sostenido en LQR: es lo unico que distingue "hubo traspaso" de
    # "hubo captura". Un traspaso que dura 1 s no capturo nada.
    lqr_s = sum(1 for r in rows if r["mode"] == 4) / len(rows) * (rows[-1]["t_s"] if rows else 0)
    return (
        {
            "attempt": idx,
            "samples": len(rows),
            "sample_hz": round(len(rows) / rows[-1]["t_s"], 1) if rows and rows[-1]["t_s"] else None,
            "alpha_peak_deg": round(peak, 2),
            "deg_from_upright": round(UPRIGHT_DEG - peak, 2),
            "entered_trans_window": peak > TRANS_NEAR_DEG,
            "handoff_to_lqr_s": round(handoff_t, 2) if handoff_t else None,
            "lqr_time_s": round(lqr_s, 2),
            "theta_abs_max_deg": round(max(thetas, default=0.0), 2),
            "hit_servo_limit": max(thetas, default=0.0) > SERVO_LIMIT_DEG,
            "modes_seen": modes_seen,
            "ended_in_stop": rows[-1]["mode"] == 0 if rows else None,
            "transition": trans or None,
        },
        rows,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--attempts", type=int, default=5)
    ap.add_argument("--max-s", type=float, default=20.0)
    ap.add_argument("--ke", type=float, default=None, help="ke_gain (ver caveat: puede no tener efecto)")
    args = ap.parse_args()

    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if args.ke is not None:
        q.cmd(ke=args.ke)
        print(f"ke_gain = {args.ke}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for i in range(1, args.attempts + 1):
        try:
            summary, rows = attempt(q, i, args.max_s)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR intento {i}: {exc}")
            q.cmd(m=0)
            continue
        if rows:
            with (DATA_DIR / f"attempt_{i:02d}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        print("  " + json.dumps({k: v for k, v in summary.items() if k != "attempt"}))
        results.append(summary)

    q.cmd(m=0)
    (DATA_DIR / "attempts.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    if results:
        peaks = [r["alpha_peak_deg"] for r in results]
        print("\n=== resumen ===")
        print(f"intentos: {len(results)}")
        print(f"pico |alpha|: min={min(peaks):.1f}  max={max(peaks):.1f}  (vertical = 180)")
        print(f"entraron a la ventana de traspaso (>{TRANS_NEAR_DEG}): {sum(r['entered_trans_window'] for r in results)}")
        print(f"traspasaron a LQR: {sum(r['handoff_to_lqr_s'] is not None for r in results)}")
        print(f"cortaron por limite de servo: {sum(r['hit_servo_limit'] for r in results)}")


if __name__ == "__main__":
    main()
