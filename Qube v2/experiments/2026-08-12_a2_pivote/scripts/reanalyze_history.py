"""Pasa el analizador nuevo por los datos que ya existen, cuyo veredicto se conoce.

Antes de ir al banco hay que saber si el analizador sirve, y para eso el proyecto ya tiene
dos conjuntos de datos con verdad conocida y **opuesta**:

    2026-08-04   pivote sano, decaimiento viscoso limpio, lambda = 0,0283, Dp = 7,52e-6
    2026-08-05   pivote trabado, tau_c = 1,26e-3, el pendulo se queda quieto a 4,75 grados

Un analizador que no reproduzca los dos no sirve, y da igual cuantos casos sinteticos pase:
las trazas sinteticas las genero yo con la misma fisica que el analizador supone, asi que
solo prueban la implementacion, no el modelo. Estas dos son medidas.

El tercer conjunto es la campana rota del 2026-08-12, y ahi lo que se espera no es un
veredicto distinto sino NINGUNO: muestreo a 9,1 Hz, un hueco de 1,24 s y una suelta que decia
15 grados y partio de 65.

    uv run python reanalyze_history.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decay_analysis as da

EXPERIMENTS = Path(__file__).resolve().parents[2]
ROOT = EXPERIMENTS.parents[1]  # ~TESIS

CASES: list[tuple[str, Path, str, dict]] = [
    (
        "2026-08-04  suelta de 64 deg",
        EXPERIMENTS / "2026-08-04_friction_spindown" / "data" / "spindown_01.csv",
        "viscoso limpio: lambda ~ 0,0283",
        {},
    ),
    (
        "2026-08-04  suelta de 43 deg",
        EXPERIMENTS / "2026-08-04_friction_spindown" / "data" / "spindown_02.csv",
        "viscoso limpio: lambda ~ 0,0283",
        {},
    ),
    (
        "2026-08-05  suelta manual",
        EXPERIMENTS / "2026-08-05_p4_gains" / "data" / "spindown_man_1.csv",
        "trabado: tau_c = 1,26e-3, reposo a 4,75 deg",
        {},
    ),
    (
        "2026-08-12  campana rota",
        ROOT / "campaña_a2_20260812_205633" / "decaimiento_15deg.csv",
        "DESCARTADA: 9,1 Hz, hueco de 1,24 s, suelta de 65 deg pidiendo 15",
        {"target_amp_deg": 15.0},
    ),
]


def show(res: da.DecayResult) -> None:
    print(f"    veredicto        {res.verdict}")
    print(
        f"    captura          {res.n} muestras, {res.duration_s:.1f} s, "
        f"{res.rate_hz:.1f} Hz = {res.samples_per_cycle:.1f} muestras/ciclo"
    )
    if math.isfinite(res.equilibrium_deg):
        print(f"    vertical         {res.equilibrium_deg:.2f} deg  (metodo: {res.equilibrium_method})")
    if math.isfinite(res.amp0_deg):
        print(f"    suelta           {res.amp0_deg:.1f} deg en t = {res.release_t_s:.2f} s")
    if res.n_peaks:
        print(f"    semiciclos       {res.n_peaks}  (semiperiodo {res.half_period_s * 1000:.0f} ms)")
    if math.isfinite(res.lam_exp):
        print(
            f"    envolvente exp   lambda = {res.lam_exp:.4f} 1/s   R2 = {res.r2_exp:.3f}   "
            f"->  Dp = {res.dp:.3e}   ({res.dp / da.REF_DP:.2f}x la referencia)"
        )
    if math.isfinite(res.r2_lin):
        print(f"    envolvente lin   pendiente = {res.slope_lin:.4f} deg/s   R2 = {res.r2_lin:.3f}")
    if math.isfinite(res.tau_c_fit):
        print(
            f"    balance energia  tau_c = {res.tau_c_fit:.3e} (t = {res.t_tau_c:5.1f})   "
            f"Dp = {res.dp_fit:.3e} (t = {res.t_dp:5.1f})"
        )
        if math.isfinite(res.cross_amp_deg):
            print(f"                     amplitud de cruce A* = {res.cross_amp_deg:.1f} deg")
    if math.isfinite(res.tau_c_from_rest):
        print(
            f"    reposo final     {res.rest_after_deg:+.2f} deg  ->  "
            f"tau_c >= {res.tau_c_from_rest:.3e} N.m  (cota inferior)"
        )
    for g in res.guards:
        if not g.ok:
            marca = "FATAL" if g.fatal else "aviso"
            print(f"    [{marca}] {g.name}: {g.detail}")
    for n in res.notes:
        print(f"    nota: {n}")


def clean_window() -> None:
    """El tramo limpio del 2026-08-05, aislado a mano.

    La grabacion completa se descarta -el centro de oscilacion se corre 13,7 deg y hay tres
    tramos separados por aportes de energia-, pero adentro tiene 10 s de decaimiento limpio
    con el centro clavado en -36,9. Ese tramo es medible y dice algo que la grabacion entera
    no deja ver.
    """
    path = EXPERIMENTS / "2026-08-05_p4_gains" / "data" / "spindown_man_1.csv"
    if not path.exists():
        return
    print("\n" + "-" * 78)
    print("  2026-08-05, tramo limpio aislado a mano (t = 6,5 a 16,2 s)")
    print("-" * 78)
    tr = da.load_trace(path)
    t = tr.t - tr.t[0]
    m = (t >= 6.5) & (t <= 16.2)
    show(da.analyze(da.Trace(t[m], tr.alpha_deg[m], tr.theta_deg[m], "tramo limpio")))


def reconstruct_tau_seco() -> None:
    """De donde salieron los 4,75 deg y el tau_seco = 1,26e-3 del registro.

    `envelope_lambda` centra con ``a - np.median(a)`` (`spindown_now.py:88`), y su docstring
    defiende esa eleccion. Para una traza que oscila simetrica alrededor de la vertical, la
    mediana ES la vertical. Para `spindown_man_1.csv` no: esa grabacion pasa la mayor parte
    del tiempo en la cola casi detenida, asi que su mediana queda 20 deg por encima del centro
    de oscilacion real. El angulo de reposo medido contra esa referencia no es un angulo
    respecto de la vertical.
    """
    path = EXPERIMENTS / "2026-08-05_p4_gains" / "data" / "spindown_man_1.csv"
    if not path.exists():
        return
    a = da.load_trace(path).alpha_deg
    median = float(np.median(a))
    plateau = float(np.median(a[-int(0.05 * a.size) :]))
    eq, _, _ = da.estimate_equilibrium(np.arange(a.size) / 500.0, a)
    print("\n" + "-" * 78)
    print("  De donde sale el tau_seco = 1,26e-3 N.m del registro (P24, Capitulo_05.tex:679)")
    print("-" * 78)
    print(f"    meseta final de la traza                  {plateau:+8.2f} deg")
    print(f"    mediana de la traza completa              {median:+8.2f} deg")
    print(f"    centro de oscilacion (puntos medios)      {eq:+8.2f} deg")
    print()
    print(
        f"    reposo medido contra la MEDIANA           {plateau - median:+8.2f} deg  ->  "
        f"tau_c = {da.tau_c_from_rest_angle(plateau - median):.2e} N.m"
    )
    print(
        f"    reposo medido contra el CENTRO real       {plateau - eq:+8.2f} deg  ->  "
        f"tau_c = {da.tau_c_from_rest_angle(plateau - eq):.2e} N.m"
    )
    print()
    print(
        "    El registro reporta 4,75 deg y 1,26e-3. La primera linea lo reproduce salvo\n"
        "    por el recorte exacto de la ventana. O sea que la cifra descansa en tomar la\n"
        "    mediana de la traza como vertical, y en esta traza la mediana esta 20 deg del\n"
        "    centro de oscilacion porque la grabacion pasa la mayor parte del tiempo en la\n"
        "    cola casi detenida. Ninguna de las dos lecturas es 'la correcta': lo que dice\n"
        "    esto es que el numero no esta establecido, no que valga la segunda."
    )


def main() -> int:
    print("=" * 78)
    print("  Re-analisis de los datos historicos con el criterio de `decay_analysis.py`")
    print("=" * 78)
    faltantes = 0
    for title, path, expected, kwargs in CASES:
        print(f"\n{title}")
        print(f"  archivo   {path.name}")
        print(f"  se espera {expected}")
        if not path.exists():
            print(f"    NO ENCONTRADO: {path}")
            faltantes += 1
            continue
        try:
            trace = da.load_trace(path)
        except ValueError as exc:
            print(f"    NO SE PUDO LEER: {exc}")
            faltantes += 1
            continue
        show(da.analyze(trace, **kwargs))

    clean_window()
    reconstruct_tau_seco()

    print("\n" + "=" * 78)
    print("  Como leer esto")
    print("=" * 78)
    print(
        "  Las dos capturas del 2026-08-04 se tomaron por polling de /rl_state a ~13 Hz, o sea\n"
        "  unas 8 muestras por ciclo. Alcanza para la envolvente y NO para el discriminador, asi\n"
        "  que el veredicto por corrida sale INDETERMINADO a proposito: la referencia viscosa de\n"
        "  todo el proyecto tambien esta submuestreada, y el argumento que la sostiene no es el\n"
        "  R2 de una corrida sino que lambda coincidiera entre dos amplitudes distintas.\n"
    )
    return 1 if faltantes else 0


if __name__ == "__main__":
    raise SystemExit(main())
