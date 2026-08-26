"""CLI de adquisición: graba, resume y grafica series capturadas por el ESP32.

    uv run python -m qube_daq status
    uv run python -m qube_daq record --seconds 10 --hz 500 -o data/captura.csv
    uv run python -m qube_daq record --seconds 10 --mode 5    # arranca swing-up y graba
    uv run python -m qube_daq plot data/captura.csv

El CSV sale con el esquema canónico del proyecto (``t_s``, ``theta_deg``,
``alpha_deg``, ``alpha_raw_deg``, ``pwm``, ``mode``), el mismo que produce
``src/firmware/capture.py``, para que el análisis existente lo lea sin adaptadores.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import requests

from qube_daq.client import Acquisition, DaqClient
from qube_rl.config import DEFAULT_ESP32_IP

CSV_FIELDS = ("t_s", "theta_deg", "alpha_deg", "alpha_raw_deg", "pwm", "mode")
CONTROL_HZ = 500.0  # CONTROL_PERIOD_US = 2000 en el firmware


def _decim_for(hz: float) -> int:
    """Decimación entera más cercana a la tasa pedida, acotada a >= 1."""
    return max(1, round(CONTROL_HZ / hz))


def write_csv(acq: Acquisition, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapped = acq.alpha_wrapped_deg
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_FIELDS)
        for i in range(acq.n):
            writer.writerow(
                [
                    f"{acq.t_s[i]:.6f}",
                    f"{acq.th_deg[i]:.4f}",
                    f"{wrapped[i]:.4f}",
                    f"{acq.al_deg[i]:.4f}",
                    int(acq.pwm[i]),
                    int(acq.mode[i]),
                ]
            )


def summarize(acq: Acquisition, requested_hz: float | None = None) -> None:
    """Imprime lo que hace falta para confiar (o no) en la captura."""
    print()
    print(f"  muestras          : {acq.n}  en {acq.blocks} bloques")
    print(f"  duración          : {acq.duration_s:.3f} s")
    print(f"  tasa efectiva     : {acq.rate_hz:.1f} Hz", end="")
    if requested_hz:
        err = 100.0 * (acq.rate_hz - requested_hz) / requested_hz if requested_hz else 0.0
        print(f"   (pedida {requested_hz:.1f} Hz, desvío {err:+.1f} %)")
    else:
        print()
    if acq.n > 1:
        dt_ms = np.diff(acq.t_s) * 1000.0
        print(f"  intervalo         : mediana {np.median(dt_ms):.3f} ms, máx {dt_ms.max():.3f} ms")
    gaps = acq.gaps()
    print(f"  huecos (>1.5x)    : {len(gaps)}")
    if acq.dropped:
        print(f"  MUESTRAS PERDIDAS : {acq.dropped}  <- el PC no alcanzó a vaciar el buffer")
    else:
        print("  muestras perdidas : 0")
    print()


def cmd_status(args: argparse.Namespace) -> int:
    with DaqClient(args.ip) as client:
        st = client.status()
    for k, v in st.items():
        print(f"  {k:<14}: {v}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    decim = _decim_for(args.hz)
    effective_hz = CONTROL_HZ / decim
    if abs(effective_hz - args.hz) > 0.01:
        print(f"Nota: {args.hz} Hz no es divisor de {CONTROL_HZ:.0f} Hz; se usará {effective_hz:.1f} Hz.")

    with DaqClient(args.ip) as client:
        if args.mode is not None:
            # El modo se fija ANTES de arrancar la captura para que el transitorio de
            # entrada quede dentro de la serie y no se pierda el arranque.
            if args.mode not in (0, 1, 2, 4, 5, 7):
                print(f"Modo {args.mode} no aceptado aquí (0,1,2,4,5,7).")
                return 2
            print(f"AVISO: el modo {args.mode} puede MOVER EL BRAZO. Despejado y péndulo libre.")
            input("ENTER para continuar, Ctrl-C para abortar... ")
            requests.get(f"http://{args.ip}/cmd", params={"m": args.mode}, timeout=2.0)

        print(f"Grabando {args.seconds:.1f} s a {effective_hz:.1f} Hz desde {args.ip}...")
        try:
            acq = client.record(seconds=args.seconds, decim=decim, poll_interval=args.poll)
        finally:
            if args.mode is not None:
                # Nunca dejar el motor energizado por haber terminado de grabar.
                for _ in range(5):
                    try:
                        requests.get(f"http://{args.ip}/cmd", params={"x": 1}, timeout=2.0)
                        break
                    except requests.RequestException:
                        continue

    summarize(acq, requested_hz=effective_hz)
    if acq.n == 0:
        print("No se recibió ninguna muestra. ¿La placa está encendida y asociada?")
        return 1

    out = Path(args.output)
    write_csv(acq, out)
    print(f"Guardado en {out}  ({acq.n} filas)")
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    import matplotlib.pyplot as plt

    path = Path(args.csv)
    data = np.genfromtxt(path, delimiter=",", names=True)
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(10, 7))
    axes[0].plot(data["t_s"], data["theta_deg"], lw=0.8)
    axes[0].set_ylabel("θ brazo [°]")
    axes[1].plot(data["t_s"], data["alpha_deg"], lw=0.8, color="tab:orange")
    axes[1].set_ylabel("α péndulo [°]")
    axes[2].plot(data["t_s"], data["pwm"], lw=0.8, color="tab:green")
    axes[2].set_ylabel("PWM")
    axes[2].set_xlabel("t [s]")
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.suptitle(f"{path.name} — {len(data['t_s'])} muestras")
    fig.tight_layout()
    if args.save:
        fig.savefig(args.save, dpi=140)
        print(f"Figura en {args.save}")
    else:
        plt.show()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="qube_daq", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--ip", default=DEFAULT_ESP32_IP, help=f"IP del ESP32 (default {DEFAULT_ESP32_IP})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Estado de la adquisición en la placa")

    rec = sub.add_parser("record", help="Grabar una captura a CSV")
    rec.add_argument("--seconds", type=float, default=10.0, help="Duración [s]")
    rec.add_argument("--hz", type=float, default=500.0, help="Tasa de muestreo pedida (default 500)")
    rec.add_argument("--poll", type=float, default=0.25, help="Intervalo entre lecturas de bloque [s]")
    rec.add_argument("--mode", type=int, default=None, help="Fijar este modo antes de grabar (MUEVE EL BRAZO)")
    rec.add_argument("-o", "--output", default="capture.csv", help="Archivo CSV de salida")

    plot = sub.add_parser("plot", help="Graficar un CSV ya grabado")
    plot.add_argument("csv", help="Archivo CSV")
    plot.add_argument("--save", default=None, help="Guardar PNG en vez de mostrar")

    args = ap.parse_args(argv)
    handlers = {"status": cmd_status, "record": cmd_record, "plot": cmd_plot}
    try:
        return handlers[args.cmd](args)
    except requests.RequestException as exc:
        print(f"ERROR de red: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
