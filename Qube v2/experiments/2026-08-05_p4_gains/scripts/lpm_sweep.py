"""Barrido del techo de PWM del LQR (`?lpm=`) — el ultimo candidato de P4.

Estado al que llega este barrido, tras 35 corridas el 2026-08-05:

  - La entrega explica el 75% de la varianza de `t_loss`, y con `tn=162` se saca lo que se
    puede de ella: la mediana pasa de 0 a 14 ms. No alcanza.
  - **La ordenada del ajuste es 90 ms**: con entrega perfecta el pendulo se pierde igual.
    Eso es del controlador, no de la entrega.
  - H1, H2 y H7 estan descartadas. H3 esta confirmada: la salida esta contra su techo el
    93% del tiempo, con `LQR_PWM_MAX = 70` sobre un `PWM_MAX` de 200 — el 35% de la
    autoridad disponible.

Este barrido pregunta si esa saturacion es CAUSA o solo sintoma.

DOS COSAS DEL DISENO:

1. **`tn` se fija en 162, no en el default 155.** Con 155 la mitad de los intentos entrega
   con err > 21.6 y `t_loss` vale 0 exactamente: no discriminan nada y diluirian el efecto.
   Fijar la entrega en su mejor punto medido es lo que deja ver al controlador. No es una
   condicion del barrido: es la misma en los cuatro niveles.

2. **La saturacion se mide contra el techo de CADA nivel.** `analyse(..., pwm_max=lpm)`.
   Medir un barrido de `lpm` contra un 70 fijo daria saturaciones falsas — es la tercera
   vez en este experimento que el techo mal elegido produce un numero sin sentido.

OJO CON LA SEGURIDAD: mas autoridad es un brazo mas rapido hacia su limite de 95 grados.
`safeStop` sigue siendo el respaldo, pero conviene mirar la placa. El script registra
`v_bus` despues de cada intento y descarta un nivel que produzca brownout.

Uso:
    uv run python lpm_sweep.py --reps 5
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

LPM_LEVELS = [70, 100, 130, 150]  # 70 = default historico y control; 150 = tope de `?lpm=`
TN = 162  # el mejor punto de entrega medido; IGUAL en los cuatro niveles
LC_MS = 400


def attempt(link: QubeLink, lpm: int, rep: int, max_s: float) -> dict:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    homing(link)
    link.send({"lpm": lpm, "tn": TN, "lc": LC_MS, "cg": 1})
    time.sleep(0.1)
    # Verificar que el firmware acepto el techo: si `lpm` no llegara, el barrido entero
    # mediria cuatro veces el mismo nivel y se veria como "no hay efecto".
    got = int(link.state().get("lqr_pwm_max", -1))
    if got != lpm:
        raise RuntimeError(f"el firmware reporta lqr_pwm_max={got}, se pidio {lpm}")

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"lpm{lpm}_r{rep}.csv")
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
        "lpm": lpm,
        "rep": rep,
        "tn": TN,
        "alive_ms": int(st.get("lqr_alive_ms") or 0),
        "v_bus_after": float(st.get("v_bus") or 0.0),
        "trans_reason": decode_reason(mask) if mask else None,
        "loop_overruns": st.get("loop_overruns"),
    }
    # La saturacion, contra el techo de ESTE nivel.
    row.update(analyse(th, al, pwm, mode, LC_MS, pwm_max=lpm))
    row["t_loss_eff_ms"] = (
        0.0
        if not row.get("handed_off")
        else (row["t_in_m4_s"] * 1000.0 if row.get("t_loss_ms") is None else row["t_loss_ms"])
    )
    return row


def veredicto(rows: list[dict]) -> None:
    print(f"\n=== barrido de lpm (n={len(rows)} intentos, tn={TN} fijo) ===")
    print(f"\n{'lpm':>5} {'traspasa':>9} {'t_loss mediano':>15} {'saturacion':>12} "
          f"{'theta max':>10} {'err entrega':>12}")
    res = {}
    for lpm in LPM_LEVELS:
        g = [r for r in rows if r["lpm"] == lpm]
        if not g:
            continue
        ho = [r for r in g if r.get("handed_off")]
        if not ho:
            print(f"{lpm:>5} {0}/{len(g):<7}  (ningun traspaso)")
            continue
        eff = [r["t_loss_eff_ms"] for r in g]
        sat = [r["sat_frac"] for r in ho if r["sat_frac"] is not None]
        res[lpm] = {
            "n": len(g), "ho": len(ho),
            "t": statistics.median(eff),
            "sat": statistics.median(sat) if sat else None,
            "th": statistics.median([r["theta_max_m4_deg"] for r in ho]),
        }
        print(f"{lpm:>5} {len(ho)}/{len(g):<7} {statistics.median(eff):>15.0f} "
              f"{(f'{statistics.median(sat):.1%}' if sat else '-'):>12} "
              f"{res[lpm]['th']:>10.1f} "
              f"{statistics.median([r['alpha_err_at_handoff_deg'] for r in ho]):>12.1f}")
        print(f"      {'':9} {sorted(eff)!s:>15}")

    base = res.get(70)
    if not base:
        print("\n  sin control (lpm=70): no se evalua")
        return

    # Criterio 1 — el control reproduce el resultado de tn=162 (mediana 14 ms, rango 12-44)
    print(f"\n  1. control lpm=70 reproduce tn=162 (mediana 14 ms): {base['t']:.0f} ms  "
          f"{'OK' if 5 <= base['t'] <= 60 else 'FUERA DE RANGO — rehacer la linea base'}")

    # Criterio 2 — el mando tiene que hacer algo: mas techo, menos saturacion
    sats = [(lpm, s["sat"]) for lpm, s in sorted(res.items()) if s["sat"] is not None]
    if len(sats) >= 3:
        # La primera version escribio `sats[i] >= sats[i+1] - 0.05`, que tolera que la
        # saturacion SUBA hasta 5 puntos y aun asi imprime "SI". Dio un falso "SI" sobre
        # 97->98->98->99. Se compara punta a punta y se exige una caida real.
        baja = sats[-1][1] < sats[0][1] - 0.05
        print(f"  2. la saturacion baja al subir el techo: "
              f"{' -> '.join(f'{s:.1%}' for _, s in sats)}  {'SI' if baja else 'NO'}")
        if not baja:
            print("     El lazo pide mas que el techo mas alto probado: no se alcanzo el")
            print("     regimen lineal y el barrido no puede concluir sobre H3.")

    # Criterio 3 — H3 causal: t_loss crece de forma monotona con el techo
    ts = [(lpm, s["t"]) for lpm, s in sorted(res.items())]
    mono = all(ts[i][1] <= ts[i + 1][1] + 3.0 for i in range(len(ts) - 1))
    mejor = max(ts, key=lambda x: x[1])
    factor = mejor[1] / max(base["t"], 1.0)
    print(f"  3. H3 causal — t_loss vs techo: {' -> '.join(f'{t:.0f}' for _, t in ts)} ms")
    print(f"     monotono: {'SI' if mono else 'NO'}   mejor lpm={mejor[0]} con {mejor[1]:.0f} ms "
          f"(x{factor:.2f} sobre el control)")
    if mono and factor >= 2.0:
        print("     CONFIRMADA: la saturacion era causa, no solo sintoma.")
    else:
        print("     NO CONFIRMADA. Con mas del doble de autoridad el LQR no sostiene mas:")
        print("     la saturacion es sintoma. Lo que queda son las ganancias y el modelo (H5).")

    # Criterio 4 — seguridad
    brown = [r for r in rows if 0 < r["v_bus_after"] < BROWNOUT_DERATE_V]
    print(f"\n  4. seguridad: {len(brown)} intentos con v_bus < {BROWNOUT_DERATE_V} V tras la corrida"
          + (f"  -> {sorted({r['lpm'] for r in brown})}" if brown else ""))
    for lpm, s in sorted(res.items()):
        print(f"     lpm={lpm}: theta max mediano {s['th']:.1f} (tope 95)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-s", type=float, default=20.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')} "
          f"lqr_pwm_max={d.get('lqr_pwm_max')}")
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
            for lpm in LPM_LEVELS:
                print(f"\n--- rep {rep}/{args.reps}  lpm={lpm} ---")
                try:
                    r = attempt(link, lpm, rep, args.max_s)
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
        link.send({"lpm": 70, "tn": 155})  # dejar el firmware en sus defaults

    (DATA / "lpm_sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        veredicto(rows)


if __name__ == "__main__":
    main()
