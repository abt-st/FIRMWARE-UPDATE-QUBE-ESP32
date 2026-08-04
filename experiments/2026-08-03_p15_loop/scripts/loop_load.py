"""P15 — ¿Por que el lazo deja de producir muestras con el motor en marcha?

Medido el 2026-08-03: en reposo el DAQ entrega 500,1 Hz con 0 perdidas, y con el swing-up
bombeando cae a 256-330 Hz con paradas de hasta 488 ms. `dropped = 0` en ambos casos, y
ese contador lo lleva el firmware: significa que el PC vacio el buffer siempre y que **las
muestras que faltan nunca se produjeron**. No es el enlace, es el lazo parandose.

Este script separa las causas candidatas. El criterio se escribe ANTES de medir:

- Si **`m1_osc`** (motor conmutando, sin lazo de control de interes) tambien colapsa, la
  causa esta del lado del motor —consumo, ruido de conmutacion, el I2C del INA219 bajo ese
  ruido— y **no** en el codigo del swing-up.
- Si solo colapsa **`m5`**, es el costo del propio lazo de bombeo.
- Si `sv0` (linea serial apagada) o `tp1000` (telemetria diezmada) recuperan la tasa, el
  culpable es un costo de comunicaciones dentro del `loop()`, no el control.

Se registra ademas la corriente del INA219 durante cada corrida: si las paradas coinciden
con los picos, apunta a alimentacion y no a software.

Uso:
    uv run python experiments/2026-08-03_p15_loop/scripts/loop_load.py --gui --reps 3
    uv run python experiments/2026-08-03_p15_loop/scripts/loop_load.py --reps 3       # sin GUI
    uv run python experiments/2026-08-03_p15_loop/scripts/loop_load.py --gui --only m5,m5_sv0

Con ``--gui`` el protocolo corre DENTRO de la app de escritorio y se ve la traza a 500 Hz
mientras se mide. No es un lujo: el firmware admite **un solo consumidor** de ``/daq/read``
y responde 503 al segundo, asi que abrir la app por un lado y el script por otro dejaria a
uno de los dos sin datos. La app es la que posee el flujo; el protocolo va montado encima.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.analysis import wrap_deg
from qube_app.buffers import TraceStore
from qube_app.link import QubeLink
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"
RUN_S = 15.0
SETTLE_TIMEOUT_S = 25.0

#: Vaiven de `m1_osc`. Medido en banco: un pulso de 250 ms a PWM 40 mueve el brazo hasta
#: 40 grados, asi que el pulso tiene que ser corto y el PWM moderado.
OSC_PWM = 35
OSC_TICK_S = 0.15
#: Fuera de esta banda el pulso siempre apunta al centro.
OSC_BAND_DEG = 20.0
#: Mas alla de esto se aborta la condicion entera y no se vuelve a accionar.
OSC_ABORT_DEG = 45.0


# ── Condiciones ───────────────────────────────────────────────────────────────
# Una condicion no habla con la placa: **emite comandos**. Quien los entrega es el
# transporte — el enlace directo sin GUI, o la cola del sondeo cuando corre dentro de la
# app. Asi el protocolo es uno solo y no hay dos versiones que se desincronicen.


class Condition:
    tick_s = 0.5

    def __init__(self, name: str, setup: dict | None = None, note: str = "") -> None:
        self.name = name
        self.setup = setup or {}
        self.note = note

    def setup_cmd(self) -> dict | None:
        return dict(self.setup) or None

    def tick_cmd(self, state: dict) -> dict | None:  # noqa: ARG002
        return None


class Oscillate(Condition):
    """`m1` con PWM alternado: el motor conmuta sin que corra ningun lazo de control.

    El watchdog de comandos del firmware SI cubre el modo 1 (2,5 s), asi que los envios
    periodicos hacen falta de todas formas.

    **Dos reglas de seguridad que esta clase aprendio a golpes (2026-08-04).**

    1. *La posicion tiene que ser fresca.* La primera version decidia la direccion con el
       `position_deg` de `/state`, que se sondea a 2 Hz. Un pulso de 250 ms a PWM 40 mueve
       el brazo hasta 40 grados, asi que con 500 ms de atraso se decide a ciegas sobre ~80
       grados de movimiento. Ahora la posicion llega del flujo del DAQ, a 500 Hz.
       (El sentido en si estaba bien y se re-verifico en banco: `p=+40` BAJA `position_deg`,
       `p=-40` la sube.)
    2. *Si la proteccion del firmware dispara, se aborta.* Cuando el brazo cruza
       `SERVO_HARD_LIMIT_DEG` el firmware hace `setMode(0)`. La primera version volvia a
       mandar `m=1` en el tick siguiente —cinco veces por segundo— y el resultado era el
       brazo empujando contra el tope mecanico con la proteccion disparando y
       re-armandose. **Una proteccion que el cliente re-arma no es una proteccion.**
    """

    tick_s = OSC_TICK_S

    def __init__(self, name: str, setup: dict | None = None, note: str = "") -> None:
        super().__init__(name, setup, note)
        self._flip = False
        self._aborted = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    def tick_cmd(self, state: dict) -> dict | None:
        if self._aborted:
            return None
        theta = state.get("position_deg")
        if theta is None:
            return None  # sin posicion fresca no se acciona
        theta = float(theta)
        if abs(theta) > OSC_ABORT_DEG:
            self._aborted = True
            print(f"    ABORTADO: el brazo llego a {theta:+.1f}deg, fuera de la banda segura")
            return {"m": 0}
        if abs(theta) > OSC_BAND_DEG:
            # `p` positivo BAJA position_deg (medido): se apunta al centro.
            pwm = OSC_PWM if theta > 0 else -OSC_PWM
        else:
            self._flip = not self._flip
            pwm = OSC_PWM if self._flip else -OSC_PWM
        return {"m": 1, "p": pwm}


def build_conditions() -> dict[str, Condition]:
    return {
        "reposo": Condition("reposo", note="motor energizado pero quieto; linea base"),
        "m1_osc": Oscillate("m1_osc", note="motor conmutando, sin lazo de control"),
        "m2_step": Condition("m2_step", {"m": 2, "s": 20.0}, note="lazo cerrado, movimiento suave"),
        "m5": Condition("m5", {"m": 5}, note="swing-up: donde aparecio"),
        "m5_sv0": Condition("m5_sv0", {"sv": 0, "m": 5}, note="swing-up con la linea serial apagada"),
        "m5_tp1000": Condition("m5_tp1000", {"tp": 1000, "m": 5}, note="swing-up con telemetria diezmada"),
    }


# ── Metricas ──────────────────────────────────────────────────────────────────


def metrics_from(name: str, rep: int, t: np.ndarray, stats, currents: list[float], st: dict) -> dict:
    dt_ms = np.diff(t) * 1000.0 if len(t) > 1 else np.zeros(0)
    long_stops = dt_ms[dt_ms > 20.0] if len(dt_ms) else np.zeros(0)
    return {
        "cond": name,
        "rep": rep,
        "muestras": len(t),
        "rate_hz": round(float(len(t) - 1) / float(t[-1] - t[0]), 1) if len(t) > 1 else 0.0,
        "dt_med_ms": round(float(np.median(dt_ms)), 3) if len(dt_ms) else None,
        "dt_max_ms": round(float(dt_ms.max()), 1) if len(dt_ms) else None,
        # Paradas largas: cuantas, y cuanto tiempo total se perdio en ellas.
        "paradas_20ms": len(long_stops),
        "tiempo_en_paradas_s": round(float(long_stops.sum()) / 1000.0, 3),
        "dropped": getattr(stats, "dropped", None),
        "i_ma_med": round(statistics.median(currents), 1) if currents else None,
        "i_ma_max": round(max(currents), 1) if currents else None,
        "loop_dt_max_us": st.get("loop_dt_max_us"),
        "loop_overruns": st.get("loop_overruns"),
    }


def describe(row: dict) -> str:
    return (
        f"{row['rate_hz']:6.1f} Hz  dt_max {row['dt_max_ms']:>7} ms"
        f"  paradas>20ms {row['paradas_20ms']:>3} ({row['tiempo_en_paradas_s']:.2f} s)"
        f"  perdidas {row['dropped']}  I {row['i_ma_med']}/{row['i_ma_max']} mA"
        f"  loop_dt_max {row['loop_dt_max_us']} overruns {row['loop_overruns']}"
    )


def write_trace(path: Path, store: TraceStore) -> None:
    """Vuelca la ventana en el esquema canonico del proyecto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t, th, al, pwm, mode = (store[k] for k in ("t_s", "th_deg", "al_deg", "pwm", "mode"))
    wrapped = wrap_deg(al)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(("t_s", "theta_deg", "alpha_deg", "alpha_raw_deg", "pwm", "mode"))
        w.writerows(
            [f"{t[i]:.6f}", f"{th[i]:.4f}", f"{wrapped[i]:.4f}", f"{al[i]:.4f}", int(pwm[i]), int(mode[i])]
            for i in range(len(t))
        )


