"""Barrido de K2 (ganancia de alpha) a autoridad alta — H5, lo ultimo que queda de P4.

Estado tras 55 corridas el 2026-08-05: H1, H2, H7 y H3-como-causa descartadas con medicion.
Lo que quedo en pie es un hecho incomodo: **la salida esta contra su techo el 98% del tiempo
a CUALQUIER autoridad** (70, 100, 130 y 150 dan todos ~98%). El LQR no es un LQR: es un rele.

La causa es la escala de K2 frente al error tipico. La region lineal es `lpm / K2`:

    K2=  8, lpm=150  ->  18.8 deg    (mas ancha que el error de entrega)
    K2= 22, lpm=150  ->   6.8 deg    (el actual)
    K2= 60, lpm=150  ->   2.5 deg
    K2=148, lpm=150  ->   1.0 deg    (el que pide el CARE)

Con entregas de 3 a 15 grados de error, K2=22 esta saturado casi siempre — que es lo medido.
**K2=8 seria el primer lazo de este proyecto que corre dentro de su region lineal.**

Y el CARE apunta al otro lado: pide K2 = 148.7 (en unidades del firmware), o sea AUN mas
rele. Las dos lecturas son plausibles y el barrido las separa, que es para lo que sirve.

LO QUE ESTA TANDA NO TOCA: **los signos de K1 y K3.** El firmware niega las dos velocidades
(`:3553-3554`); para alpha la doble negacion se cancela pero para theta no, asi que K3
entraria con el signo opuesto al del CARE. Eso es lectura de codigo —el mismo tipo de
razonamiento que ya fallo hoy con H7— y un signo mal a esta autoridad no es un experimento
fallido sino el motor empujando el pendulo hacia abajo a fondo. Va en su propia tanda.

Uso:
    uv run python k2_sweep.py --reps 5
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m4_daq import (
    BROWNOUT_CUT_V,
    BROWNOUT_DERATE_V,
    analyse,
    decode_reason,
    homing,
    wait_for_rest,
)

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

# Ascendente a proposito: la rep 1 va de lo suave a lo agresivo y se puede cortar mirandola.
K2_LEVELS = [8, 22, 60, 148]  # 22 = el del firmware y control; 148 = el que pide el CARE
K2_CONTROL = 22
LPM = 150  # fijo en los cuatro: el CARE supone autoridad amplia, y a 70 no se probaria nada
TN = 162
LC_MS = 400
# Los tres tiers de gain scheduling se igualan a K2: si `lqr2n`/`lqr2vn` quedaran en sus
# defaults (30 y 55), cerca de la vertical correria SIEMPRE el mismo K2 y el barrido no
# mediria nada justo donde importa.
NEAR_MULT, VERY_NEAR_MULT = 30.0 / 22.0, 55.0 / 22.0


def attempt(link: QubeLink, k2: int, rep: int, max_s: float) -> dict:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    homing(link)
    link.send({
        "lqr2": k2,
        "lqr2n": round(k2 * NEAR_MULT, 1),
        "lqr2vn": round(k2 * VERY_NEAR_MULT, 1),
        "lpm": LPM, "tn": TN, "lc": LC_MS, "cg": 1,
    })
    time.sleep(0.1)
    st0 = link.state()
    if int(st0.get("lqr_pwm_max", -1)) != LPM:
        raise RuntimeError(f"lqr_pwm_max={st0.get('lqr_pwm_max')}, se pidio {LPM}")

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"k2_{k2}_r{rep}.csv")
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

    th = np.concatenate([p[1] for p in parts])
    al = np.concatenate([p[2] for p in parts])
    pwm = np.concatenate([p[3] for p in parts])
    mode = np.concatenate([p[4] for p in parts])

    st = link.state()
    mask = int(st.get("swing_trans_reason") or 0)
    row: dict = {
        "k2": k2, "rep": rep, "lpm": LPM, "tn": TN,
        "region_lineal_deg": round(LPM / k2, 2),
        "alive_ms": int(st.get("lqr_alive_ms") or 0),
        "v_bus_after": float(st.get("v_bus") or 0.0),
        "trans_reason": decode_reason(mask) if mask else None,
        "loop_overruns": st.get("loop_overruns"),
    }
    row.update(analyse(th, al, pwm, mode, LC_MS, pwm_max=LPM))
    row["t_loss_eff_ms"] = (
        0.0
        if not row.get("handed_off")
        else (row["t_in_m4_s"] * 1000.0 if row.get("t_loss_ms") is None else row["t_loss_ms"])
    )
    return row


def veredicto(rows: list[dict]) -> None:
    print(f"\n=== barrido de K2 (n={len(rows)}, lpm={LPM} y tn={TN} fijos) ===")
    print(f"\n{'K2':>5} {'lineal':>7} {'traspasa':>9} {'t_loss med':>11} {'saturacion':>11} "
          f"{'theta max':>10} {'err entrega':>12}")
    res = {}
    for k2 in K2_LEVELS:
        g = [r for r in rows if r["k2"] == k2]
        if not g:
            continue
        ho = [r for r in g if r.get("handed_off")]
        if not ho:
            print(f"{k2:>5} {LPM / k2:>7.1f} {0}/{len(g):<7}  (ningun traspaso)")
            continue
        eff = [r["t_loss_eff_ms"] for r in g]
        sat = [r["sat_frac"] for r in ho if r["sat_frac"] is not None]
        res[k2] = {"n": len(g), "ho": len(ho), "t": statistics.median(eff),
                   "sat": statistics.median(sat) if sat else None,
                   "th": statistics.median([r["theta_max_m4_deg"] for r in ho]),
                   "err": statistics.median([r["alpha_err_at_handoff_deg"] for r in ho])}
        s = res[k2]
        print(f"{k2:>5} {LPM / k2:>7.1f} {len(ho)}/{len(g):<7} {s['t']:>11.0f} "
              f"{(f'{s[chr(115) + chr(97) + chr(116)]:.1%}' if s['sat'] else '-'):>11} "
              f"{s['th']:>10.1f} {s['err']:>12.1f}")
        print(f"      {'':7} {'':9} {sorted(eff)!s:>11}")

    base = res.get(K2_CONTROL)
    if not base:
        print(f"\n  sin control (K2={K2_CONTROL}): no se evalua")
        return

    # 1. El control tiene que reproducir la celda lpm=150 del barrido anterior de la MISMA
    #    sesion (mediana 60 ms, rango 12-70). Es la unica referencia valida: hoy quedo
    #    demostrado que entre tandas separadas por una hora las entregas derivan.
    print(f"\n  1. control K2={K2_CONTROL} reproduce la celda lpm=150 (mediana 60 ms): "
          f"{base['t']:.0f} ms  {'OK' if 20 <= base['t'] <= 110 else 'FUERA DE RANGO'}")

    # 2. El mando tiene que salir de la saturacion en ALGUN nivel. Si los cuatro siguen al
    #    98%, K2 tampoco es la variable y el rele viene de otro lado.
    sats = [(k, s["sat"]) for k, s in sorted(res.items()) if s["sat"] is not None]
    if sats:
        min_k, min_s = min(sats, key=lambda x: x[1])
        print(f"  2. sale de la saturacion: {' -> '.join(f'{s:.0%}' for _, s in sats)}  "
              f"minimo {min_s:.1%} en K2={min_k}  {'SI' if min_s < 0.80 else 'NO'}")
        if min_s >= 0.80:
            print("     Ningun K2 saca al lazo del tope: el rele no viene de esta ganancia.")

    # 3. H5: algun nivel mejora t_loss por factor 2 sobre el control.
    mejor = max(res.items(), key=lambda kv: kv[1]["t"])
    f = mejor[1]["t"] / max(base["t"], 1.0)
    print(f"  3. H5 — mejor K2={mejor[0]} con {mejor[1]['t']:.0f} ms  (x{f:.2f} sobre el "
          f"control, hace falta x2)")
    print(f"     {'CONFIRMADA' if f >= 2.0 else 'NO CONFIRMADA'}")
    if f < 2.0:
        print("     Con la region lineal barrida de 1 a 19 grados, ningun K2 sostiene mas.")
        print("     Se agotan las hipotesis de sintonia: la sospecha pasa al MODELO.")

    # 4. Seguridad
    brown = [r for r in rows if 0 < r["v_bus_after"] < BROWNOUT_DERATE_V]
    print(f"\n  4. seguridad: {len(brown)} intentos con v_bus < {BROWNOUT_DERATE_V} V"
          + (f"  -> K2 {sorted({r['k2'] for r in brown})}" if brown else ""))
    for k2, s in sorted(res.items()):
        print(f"     K2={k2}: theta max mediano {s['th']:.1f} (tope 95)")
    print("\n  RECORDAR: la covariable manda. Si los err de entrega difieren entre niveles,")
    print("  leer el residuo antes de atribuirle nada a K2.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-s", type=float, default=20.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if d.get("lqr_pwm_max") is None:
        raise SystemExit("Firmware sin `?lpm=`: hay que flashear >= v1.58.9.")
    v_bus = float(d.get("v_bus") or 0.0)
    if v_bus < BROWNOUT_CUT_V:
        raise SystemExit(f"v_bus = {v_bus:.2f} V < {BROWNOUT_CUT_V}: el firmware anula todo "
                         "comando de motor. Encender la fuente del motor.")
    if v_bus < BROWNOUT_DERATE_V:
        raise SystemExit(f"v_bus = {v_bus:.2f} V < {BROWNOUT_DERATE_V}: el PWM se escala por "
                         "tension y nada seria atribuible.")

    DATA.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    try:
        for rep in range(1, args.reps + 1):
            for k2 in K2_LEVELS:
                print(f"\n--- rep {rep}/{args.reps}  K2={k2} (lineal {LPM / k2:.1f} deg) ---")
                try:
                    r = attempt(link, k2, rep, args.max_s)
                except Exception as exc:
                    print(f"  ERROR: {exc}")
                    link.send({"m": 0})
                    continue
                if not r.get("handed_off"):
                    print("  SIN TRASPASO  -> cuenta como t_loss = 0")
                else:
                    sat = "-" if r["sat_frac"] is None else f"{r['sat_frac']:.1%}"
                    print(f"  t_loss={r['t_loss_eff_ms']:.0f} ms  sat={sat}  "
                          f"theta_max={r['theta_max_m4_deg']:.1f}  "
                          f"entrega err={r['alpha_err_at_handoff_deg']:.1f}  "
                          f"v_bus={r['v_bus_after']:.1f}")
                rows.append(r)
    finally:
        link.send({"m": 0})
        # Dejar el firmware en sus defaults compilados.
        link.send({"lqr2": 22, "lqr2n": 30, "lqr2vn": 55, "lpm": 70, "tn": 155})

    (DATA / "k2_sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        veredicto(rows)


if __name__ == "__main__":
    main()
