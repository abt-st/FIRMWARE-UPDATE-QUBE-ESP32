"""P2 — Barrido del tope de la referencia de bombeo (`pr`, swingupPumpRefMaxDeg).

Reutiliza el runner del barrido de swingupPwmMax; la variable barrida cambia, la
metrica (meseta de amplitud en el apice) es la misma.

Motivo: medido en banco, el bombeo se queda en PWM 48-49 contra un tope de 50, o sea
SATURADO casi todo el tiempo. Con la salida recortada, `ke_gain` no puede influir —
por eso los barridos historicos de ese parametro nunca fueron atribuibles, incluso
despues de arreglar alpha_dot (bug F1).

Metrica: la MESETA de amplitud, no el pico unico. El bombeo crece ~9 deg/ciclo y
se estanca a los ~20 ciclos; lo que caracteriza la energia inyectable es donde se
estanca, y un pico aislado puede ser ruido.

`E/E*` se calcula en el apice (velocidad ~0), donde vale (1-cos alpha)/2 — geometria
pura, independiente del estimador de velocidad, cuya escala a alta velocidad esta en
duda (P9).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE_DT = 0.04


class Qube:
    def __init__(self, ip):
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


def peaks_of(rows):
    al = [(float(r["t_s"]), float(r["alpha_deg"])) for r in rows]
    out = []
    for i in range(1, len(al) - 1):
        a0, a1, a2 = al[i - 1][1], al[i][1], al[i + 1][1]
        if abs(a1) > abs(a0) and abs(a1) >= abs(a2) and abs(a1) > 20:
            out.append((al[i][0], abs(a1)))
    return out


def run(q, sp, rep, secs):
    q.homing()
    q.cmd(pr=sp)
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic() - t0) < secs:
        try:
            d = q.state()
        except requests.RequestException:
            time.sleep(SAMPLE_DT)
            continue
        rows.append({"t_s": round(t, 4), "mode": d.get("mode"),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"), "pwm": d.get("pwm")})
        if d.get("mode") == 0:
            break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    pk = peaks_of([r for r in rows if r["mode"] == 5])
    # Meseta = mediana del ultimo tercio de los picos. Mediana y no media: hay picos
    # sueltos bajos cuando el bombeo pierde fase, y sesgarian el promedio.
    tail = [v for _, v in pk[len(pk) * 2 // 3:]] if len(pk) >= 6 else [v for _, v in pk]
    meseta = statistics.median(tail) if tail else 0.0
    pwm_in = [abs(float(r["pwm"])) for r in rows if r["mode"] == 5]
    return {
        "sp": sp, "rep": rep, "picos": len(pk),
        "meseta_deg": round(meseta, 2),
        "pico_max_deg": round(max((v for _, v in pk), default=0.0), 2),
        "E_ratio_meseta": round((1 - math.cos(math.radians(meseta))) / 2, 4),
        "pwm_max": round(max(pwm_in, default=0.0), 0),
        "frac_saturado": round(sum(1 for x in pwm_in if x >= sp - 2) / len(pwm_in), 3) if pwm_in else None,
        "theta_max": round(max((abs(float(r["theta_deg"])) for r in rows if r["mode"] == 5), default=0.0), 1),
        "corto_por_limite": any(r["mode"] == 0 for r in rows),
    }, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--values", default="50,65,80,100")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--secs", type=float, default=20.0)
    args = ap.parse_args()

    q = Qube(args.ip)
    DATA.mkdir(parents=True, exist_ok=True)
    out = []
    for sp in [int(x) for x in args.values.split(",")]:
        for rep in range(1, args.reps + 1):
            print(f"\n--- swingupPwmMax={sp}  rep {rep} ---")
            try:
                s, rows = run(q, sp, rep, args.secs)
            except Exception as exc:  # noqa: BLE001
                print(f"    ERROR: {exc}")
                q.cmd(m=0)
                continue
            with (DATA / f"sweep_sp{sp}_r{rep}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print("    " + json.dumps(s))
            out.append(s)
    q.cmd(m=0)
    (DATA / "sweep_pwmmax.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n=== resumen ===")
    print(f"{'sp':>5} {'meseta':>9} {'E/E*':>7} {'pico max':>9} {'sat':>6} {'theta max':>10}")
    for sp in sorted({s['sp'] for s in out}):
        g = [s for s in out if s["sp"] == sp]
        print(f"{sp:>5} {statistics.mean(s['meseta_deg'] for s in g):>9.1f} "
              f"{statistics.mean(s['E_ratio_meseta'] for s in g):>7.3f} "
              f"{max(s['pico_max_deg'] for s in g):>9.1f} "
              f"{statistics.mean(s['frac_saturado'] for s in g):>6.2f} "
              f"{max(s['theta_max'] for s in g):>10.1f}")


if __name__ == "__main__":
    main()
