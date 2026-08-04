"""m5 — swing-up medido a 500 Hz, separando la fase de bombeo de la del LQR.

Por que hacia falta. Las campanas previas reportaban `hit_servo_limit` mirando el
`theta` maximo de TODO el episodio, que incluye lo que pasa DESPUES del traspaso. Y P4
tiene documentado que el LQR se fuga al tope. Con eso, un tope tocado por el LQR se
contabilizaba contra el swing-up: P12 podia estar sobreestimado desde el principio.

El DAQ trae `mode` por muestra, asi que aca la separacion es exacta y a 500 Hz:

    theta_max_m5  -> lo que hace el BOMBEO      (P12 de verdad)
    theta_max_m4  -> lo que hace el LQR despues (P4, no es asunto de m5)

Criterio de m5 funcional (escrito antes de medir), n=5:

  1. **Entrega**: traspasa a m4 con |alpha| >= 165 en >= 4 de 5 intentos.
  2. **Calidad de la entrega**: E/E* en [0,95, 1,05] en los intentos que traspasan.
  3. **P12**: el brazo NO supera SERVO_HARD_LIMIT_DEG (95) *durante la fase de bombeo*
     en >= 4 de 5. Lo que haga despues del traspaso es P4.

`al_deg` llega SIN envolver, asi que el pico se calcula acotando UNA vez sobre el array
entero — no muestra a muestra, que es donde P14 encontro cuatro compuertas comparando un
angulo sin acotar.

Contrato del firmware: un solo consumidor de /daq/read. No correr con la GUI abierta.

Uso:
    uv run python m5_daq.py --reps 5
    uv run python m5_daq.py --reps 5 --sp 55      # barrer el PWM de bombeo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

SERVO_LIMIT_DEG = 95.0
TRANS_ALPHA_MIN = 165.0
REASON_BITS = {0x01: "near+slow", 0x02: "peak", 0x04: "forced", 0x08: "energy"}


def decode_reason(mask: int) -> str:
    return "+".join(n for b, n in REASON_BITS.items() if mask & b) or "-"


def wait_for_rest(link: QubeLink, timeout: float = 25.0, tol: float = 0.5) -> bool:
    link.send({"m": 0})
    end = time.perf_counter() + timeout
    prev, stable = None, 0
    while time.perf_counter() < end:
        a = float(link.state().get("pend_position_deg", 0.0))
        if prev is not None and abs(a - prev) < tol:
            stable += 1
            if stable >= 8:
                return True
        else:
            stable = 0
        prev = a
        time.sleep(0.15)
    return False


def homing(link: QubeLink, timeout: float = 30.0) -> dict:
    link.send({"m": 3})
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        d = link.state()
        if d.get("homing_phase") == "DONE":
            return d
        if d.get("homing_phase") == "FAIL":
            raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
        time.sleep(0.2)
    raise RuntimeError("homing timeout")


def attempt(link: QubeLink, rep: int, max_s: float, sp: int | None,
            settle: bool = False, zero: bool = False, settle_timeout: float = 20.0) -> dict | None:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    h = homing(link)
    # P22: entre el homing y el `m=5` NO habia ninguna espera. El homing golpea el brazo
    # contra los dos topes y eso deja al pendulo oscilando; los intentos que resuelven el
    # swing-up en 1,0-1,5 s estan rematando esa energia, no bombeando desde cero.
    # `settle` la elimina para poder medir el swing-up honesto — y es el arreglo candidato.
    alpha_at_start = None
    if settle:
        wait_for_rest(link, timeout=settle_timeout)
    if zero:
        # `zp=1` re-establece la referencia del pendulo AQUI. Solo es valido con el
        # pendulo fisicamente colgando y quieto, que es lo que garantiza el settle de
        # arriba. Sin esto la referencia deriva: medido el 2026-08-04, un pendulo en
        # reposo verificado leia 82,62 / 97,38 / 91,06 y una vez -264,02 grados, cuando
        # colgando tiene que leer 0. El firmware usa alpha para la energia, las cuatro
        # compuertas de traspaso y el techo de P18: con la referencia corrida, el bombeo
        # trabaja contra un angulo que no es el real.
        link.send({"zp": 1})
        time.sleep(0.2)
    st0 = link.state()
    alpha_at_start = float(st0.get("pend_position_deg", 0.0))
    if sp is not None:
        link.send({"sp": sp})

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"m5_sp{sp if sp is not None else 0}{'_zero' if zero else ('_settle' if settle else '')}_r{rep}.csv")
    rec.open()
    parts: list[tuple[np.ndarray, ...]] = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for c in stream.drain():
                rec.write(c)
                parts.append((c.t_s, c.th_deg, c.al_deg, c.pwm, c.mode))

    link.reset_loop_metrics()
    stream.start()
    try:
        pump(0.5)
        link.send({"m": 5})
        pump(max_s)
    finally:
        link.send({"m": 0})
        stream.stop()
        for c in stream.drain():
            rec.write(c)
            parts.append((c.t_s, c.th_deg, c.al_deg, c.pwm, c.mode))
        rec.close()

    if not parts:
        print("    ERROR: no llego ninguna muestra")
        return None
    t = np.concatenate([p[0] for p in parts])
    th = np.concatenate([p[1] for p in parts])
    al = np.concatenate([p[2] for p in parts])
    mode = np.concatenate([p[4] for p in parts])

    in5 = mode == 5
    in4 = mode == 4
    # Acotar UNA vez sobre el array entero, no muestra a muestra (leccion de P14).
    al_wrapped = np.abs((al + 180.0) % 360.0 - 180.0)

    st = link.state()
    mask = int(st.get("swing_trans_reason") or 0)
    trans = None
    if mask:
        trans = {
            "reason": decode_reason(mask),
            "alpha_deg": float(st["swing_trans_alpha"]),
            "vel_dps": float(st["swing_trans_vel"]),
            "energy_ratio": float(st["swing_trans_energy"]),
        }

    return {
        "rep": rep,
        "sp": sp if sp is not None else st.get("swingup_pwm_max"),
        "homing_range": round(float(h.get("homing_range", 0.0)), 2),
        "settled_after_homing": bool(settle),
        "alpha_at_start_deg": round(alpha_at_start, 2),
        "samples": int(t.size),
        "rate_hz": round(float(t.size / max(t[-1] - t[0], 1e-9)), 1),
        "t_in_m5_s": round(float(in5.sum()) / 500.0, 2),
        "t_in_m4_s": round(float(in4.sum()) / 500.0, 2),
        "alpha_peak_m5_deg": round(float(al_wrapped[in5].max()) if in5.any() else 0.0, 1),
        # LA distincion que motiva este script:
        "theta_max_m5_deg": round(float(np.abs(th[in5]).max()) if in5.any() else 0.0, 1),
        "theta_max_m4_deg": round(float(np.abs(th[in4]).max()) if in4.any() else 0.0, 1),
        "limit_hit_in_m5": bool(in5.any() and np.abs(th[in5]).max() > SERVO_LIMIT_DEG),
        "limit_hit_in_m4": bool(in4.any() and np.abs(th[in4]).max() > SERVO_LIMIT_DEG),
        "handed_off": bool(in4.any()),
        "pend_wraps": st.get("pend_wraps"),
        "ceiling_hits": st.get("swing_ceiling_hits"),
        "loop_overruns": st.get("loop_overruns"),
        "transition": trans,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-s", type=float, default=18.0)
    ap.add_argument("--sp", type=int, default=None, help="swingupPwmMax (def: el del firmware)")
    ap.add_argument(
        "--zero",
        action="store_true",
        help="llamar zp=1 tras el settle para re-establecer la referencia del pendulo. "
        "Implica --settle: solo es valido con el pendulo colgando y quieto",
    )
    ap.add_argument(
        "--settle",
        action="store_true",
        help="esperar reposo del pendulo DESPUES del homing (P22). Sin esto, el swing-up "
        "arranca con la energia residual que dejo el homing al golpear los topes",
    )
    args = ap.parse_args()
    if args.zero:
        args.settle = True  # zp=1 sin reposo verificado fija un cero equivocado

    link = QubeLink(args.ip)
    d = link.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")

    DATA.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for rep in range(1, args.reps + 1):
            print(f"\n--- intento {rep}/{args.reps} ---")
            try:
                r = attempt(link, rep, args.max_s, args.sp, settle=args.settle, zero=args.zero)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                link.send({"m": 0})
                continue
            if r is None:
                continue
            tr = r["transition"]
            ent = (
                f"alpha={tr['alpha_deg']:.1f} E/E*={tr['energy_ratio']:.3f} ({tr['reason']})"
                if tr
                else "SIN TRASPASO"
            )
            print(
                f"  pico_m5={r['alpha_peak_m5_deg']:.1f}deg  theta_m5={r['theta_max_m5_deg']:.1f}"
                f"  theta_m4={r['theta_max_m4_deg']:.1f}  [{r['rate_hz']:.0f} Hz]"
            )
            print(f"  entrega: {ent}")
            rows.append(r)
    finally:
        link.send({"m": 0})

    (DATA / f"m5_sp{args.sp if args.sp is not None else 0}{'_zero' if args.zero else ('_settle' if args.settle else '')}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    if not rows:
        return
    n = len(rows)
    c1 = sum(r["handed_off"] and r["transition"] and abs(r["transition"]["alpha_deg"]) >= TRANS_ALPHA_MIN for r in rows)
    ok_e = [r for r in rows if r["transition"] and 0.95 <= r["transition"]["energy_ratio"] <= 1.05]
    c3 = sum(not r["limit_hit_in_m5"] for r in rows)
    print(f"\n=== criterio de m5 (n={n}) ===")
    print(f"  1. entrega con |alpha| >= {TRANS_ALPHA_MIN:.0f}: {c1}/{n}  {'PASS' if c1 >= 4 else 'FAIL'}")
    print(f"  2. E/E* en [0,95, 1,05]:          {len(ok_e)}/{n}  {'PASS' if len(ok_e) >= 4 else 'FAIL'}")
    print(f"  3. sin tocar el tope EN BOMBEO:   {c3}/{n}  {'PASS' if c3 >= 4 else 'FAIL'}")
    print()
    print(f"  theta max en BOMBEO (m5): {sorted(r['theta_max_m5_deg'] for r in rows)}")
    print(f"  theta max tras traspaso : {sorted(r['theta_max_m4_deg'] for r in rows)}")
    print(f"  picos |alpha| en m5     : {sorted(r['alpha_peak_m5_deg'] for r in rows)}")
    hits5 = sum(r["limit_hit_in_m5"] for r in rows)
    hits4 = sum(r["limit_hit_in_m4"] for r in rows)
    print(f"\n  tope tocado en bombeo: {hits5}/{n}   tras el traspaso: {hits4}/{n}")
    if hits4 > hits5:
        print("  >> El tope lo toca el LQR, no el bombeo: eso es P4, no P12.")


if __name__ == "__main__":
    main()
