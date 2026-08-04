"""¿El encoder del pendulo pierde cuentas en las corridas energeticas?

Prueba discriminante, con el ciclo cerrado sobre una referencia FISICA que no depende de
ningun cero de software: **el pendulo colgando**. Un pendulo en reposo apunta hacia abajo,
siempre, sea cual sea la posicion del brazo. Entonces:

    1. con el pendulo colgando y quieto, poner el cero (`zp=1`) -> alpha = 0
    2. correr el swing-up unos segundos (con vueltas si las hay)
    3. esperar a que vuelva a colgar y quedarse quieto
    4. leer alpha: **deberia volver a 0**

Lo que sobre es deriva. Si es reproducible y crece con la velocidad alcanzada, son pulsos
perdidos en la cadena de acondicionamiento (Schmitt + RC) a alta velocidad — y no un
problema del cero, que es lo que parecia a simple vista.

Por que importa: la etapa 2.6 del bring-up valido este encoder girandolo **a mano**, una
vuelta completa, 2048 cuentas exactas. A mano son decenas de grados por segundo; en un
swing-up son cientos. Una validacion lenta no dice nada sobre el regimen rapido.

Y si hay perdida, contamina hacia atras: `E/E*`, el angulo de traspaso y todo lo que el
LQR recibe se miden con esta misma alpha, justo en las corridas mas energeticas.

Uso:
    uv run python experiments/2026-08-03_alpha_drift/scripts/alpha_drift.py --ciclos 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.analysis import derive_velocity
from qube_app.buffers import TraceStore
from qube_app.link import QubeLink
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"
SWING_S = 12.0
SETTLE_TIMEOUT_S = 60.0
#: Cuentas por vuelta del encoder del pendulo (2048 en cuadratura X4).
CPR = 2048
#: El brazo tiene que arrancar el ciclo bien dentro del limite blando (+-95). Si quedo
#: parado afuera —tipico despues de que el swing-up lo lleve al tope y el firmware corte—
#: cualquier modo muere al instante y la corrida no mide nada. Paso el 2026-08-04: cuatro
#: ciclos reportaron "deriva 0,00" que en realidad eran "el swing-up nunca arranco".
ARM_START_MAX_DEG = 60.0
#: Debajo de esta velocidad pico se considera que el bombeo NO ocurrio, y la corrida se
#: marca invalida en vez de anotar una deriva nula que no significa nada.
MIN_SWING_VEL_DPS = 300.0


def wait_until_still(link: QubeLink, timeout: float = SETTLE_TIMEOUT_S) -> dict | None:
    """Espera a que la cuenta del pendulo deje de cambiar. Devuelve el ultimo `/state`.

    Se vigila la CUENTA CRUDA, no el angulo con offset: es lo unico que no depende de
    ninguna convencion ni de ningun cero.
    """
    last_count, stable, end = None, 0, time.monotonic() + timeout
    st: dict | None = None
    while time.monotonic() < end:
        try:
            st = link.state(retries=1)
        except Exception:
            time.sleep(0.4)
            continue
        count = st.get("pend_count")
        stable = stable + 1 if count == last_count else 0
        last_count = count
        if stable >= 10:  # ~5 s sin moverse una sola cuenta
            return st
        time.sleep(0.5)
    return st


def recenter(link: QubeLink) -> float:
    """Devuelve el brazo a la zona util. Necesario ENTRE ciclos, no solo al principio.

    El swing-up empuja el brazo contra el tope y el firmware corta el modo, dejandolo
    parado afuera; a partir de ahi cualquier modo muere al instante y las corridas
    siguientes no miden nada. Se intenta primero con el PID, que es suave; si el brazo
    quedo tan afuera que ni el PID puede accionar (el limite blando lo mata), se recurre
    al homing, que esta hecho justamente para recuperar el cero desde cualquier parte.
    """
    theta = float(link.state().get("position_deg") or 0.0)
    if abs(theta) <= ARM_START_MAX_DEG:
        return theta

    if abs(theta) < 90.0:
        print(f"  recentrando con el PID (theta={theta:+.1f})...")
        link.send({"m": 2, "s": 0.0})
        end = time.monotonic() + 8.0
        while time.monotonic() < end:
            time.sleep(0.4)
            theta = float(link.state(retries=1).get("position_deg") or 0.0)
            if abs(theta) < 15.0:
                break
        link.send({"m": 0})

    if abs(theta) > ARM_START_MAX_DEG:
        print(f"  el PID no alcanzo (theta={theta:+.1f}); recentrando con homing...")
        link.send({"m": 3})
        end = time.monotonic() + 60.0
        while time.monotonic() < end:
            time.sleep(0.7)
            st = link.state(retries=1)
            if st.get("homing_phase") in ("DONE", "FAIL"):
                break
        theta = float(link.state().get("position_deg") or 0.0)
    return theta


def cycle(link: QubeLink, n: int, suave: bool = False, sp: int | None = None) -> dict:
    etiqueta = "perturbacion lenta" if suave else (f"swing-up sp={sp}" if sp else "swing-up")
    print(f"\n--- ciclo {n} ({etiqueta}) ---")
    theta = recenter(link)
    if abs(theta) > ARM_START_MAX_DEG:
        raise SystemExit(
            f"El brazo quedo en {theta:+.1f} deg y no se pudo recentrar. Cualquier modo "
            "moriria contra el limite blando y la corrida no mediria nada."
        )

    print("  esperando reposo para poner el cero...")
    st = wait_until_still(link)
    if st is None:
        raise SystemExit("no se pudo leer la placa")
    count_before = int(st["pend_count"])

    link.send({"zp": 1})
    time.sleep(0.5)
    st = link.state()
    print(f"  cero puesto colgando: alpha={float(st['pend_position_deg']):.2f}  count={st['pend_count']}")
    wraps_before = int(st.get("pend_wraps", 0))

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    store = TraceStore(window_s=SWING_S + 5.0, rate_hz=500.0)
    stream.start()
    end = time.perf_counter() + SWING_S
    try:
        if suave:
            # Perturbacion LENTA: el brazo va y viene con el PID y el pendulo oscila unas
            # decenas de grados por segundo. A esa velocidad no puede haber perdida de
            # pulsos, asi que lo que se mida aca es repetibilidad MECANICA del colgado.
            while time.perf_counter() < end:
                for sp in (-20.0, 20.0):
                    link.send({"m": 2, "s": sp})
                    stop = min(end, time.perf_counter() + 2.0)
                    while time.perf_counter() < stop:
                        time.sleep(0.05)
                        for chunk in stream.drain():
                            store.extend(chunk)
        else:
            # `sp` fija el PWM maximo del bombeo, o sea la energia que se le inyecta: es
            # la perilla para llegar a distintas velocidades pico. El traspaso se
            # desactiva aparte (`tr=0`) para que el regimen no cambie a mitad de corrida.
            if sp is not None:
                link.send({"sp": sp})
            link.send({"m": 5})
            while time.perf_counter() < end:
                time.sleep(0.05)
                for chunk in stream.drain():
                    store.extend(chunk)
    finally:
        link.stop_motor()
        stream.stop()
        for chunk in stream.drain():
            store.extend(chunk)

    t, alpha_raw = store["t_s"], store["al_deg"]
    vel = derive_velocity(t, alpha_raw) if len(t) > 3 else np.zeros(1)
    vel_max = float(np.abs(vel).max())

    print(f"  swing-up hecho (|alpha_dot| max {vel_max:.0f} deg/s); esperando que vuelva a colgar...")
    st = wait_until_still(link)
    if st is None:
        raise SystemExit("no se pudo leer la placa")

    alpha_after = float(st["pend_position_deg"])
    count_after = int(st["pend_count"])
    wraps_after = int(st.get("pend_wraps", 0))
    # La deriva se mide sobre la CUENTA, descontando las vueltas enteras que el firmware
    # ya contabilizo: lo que quede es lo que no cierra.
    d_counts = count_after - count_before - (wraps_after - wraps_before) * CPR
    row = {
        "ciclo": n,
        "sp": sp,
        "count_antes": count_before,
        "count_despues": count_after,
        "wraps": wraps_after - wraps_before,
        "deriva_cuentas": d_counts,
        "deriva_deg": round(d_counts * 360.0 / CPR, 2),
        "alpha_colgando_despues": round(alpha_after, 2),
        "vel_max_dps": round(vel_max, 0),
        # Una corrida donde el bombeo no ocurrio NO es una medicion de deriva nula.
        "valido": bool(suave or vel_max >= MIN_SWING_VEL_DPS),
        "trans_reason": st.get("swing_trans_reason"),
        "trans_alpha": st.get("swing_trans_alpha"),
        "trans_energy": st.get("swing_trans_energy"),
        "muestras": len(t),
    }
    marca = "" if row["valido"] else "   <-- INVALIDA: el bombeo no ocurrio"
    print(
        f"  colgando DESPUES: alpha={alpha_after:+.2f}  ->  deriva {row['deriva_deg']:+.2f} deg"
        f" ({d_counts:+d} cuentas, {row['wraps']} vueltas contabilizadas){marca}"
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--ciclos", type=int, default=3)
    ap.add_argument(
        "--suave",
        action="store_true",
        help="Perturbar despacio (PID yendo y viniendo) en vez de swing-up: mide la "
        "repetibilidad mecanica del colgado, donde no puede haber perdida de pulsos",
    )
    ap.add_argument(
        "--barrido",
        default="",
        help="Lista de valores de `sp` (PWM maximo del bombeo) para alcanzar distintas "
        "velocidades pico y buscar el umbral donde arranca la deriva. Desactiva el "
        "traspaso (`tr=0`) para que el regimen no cambie a mitad de corrida.",
    )
    args = ap.parse_args()

    link = QubeLink(args.ip)
    st = link.state()
    print(f"Placa: modo={st.get('mode')} ina_ok={st.get('ina_ok')} v_bus={st.get('v_bus')}")
    if not st.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    DATA.mkdir(parents=True, exist_ok=True)

    sps = [int(v) for v in args.barrido.split(",") if v.strip()]
    plan: list[int | None] = sps if sps else [None] * args.ciclos
    if sps:
        link.send({"tr": 0})  # sin traspaso: bombeo puro de punta a punta
        print("Traspaso desactivado (tr=0) para el barrido.")

    out: list[dict] = []
    try:
        for n, sp in enumerate(plan, start=1):
            out.append(cycle(link, n, suave=args.suave, sp=sp))
            name = "alpha_drift_suave.json" if args.suave else ("alpha_drift_sp.json" if sps else "alpha_drift.json")
            (DATA / name).write_text(json.dumps(out, indent=2), encoding="utf-8")
    finally:
        link.send({"m": 0, "tr": 1, "sp": 60})  # restaurar los valores del firmware
        link.stop_motor()

    print("\n=== resumen ===")
    print(f"{'ciclo':>6} {'sp':>4} {'vel max':>9} {'vueltas':>8} {'deriva':>10} {'cuentas':>9}")
    for r in out:
        print(
            f"{r['ciclo']:>6} {r['sp'] or '-'!s:>4} {r['vel_max_dps']:>8.0f}° {r['wraps']:>8} "
            f"{r['deriva_deg']:>9.2f}° {r['deriva_cuentas']:>9}  {'' if r['valido'] else 'INVALIDA'}"
        )
    validas = [r for r in out if r["valido"]]
    if not validas:
        print("\nNinguna corrida valida: el bombeo no ocurrio en ninguna. No hay nada que concluir.")
        return 1
    derivas = [abs(r["deriva_deg"]) for r in validas]
    print(
        f"\nDeriva |media| {sum(derivas) / len(derivas):.2f}°, maxima {max(derivas):.2f}°."
        "\nCriterio: si la deriva es reproducible y >1 cuenta (0,176°), el encoder pierde"
        "\npulsos en regimen rapido y toda alpha medida en corridas energeticas queda en duda."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
