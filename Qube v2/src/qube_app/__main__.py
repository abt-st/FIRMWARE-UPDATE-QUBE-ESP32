"""Entrada de la app de escritorio del QUBE.

    uv run python -m qube_app                       # GUI (requiere: uv sync --extra app)
    uv run python -m qube_app --selftest            # adquisición sin GUI, contra la placa
    uv run python -m qube_app --selftest --fake     # ídem contra una placa simulada

La autoprueba existe para estrenar el DAQ en banco **sin** una GUI de por medio: si algo
falla, falla en el transporte y no en el dibujo. Reporta lo mismo que ``qube_daq record``
—tasa efectiva medida, intervalos, huecos y muestras perdidas— y además compara
``loop_dt_max_us`` con y sin adquisición activa, que es lo que el diseño del DAQ dejó
declarado como no medido.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time

import numpy as np
import requests

from qube_app.link import QubeLink
from qube_app.stream import CONTROL_HZ, DaqStream
from qube_daq.__main__ import _decim_for
from qube_rl.config import DEFAULT_ESP32_IP


def _fix_windows_console() -> None:
    """Pone la consola en UTF-8 antes de imprimir nada.

    En el ejecutable empaquetado la consola arranca en la página de códigos heredada
    (850/1252) y los rótulos del proyecto —°, α, θ, ·— salen como basura. Corriendo con
    ``uv run`` no se notaba porque la consola ya venía configurada por el terminal.
    """
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def _measure_loop_health(link: QubeLink, seconds: float) -> dict:
    """Resetea las métricas del lazo, espera y las lee. Sin DAQ de por medio."""
    link.reset_loop_metrics()
    time.sleep(seconds)
    st = link.state()
    return {
        "loop_dt_max_us": st.get("loop_dt_max_us"),
        "loop_overruns": st.get("loop_overruns"),
        "loop_dt_nom_us": st.get("loop_dt_nom_us"),
    }


def selftest(args: argparse.Namespace) -> int:
    decim = _decim_for(args.hz)
    nominal_hz = CONTROL_HZ / decim
    link: QubeLink | None = None
    baseline: dict = {}

    if args.fake:
        from qube_app.fake import FakeDaqClient

        stream = DaqStream(decim=decim, poll_interval=args.poll, client=FakeDaqClient())
        print(f"Placa SIMULADA · {nominal_hz:.0f} Hz nominal · sondeo {args.poll:.2f} s")
    else:
        link = QubeLink(args.ip)
        print(f"Placa en {args.ip} · {nominal_hz:.0f} Hz nominal · sondeo {args.poll:.2f} s")
        # Referencia del lazo SIN adquisición, para poder atribuirle a la captura lo que
        # le cueste. Medir sólo el "después" no permite afirmar nada.
        print("  midiendo el lazo en reposo (sin DAQ)...")
        baseline = _measure_loop_health(link, min(5.0, args.seconds))
        print(f"    loop_dt_max_us={baseline['loop_dt_max_us']}  loop_overruns={baseline['loop_overruns']}")
        link.reset_loop_metrics()
        stream = DaqStream(args.ip, decim=decim, poll_interval=args.poll)

    # Sólo se guardan las marcas de tiempo: es lo único que la autoprueba analiza, y
    # quedarse con las cuatro trazas enteras sería reservar memoria para no mirarla.
    marks: list[np.ndarray] = []
    print(f"  adquiriendo {args.seconds:.1f} s...")
    stream.start()
    t_end = time.perf_counter() + args.seconds
    try:
        while time.perf_counter() < t_end:
            time.sleep(0.1)
            marks.extend(c.t_s for c in stream.drain())
    except KeyboardInterrupt:
        print("\n  interrumpido.")
    finally:
        stream.stop()
    marks.extend(c.t_s for c in stream.drain())

    stats = stream.stats
    t = np.concatenate(marks) if marks else np.zeros(0)
    print()
    print(f"  muestras          : {stats.samples}  en {stats.blocks} bloques")
    print(f"  duración          : {stats.duration_s:.3f} s")
    err = 100.0 * (stats.rate_hz - nominal_hz) / nominal_hz if nominal_hz else 0.0
    print(f"  tasa efectiva     : {stats.rate_hz:.1f} Hz   (nominal {nominal_hz:.1f} Hz, desvío {err:+.1f} %)")
    if len(t) > 1:
        dt_ms = np.diff(t) * 1000.0
        print(f"  intervalo         : mediana {np.median(dt_ms):.3f} ms, máx {dt_ms.max():.3f} ms")
    print(f"  huecos (>1.5x)    : {stats.gaps}")
    print(f"  503 (ocupado)     : {stats.busy_503}   errores de red: {stats.errors}")
    if stats.dropped:
        print(f"  MUESTRAS PERDIDAS : {stats.dropped}  <- el PC no alcanzó a vaciar el buffer")
    else:
        print("  muestras perdidas : 0")

    if link is not None:
        during = link.state()
        print()
        print("  salud del lazo    :            sin DAQ      con DAQ")
        print(
            f"    loop_dt_max_us  : {baseline['loop_dt_max_us']:>12}  {during.get('loop_dt_max_us'):>11}"
            f"   (nominal {during.get('loop_dt_nom_us')})"
        )
        print(f"    loop_overruns   : {baseline['loop_overruns']:>12}  {during.get('loop_overruns'):>11}")
        link.close()
    print()

    if stats.samples == 0:
        print("No se recibió ninguna muestra. ¿La placa está encendida y asociada al SoftAP?")
        return 1
    return 0


def run_gui(args: argparse.Namespace) -> int:
    try:
        from qube_app.ui.main_window import launch
    except ImportError as exc:
        print(f"No se pudo cargar la interfaz ({exc}).")
        print("Instalar las dependencias de la app:  uv sync --extra app")
        return 1
    return launch(ip=args.ip, fake=args.fake, poll_interval=args.poll, hz=args.hz)


def main(argv: list[str] | None = None) -> int:
    _fix_windows_console()
    ap = argparse.ArgumentParser(
        prog="qube_app", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--ip", default=DEFAULT_ESP32_IP, help=f"IP del ESP32 (default {DEFAULT_ESP32_IP})")
    ap.add_argument("--hz", type=float, default=500.0, help="Tasa de adquisición pedida (default 500)")
    ap.add_argument("--poll", type=float, default=0.2, help="Intervalo entre lecturas de bloque [s]")
    ap.add_argument("--fake", action="store_true", help="Placa simulada, sin hardware")
    ap.add_argument("--selftest", action="store_true", help="Adquirir y reportar, sin abrir la GUI")
    ap.add_argument("--seconds", type=float, default=10.0, help="Duración de la autoprueba [s]")
    ap.add_argument(
        "--demo-seconds",
        type=float,
        default=None,
        help="Abre la GUI simulada, adquiere N segundos y se cierra sola (verificación sin banco)",
    )
    args = ap.parse_args(argv)

    try:
        if args.demo_seconds is not None:
            from qube_app.ui.main_window import demo_seconds

            return demo_seconds(args.demo_seconds)
        return selftest(args) if args.selftest else run_gui(args)
    except requests.RequestException as exc:
        print(f"ERROR de red: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
