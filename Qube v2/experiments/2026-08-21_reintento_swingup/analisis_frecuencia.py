"""Frecuencia de oscilacion del pendulo: bombeo (modo 5) contra caida libre.

La pregunta que responde: el bombeo del swing-up, ¿corre cerca de la frecuencia
propia del pendulo? Comparar contra UN numero de f_n no sirve — el periodo del
pendulo crece con la amplitud, y en el swing-up la amplitud recorre 0..180 deg.
Asi que la comparacion se hace BANDA POR BANDA de amplitud.

    uv run python analisis_frecuencia.py
"""
import csv
from pathlib import Path

import numpy as np
from scipy.special import ellipk

DATA = Path(__file__).parent / "data"


def load(fn):
    cols = {k: [] for k in ("t", "th", "al", "pwm", "md")}
    with open(DATA / fn) as f:
        for r in csv.DictReader(f):
            cols["t"].append(float(r["t_s"]))
            cols["th"].append(float(r["th_deg"]))
            cols["al"].append(float(r["al_deg"]))
            cols["pwm"].append(int(r["pwm"]))
            cols["md"].append(int(r["mode"]))
    return {k: np.array(v) for k, v in cols.items()}


def medios_ciclos(t, x, cero=0.0, amp_min=8.0):
    """(amplitud pico, frecuencia) por cada medio ciclo entre cruces por cero.

    El instante del cruce se interpola entre las dos muestras que lo rodean: a
    500 Hz el paso del encoder es de un conteo entero, y quedarse con la muestra
    mas cercana metia hasta 2 ms de error en periodos de ~500 ms.
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
        if b - a < 15:          # medio ciclo mas corto que 30 ms: es ruido
            continue
        T = 2 * (tc[k + 1] - tc[k])
        amp = np.max(np.abs(y[a:b + 1]))
        if 0.15 < T / 2 < 3.0 and amp > amp_min:
            out.append((amp, 1.0 / T))
    return out


def f_pequeno_angulo(ciclos, amp_max=60.0):
    """Extrapola a amplitud cero descontando el factor no lineal T/T0."""
    A = np.array([a for a, _ in ciclos])
    F = np.array([f for _, f in ciclos])
    s = A < amp_max
    if s.sum() < 3:
        return np.nan, 0
    fac = (2 / np.pi) * ellipk(np.sin(np.radians(A[s]) / 2) ** 2)
    return float(np.median(F[s] * fac)), int(s.sum())


def main():
    bombeo = []
    for fn in ("tanda1_sin_hold.csv", "tanda2_hold_banda_unica.csv",
               "tanda3_hold_histeresis.csv", "tanda4_hold_histeresis.csv"):
        d = load(fn)
        m = (d["md"] == 5) & (np.abs(d["pwm"]) > 0)   # modo 5 CON par aplicado
        bombeo += medios_ciclos(d["t"][m], d["al"][m])

    libre = {}
    for nom, fn, modo in (("brazo libre", "caida_libre_brazo_libre.csv", 0),
                          ("brazo retenido", "caida_libre_brazo_retenido.csv", 2)):
        d = load(fn)
        m = d["md"] == modo
        cero = float(np.median(d["al"][m][-500:]))    # el reposo final ES el cero
        libre[nom] = medios_ciclos(d["t"][m], d["al"][m], cero, amp_min=6.0)

    print("f_n extrapolada a angulo pequeno")
    for nom, cic in libre.items():
        f0, n = f_pequeno_angulo(cic)
        print(f"   {nom:16s} {f0:6.3f} Hz   (n={n} medios ciclos < 60 deg)")

    print("\nfrecuencia por banda de amplitud [Hz]")
    print("   amplitud     bombeo    libre     cociente")
    L = libre["brazo libre"]
    for lo, hi in ((20, 40), (40, 60), (60, 80), (80, 100), (100, 120), (120, 145)):
        b = [f for a, f in bombeo if lo <= a < hi]
        l = [f for a, f in L if lo <= a < hi]
        if not (b and l):
            continue
        print(f"   {lo:3d}-{hi:3d}     {np.median(b):6.3f}    {np.median(l):6.3f}"
              f"     {np.median(b) / np.median(l):6.3f}")


if __name__ == "__main__":
    main()
