"""Figura de la frecuencia natural del pendulo, medida en caida libre a 500 Hz.

    uv run python grafica_frecuencia.py

Produce `fig_frecuencia_natural.png` en esta carpeta.

Una sola traza y un solo mensaje: el pendulo oscila cada vez MAS RAPIDO a medida
que se apaga. La frecuencia natural no es un numero suelto, sube al bajar la
amplitud siguiendo T = T0 * (2/pi) K(sin^2(A/2)).

Notas de medicion:

* Traza del DAQ del chip a 500 Hz, brazo libre, motor verificado en pwm = 0.
* El cero de alpha se estima como punto medio de picos consecutivos, que cancela
  el decaimiento a primer orden. Centrar por la mediana de la cola ya sesgo una
  estimacion de friccion en este banco.
* Este es el valor de BRAZO LIBRE. Con el brazo empotrado la f_n baja a 1,70 Hz;
  con el brazo sujeto por el PID del modo 2 baja a 1,41 Hz. La comparacion entre
  las tres condiciones esta en `analisis_frecuencia.py`, no en esta figura.
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "fig_frecuencia_natural.png"

C_TRAZA = "#3D6A94"
C_MARCA = "#C0651A"
C_TEXTO = "#3f4a52"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "savefig.dpi": 200,
    "axes.grid": True,
    "grid.alpha": 0.25,
})


def caida_libre():
    """Tramo contiguo de decaimiento sin par, ya centrado en su equilibrio."""
    cols = {k: [] for k in ("t", "al", "md")}
    with open(DATA / "caida_libre_brazo_libre.csv") as f:
        for r in csv.DictReader(f):
            cols["t"].append(float(r["t_s"]))
            cols["al"].append(float(r["al_deg"]))
            cols["md"].append(int(r["mode"]))
    d = {k: np.array(v) for k, v in cols.items()}

    idx = np.where(d["md"] == 0)[0]                  # modo 0 = motor apagado
    t = d["t"][idx]
    cortes = np.concatenate(([0], np.where(np.diff(t) > 0.05)[0] + 1, [len(idx)]))
    a, b = max(((cortes[k], cortes[k + 1]) for k in range(len(cortes) - 1)),
               key=lambda ab: t[ab[1] - 1] - t[ab[0]])
    s = idx[a:b]
    t, al = d["t"][s] - d["t"][s][0], d["al"][s]

    pp, _ = find_peaks(al, distance=100)
    pn, _ = find_peaks(-al, distance=100)
    k = min(len(pp), len(pn))
    mids = (al[pp[:k]] + al[pn[:k]]) / 2.0
    return t, al - np.median(mids[k // 2:])


def marca_periodo(ax, t0, t1, y, f, texto_arriba=True):
    """Flecha de doble punta entre dos picos, rotulada con T y con 1/T."""
    ax.annotate("", xy=(t0, y), xytext=(t1, y),
                arrowprops=dict(arrowstyle="<->", color=C_MARCA, lw=1.8))
    for x in (t0, t1):
        ax.plot([x, x], [0, y], color=C_MARCA, lw=0.9, ls=":", alpha=0.8)
    dy = 9 if texto_arriba else -9
    ax.annotate(f"T = {t1 - t0:.2f} s\n{f:.2f} Hz".replace(".", ","),
                xy=((t0 + t1) / 2, y), xytext=(0, dy),
                textcoords="offset points", ha="center",
                va="bottom" if texto_arriba else "top",
                fontsize=11, color=C_MARCA, linespacing=1.3,
                fontweight="bold")


def main():
    t, al = caida_libre()
    pp, _ = find_peaks(al, distance=100)

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.plot(t, al, color=C_TRAZA, lw=1.2)
    ax.axhline(0, color="k", lw=0.7, alpha=0.4)
    ax.plot(t[pp], al[pp], "o", color=C_TRAZA, ms=4)

    # Primer ciclo (amplitud grande, lento) y ultimo ciclo medido (rapido).
    for i, (y, arriba) in ((0, (152, True)), (len(pp) - 2, (52, True))):
        t0, t1 = t[pp[i]], t[pp[i + 1]]
        marca_periodo(ax, t0, t1, y, 1.0 / (t1 - t0), arriba)

    ax.set_xlabel("Tiempo desde que se corta el motor (s)")
    ax.set_ylabel("Ángulo del péndulo (°)")
    ax.set_xlim(0, t[-1])
    ax.set_ylim(-150, 190)
    ax.set_title("El péndulo oscila cada vez más rápido a medida que se apaga\n"
                 "Caída libre con el brazo suelto, 500 muestras por segundo",
                 fontsize=12, loc="left", color=C_TEXTO, linespacing=1.4)

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT, facecolor="white")
    plt.close()

    print("periodo por ciclo (s):", np.round(np.diff(t[pp]), 3))
    print("frecuencia por ciclo (Hz):", np.round(1 / np.diff(t[pp]), 3))
    print(f"OK: {OUT.name}")


if __name__ == "__main__":
    main()
