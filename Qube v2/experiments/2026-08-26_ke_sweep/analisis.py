"""Consolidación de la campaña: tandas, salud del enlace y frecuencia de bombeo.

La comparación de frecuencia se hace **banda por banda de amplitud** y no contra un
único `f_n`. El período del péndulo crece con la amplitud —para 90° ya es ~1,18× el de
ángulo pequeño— y el swing-up recorre 0..180°, así que un solo número compara cosas
distintas. El método es el de `experiments/2026-08-21_reintento_swingup`, reusado a
propósito: cambiarlo haría que las dos campañas no se puedan empalmar.

La referencia de caída libre es **de esta misma sesión**. El banco deriva dentro de una
sesión, así que una `f_n` de otro día no es la de estas tandas.

    uv run python analisis.py
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

import numpy as np
from scipy.special import ellipk

DATA = Path(__file__).parent / "data"


def cargar(nombre: str) -> dict:
    cols: dict[str, list] = {k: [] for k in ("t", "th", "al", "pwm", "md")}
    with (DATA / nombre).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cols["t"].append(float(r["t_s"]))
            cols["th"].append(float(r["th_deg"]))
            cols["al"].append(float(r["al_deg"]))
            cols["pwm"].append(int(r["pwm"]))
            cols["md"].append(int(r["mode"]))
    return {k: np.array(v) for k, v in cols.items()}


def medios_ciclos(t, x, cero: float = 0.0, amp_min: float = 8.0) -> list[tuple[float, float]]:
    """(amplitud pico, frecuencia) por medio ciclo entre cruces por cero interpolados.

    El cruce se interpola entre las dos muestras que lo rodean: a 500 Hz el paso del
    encoder es un conteo entero y quedarse con la muestra más cercana mete hasta 2 ms de
    error en períodos de ~500 ms.
    """
    y = x - cero
    sg = np.sign(y)
    idx = np.where(sg[:-1] != sg[1:])[0]
    if len(idx) < 3:
        return []
    tc = t[idx] + (t[idx + 1] - t[idx]) * (-y[idx] / (y[idx + 1] - y[idx]))
    out = []
    for k in range(len(idx) - 1):
        a, b = idx[k], idx[k + 1]
        if b - a < 15:  # medio ciclo más corto que 30 ms: es ruido
            continue
        T = 2 * (tc[k + 1] - tc[k])
        amp = float(np.max(np.abs(y[a : b + 1])))
        if 0.15 < T / 2 < 3.0 and amp > amp_min:
            out.append((amp, 1.0 / T))
    return out


def f_pequeno_angulo(ciclos, amp_max: float = 60.0) -> tuple[float, int]:
    """Extrapola a amplitud cero descontando el factor no lineal T/T0 = (2/pi)·K(sin²(A/2))."""
    if not ciclos:
        return float("nan"), 0
    A = np.array([a for a, _ in ciclos])
    F = np.array([f for _, f in ciclos])
    s = A < amp_max
    if s.sum() < 3:
        return float("nan"), 0
    fac = (2 / np.pi) * ellipk(np.sin(np.radians(A[s]) / 2) ** 2)
    return float(np.median(F[s] * fac)), int(s.sum())


def registros() -> list[dict]:
    out = []
    for p in sorted(DATA.glob("registro_*.jsonl")):
        for linea in p.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                out.append(json.loads(linea))
    return out


def tabla_tandas(regs: list[dict]) -> None:
    print("== Tandas ==")
    print(
        f"{'ke':>6} {'trasp':>6} {'alpha':>8} {'E/E*':>6} {'alive':>7} {'fail':>5} "
        f"{'ceil':>5} {'brazo':>7} {'>95':>5} {'RTTmed':>7} {'RTTp95':>7} {'Hz_daq':>7} {'dovr':>5}"
    )
    for r in regs:
        if "abortada" in r:
            print(f"{r['ke']:>6g}  ABORTADA: {r['abortada']}  (homing range={r['homing'].get('range')})")
            continue
        fw, d, br = r["firmware"], r.get("daq", {}), r.get("brazo", {})
        enl = r.get("enlace_durante", {})
        alive = fw.get("lqr_alive_ms")
        print(
            f"{r['ke']:>6g} {fw.get('swing_trans_reason', 0):>6} "
            f"{(fw.get('swing_trans_alpha') or 0):>8.2f} {(fw.get('swing_trans_energy') or 0):>6.3f} "
            f"{(alive if alive is not None else -1):>7} {fw.get('swing_fail_reason', 0):>5} "
            f"{fw.get('swing_ceiling_hits', 0):>5} {br.get('max_abs_deg', 0):>7.2f} "
            f"{br.get('n_sobre_95', 0):>5} {enl.get('mediana_ms', 0):>7.1f} {enl.get('p95_ms', 0):>7.1f} "
            f"{d.get('tasa_hz', 0):>7.1f} {(r.get('delta') or {}).get('loop_overruns', -1):>5}"
        )


def tabla_enlace(regs: list[dict]) -> None:
    print("\n== Enlace: RTT de /rl_state, antes / durante / después [ms] ==")
    print(f"{'ke':>6} {'antes_med':>10} {'dur_med':>9} {'desp_med':>9} {'antes_p95':>10} {'dur_p95':>9} {'factor':>7}")
    for r in regs:
        if "abortada" in r:
            continue
        a, d, p = r.get("enlace_antes", {}), r.get("enlace_durante", {}), r.get("enlace_despues", {})
        if not (a.get("mediana_ms") and d.get("mediana_ms")):
            continue
        print(
            f"{r['ke']:>6g} {a['mediana_ms']:>10.1f} {d['mediana_ms']:>9.1f} "
            f"{p.get('mediana_ms', 0):>9.1f} {a.get('p95_ms', 0):>10.1f} {d.get('p95_ms', 0):>9.1f} "
            f"{d['mediana_ms'] / a['mediana_ms']:>7.2f}"
        )


def frecuencias(regs: list[dict]) -> None:
    # -- Bombeo: modo 5 CON par aplicado, de todas las tandas con traza --------
    bombeo: list[tuple[float, float]] = []
    por_ke: dict[float, list] = {}
    for r in regs:
        if not r.get("csv") or not (DATA / r["csv"]).exists():
            continue
        d = cargar(r["csv"])
        m = (d["md"] == 5) & (np.abs(d["pwm"]) > 0)
        ciclos = medios_ciclos(d["t"][m], d["al"][m])
        bombeo += ciclos
        por_ke.setdefault(r["ke"], []).extend(ciclos)

    # -- Caída libre de ESTA sesión -------------------------------------------
    libre: dict[str, list] = {}
    for nombre, fn, modo in (
        ("brazo libre", "caida_libre_brazo_libre.csv", 0),
        ("brazo retenido", "caida_libre_brazo_retenido.csv", 2),
    ):
        if not (DATA / fn).exists():
            continue
        d = cargar(fn)
        m = d["md"] == modo
        if m.sum() < 600:
            continue
        cero = float(np.median(d["al"][m][-500:]))  # el reposo final ES el cero
        libre[nombre] = medios_ciclos(d["t"][m], d["al"][m], cero, amp_min=6.0)

    print("\n== f_n extrapolada a ángulo pequeño (caída libre de esta sesión) ==")
    for nombre, cic in libre.items():
        f0, n = f_pequeno_angulo(cic)
        print(f"   {nombre:16s} {f0:6.3f} Hz   (n={n} medios ciclos < 60°)")
    print("   referencia 2026-08-13 (memoria del proyecto): 1,70 Hz")

    if not libre:
        print("   (sin caída libre en esta sesión: no se puede comparar)")
        return

    ref = libre.get("brazo retenido") or next(iter(libre.values()))
    nombre_ref = "brazo retenido" if "brazo retenido" in libre else next(iter(libre))
    print(f"\n== Frecuencia por banda de amplitud [Hz] — referencia: {nombre_ref} ==")
    print(f"   {'amplitud':>10} {'bombeo':>8} {'libre':>8} {'cociente':>9} {'n_bomb':>7} {'n_lib':>6}")
    for lo, hi in ((20, 40), (40, 60), (60, 80), (80, 100), (100, 120), (120, 145), (145, 175)):
        b = [f for a, f in bombeo if lo <= a < hi]
        li = [f for a, f in ref if lo <= a < hi]
        if not (b and li):
            continue
        print(
            f"   {lo:3d}-{hi:3d}    {statistics.median(b):8.3f} {statistics.median(li):8.3f} "
            f"{statistics.median(b) / statistics.median(li):9.3f} {len(b):7d} {len(li):6d}"
        )

    print("\n== Frecuencia de bombeo por ke (banda 40-100°) ==")
    for ke in sorted(por_ke):
        b = [f for a, f in por_ke[ke] if 40 <= a < 100]
        if b:
            print(f"   ke={ke:>5g}   {statistics.median(b):6.3f} Hz   (n={len(b)})")


def main() -> int:
    regs = registros()
    if not regs:
        print("no hay registros todavía")
        return 1
    tabla_tandas(regs)
    tabla_enlace(regs)
    frecuencias(regs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
