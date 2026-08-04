"""¿Quién le roba tiempo a quién? — carga del lazo de 500 Hz vs tráfico de red.

Pregunta que responde: la hipótesis de que "la ESP32 va lenta porque además del WiFi
carga con todo el lazo, y descargándola mejoraría la transmisión". Es medible con
instrumentación que YA existe en el firmware y no requiere tocar una línea de código:

    loop_dt_max_us  — peor período real del lazo desde el último reset (nominal 2000)
    loop_overruns   — veces que el atraso superó 5 períodos y hubo que resincronizar
    /cmd?rj=1       — resetea ambos contadores

Las dos direcciones posibles de la interferencia dan resultados distintos y separables:

  · Si el LAZO carga a la placa   -> dt_max crece con la complejidad del modo
                                     (0 sin ley de control < 4 LQR < 7 red neuronal),
                                     y es indiferente al tráfico de red.
  · Si la RED le roba al lazo     -> dt_max apenas se mueve entre modos, pero se
                                     dispara cuando se martilla el enlace.

Fases
-----
A  modo 0, enlace ocioso    (1 lectura/s)      -> línea base
B  modo 0, enlace martillado (continuo)        -> cuánto le roba la radio al lazo
C  modos 4 y 7, enlace ocioso  [--with-control] -> cuánto cuesta la ley de control

**La fase C ENERGIZA EL MOTOR**: el LQR y la red neuronal mandan PWM. Es opt-in, exige
confirmación, dura poco y siempre termina en `/cmd?x=1`. Brazo despejado y alguien
presente. Las fases A y B corren en modo 0 (motor deshabilitado) y son seguras.

Uso
---
    python measure_loop_load.py                      # fases A y B (seguras)
    python measure_loop_load.py --with-control       # + fase C (mueve el brazo)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_IP = os.environ.get("QUBE_IP", "192.168.4.1")
NOMINAL_US = 2000  # CONTROL_PERIOD_US del firmware (500 Hz)


def _get(session: requests.Session, url: str, timeout: float = 2.0) -> dict | None:
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def phase(session: requests.Session, base: str, name: str, mode: int, seconds: float, hammer: bool) -> dict:
    """Corre una fase y devuelve la salud del lazo al terminar.

    ``hammer=True`` satura el enlace con /rl_step; ``False`` lo deja casi ocioso
    (1 lectura/s), que es la condición en la que el lazo debería lucir mejor.
    """
    _get(session, f"{base}/cmd?m={mode}")
    time.sleep(0.3)
    # Resetear DESPUÉS de fijar el modo: el cambio de modo en sí no debe contarse,
    # y el peor caso del arranque del firmware tampoco (lo domina el escaneo WiFi).
    _get(session, f"{base}/cmd?rj=1")

    print(f"  [{name}] modo {mode}, {seconds:.0f} s, enlace {'MARTILLADO' if hammer else 'ocioso'}...")
    requests_sent = 0
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        if hammer:
            _get(session, f"{base}/rl_step?a=0.0", timeout=0.4)
            requests_sent += 1
        else:
            _get(session, f"{base}/rl_step?a=0.0", timeout=0.4)
            requests_sent += 1
            time.sleep(1.0)

    final = _get(session, f"{base}/state") or {}
    result = {
        "phase": name,
        "mode": mode,
        "seconds": seconds,
        "hammer": hammer,
        "requests": requests_sent,
        "req_per_s": requests_sent / seconds,
        "loop_dt_max_us": final.get("loop_dt_max_us"),
        "loop_overruns": final.get("loop_overruns"),
    }
    dt = result["loop_dt_max_us"]
    over = result["loop_overruns"]
    ratio = f"{dt / NOMINAL_US:.1f}x" if isinstance(dt, (int, float)) else "?"
    print(f"      dt_max={dt} us ({ratio} del nominal)  overruns={over}  ({result['req_per_s']:.1f} req/s)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default=DEFAULT_IP, help=f"IP del ESP32 (default {DEFAULT_IP})")
    ap.add_argument("--label", default="loopload", help="Etiqueta del archivo de salida")
    ap.add_argument("--seconds", type=float, default=30.0, help="Duración de cada fase [s]")
    ap.add_argument("--with-control", action="store_true", help="Agregar fase C: modos 4 y 7 (MUEVE EL BRAZO)")
    args = ap.parse_args()

    base = f"http://{args.ip}"
    session = requests.Session()
    session.headers.update({"Connection": "keep-alive"})

    if _get(session, f"{base}/state") is None:
        print(f"ERROR: {args.ip} no responde. ¿El PC está asociado a la red correcta?")
        raise SystemExit(1)

    phases: list[dict] = []
    try:
        print("\nFases seguras (modo 0, motor deshabilitado):")
        phases.append(phase(session, base, "A_idle", 0, args.seconds, hammer=False))
        phases.append(phase(session, base, "B_hammer", 0, args.seconds, hammer=True))

        if args.with_control:
            print("\n  AVISO: la fase C ENERGIZA EL MOTOR (LQR y red neuronal mandan PWM).")
            print("  Brazo despejado, péndulo colgando libre, alguien presente.")
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input("  ENTER para continuar, Ctrl-C para abortar... ")
            print("\nFase C (motor habilitado, enlace ocioso):")
            phases.append(phase(session, base, "C_lqr", 4, min(args.seconds, 15.0), hammer=False))
            _get(session, f"{base}/cmd?x=1")
            time.sleep(2.0)
            phases.append(phase(session, base, "C_nn", 7, min(args.seconds, 15.0), hammer=False))
    finally:
        # Pase lo que pase —incluido Ctrl-C— el motor queda detenido.
        for _ in range(5):
            if _get(session, f"{base}/cmd?x=1") is not None:
                break
            time.sleep(0.5)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DATA_DIR / f"{stamp}_{args.label}.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "ip": args.ip,
                "host": socket.gethostname(),
                "nominal_us": NOMINAL_US,
                "phases": phases,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n" + "-" * 62)
    print(f"{'fase':<10} {'modo':>5} {'enlace':>12} {'dt_max_us':>10} {'overruns':>9}")
    for p in phases:
        print(
            f"{p['phase']:<10} {p['mode']:>5} {'martillado' if p['hammer'] else 'ocioso':>12} "
            f"{p['loop_dt_max_us']!s:>10} {p['loop_overruns']!s:>9}"
        )
    print("-" * 62)
    print("Lectura: si B >> A, la RED le roba al lazo. Si C >> A con el enlace ocioso,")
    print("es la LEY DE CONTROL la que carga la placa. Ambas cosas pueden ser ciertas;")
    print("lo que decide el rediseño es cuál domina.")
    print(f"\nGuardado en {path}")


if __name__ == "__main__":
    main()
