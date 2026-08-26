"""Campana A2 — decaimiento libre del pendulo, 8 corridas.

Mide la friccion del pivote soltando el pendulo desde tres amplitudes y ajustando la
envolvente. Reemplaza a `campana_a2.py`, que muestreaba a 9 Hz por polling de `/state` y
decidia contando cruces por cero de una senal que nunca cambia de signo.

Que cambia, en concreto:

    adquisicion    /daq a 250 Hz por bloques binarios, no polling de /state a 9 Hz
    referencia     el centro de oscilacion medido en la propia corrida, no `zp`
    criterio       balance de energia por semiciclo, no conteo de ciclos
    guardas        una corrida que no cumple se DESCARTA; no se le inventa un veredicto

**Orden intercalado, no monotonico.** El banco se degrada dentro de una misma sesion, asi
que una tanda 15-15-35-35-60-60 no permitiria separar el efecto de la amplitud del efecto
del tiempo. Se alterna, y la primera corrida se repite al final: la diferencia entre esas
dos mide la deriva de la sesion y acota cuanto vale comparar el resto.

Protocolo por corrida — los cuatro puntos importan y los cuatro salieron de un fallo:

    1. El pendulo arranca COLGANDO Y QUIETO unos segundos antes de que lo levantes. Esa
       pre-lectura es la unica referencia de vertical que le queda a una traza en la que el
       pendulo no llega a oscilar, o sea al caso trabado, que es justo el que hay que poder
       medir.
    2. El BRAZO va sujeto a mano, firme. Con el brazo suelto los dos grados de libertad se
       acoplan, la energia se trasvasa y vuelve, y la envolvente deja de decaer: el
       2026-08-05 el brazo se movio 13 grados y el ajuste dio R2 = 0,02. El 2026-08-12 se
       movio 128 y nadie lo miro.
    3. El motor queda en modo 0 (sin par). Hay una mano en el mecanismo.
    4. Se levanta y se suelta LIMPIO, sin impulso, y no se toca nada mas hasta que termine.
       Un empujon de mas mete energia y parte la corrida en dos tramos.

Uso:
    uv run python run_a2.py                 # campana completa
    uv run python run_a2.py --solo 35       # una amplitud
    uv run python run_a2.py --analizar      # re-analiza los CSV ya grabados, sin banco
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import decay_analysis as da
from qube_app.link import QubeLink
from qube_daq.client import DaqClient

DATA = Path(__file__).resolve().parent.parent / "data"

#: 250 Hz = 147 muestras por ciclo, con el buffer del firmware (2048 muestras) aguantando
#: 8,2 s contra un sondeo de 0,25 s: 33x de margen. A 500 Hz el margen baja a 16x y el caudal
#: se duplica, sin ganar nada: 147 muestras por ciclo ya sobran para ubicar los picos.
DECIM = 2
NOMINAL_RATE_HZ = 500.0 / DECIM
BROWNOUT_CUT_V = 4.5

# ── Fases cronometradas de cada corrida ─────────────────────────────────────────
# El operador no puede estar mirando la pantalla -tiene las dos manos en el banco y la vista
# en el pendulo-, asi que las fases se cantan por tiempo y con sonido, y la suelta cae en un
# instante fijo. El analisis no depende de que se cumpla al segundo: `find_release` ubica la
# suelta en los datos. Lo que si depende del cronograma es la PRE-LECTURA colgando, que es la
# unica referencia de vertical que le queda a una traza donde el pendulo no llega a oscilar.
T_COLGANDO = 5.0  # quieto, colgando. El analizador usa los primeros 2 s (PREROLL_S)
T_LEVANTAR = 6.0  # levantar a la amplitud pedida y sostener
T_CUENTA = 3.0  # 3, 2, 1
T_DECAIMIENTO = 56.0  # 2,3 vidas medias si el pivote esta como el 2026-08-04
SECONDS = T_COLGANDO + T_LEVANTAR + T_CUENTA + T_DECAIMIENTO
T_SUELTA = T_COLGANDO + T_LEVANTAR + T_CUENTA
PREFLIGHT_S = 6.0

#: (amplitud, rol). La primera y la ultima son la misma amplitud a proposito.
PLAN: list[tuple[float, str]] = [
    (35.0, "linea base A"),
    (15.0, ""),
    (60.0, ""),
    (35.0, ""),
    (15.0, ""),
    (60.0, ""),
    (35.0, ""),
    (35.0, "linea base B (replica de la 1)"),
]

C = {"t": "\033[1;36m", "ok": "\033[1;32m", "no": "\033[1;31m", "d": "\033[0;33m",
     "n": "\033[0m", "b": "\033[1m"}
if sys.platform == "win32":
    import os

    os.system("")


def head(txt: str) -> None:
    print(f"\n{C['t']}{'=' * 74}\n  {txt}\n{'=' * 74}{C['n']}")


def ask(prompt: str) -> str:
    """`input()` que explica en vez de reventar cuando no hay terminal de verdad.

    No alcanza con mirar `sys.stdin.isatty()`: hay envoltorios que lo informan como terminal
    y despues devuelven EOF en la primera lectura. Lo unico confiable es intentar leer.
    """
    try:
        return input(prompt)
    except EOFError:
        print(f"\n\n{C['no']}  No hay terminal interactiva: la lectura del teclado devolvio EOF.{C['n']}")
        print("  La campana necesita una, y no solo por el ENTER: la cuenta para soltar se")
        print("  dibuja en vivo, y por una tuberia llegaria despues de que la corrida termino.")
        print("\n  Abri una terminal normal (PowerShell o Windows Terminal) y corre:")
        print(f"    cd '{Path(__file__).resolve().parent}'")
        print("    uv run python run_a2.py")
        print("\n  Para trabajar sobre lo ya grabado no hace falta terminal:")
        print("    uv run python run_a2.py --analizar")
        raise SystemExit(2) from None


# ── Guia sonora y visual de la corrida ──────────────────────────────────────────
try:  # pitido audible en Windows; en el resto queda el BEL del terminal
    import winsound

    def beep(freq: int, ms: int) -> None:
        try:
            winsound.Beep(freq, ms)
        except RuntimeError:
            pass

except ImportError:

    def beep(freq: int, ms: int) -> None:  # noqa: ARG001
        sys.stdout.write("\a")
        sys.stdout.flush()


def countdown(stop: threading.Event, amp: float) -> None:
    """Canta las fases de la corrida mientras el DAQ graba, en un hilo aparte.

    Va por reloj de pared y no por los bloques que llegan: si la radio se atrasa, el aviso de
    soltar tiene que seguir cayendo donde corresponde. Que la captura se retrase un poco no
    importa -las muestras viajan con la marca del tick que las produjo- pero que la persona
    suelte tarde, si.
    """
    t0 = time.perf_counter()
    ultimo = -1

    def linea(txt: str, color: str = "") -> None:
        sys.stdout.write(f"\r    {color}{txt:<66}{C['n']}")
        sys.stdout.flush()

    while not stop.is_set():
        t = time.perf_counter() - t0
        if t >= SECONDS:
            break
        entero = int(t)
        nuevo = entero != ultimo

        if t < T_COLGANDO:
            linea(f"COLGANDO, no lo toques      {T_COLGANDO - t:4.1f} s", C["d"])
        elif t < T_COLGANDO + T_LEVANTAR:
            resta = T_COLGANDO + T_LEVANTAR - t
            if nuevo and entero == int(T_COLGANDO):
                beep(700, 120)
            linea(f"LEVANTA a ~{amp:.0f} grados y SOSTEN   {resta:4.1f} s", C["b"])
        elif t < T_SUELTA:
            n = max(math.ceil(T_SUELTA - t), 1)
            if nuevo:
                beep(900, 120)
            linea(f">>>  {n}  <<<   prepara la suelta", C["t"])
        elif t < T_SUELTA + 1.5:
            if nuevo and entero == int(T_SUELTA):
                beep(1500, 400)
            linea(">>>>>>  S U E L T A  <<<<<<", C["ok"])
        else:
            resta = SECONDS - t
            if nuevo and int(resta) in (10, 5):
                beep(500, 80)
            linea(f"grabando el decaimiento, NO TOQUES   {resta:4.1f} s", C["d"])

        ultimo = entero
        time.sleep(0.08)

    beep(400, 250)
    sys.stdout.write("\r" + " " * 72 + "\r")
    sys.stdout.flush()


def write_csv(path: Path, acq) -> None:
    """Esquema canonico del proyecto (`qube_daq/__main__.py:26`), para que `load_trace`,
    `qube_daq plot` y el resto de las herramientas lean estos archivos sin adaptadores."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapped = (acq.al_deg + 180.0) % 360.0 - 180.0
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(("t_s", "theta_deg", "alpha_deg", "alpha_raw_deg", "pwm", "mode"))
        w.writerows(
            [
                f"{acq.t_s[i]:.6f}", f"{acq.th_deg[i]:.4f}", f"{wrapped[i]:.4f}",
                f"{acq.al_deg[i]:.4f}", int(acq.pwm[i]), int(acq.mode[i]),
            ]
            for i in range(acq.n)
        )