def summarize(out: list[dict], names: list[str]) -> None:
    print("\n=== resumen (mediana de las repeticiones) ===")
    print(
        f"{'condicion':>12} {'n':>2} {'Hz':>7} {'dt max ms':>10} {'paradas':>8}"
        f" {'t parado':>9} {'perdidas':>9} {'I max':>7}"
    )
    for name in names:
        g = [r for r in out if r["cond"] == name]
        if not g:
            continue
        print(
            f"{name:>12} {len(g):>2} {statistics.median(r['rate_hz'] for r in g):>7.1f}"
            f" {max(r['dt_max_ms'] or 0 for r in g):>10.1f}"
            f" {statistics.median(r['paradas_20ms'] for r in g):>8.0f}"
            f" {statistics.median(r['tiempo_en_paradas_s'] for r in g):>9.2f}"
            f" {max(r['dropped'] or 0 for r in g):>9}"
            f" {max(r['i_ma_max'] or 0 for r in g):>7.0f}"
        )
    print("\nCriterio: si m1_osc tambien colapsa, la causa es el motor y no el lazo de swing-up.")
    print("Si sv0 o tp1000 recuperan la tasa, es un costo de comunicaciones dentro del loop().")


def with_fresh_theta(state: dict, store: TraceStore) -> dict:
    """Reemplaza `position_deg` por la ultima muestra del DAQ.

    `/state` se sondea a 2 Hz; el DAQ entrega a 500 Hz. Para decidir si accionar el motor
    hay que mirar donde esta el brazo AHORA, no donde estaba hace medio segundo.
    """
    if not len(store):
        return state
    fresh = dict(state)
    fresh["position_deg"] = float(store["th_deg"][-1])
    return fresh


