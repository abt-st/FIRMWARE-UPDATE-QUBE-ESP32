"""Analisis de la campania de validacion: repetibilidad entre repeticiones y veredictos.

Separado del runner a proposito: se puede re-analizar sin volver a mover el hardware,
que es lo caro y lo que no se puede repetir a voluntad.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MODES = {0: "STOP", 1: "PWM manual", 2: "PID servo", 3: "Homing",
         4: "LQR", 5: "Swing-up", 6: "Deep RL (HTTP)", 7: "Deep RL (chip)"}


def spread(vals: list[float]) -> str:
    """min–max + desviacion. Con n=3 la desviacion sola engania; el rango no."""
    if not vals:
        return "-"
    if len(vals) == 1:
        return f"{vals[0]:.2f}"
    return f"{min(vals):.2f}–{max(vals):.2f} (sd={statistics.pstdev(vals):.3f})"


def main() -> None:
    reps = json.loads((DATA / "reps.json").read_text(encoding="utf-8"))
    verdicts = {}
    vpath = DATA / "verdicts.json"
    if vpath.exists():
        verdicts = json.loads(vpath.read_text(encoding="utf-8"))

    print("=" * 78)
    print("REPETIBILIDAD ENTRE REPETICIONES")
    print("=" * 78)
    for m_str, rs in sorted(reps.items(), key=lambda kv: int(kv[0])):
        m = int(m_str)
        good = [r for r in rs if "error" not in r]
        errs = len(rs) - len(good)
        print(f"\nm{m}  {MODES[m]}   ({len(good)}/{len(rs)} ok" + (f", {errs} error" if errs else "") + ")")
        if not good:
            for r in rs:
                print(f"    ERROR: {r.get('error')}")
            continue
        print(f"    muestreo Hz     {spread([r['sample_hz'] for r in good if r.get('sample_hz')])}")
        print(f"    |theta| max     {spread([r['theta_abs_max'] for r in good])}")
        print(f"    PWM max         {spread([r['pwm_abs_max'] for r in good])}")
        print(f"    PWM activo frac {spread([r['pwm_active_frac'] for r in good])}")
        if any(r.get("hit_limit") for r in good):
            print(f"    cortes por limite: {sum(r['hit_limit'] for r in good)}/{len(good)}")

        # Metricas propias del modo
        if m == 1:
            print(f"    err seguim. PWM {spread([r['pwm_track_err_max'] for r in good if r.get('pwm_track_err_max') is not None])}")
        if m == 2:
            print(f"    error regimen   {spread([r['sse_max_deg'] for r in good if r.get('sse_max_deg') is not None])}")
            print(f"    sobrepaso %     {spread([r['overshoot_pct_max'] for r in good if r.get('overshoot_pct_max') is not None])}")
        if m == 5:
            print(f"    criterio        {set(r.get('trans_reason') for r in good)}")
            print(f"    alpha traspaso  {spread([r['trans_alpha'] for r in good if r.get('trans_alpha')])}")
            print(f"    E/E* traspaso   {spread([r['trans_energy'] for r in good if r.get('trans_energy')])}")
            print(f"    pico |alpha|    {spread([r['alpha_peak'] for r in good if r.get('alpha_peak')])}")
        if m == 7:
            print(f"    sd(PWM)        {spread([r['pwm_std'] for r in good if r.get('pwm_std') is not None])}")

    # ── Homing: la metrica transversal ────────────────────────────────────────
    print("\n" + "=" * 78)
    print("HOMING — todas las corridas de la campania")
    print("=" * 78)
    ranges, from_m3 = [], []
    for m_str, rs in reps.items():
        for r in rs:
            if r.get("pre_homing"):
                ranges.append(r["pre_homing"]["range"])
            if int(m_str) == 3 and r.get("range"):
                from_m3.append(r["range"])
    todos = ranges + from_m3
    if todos:
        print(f"    corridas        {len(todos)}")
        print(f"    recorrido       {spread(todos)}")
        print(f"    dispersion      {max(todos) - min(todos):.3f} deg "
              f"({(max(todos) - min(todos)) / 0.17578:.1f} conteos de encoder)")
    if from_m3:
        print(f"    centro (m3)     {spread(from_m3)}")

    if verdicts:
        print("\n" + "=" * 78)
        print("VEREDICTOS")
        print("=" * 78)
        for m_str, v in sorted(verdicts.items(), key=lambda kv: int(kv[0])):
            flag = "PASS" if v["pass"] else "FAIL"
            print(f"  m{m_str} {MODES[int(m_str)]:<18} {flag:<5} {v['reason']}")
        n_pass = sum(1 for v in verdicts.values() if v["pass"])
        print(f"\n  {n_pass}/{len(verdicts)} modos aprobados")


if __name__ == "__main__":
    main()