def report(res: da.DecayResult) -> None:
    color = C["no"] if res.discarded else (C["ok"] if res.verdict == da.VISCOSO else C["d"])
    print(f"    {C['b']}veredicto{C['n']}        {color}{res.verdict}{C['n']}")
    print(
        f"    captura          {res.n} muestras, {res.duration_s:.1f} s, {res.rate_hz:.1f} Hz"
    )
    if math.isfinite(res.equilibrium_deg):
        print(f"    vertical         {res.equilibrium_deg:.2f} deg ({res.equilibrium_method})")
    if math.isfinite(res.amp0_deg):
        # Solo se informa el conteo si de verdad se conto: una guarda fatal corta antes de
        # buscar picos, y ahi `n_peaks` vale 0 por no haberse calculado, no por no haber
        # oscilacion. Imprimir "0 semiciclos" en ese caso se lee como pendulo trabado.
        picos = f", {res.n_peaks} semiciclos" if res.peaks_a.size or not res.discarded else ""
        print(f"    suelta           {res.amp0_deg:.1f} deg{picos}")
    if math.isfinite(res.lam_exp):
        print(
            f"    envolvente       lambda = {res.lam_exp:.4f} 1/s  R2 = {res.r2_exp:.3f}  ->  "
            f"Dp = {res.dp:.3e} ({res.dp / da.REF_DP:.2f}x ref)"
        )
    if math.isfinite(res.tau_c_fit):
        print(
            f"    balance energia  tau_c = {res.tau_c_fit:.3e} (t = {res.t_tau_c:5.1f})   "
            f"Dp = {res.dp_fit:.3e} (t = {res.t_dp:5.1f})"
        )
    if math.isfinite(res.tau_c_from_rest):
        print(
            f"    reposo final     {res.rest_after_deg:+.2f} deg  ->  tau_c >= "
            f"{res.tau_c_from_rest:.3e} N.m"
        )
    for g in res.guards:
        if not g.ok:
            marca = f"{C['no']}FATAL{C['n']}" if g.fatal else f"{C['d']}aviso{C['n']}"
            print(f"    [{marca}] {g.name}: {g.detail}")
    for n in res.notes:
        print(f"    {C['d']}nota:{C['n']} {n}")


