"""P6 — Barrido del PID del modo 2: sobrepaso y error de regimen.

Contexto (docs/REGISTRO_PROBLEMAS.md, P6). La campana del 2026-07-30 reporto
"sobrepaso 68-77%". Esa cifra estaba inflada por la metrica: `validate.py`
normalizaba por |setpoint| en vez del tamano del escalon y tomaba max(|theta|) de
todo el segmento, transitorio de entrada incluido. Recalculado sobre las MISMAS
trazas con `step_overshoot`, el sobrepaso real es **38.8-42.0%** en el escalon
grande. Sigue siendo mucho; la causa candidata es amortiguamiento derivativo
insuficiente: Td = Kd/Kp = 0.05 s, con ~113 PWM de empuje inicial contra ~44 de
freno a 295 deg/s.

Aparte del sobrepaso hay un error de regimen de 4.8 deg que NO es del ajuste sino
friccion estatica: hasta el 2026-07-31 el kick anti-friccion exigia |err| > 8 deg y
aplicaba 12 PWM, y ninguna de las dos cosas servia — la banda donde el brazo queda
pegado es 0.8-8 deg, y 12 PWM no arranca un mecanismo que en homing necesita 45.
Ahora son `?se=` (umbral) y `?sk=` (piso) y se barren aca.

Se mide `hunting` a proposito: subir el piso del kick puede cambiar un error de
regimen por un ciclo limite alrededor del setpoint, que es peor. Un punto con
sobrepaso bajo y hunting alto NO es un punto bueno.

Uso:
    python sweep_pid.py --ip 192.168.100.50 --kd 0.15,0.3,0.45,0.6 --reps 3
    python sweep_pid.py --kp 2 --kd 0.3,0.45,0.6            # segunda pasada
    python sweep_pid.py --sweep-stiction --sk 12,20,30,40   # kick anti-friccion
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "2026-07-30_full_validation" / "scripts"))
from validate import Qube, step_overshoot

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE_DT = 0.04
STEPS = (20.0, -20.0, 0.0)   # mismo protocolo que la campana de validacion
SEG_S = 3.5
SETTLE_BAND_DEG = 2.0


def settling_time(seg: list[dict], sp: float) -> float | None:
    """Ultimo instante en que |theta - sp| sale de la banda, medido desde el escalon."""
    th = [(float(r["t_s"]), float(r["theta_deg"])) for r in seg]
    out = [t for t, v in th if abs(v - sp) > SETTLE_BAND_DEG]
    if not out:
        return 0.0
    if out[-1] >= th[-1][0] - 1e-9:
        return None          # nunca se asento dentro de la ventana
    return round(out[-1] - th[0][0], 2)


def hunting(seg: list[dict], sp: float) -> dict:
    """Actividad en regimen (ultimo 30%): cruces del setpoint y PWM no nulo.

    Un lazo asentado deja de accionar. Si el brazo sigue cruzando el setpoint y el
    puente sigue conmutando, hay ciclo limite — tipicamente un kick anti-friccion
    demasiado alto que empuja, pasa, y vuelve a empujar al otro lado.
    """
    tail = seg[int(len(seg) * 0.7):]
    if len(tail) < 3:
        return {"cruces": 0, "pwm_activo_frac": 0.0, "pp_deg": 0.0}
    err = [float(r["theta_deg"]) - sp for r in tail]
    cruces = sum(1 for a, b in itertools.pairwise(err) if a * b < 0)
    act = sum(1 for r in tail if r.get("pwm") is not None and abs(float(r["pwm"])) > 0)
    th = [float(r["theta_deg"]) for r in tail]
    return {"cruces": cruces,
            "pwm_activo_frac": round(act / len(tail), 2),
            "pp_deg": round(max(th) - min(th), 2)}


def run_point(q: Qube, gains: dict, rep: int) -> tuple[dict, list[dict]]:
    q.homing_retry()
    q.cmd(**gains)          # kp/ki/kd/se/sk — el firmware llama resetPid() en cada uno
    rows: list[dict] = []
    per_step: list[dict] = []

    for sp in STEPS:
        q.cmd(m=2, s=sp)
        seg, t0 = [], time.monotonic()
        while (t := time.monotonic() - t0) < SEG_S:
            try:
                d = q.state()
            except Exception:
                time.sleep(SAMPLE_DT)
                continue
            seg.append({"t_s": round(t, 4), "cmd_sp": sp, "mode": d.get("mode"),
                        "theta_deg": d.get("position_deg"), "alpha_deg": d.get("pend_position_deg"),
                        "pwm": d.get("pwm"), "i_ma": d.get("i_ma"), "v_bus": d.get("v_bus")})
            time.sleep(SAMPLE_DT)
        seg = [r for r in seg if r.get("theta_deg") is not None]
        rows += seg
        if not seg:
            continue
        th = [float(r["theta_deg"]) for r in seg]
        tail = seg[int(len(seg) * 0.7):]
        peak_abs = max(abs(v) for v in th)
        per_step.append({
            "sp": sp,
            "theta_0": round(th[0], 2),
            "escalon": round(sp - th[0], 2),
            "overshoot_pct": step_overshoot(seg, sp),
            # Metrica vieja, solo para empalmar con las tandas del 2026-07-30.
            "overshoot_legacy": (round((peak_abs - abs(sp)) / abs(sp) * 100, 1)
                                 if abs(sp) > 1 else None),
            "sse_deg": round(abs(statistics.mean(float(r["theta_deg"]) for r in tail) - sp), 2),
            "settle_s": settling_time(seg, sp),
            **hunting(seg, sp),
        })
    q.cmd(m=0)

    ov = [s["overshoot_pct"] for s in per_step if s["overshoot_pct"] is not None]
    return {
        **gains, "rep": rep,
        "overshoot_max": max(ov) if ov else None,
        "overshoot_legacy_max": max([s["overshoot_legacy"] for s in per_step
                                     if s["overshoot_legacy"] is not None], default=None),
        "sse_max": max(s["sse_deg"] for s in per_step) if per_step else None,
        "cruces_max": max(s["cruces"] for s in per_step) if per_step else None,
        "pwm_activo_max": max(s["pwm_activo_frac"] for s in per_step) if per_step else None,
        "hit_limit": any(abs(float(r["theta_deg"])) > 95.0 for r in rows),
        "pasos": per_step,
    }, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--kp", default="3.0")
    ap.add_argument("--ki", default="0.5")
    ap.add_argument("--kd", default="0.15,0.3,0.45,0.6")
    ap.add_argument("--se", default="2.0")
    ap.add_argument("--sk", default="30")
    ap.add_argument("--sweep-stiction", action="store_true",
                    help="barre se/sk en vez de kd (para el error de regimen)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tag", default="kd")
    args = ap.parse_args()

    def vals(s):
        return [float(x) for x in s.split(",")]

    puntos: list[dict] = []
    if args.sweep_stiction:
        for se in vals(args.se):
            for sk in vals(args.sk):
                puntos.append({"kp": vals(args.kp)[0], "ki": vals(args.ki)[0],
                               "kd": vals(args.kd)[0], "se": se, "sk": sk})
    else:
        for kp in vals(args.kp):
            for kd in vals(args.kd):
                puntos.append({"kp": kp, "ki": vals(args.ki)[0], "kd": kd,
                               "se": vals(args.se)[0], "sk": vals(args.sk)[0]})

    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    DATA.mkdir(parents=True, exist_ok=True)

    out: list[dict] = []
    # Intercalado por repeticion: una deriva lenta del banco afecta a todos los
    # puntos por igual en vez de castigar al ultimo.
    for rep in range(1, args.reps + 1):
        for p in puntos:
            name = "_".join(f"{k}{v:g}" for k, v in p.items())
            print(f"\n--- {name} rep {rep} ---")
            try:
                s, rows = run_point(q, p, rep)
            except Exception as exc:
                print(f"    ERROR: {exc}")
                q.cmd(m=0)
                continue
            if rows:
                with (DATA / f"{args.tag}_{name}_r{rep}.csv").open("w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
            print(f"    overshoot={s['overshoot_max']}% (vieja {s['overshoot_legacy_max']}%) "
                  f"sse={s['sse_max']} cruces={s['cruces_max']} pwm_act={s['pwm_activo_max']}")
            out.append(s)
            (DATA / f"sweep_{args.tag}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Restaurar los defaults del firmware para no dejar el banco con lo ultimo barrido.
    q.cmd(m=0, kp=3.0, ki=0.5, kd=0.15, se=2.0, sk=30)

    print("\n=== resumen ===")
    print(f"{'punto':>28} {'n':>3} {'sobrepaso %':>14} {'sse':>7} {'cruces':>7} {'pwm act':>8}")
    for p in puntos:
        name = " ".join(f"{k}={v:g}" for k, v in p.items())
        g = [r for r in out if all(r.get(k) == v for k, v in p.items())]
        if not g:
            continue
        ov = [r["overshoot_max"] for r in g if r["overshoot_max"] is not None]
        sse = [r["sse_max"] for r in g if r["sse_max"] is not None]
        print(f"{name:>28} {len(g):>3} {statistics.median(ov) if ov else float('nan'):>13.1f}"
              f" {statistics.median(sse) if sse else float('nan'):>7.2f}"
              f" {max(r['cruces_max'] or 0 for r in g):>7}"
              f" {max(r['pwm_activo_max'] or 0 for r in g):>8.2f}")
    print("\nCriterio: sobrepaso < 20% sin degradar sse (hoy 4.8) ni disparar hunting"
          " (cruces altos + pwm activo ~1.0 en regimen = ciclo limite).")


if __name__ == "__main__":
    main()
