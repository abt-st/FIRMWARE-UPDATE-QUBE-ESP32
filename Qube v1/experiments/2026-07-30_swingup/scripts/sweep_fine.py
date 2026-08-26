"""P2 — Barrido FINO de `swingupPwmMax` (50..60, paso 1).

El barrido grueso (50/65/80/100) mostro que 50 da la mejor meseta y que a 65 la
corrida ya muere: el brazo cruza los 95 deg y salta safeStop antes de acumular
energia (los ciclos caen de 50 a 10). Pero entre 50 y 65 hay una region sin explorar
donde podria entrar mas energia por ciclo sin matar la corrida.

DISEÑO: dos pasadas, ascendente y descendente. Asi cada valor recibe una repeticion
temprana y una tardia, y una eventual deriva del banco (tension de bateria, friccion
con la temperatura) aparece como diferencia ENTRE pasadas en vez de disfrazarse de
tendencia con el parametro. Sin esto, con ~15 min de campania, una deriva monotona
seria indistinguible del efecto que se busca.

METRICA: la meseta (mediana del ultimo tercio de los picos), no el pico maximo. El
bombeo crece ~9 deg/ciclo y se estanca; lo que caracteriza la energia inyectable es
donde se estanca. `E/E*` se evalua en el apice, donde vale (1-cos alpha)/2 —
geometria pura, sin depender del estimador de velocidad (P9).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import DATA, SAMPLE_DT, Qube, peaks_of  # noqa: E402


def run(q: Qube, sp: int, tag: str, secs: float) -> tuple[dict, list[dict]]:
    q.homing()
    # Se fija TODO el resto en sus valores por defecto medidos, para que la unica
    # variable sea sp: ley resonante, sin recentrado, referencia en 70.
    q.cmd(pl=0, pc=0, pr=70, sp=sp)
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic() - t0) < secs:
        try:
            d = q.state()
        except Exception:  # noqa: BLE001
            time.sleep(SAMPLE_DT)
            continue
        rows.append({"t_s": round(t, 4), "mode": d.get("mode"),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"), "pwm": d.get("pwm")})
        if d.get("mode") == 0:
            break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    inm = [r for r in rows if r["mode"] == 5]
    pk = peaks_of(inm)
    tail = [v for _, v in pk[len(pk) * 2 // 3:]] if len(pk) >= 6 else [v for _, v in pk]
    meseta = statistics.median(tail) if tail else 0.0
    th = [abs(float(r["theta_deg"])) for r in inm]
    pw = [abs(float(r["pwm"])) for r in inm]
    return {
        "sp": sp, "pasada": tag, "picos": len(pk),
        "meseta": round(meseta, 2),
        "E_ratio": round((1 - math.cos(math.radians(meseta))) / 2, 4),
        "pico_max": round(max((v for _, v in pk), default=0.0), 2),
        "theta_max": round(max(th, default=0.0), 1),
        "pwm_max": round(max(pw, default=0.0), 0),
        "t_bombeo": round(inm[-1]["t_s"], 1) if inm else 0.0,
        "murio": any(r["mode"] == 0 for r in rows),
    }, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--lo", type=int, default=50)
    ap.add_argument("--hi", type=int, default=60)
    ap.add_argument("--secs", type=float, default=20.0)
    args = ap.parse_args()

    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    DATA.mkdir(parents=True, exist_ok=True)

    vals = list(range(args.lo, args.hi + 1))
    plan = [(v, "sube") for v in vals] + [(v, "baja") for v in reversed(vals)]
    out: list[dict] = []
    for i, (sp, tag) in enumerate(plan, 1):
        print(f"\n--- [{i}/{len(plan)}] sp={sp} ({tag}) ---")
        try:
            s, rows = run(q, sp, tag, args.secs)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: {exc}")
            q.cmd(m=0)
            continue
        with (DATA / f"fine_sp{sp}_{tag}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("    " + json.dumps(s))
        out.append(s)
        (DATA / "sweep_fine.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    q.cmd(m=0, sp=50)
    print("\n=== resumen (media de las dos pasadas) ===")
    print(f"{'sp':>4} {'meseta':>9} {'E/E*':>8} {'pico':>8} {'th max':>8} {'ciclos':>8} {'murio':>7}")
    for sp in vals:
        g = [r for r in out if r["sp"] == sp]
        if not g:
            continue
        print(f"{sp:>4} {statistics.mean(r['meseta'] for r in g):>9.2f}"
              f" {statistics.mean(r['E_ratio'] for r in g):>8.4f}"
              f" {max(r['pico_max'] for r in g):>8.2f}"
              f" {max(r['theta_max'] for r in g):>8.1f}"
              f" {statistics.mean(r['picos'] for r in g):>8.1f}"
              f" {sum(r['murio'] for r in g):>7}")

    print("\n=== control de deriva (misma sp, pasada temprana vs tardia) ===")
    diffs = []
    for sp in vals:
        a = next((r["meseta"] for r in out if r["sp"] == sp and r["pasada"] == "sube"), None)
        b = next((r["meseta"] for r in out if r["sp"] == sp and r["pasada"] == "baja"), None)
        if a is not None and b is not None:
            diffs.append(b - a)
            print(f"  sp={sp}: sube={a:.2f}  baja={b:.2f}  delta={b-a:+.2f}")
    if diffs:
        print(f"\n  deriva media entre pasadas: {statistics.mean(diffs):+.2f} deg")
        print("  (si esto es comparable a la variacion con sp, el efecto buscado no es separable)")


if __name__ == "__main__":
    main()