def preflight(daq: DaqClient) -> bool:
    """Comprueba que la adquisicion entregue lo que dice antes de gastar 8 corridas.

    Existe por un fallo concreto del 2026-08-12: habia una sesion de DAQ colgada de antes, y
    entre los dos consumidores el firmware entregaba el 16% de las muestras **informando
    `dropped = 0`**. O sea que el modo de falla es silencioso: el contador de descartes no lo
    ve, porque el firmware no descarto nada -alguien se lo llevo-. Sin esta comprobacion, la
    campana habria grabado ocho corridas incompletas sin una sola senal de alarma.
    """
    print(f"\n  {C['b']}comprobacion previa de la adquisicion ({PREFLIGHT_S:.0f} s){C['n']}")
    try:
        daq.stop()  # limpiar cualquier sesion colgada de antes
    except requests.RequestException:
        pass
    time.sleep(0.3)
    try:
        acq = daq.record(seconds=PREFLIGHT_S, decim=DECIM, poll_interval=0.25)
    except requests.RequestException as exc:
        print(f"  {C['no']}no se pudo adquirir: {type(exc).__name__}{C['n']}")
        return False

    esperadas = PREFLIGHT_S * NOMINAL_RATE_HZ
    frac = acq.n / esperadas if esperadas else 0.0
    print(f"    {acq.n} muestras de ~{esperadas:.0f} esperadas ({frac * 100:.0f}%), "
          f"{acq.rate_hz:.1f} Hz efectivos, descartadas {acq.dropped}")
    if frac >= 0.85 and acq.dropped == 0:
        print(f"    {C['ok']}adquisicion sana{C['n']}")
        return True

    print(f"\n  {C['no']}La adquisicion no entrega lo que deberia.{C['n']}")
    print("  La causa tipica es que haya OTRO cliente hablando con la placa: el firmware sirve")
    print("  /daq/read a un solo consumidor y entre dos se reparten las muestras, con el")
    print("  contador de descartes informando 0 porque el firmware no descarto nada.")
    print("  Revisa que no queden abiertos:")
    print("    - la app de escritorio del QUBE (`qube_app`)")
    print("    - una pestana del navegador en http://192.168.4.1")
    print("    - otro script o terminal con una captura corriendo")
    return False