def is_quiet(window: list[tuple[float, float]]) -> bool:
    """Reposo por ESTABILIDAD, no por cercania a cero: el cero de alfa puede haberse
    redefinido y el criterio ingenuo no se cumple nunca."""
    return len(window) >= 6 and (max(v for _, v in window) - min(v for _, v in window) < 1.5)


# ── Modo sin GUI ──────────────────────────────────────────────────────────────


def run_headless(ip: str, names: list[str], reps: int) -> int:
    link = QubeLink(ip)
    conds = build_conditions()
    out: list[dict] = []
    try:
        for rep in range(1, reps + 1):
            for name in names:
                cond = conds[name]
                print(f"\n--- {name} · rep {rep} --- {cond.note}")
                out.append(run_once_headless(link, cond, rep))
                (DATA / "loop_load.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    finally:
        link.send({"m": 0, "sv": 1, "tp": 100})
        link.stop_motor()
    summarize(out, names)
    return 0


def run_once_headless(link: QubeLink, cond: Condition, rep: int) -> dict:
    link.send({"m": 0, "sv": 1, "tp": 100})
    window: list[tuple[float, float]] = []
    end = time.monotonic() + SETTLE_TIMEOUT_S
    while time.monotonic() < end:
        try:
            alpha = float(link.state(retries=1)["pend_position_deg"])
        except Exception:
            time.sleep(0.3)
            continue
        now = time.monotonic()
        window.append((now, alpha))
        window = [(t, v) for t, v in window if now - t <= 2.5]
        if is_quiet(window):
            break
        time.sleep(0.15)

    link.reset_loop_metrics()
    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    store = TraceStore(window_s=RUN_S + 5.0, rate_hz=500.0)
    currents: list[float] = []
    stream.start()
    if (cmd := cond.setup_cmd()) is not None:
        link.send(cmd)
    stop_at, next_tick = time.perf_counter() + RUN_S, 0.0
    try:
        while time.perf_counter() < stop_at:
            time.sleep(0.05)
            for chunk in stream.drain():
                store.extend(chunk)
            if time.monotonic() >= next_tick:
                next_tick = time.monotonic() + cond.tick_s
                try:
                    st = link.state(retries=1)
                    currents.append(float(st.get("i_ma") or 0.0))
                    if (cmd := cond.tick_cmd(with_fresh_theta(st, store))) is not None:
                        link.send(cmd)
                except Exception:
                    pass
    finally:
        link.send({"m": 0})
        stats = stream.stats
        stream.stop()
        for chunk in stream.drain():
            store.extend(chunk)
        link.send({"sv": 1, "tp": 100})

    row = metrics_from(cond.name, rep, store["t_s"], stats, currents, link.state())
    write_trace(DATA / f"{cond.name}_r{rep}.csv", store)
    print("    " + describe(row))
    return row


# ── Modo con GUI ──────────────────────────────────────────────────────────────


def run_in_gui(ip: str, names: list[str], reps: int) -> int:
    """Corre el protocolo dentro de la app, para ver la traza mientras se mide.

    Todo ocurre en el hilo de Qt sobre un temporizador y **sin una sola llamada
    bloqueante**: los comandos se encolan en el sondeo y el reposo se evalua sobre el
    ultimo `/state` que ese mismo sondeo ya trajo. Un `time.sleep` aca congelaria la
    interfaz justo cuando se la quiere mirar.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from qube_app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(ip=ip, fake=False)
    win.show()

    conds = build_conditions()
    plan = [(name, rep) for rep in range(1, reps + 1) for name in names]
    out: list[dict] = []
    ctx: dict = {"i": 0, "phase": "settle", "until": 0.0, "next_tick": 0.0, "win": [], "i_ma": []}

    def banner(text: str) -> None:
        win.status.setText(text)
        print(text)

    def step() -> None:
        if ctx["i"] >= len(plan):
            (DATA / "loop_load.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
            win.poller.submit(m=0, sv=1, tp=100)
            summarize(out, names)
            timer.stop()
            QTimer.singleShot(800, win.close)
            return

        name, rep = plan[ctx["i"]]
        cond = conds[name]
        now = time.monotonic()
        st = win.poller.latest

        if ctx["phase"] == "settle":
            if not ctx["win"]:
                banner(f"[{ctx['i'] + 1}/{len(plan)}] {name} rep {rep} — esperando reposo…")
                win.poller.submit(m=0, sv=1, tp=100)
                ctx["until"] = now + SETTLE_TIMEOUT_S
            if (alpha := st.get("pend_position_deg")) is not None:
                ctx["win"].append((now, float(alpha)))
                ctx["win"] = [(t, v) for t, v in ctx["win"] if now - t <= 2.5]
            if is_quiet(ctx["win"]) or now > ctx["until"]:
                ctx["win"] = []
                ctx["phase"] = "arm"
            return

        if ctx["phase"] == "arm":
            win.poller.submit(rj=1)
            win.session.btn_stream.setChecked(True)  # la app arranca SU flujo: un consumidor
            if (cmd := cond.setup_cmd()) is not None:
                win.poller.submit(**cmd)
            ctx.update(until=now + RUN_S, next_tick=now, phase="run", i_ma=[])
            banner(f"[{ctx['i'] + 1}/{len(plan)}] {name} rep {rep} — midiendo {RUN_S:.0f} s… ({cond.note})")
            return

        if now >= ctx["next_tick"]:
            ctx["next_tick"] = now + cond.tick_s
            ctx["i_ma"].append(float(st.get("i_ma") or 0.0))
            if (cmd := cond.tick_cmd(with_fresh_theta(st, win.store))) is not None:
                win.poller.submit(**cmd)
        if now < ctx["until"]:
            return

        stats = win.stream.stats if win.stream else None
        win.poller.submit(m=0)
        row = metrics_from(name, rep, win.store["t_s"].copy(), stats, ctx["i_ma"], st)
        write_trace(DATA / f"{name}_r{rep}.csv", win.store)
        win.session.btn_stream.setChecked(False)
        out.append(row)
        print("    " + describe(row))
        ctx.update(i=ctx["i"] + 1, phase="settle")

    timer = QTimer()
    timer.timeout.connect(step)
    timer.start(100)
    app.exec()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", default="", help="lista separada por comas de condiciones a correr")
    ap.add_argument("--gui", action="store_true", help="correr el protocolo dentro de la app")
    args = ap.parse_args()

    conds = build_conditions()
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(conds)
    if unknown := [n for n in names if n not in conds]:
        raise SystemExit(f"condiciones desconocidas: {unknown}. Disponibles: {list(conds)}")

    link = QubeLink(args.ip)
    st = link.state()
    print(f"Placa: modo={st.get('mode')} ina_ok={st.get('ina_ok')} v_bus={st.get('v_bus')}")
    if not st.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if not st.get("homing_ok"):
        raise SystemExit("Sin homing valido: el limite de +-95 grados cae en un punto arbitrario.")
    link.close()
    DATA.mkdir(parents=True, exist_ok=True)

    return run_in_gui(args.ip, names, args.reps) if args.gui else run_headless(args.ip, names, args.reps)


if __name__ == "__main__":
    sys.exit(main())
