"""P5 — Caracterizar el pendulo por oscilacion libre.

Objetivo: obtener el periodo natural real y contrastarlo con el que implican las
constantes del firmware (PEND_MASS/PEND_LENGTH/PEND_INERTIA) que entran en `E/E*`.
Si no coinciden, `E/E*` no sirve como criterio de traspaso ni como metrica de bombeo.

Metodo: patear el pendulo con un pulso corto del brazo (modo 1), cortar, y registrar
la oscilacion libre. El periodo se estima por cruces por cero del angulo, que es
robusto al ruido de cuantizacion (0.176 deg/conteo) — mucho mas que derivar.

Ojo: se muestrea a ~13 Hz por la latencia HTTP. Para una oscilacion de ~1-2 Hz eso son
7-13 muestras por ciclo: alcanza para el PERIODO promediado sobre muchos ciclos, NO
para la forma de onda ni para la amortiguacion fina.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE_DT = 0.035


class Qube:
    def __init__(self, ip: str) -> None:
        self.base = f"http://{ip}"
        self.s = requests.Session()
        self.s.headers.update({"Connection": "keep-alive"})
        self.s.mount("http://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=4))

    def cmd(self, **p):
        return self.s.get(f"{self.base}/cmd", params=p, timeout=3).json()

    def state(self):
        for i in range(3):
            try:
                r = self.s.get(f"{self.base}/state", timeout=2)
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if i == 2:
                    raise
                time.sleep(0.15)

    def homing(self, timeout=30.0, settle=0.0):
        # Espera opcional antes de disparar. Por defecto 0: el firmware ya espera
        # quietud en la fase WAIT_QUIET. Se midio que esperar desde el cliente NO
        # cambia la tasa de fallo — la causa del fallo intermitente era un punto duro
        # mecanico, no inercia residual (ver docs/REGISTRO_PROBLEMAS.md, P3).
        if settle > 0:
            self.cmd(m=0)
            time.sleep(settle)
        self.cmd(m=3)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            d = self.state()
            if d.get("homing_phase") == "DONE":
                return d
            if d.get("homing_phase") == "FAIL":
                raise RuntimeError(f"homing FAIL {d.get('homing_fail')}")
            time.sleep(0.2)
        raise RuntimeError("homing timeout")


def zero_crossings(ts: list[float], xs: list[float]) -> list[float]:
    """Instantes de cruce por cero con interpolacion lineal."""
    out = []
    for i in range(1, len(xs)):
        a, b = xs[i - 1], xs[i]
        if a == 0.0:
            out.append(ts[i - 1])
        elif (a < 0) != (b < 0):
            frac = abs(a) / (abs(a) + abs(b))
            out.append(ts[i - 1] + frac * (ts[i] - ts[i - 1]))
    return out


def run(q: Qube, idx: int, kick_pwm: int, kick_ms: int, watch_s: float):
    q.homing()
    # Patada corta desde el centro. El modo 1 tiene deadman de 2.5 s, pero el pulso
    # es de decimas: se corta explicitamente enseguida.
    q.cmd(m=1)
    q.cmd(p=kick_pwm)
    time.sleep(kick_ms / 1000.0)
    q.cmd(p=-kick_pwm)          # frenar el brazo para no arrastrar la oscilacion
    time.sleep(kick_ms / 1000.0)
    q.cmd(m=0)

    rows, t0 = [], time.monotonic()
    while (t := time.monotonic() - t0) < watch_s:
        try:
            d = q.state()
        except requests.RequestException:
            time.sleep(SAMPLE_DT)
            continue
        rows.append({"t_s": round(t, 4),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"),
                     "pwm": d.get("pwm")})
        time.sleep(SAMPLE_DT)

    ts = [r["t_s"] for r in rows]
    al = [float(r["alpha_deg"]) for r in rows]
    # Quitar el offset residual: el cero del pendulo puede no ser exactamente el
    # reposo, y un sesgo desplaza los cruces y sesga el periodo.
    bias = statistics.mean(al[-max(5, len(al) // 5):])
    xs = [a - bias for a in al]
    zc = zero_crossings(ts, xs)
    half = [zc[i + 1] - zc[i] for i in range(len(zc) - 1)]
    # Semiperiodos -> periodo. Se descartan los primeros cruces: el brazo todavia
    # esta disipando la patada y ahi la oscilacion no es libre.
    half_clean = half[2:] if len(half) > 6 else half
    T = 2 * statistics.mean(half_clean) if half_clean else None
    amp0 = max((abs(x) for x in xs[: len(xs) // 4]), default=0.0)
    return {
        "run": idx, "kick_pwm": kick_pwm, "kick_ms": kick_ms,
        "samples": len(rows), "sample_hz": round(len(rows) / ts[-1], 1) if ts else None,
        "bias_deg": round(bias, 3),
        "amp_inicial_deg": round(amp0, 2),
        "cruces": len(zc),
        "periodo_s": round(T, 4) if T else None,
        "freq_hz": round(1 / T, 4) if T else None,
        "semiperiodos_sd": round(statistics.pstdev(half_clean), 4) if len(half_clean) > 1 else None,
    }, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--watch-s", type=float, default=20.0)
    args = ap.parse_args()

    q = Qube(args.ip)
    DATA.mkdir(parents=True, exist_ok=True)
    out = []
    # Dos amplitudes de patada: si el periodo depende de la amplitud, el pendulo no
    # esta en regimen lineal y comparar contra sqrt(mgl/I) no seria valido.
    kicks = [(70, 180), (70, 180), (110, 220), (110, 220)]
    for i in range(1, args.runs + 1):
        pwm, ms = kicks[(i - 1) % len(kicks)]
        print(f"\n--- corrida {i}: patada PWM {pwm} durante {ms} ms ---")
        try:
            s, rows = run(q, i, pwm, ms, args.watch_s)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: {exc}")
            q.cmd(m=0)
            continue
        with (DATA / f"free_{i:02d}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("    " + json.dumps(s))
        out.append(s)
    q.cmd(m=0)
    (DATA / "free_swing.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    per = [s["periodo_s"] for s in out if s.get("periodo_s")]
    if per:
        print(f"\nperiodo: {min(per):.4f}–{max(per):.4f} s   "
              f"media {statistics.mean(per):.4f} s   f = {1/statistics.mean(per):.3f} Hz")


if __name__ == "__main__":
    main()