def capture_one(link: QubeLink, daq: DaqClient, amp: float, tag: str, out: Path) -> da.DecayResult:
    print(f"\n{C['d']}    Antes de empezar: pendulo COLGANDO y quieto, brazo SUJETO A MANO, firme.{C['n']}")
    print(f"{C['d']}    Despues no toques nada hasta que suene el pitido largo del final.{C['n']}")
    print(f"\n    la corrida dura {SECONDS:.0f} s y va sola:")
    print(f"      {0:>5.0f} - {T_COLGANDO:>4.0f} s   colgando, quieto")
    print(f"      {T_COLGANDO:>5.0f} - {T_COLGANDO + T_LEVANTAR:>4.0f} s   levanta a ~{amp:.0f} grados y sosten")
    print(f"      {T_COLGANDO + T_LEVANTAR:>5.0f} - {T_SUELTA:>4.0f} s   cuenta 3, 2, 1")
    print(f"      {C['b']}{T_SUELTA:>5.0f} s        SUELTA{C['n']}  (pitido agudo largo)")
    print(f"      {T_SUELTA:>5.0f} - {SECONDS:>4.0f} s   decaimiento, sin tocar")
    input(f"\n  {C['b']}ENTER para arrancar...{C['n']}")

    link.send({"m": 0})
    time.sleep(0.3)
    stop = threading.Event()
    guia = threading.Thread(target=countdown, args=(stop, amp), daemon=True)
    guia.start()
    try:
        acq = daq.record(seconds=SECONDS, decim=DECIM, poll_interval=0.25)
    except requests.RequestException as exc:
        # El stack WiFi de la ESP32 se queda sin responder unos segundos cada tanto. No es
        # que la placa se reinicie, pero una campana de ocho corridas no se puede caer por
        # eso: se devuelve una corrida marcada y el operador decide si la repite.
        stop.set()
        guia.join(timeout=1.0)
        print(f"\n  {C['no']}el enlace se cayo durante la captura: {type(exc).__name__}{C['n']}")
        res = da.DecayResult(verdict=da.DESCARTADA)
        res.guards.append(da.Guard("enlace", False, f"{type(exc).__name__} durante la captura"))
        return res
    finally:
        stop.set()
        guia.join(timeout=1.0)
    print(f"  {acq.n} muestras, {acq.rate_hz:.1f} Hz efectivos, descartadas por el firmware: {acq.dropped}")

    path = out / f"decay_{tag}.csv"
    write_csv(path, acq)
    trace = da.Trace(acq.t_s, acq.al_deg, acq.th_deg, path.name, dropped=acq.dropped)
    res = da.analyze(trace, target_amp_deg=amp, nominal_rate_hz=NOMINAL_RATE_HZ)
    report(res)
    return res


