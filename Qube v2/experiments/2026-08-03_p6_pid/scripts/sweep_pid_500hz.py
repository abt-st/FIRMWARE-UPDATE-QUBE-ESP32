"""P6 / etapa 4 — Barrido del PID del modo 2, medido sobre la traza a 500 Hz.

Sucesor de ``experiments/2026-07-31_pid/scripts/sweep_pid.py``. Cambian dos cosas, y las
dos por mediciones de hoy (2026-08-03):

1. **La traza sale del DAQ a 500 Hz**, no de sondear ``/state`` a 25 Hz. El transitorio
   que decide el sobrepaso dura decimas de segundo; a 25 Hz el pico cae entre muestras.
2. **El segmento dura 14 s, no 3,5 s.** Medido hoy sobre el mismo escalon: con 5 s de
   ventana el ``sse`` da 7,7-15,9 grados y con 14 s da 2,72. El numero corto no es el
   error de regimen, es el transitorio sin terminar. Comparar tandas con ventanas
   distintas no significa nada.

Se conserva del original lo que estaba bien: repeticiones **intercaladas** para que una
deriva lenta del banco no castigue al ultimo punto, la metrica de ``hunting`` (subir el
piso del kick puede cambiar un error de regimen por un ciclo limite, que es peor), el
guardado de la traza cruda de cada punto, y restaurar los defaults del firmware al salir.

Uso:
    uv run python experiments/2026-08-03_p6_pid/scripts/sweep_pid_500hz.py --control
    uv run python experiments/2026-08-03_p6_pid/scripts/sweep_pid_500hz.py --kd 0.15,0.3,0.45,0.6
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.analysis import step_metrics
from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

#: Escalon de la etapa 4. Cruza el cero a proposito: es donde la metrica vieja de
#: sobrepaso se rompia, y donde el kick anti-friccion tiene que actuar en ambos sentidos.
SP_FROM, SP_TO = 17.0, -20.0
HOLD_FROM_S = 6.0
HOLD_TO_S = 14.0
#: Limite blando del brazo. Si se cruza, el punto se descarta y se corta.
HARD_LIMIT_DEG = 95.0


def wait_for_rest(link: QubeLink, timeout: float = 25.0) -> bool:
    """Espera que el pendulo se aquiete, por ESTABILIDAD y no por cercania a cero.

    El cero de alfa puede haberse redefinido (el swing-up y el acotado de vueltas lo
    mueven), asi que el criterio ingenuo nunca se cumple. Lanzar un escalon con el
    pendulo oscilando arrastra el brazo: costo un dato malo hoy mismo.
    """
    link.send({"m": 0})
    window: list[tuple[float, float]] = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            alpha = float(link.state(retries=1)["pend_position_deg"])
        except Exception:
            time.sleep(0.3)
            continue
        window.append((time.monotonic(), alpha))
        window = [(t, v) for t, v in window if time.monotonic() - t <= 2.5]
        if len(window) >= 8 and max(v for _, v in window) - min(v for _, v in window) < 1.5:
            return True
        time.sleep(0.15)
    return False


def hunting(t: np.ndarray, theta: np.ndarray, pwm: np.ndarray, sp: float) -> dict:
    """Actividad en regimen (ultimo 30% del segmento).

    Un lazo asentado deja de accionar. Si el brazo sigue cruzando el setpoint y el puente
    sigue conmutando, hay ciclo limite — tipicamente un kick anti-friccion demasiado alto
    que empuja, pasa, y vuelve a empujar del otro lado.
    """
    tail = slice(int(len(t) * 0.7), len(t))
    err = theta[tail] - sp
    if len(err) < 3:
        return {"cruces": 0, "pwm_activo_frac": 0.0, "pp_deg": 0.0}
    return {
        "cruces": int(np.count_nonzero(np.diff(np.signbit(err)))),
        "pwm_activo_frac": round(float(np.count_nonzero(pwm[tail])) / len(err), 3),
        "pp_deg": round(float(err.max() - err.min()), 3),
    }


def run_point(link: QubeLink, gains: dict, rep: int, tag: str) -> dict | None:
    """Un punto del barrido: fija ganancias, lanza el escalon y mide a 500 Hz."""
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    link.send(gains)  # el firmware llama resetPid() en cada cambio de ganancia

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    name = "_".join(f"{k}{v:g}" for k, v in gains.items())
    rec = Recorder(DATA / f"{tag}_{name}_r{rep}.csv")
    rec.open()
    t_mark = 0.0
    marks: list[np.ndarray] = []
    th_all: list[np.ndarray] = []
    pwm_all: list[np.ndarray] = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for chunk in stream.drain():
                rec.write(chunk)
                marks.append(chunk.t_s)
                th_all.append(chunk.th_deg)
                pwm_all.append(chunk.pwm)

    link.reset_loop_metrics()
    stream.start()
    try:
        pump(0.8)
        link.send({"m": 2, "s": SP_FROM})
        pump(HOLD_FROM_S)
        t_mark = float(marks[-1][-1]) if marks else 0.0
        link.send({"s": SP_TO})
        pump(HOLD_TO_S)
    finally:
        link.send({"m": 0})
        stream.stop()
        for chunk in stream.drain():
            rec.write(chunk)
            marks.append(chunk.t_s)
            th_all.append(chunk.th_deg)
            pwm_all.append(chunk.pwm)
        rec.close()

    if not marks:
        print("    ERROR: no llego ninguna muestra")
        return None
    t, theta, pwm = np.concatenate(marks), np.concatenate(th_all), np.concatenate(pwm_all)
    seg = t >= t_mark
    m = step_metrics(t[seg], theta[seg], setpoint_deg=SP_TO)
    if m is None:
        print("    ERROR: segmento insuficiente")
        return None

    st = link.state()
    row = {
        **gains,
        "rep": rep,
        "n": int(np.count_nonzero(seg)),
        "y0_deg": round(m.y0_deg, 2),
        "pico_deg": round(m.peak_deg, 2),
        "overshoot_pct": round(m.overshoot_pct, 1),
        "overshoot_legacy_pct": round(m.overshoot_legacy_pct, 1),
        "sse_deg": round(m.sse_deg, 2),
        "settle_s": round(m.settling_s, 2),
        **hunting(t[seg], theta[seg], pwm[seg], SP_TO),
        "hit_limit": bool(np.abs(theta).max() > HARD_LIMIT_DEG),
        "rate_hz": round(stream.stats.rate_hz, 1),
        "dropped": stream.stats.dropped,
        "loop_dt_max_us": st.get("loop_dt_max_us"),
        "loop_overruns": st.get("loop_overruns"),
    }
    print(
        f"    sobrepaso={row['overshoot_pct']:5.1f}% (legacy {row['overshoot_legacy_pct']:7.1f}%)"
        f"  sse={row['sse_deg']:5.2f}  settle={row['settle_s']:5.2f}s"
        f"  cruces={row['cruces']:3d}  pwm_act={row['pwm_activo_frac']:.2f}"
        f"  [{row['rate_hz']:.0f} Hz, perdidas {row['dropped']}]"
    )
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--kp", default="3.0")
    ap.add_argument("--ki", default="0.5")
    ap.add_argument("--kd", default="0.15")
    ap.add_argument("--se", default="2.0")
    ap.add_argument("--sk", default="30")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--tag", default="kd")
    ap.add_argument(
        "--control",
        action="store_true",
        help="Paso 4.1/4.2: kick viejo (se=8, sk=12) contra el nuevo (se=2, sk=30)",
    )
    args = ap.parse_args()

    def vals(s: str) -> list[float]:
        return [float(x) for x in s.split(",")]

    if args.control:
        base = {"kp": vals(args.kp)[0], "ki": vals(args.ki)[0], "kd": vals(args.kd)[0]}
        puntos = [{**base, "se": 8.0, "sk": 12.0}, {**base, "se": 2.0, "sk": 30.0}]
        args.tag = "control"
    else:
        puntos = [
            {"kp": kp, "ki": vals(args.ki)[0], "kd": kd, "se": vals(args.se)[0], "sk": sk}
            for kp in vals(args.kp)
            for kd in vals(args.kd)
            for sk in vals(args.sk)
        ]

    link = QubeLink(args.ip)
    st = link.state()
    print(f"Placa: modo={st.get('mode')} ina_ok={st.get('ina_ok')} v_bus={st.get('v_bus')}")
    if not st.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if not st.get("homing_ok"):
        raise SystemExit(
            "Sin homing valido: el cero del brazo es arbitrario y el limite de +-95 cae en cualquier parte."
        )
    DATA.mkdir(parents=True, exist_ok=True)

    out: list[dict] = []
    try:
        for rep in range(1, args.reps + 1):
            for p in puntos:
                print(f"\n--- {' '.join(f'{k}={v:g}' for k, v in p.items())} · rep {rep} ---")
                row = run_point(link, p, rep, args.tag)
                if row is None:
                    continue
                if row["hit_limit"]:
                    print("    LIMITE DEL BRAZO TOCADO — se corta el barrido")
                    out.append(row)
                    raise SystemExit(1)
                out.append(row)
                (DATA / f"sweep_{args.tag}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    finally:
        # No dejar el banco con lo ultimo barrido ni el motor energizado.
        link.send({"m": 0, "kp": 3.0, "ki": 0.5, "kd": 0.15, "se": 2.0, "sk": 30})
        link.stop_motor()

    print("\n=== resumen (mediana de las repeticiones) ===")
    print(f"{'punto':>34} {'n':>2} {'sobrepaso %':>12} {'sse':>7} {'settle':>7} {'cruces':>7} {'pwm act':>8}")
    for p in puntos:
        g = [r for r in out if all(r.get(k) == v for k, v in p.items())]
        if not g:
            continue
        name = " ".join(f"{k}={v:g}" for k, v in p.items())
        print(
            f"{name:>34} {len(g):>2} {statistics.median(r['overshoot_pct'] for r in g):>11.1f}"
            f" {statistics.median(r['sse_deg'] for r in g):>7.2f}"
            f" {statistics.median(r['settle_s'] for r in g):>7.2f}"
            f" {max(r['cruces'] for r in g):>7}"
            f" {max(r['pwm_activo_frac'] for r in g):>8.2f}"
        )
    print("\nCriterio P6: sobrepaso < 20% sin degradar sse ni disparar hunting")
    print("(cruces altos + pwm activo ~1,0 en regimen = ciclo limite, y eso es peor que el error).")


if __name__ == "__main__":
    main()
