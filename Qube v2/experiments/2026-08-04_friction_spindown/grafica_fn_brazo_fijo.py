"""Demostracion de f_n = 1,70 Hz con el brazo sujeto.

    uv run python grafica_fn_brazo_fijo.py

Produce `fig_fn_brazo_fijo.png` en esta carpeta.

Que demuestra y como. La prediccion geometrica para una barra uniforme,
omega_n = sqrt(3g / 2 Lp), da 1,6998 Hz con la longitud medida Lp = 0,129 m y no
mide nada: sale solo del largo. Contra eso se contrastan las dos caidas libres
del 2026-08-04, que son la unica captura del banco con el brazo efectivamente
sujeto (se movio 3,7 y 1,2 grados en 25 s de registro).

Tres cuidados que hacen valida la comparacion:

1. El muestreo es de ~14 Hz, la misma tasa por la que se descarto la medicion de
   2,28 Hz del 2026-07-30. La diferencia es el metodo: alli se conto cruces sobre
   seis muestras por ciclo; aqui la frecuencia sale de la recta que une el PRIMER
   y el ULTIMO cruce de un registro de ~80 semiciclos, donde el error de un paso
   de muestreo se reparte entre cuarenta ciclos.
2. El cero de alpha se estima como punto medio de picos consecutivos, no como
   mediana de la cola: centrar por la mediana ya sesgo una estimacion de friccion
   en este banco.
3. La prediccion es de amplitud infinitesimal y la medicion corre entre 20 y 58
   grados, donde el periodo del pendulo ya es mas largo. Por eso cada corrida se
   corrige por T/T0 = (2/pi) K(sin^2(A/2)) antes de compararla. Sin esa
   correccion la comparacion no es legitima.

Resultado: 1,70 Hz de la corrida 1 y 1,74 Hz de la corrida 2 contra 1,70 Hz de la
prediccion. Son n=2 y difieren entre si un 2,6 %, asi que respaldan el valor como
cifra central, no al +-1,5 %.
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks
from scipy.special import ellipk

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "fig_fn_brazo_fijo.png"

G = 9.81
LP = 0.129                       # m, longitud medida del pendulo
F_TEORICO = np.sqrt(3 * G / (2 * LP)) / (2 * np.pi)

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


def factor_amplitud(A_deg):
    """T/T0 del pendulo de amplitud finita."""
    return (2 / np.pi) * ellipk(np.sin(np.radians(A_deg) / 2) ** 2)


def medir(fn):
    cols = {k: [] for k in ("t", "theta", "alpha")}
    with open(DATA / fn) as f:
        for r in csv.DictReader(f):
            for k in cols:
                cols[k].append(float(r[k]))
    t = np.array(cols["t"])
    t -= t[0]
    al = np.degrees(np.array(cols["alpha"]))
    brazo = np.degrees(np.ptp(np.array(cols["theta"])))

    pp, _ = find_peaks(al)
    pn, _ = find_peaks(-al)
    k = min(len(pp), len(pn))
    y = al - float(np.median((al[pp[:k]] + al[pn[:k]]) / 2))

    sg = np.sign(y)
    idx = np.where(sg[:-1] != sg[1:])[0]
    tc = t[idx] + (t[idx + 1] - t[idx]) * (-y[idx] / (y[idx + 1] - y[idx]))
    keep = [0]
    for i in range(1, len(tc)):
        if tc[i] - tc[keep[-1]] > 0.2:      # cruce espurio por ruido
            keep.append(i)
    tc = tc[keep]
    n = len(tc) - 1

    f_crudo = n / (2 * (tc[-1] - tc[0]))
    amps = [np.max(np.abs(y[np.argmin(np.abs(t - tc[i])):
                            np.argmin(np.abs(t - tc[i + 1])) + 1]))
            for i in range(n)]
    factor = float(np.median(factor_amplitud(np.array(amps))))

    return dict(t=t, y=y, brazo=brazo, n=n, dur=tc[-1] - tc[0],
                f_crudo=f_crudo, f=f_crudo * factor,
                amp_med=float(np.median(amps)))


def main():
    r1 = medir("spindown_01.csv")
    r2 = medir("spindown_02.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.6),
                                   gridspec_kw={"width_ratios": [1.35, 1]})

    # ── (a) como se ve la medicion ───────────────────────────────────────────
    m = r2["t"] <= 4.0
    ax1.plot(r2["t"][m], r2["y"][m], "-o", color=C_TRAZA, lw=1.2, ms=3.5)
    ax1.axhline(0, color="k", lw=0.7, alpha=0.4)
    ax1.set_xlabel("Tiempo (s)")
    ax1.set_ylabel("Ángulo del péndulo (°)")
    ax1.set_xlim(0, 4)
    ax1.set_ylim(-72, 76)
    dur = f"{r2['dur']:.1f}".replace(".", ",")
    ax1.set_title("Caída libre con el brazo sujeto",
                  fontsize=11.5, loc="left", color=C_TEXTO)
    ax1.text(0.03, 0.04, f"{r2['n']} semiciclos en {dur} s",
             transform=ax1.transAxes, fontsize=11.5, color=C_MARCA,
             fontweight="bold", va="bottom")

    # ── (b) el numero contra la prediccion ───────────────────────────────────
    filas = [
        ("Predicción geométrica\n" + r"$\sqrt{3g/2L_p}$, $L_p$ = 0,129 m",
         F_TEORICO, C_TEXTO),
        ("Caída libre 1", r1["f"], C_TRAZA),
        ("Caída libre 2", r2["f"], C_TRAZA),
    ]
    ypos = np.arange(len(filas))[::-1]

    ax2.axvspan(F_TEORICO * 0.97, F_TEORICO * 1.03, color=C_MARCA, alpha=0.10)
    ax2.axvline(F_TEORICO, color=C_MARCA, lw=1.6, ls="--")

    for y, (etq, val, color) in zip(ypos, filas):
        ax2.plot([val], [y], "o", ms=13, color=color, zorder=3)
        ax2.annotate(f"{val:.2f} Hz".replace(".", ","), xy=(val, y),
                     xytext=(0, 16), textcoords="offset points",
                     ha="center", fontsize=11.5, fontweight="bold", color=color)

    ax2.set_yticks(ypos)
    ax2.set_yticklabels([e for e, _, _ in filas], fontsize=10)
    ax2.set_ylim(-0.7, len(filas) - 0.3)
    ax2.set_xlim(1.60, 1.84)
    ax2.set_xlabel("Frecuencia natural (Hz)")
    ax2.grid(axis="y", visible=False)
    ax2.set_title("Medido contra predicho",
                  fontsize=11.5, loc="left", color=C_TEXTO)

    for ax in (ax1, ax2):
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT, facecolor="white")
    plt.close()

    print(f"prediccion geometrica      {F_TEORICO:.4f} Hz")
    for nom, r in (("caida libre 1", r1), ("caida libre 2", r2)):
        print(f"{nom}: brazo {r['brazo']:.2f} deg | {r['n']} semiciclos en "
              f"{r['dur']:.2f} s | crudo {r['f_crudo']:.4f} Hz | "
              f"amplitud mediana {r['amp_med']:.1f} deg | "
              f"corregido {r['f']:.4f} Hz")
    print(f"OK: {OUT.name}")


if __name__ == "__main__":
    main()
