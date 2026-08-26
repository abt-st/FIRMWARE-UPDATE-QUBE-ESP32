"""Valida `analyse()` de m4_daq.py contra trazas cuyas cifras ya se conocen.

Las 10 corridas de `2026-08-04_m5_swingup/` traen el modo 4 completo a 500 Hz con el catch
por defecto (lc=400), y de ellas salieron los numeros que esta campana usa como referencia:
saturacion mediana 70,4% y perdida del pendulo entre 0 y 86 ms del traspaso.

Correr esto ANTES de la sesion de banco. Un error de metrica descubierto con el motor
girando cuesta la sesion entera; descubierto aca no cuesta nada. Este experimento ya tiene
tres casos de conclusiones sacadas de la instrumentacion y no del equipo.

    uv run python selftest.py
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m4_daq import analyse

M5 = Path(__file__).resolve().parents[2] / "2026-08-04_m5_swingup" / "data"
LC_DEFAULT_MS = 400  # las trazas del m5 corrieron con el catch por defecto

# Referencia, de la medicion del 2026-08-05 sobre estas mismas trazas.
EXPECTED_SAT_MEDIAN = 0.704
EXPECTED_T_LOSS_MAX = 86.0


def load(path: Path) -> tuple[np.ndarray, ...]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    return (
        np.array([float(r["theta_deg"]) for r in rows]),
        np.array([float(r["alpha_deg"]) for r in rows]),
        np.array([float(r["pwm"]) for r in rows]),
        np.array([int(float(r["mode"])) for r in rows]),
    )


def main() -> int:
    print(f"{'rep':>4} {'t_loss ms':>10} {'sat':>8} {'ingenua':>8} {'n post':>7} {'th max':>7}")
    sats, losses = [], []
    for rep in range(1, 11):
        p = M5 / f"m5_sp60_r{rep}.csv"
        if not p.exists():
            print(f"{rep:>4}  (sin CSV)")
            continue
        m = analyse(*load(p), LC_DEFAULT_MS)
        if not m["handed_off"]:
            print(f"{rep:>4}  (sin traspaso)")
            continue
        if m["t_loss_ms"] is not None:
            losses.append(m["t_loss_ms"])
        if m["sat_frac"] is not None:
            sats.append(m["sat_frac"])
        sat = "-" if m["sat_frac"] is None else f"{m['sat_frac']:.1%}"
        naive = "-" if m["sat_frac_naive"] is None else f"{m['sat_frac_naive']:.1%}"
        print(f"{rep:>4} {m['t_loss_ms']!s:>10} {sat:>8} {naive:>8} "
              f"{m['n_post_catch']:>7} {m['theta_max_m4_deg']:>7.1f}")

    ok = True
    med = statistics.median(sats)
    print(f"\nsaturacion mediana: {med:.1%}   esperado {EXPECTED_SAT_MEDIAN:.1%}")
    if abs(med - EXPECTED_SAT_MEDIAN) > 0.02:
        print("  FALLA: la metrica de saturacion no reproduce la referencia")
        ok = False

    print(f"t_loss max: {max(losses):.0f} ms   esperado <= {EXPECTED_T_LOSS_MAX:.0f}")
    if max(losses) > EXPECTED_T_LOSS_MAX:
        print("  FALLA: la metrica de perdida no reproduce la referencia")
        ok = False

    # La prueba ingenua tiene que seguir dando ~0: es el control negativo que demuestra
    # que el techo efectivo esta bien calculado y no es una correccion cosmetica.
    print("\ncontrol negativo (la prueba ingenua contra LQR_PWM_MAX debe dar ~0%): "
          "ver la columna 'ingenua' arriba")

    print("\n" + ("OK — la metrica reproduce la referencia" if ok else "FALLA"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