def summarize(runs: list[tuple[float, da.DecayResult]], out: Path) -> None:
    head("Resumen de la campana A2")
    for i, (amp, r) in enumerate(runs, 1):
        print(f"  {i}. {amp:4.0f} deg   {r.summary()}")

    agg = da.compare_across_amplitudes(runs)
    print(f"\n  corridas: {agg['n_total']} totales, {agg['n_usables']} usables, "
          f"{agg['n_descartadas']} descartadas, {agg['n_trabadas']} trabadas")
    for amp, v in sorted(agg["por_amplitud"].items()):
        std = f" +- {v['lambda_std']:.4f}" if math.isfinite(v["lambda_std"]) else ""
        print(f"    {amp:4.0f} deg  n={v['n']}  lambda = {v['lambda_mediana']:.4f}{std}   "
              f"Dp = {v['dp']:.3e} ({v['dp'] / da.REF_DP:.2f}x ref)")
    if math.isfinite(agg.get("tau_c_cota_inferior", float("nan"))):
        print(f"\n  tau_c >= {agg['tau_c_cota_inferior']:.3e} N.m  (mejor cota de "
              f"{agg['n_reposos']} angulos de reposo)")

    # Deriva de la sesion: las corridas 1 y 8 son la misma amplitud, separadas por la tanda.
    if len(runs) == len(PLAN) and not runs[0][1].discarded and not runs[-1][1].discarded:
        r0, r1 = runs[0][1], runs[-1][1]
        l0, l1 = r0.lam_exp, r1.lam_exp
        if math.isfinite(l0) and math.isfinite(l1) and l0 > 0:
            print(f"\n  deriva de la sesion: lambda paso de {l0:.4f} a {l1:.4f} "
                  f"({l1 / l0:.2f}x entre la primera corrida y la ultima)")
            # La primera y la ultima se piden a la misma amplitud justamente para que la
            # comparacion sea limpia. Si las sueltas reales no coincidieron, el numero mezcla
            # deriva con amplitud y no se puede leer como deriva: hay que decirlo.
            if abs(r0.amp0_deg - r1.amp0_deg) > 0.15 * max(r0.amp0_deg, r1.amp0_deg):
                print(f"    {C['no']}OJO: soltaron desde {r0.amp0_deg:.1f} y {r1.amp0_deg:.1f} deg, "
                      f"no desde la misma amplitud.{C['n']}")
                print("    Ese factor mezcla deriva temporal con dependencia de la amplitud y no")
                print("    se puede atribuir a ninguna de las dos.")

    print(f"\n  {C['b']}veredicto de campana: {agg['veredicto']}{C['n']}")
    for n in agg["notas"]:
        print(f"    {n}")
    if agg["n_descartadas"]:
        print(f"\n  {C['no']}Hay {agg['n_descartadas']} corridas descartadas. Van listadas con su "
              f"motivo en el README; no entran en ningun promedio.{C['n']}")

    payload = {
        "agregado": agg,
        "corridas": [
            {"amplitud_objetivo": amp,
             **{k: v for k, v in asdict(r).items() if not isinstance(v, np.ndarray)},
             "guards": [{"name": g.name, "ok": g.ok, "fatal": g.fatal, "detail": g.detail}
                        for g in r.guards]}
            for amp, r in runs
        ],
    }
    (out / "resumen.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"\n  Resultados en {out}")


def analyze_existing(out: Path) -> int:
    """Re-analiza los CSV ya grabados. No necesita el banco."""
    files = sorted(out.glob("decay_*.csv"))
    if not files:
        print(f"  No hay CSV en {out}")
        return 1
    runs = []
    for path in files:
        # `decay_03_60deg.csv` -> 60. Se busca el token que termina en "deg" y no una
        # posicion fija, que es como se confundia el indice de corrida con la amplitud.
        tokens = [tk for tk in path.stem.split("_") if tk.endswith("deg")]
        if not tokens:
            print(f"  {path.name}: no se puede leer la amplitud del nombre; se omite.")
            continue
        amp = float(tokens[-1].removesuffix("deg"))
        head(f"{path.name}  (objetivo {amp:.0f} deg)")
        res = da.analyze(da.load_trace(path), target_amp_deg=amp, nominal_rate_hz=NOMINAL_RATE_HZ)
        report(res)
        runs.append((amp, res))
    summarize(runs, out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Campana A2 — decaimiento libre del pendulo")
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--solo", type=float, nargs="+", help="solo estas amplitudes")
    ap.add_argument("--dir", default=None, help="carpeta de salida (por defecto, una nueva)")
    ap.add_argument("--analizar", action="store_true", help="re-analiza CSV existentes, sin banco")
    args = ap.parse_args()

    out = Path(args.dir) if args.dir else DATA / time.strftime("a2_%Y%m%d_%H%M%S")
    if args.analizar:
        if args.dir is None:
            candidatos = sorted(DATA.glob("a2_*"))
            if not candidatos:
                print("  No hay campanas grabadas.")
                return 1
            out = candidatos[-1]
        return analyze_existing(out)

    # La campana es interactiva por necesidad: hay que sostener el brazo, levantar el
    # pendulo y soltarlo con el cronometro. Sin terminal de verdad no hay ni ENTER ni guia
    # en vivo, y el aviso de cuando soltar llegaria despues de que la corrida termino.
    if not sys.stdin.isatty():
        print(f"{C['no']}  Esto necesita una terminal interactiva.{C['n']}")
        print("  Sin ella no se puede confirmar cada corrida ni ver la cuenta para soltar.")
        print("  Abri una terminal normal y corre:")
        print(f"    cd {Path(__file__).resolve().parent}")
        print("    uv run python run_a2.py")
        print("\n  Para trabajar sobre lo ya grabado no hace falta terminal:")
        print("    uv run python run_a2.py --analizar")
        return 2

    head("Campana A2 — decaimiento libre del pendulo")
    print(
        f"{C['d']}  {len(PLAN)} corridas de {SECONDS:.0f} s, a {NOMINAL_RATE_HZ:.0f} Hz.\n"
        f"  Amplitudes intercaladas para separar el efecto de la amplitud de la deriva de\n"
        f"  la sesion. La corrida 1 y la 8 son la misma: su diferencia mide esa deriva.{C['n']}"
    )

    link = QubeLink(args.ip)
    state = link.state()
    v = float(state.get("v_bus") or 0.0)
    print(f"\n  placa: modo={state.get('mode')}  v_bus={v:.2f} V  "
          f"ina_ok={state.get('ina_ok')}  pend={float(state.get('pend_position_deg') or 0):.2f} deg")
    if v and v < BROWNOUT_CUT_V:
        print(f"{C['no']}  v_bus = {v:.2f} V esta bajo. Revisar alimentacion antes de seguir.{C['n']}")

    link.send({"m": 0})
    # La telemetria serial son ~120 caracteres cada 100 ms contra un lazo de 2 ms
    # (esp32_qube.ino:801-805): se apaga durante la adquisicion.
    link.send({"sv": 0})
    print(f"  modo 0 (sin par) y telemetria serial apagada.")
    print(f"{C['d']}  El cero del pendulo (zp) NO se toca: el analisis usa el centro de oscilacion\n"
          f"  medido en cada corrida, asi que el offset del encoder da lo mismo.{C['n']}")

    plan = [(a, r) for a, r in PLAN if not args.solo or a in args.solo]
    runs: list[tuple[float, da.DecayResult]] = []
    # Timeout holgado: el stack WiFi de la ESP32 se bloquea hasta ~1 s cada tanto y el
    # default de 2 s del cliente se queda corto durante una captura larga.
    daq = DaqClient(args.ip, timeout=6.0)
    try:
        if not preflight(daq) and input(f"\n  {C['b']}seguir igual? [s/N] {C['n']}").strip().lower() != "s":
            return 1
        for i, (amp, rol) in enumerate(plan, 1):
            head(f"Corrida {i}/{len(plan)} — {amp:.0f} deg" + (f"   [{rol}]" if rol else ""))
            tag = f"{i:02d}_{amp:.0f}deg"
            res = capture_one(link, daq, amp, tag, out)
            while res.discarded and ask(
                f"  {C['b']}repetir esta corrida? [s/N] {C['n']}"
            ).strip().lower() == "s":
                res = capture_one(link, daq, amp, tag, out)
            runs.append((amp, res))
            time.sleep(1.0)  # que la placa respire entre sesiones de DAQ
    except KeyboardInterrupt:
        print(f"\n{C['d']}  interrumpido; se resume lo grabado hasta aca.{C['n']}")
    finally:
        try:
            link.send({"m": 0})
            link.send({"sv": 1})
        except Exception:
            pass
        daq.close()

    if runs:
        summarize(runs, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
