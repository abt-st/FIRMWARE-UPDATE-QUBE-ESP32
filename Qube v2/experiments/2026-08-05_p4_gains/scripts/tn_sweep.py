"""Barrido del umbral de traspaso (`?tn=`), la unica variable que resulto importar.

La campana de m4 del 2026-08-05 dio `corr(error de entrega, t_loss) = -0.956` con R2 = 0.914:
cuanto aguanta el pendulo lo decide la entrega y practicamente nada mas. `?tn=` es el mando
que gobierna esa entrega —de el se derivan los tres umbrales de traspaso— y es HTTP.

DOS COSAS QUE HAY QUE SABER ANTES DE LEER EL RESULTADO:

1. **El techo esta calculado de antemano.** El ajuste es `t_loss = -3.52*err + 76.8`, o sea
   que con una entrega PERFECTA (err = 0) el pendulo se pierde igual en ~77 ms. Este barrido
   puede eliminar el regimen malo (las entregas con err > 21.8, donde t_loss ya vale 0), no
   resolver P4. Un exito completo aca sigue siendo un LQR que no sostiene.

2. **Subir `tn` puede hacer que no dispare nunca.** El 2026-07-31, tn de 165/170/175 dio 0
   traspasos en 4 intentos cada uno. Eso fue ANTES de P22 (la referencia de alpha derivaba),
   y hoy 5 de 10 entregas superan 165 solas — pero el riesgo es real y es lo que obliga a la
   metrica compuesta de abajo.

METRICA PRIMARIA: `t_loss` esperado POR INTENTO, contando los intentos sin traspaso como 0.
Un nivel que dispara 1 de 5 con una entrega perfecta no sirve, y una metrica que promedie
solo los traspasos lo premiaria. Este es el numero que decide.

Uso:
    uv run python tn_sweep.py --reps 5
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

# 155 es el default del firmware y sirve de control. 175 es donde el 2026-07-31 dejaba de
# disparar; se incluye a proposito para que el barrido encuentre el borde en vez de suponerlo.
TN_LEVELS = [155, 162, 168, 175]
LC_MS = 400  # el catch queda en su default: la campana de hoy mostro que no cambia nada


def attempt(link: QubeLink, tn: int, rep: int, max_s: float) -> dict:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    homing(link)
    link.send({"tn": tn, "lc": LC_MS, "cg": 1})
    time.sleep(0.1)

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"tn{tn}_r{rep}.csv")
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
        "tn": tn,
        "rep": rep,
        "alive_ms": int(st.get("lqr_alive_ms") or 0),
        # Cuanto tuvo que bombear: subir tn alarga el bombeo y expone mas al tope del brazo
        "t_in_m5_s": round(float((mode == 5).sum()) / 500.0, 2),
        "theta_max_m5_deg": round(float(np.abs(th[mode == 5]).max()), 1) if (mode == 5).any() else None,
        "trans_reason": decode_reason(mask) if mask else None,
        "loop_overruns": st.get("loop_overruns"),
    }
    row.update(analyse(th, al, pwm, mode, LC_MS))
    # METRICA PRIMARIA. Sin traspaso el intento aporta 0: no se lo excluye del promedio, que
    # es lo que premiaria a un nivel que dispara 1 de 5 con una entrega perfecta.
    # Y si traspaso y NUNCA perdio el pendulo (`t_loss_ms` es None), eso es el mejor caso
    # posible, no el peor: vale todo el tiempo que estuvo en modo 4.
    if not row.get("handed_off"):
        row["t_loss_eff_ms"] = 0.0
    elif row.get("t_loss_ms") is None:
        row["t_loss_eff_ms"] = row["t_in_m4_s"] * 1000.0
        row["nunca_perdido"] = True
    else:
        row["t_loss_eff_ms"] = row["t_loss_ms"]
    return row


def veredicto(rows: list[dict]) -> None:
    print(f"\n=== barrido de tn (n={len(rows)} intentos) ===")
    print(f"\n{'tn':>5} {'traspasa':>9} {'err entrega':>26} {'t_loss eff (ms)':>26} {'t m5 (s)':>9}")
    resumen = {}
    for tn in TN_LEVELS:
        g = [r for r in rows if r["tn"] == tn]
        if not g:
            continue
        ho = [r for r in g if r.get("handed_off")]
        errs = [r["alpha_err_at_handoff_deg"] for r in ho]
        eff = [r["t_loss_eff_ms"] for r in g]
        resumen[tn] = {"n": len(g), "ho": len(ho), "eff_med": statistics.median(eff),
                       "err_med": statistics.median(errs) if errs else None}
        print(f"{tn:>5} {len(ho)}/{len(g):<7} "
              f"{('mediana ' + f'{statistics.median(errs):.1f}') if errs else 'sin traspaso':>26} "
              f"{'mediana ' + f'{statistics.median(eff):.1f}':>26} "
              f"{statistics.median([r['t_in_m5_s'] for r in g]):>9.1f}")
        print(f"      {'':9} {sorted(round(e, 1) for e in errs)!s:>26} {sorted(eff)!s:>26}")

    base = resumen.get(155)
    if not base:
        print("\n  sin control (tn=155): no se evalua")
        return
    print(f"\n  control tn=155: {base['ho']}/{base['n']} traspasan, "
          f"t_loss efectivo mediano {base['eff_med']:.1f} ms")
    ganadores = []
    for tn, s in resumen.items():
        if tn == 155:
            continue
        # Las DOS cosas: dispara de forma fiable Y mejora el t_loss efectivo por factor 1.5.
        fiable = s["ho"] >= 3
        mejora = s["eff_med"] >= 1.5 * max(base["eff_med"], 1.0)
        marca = "MEJOR" if (fiable and mejora) else ("no dispara" if not fiable else "sin mejora")
        f = s["eff_med"] / max(base["eff_med"], 1.0)
        print(f"    tn={tn}: {s['ho']}/{s['n']} traspasos, x{f:.2f} en t_loss efectivo  -> {marca}")
        if fiable and mejora:
            ganadores.append((tn, s["eff_med"]))
    if ganadores:
        mejor = max(ganadores, key=lambda x: x[1])
        print(f"\n  RESULTADO: tn={mejor[0]} mejora de forma fiable.")
    else:
        print("\n  RESULTADO: ningun nivel mejora de forma fiable. tn=155 se queda.")
    print("\n  RECORDAR el techo pre-registrado: el ajuste da t_loss = 76.8 ms con entrega")
    print("  perfecta. Ningun tn resuelve P4; el cuello que queda es la saturacion (H3).")


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
        # Intercaladas: rep externo, nivel interno. El banco deriva dentro de una sesion.
        for rep in range(1, args.reps + 1):
            for tn in TN_LEVELS:
                print(f"\n--- rep {rep}/{args.reps}  tn={tn} ---")
                try:
                    r = attempt(link, tn, rep, args.max_s)
                except Exception as exc:
                    print(f"  ERROR: {exc}")
                    link.send({"m": 0})
                    continue
                if not r.get("handed_off"):
                    print(f"  SIN TRASPASO tras {r['t_in_m5_s']:.1f} s de bombeo "
                          f"(theta max {r['theta_max_m5_deg']})  -> cuenta como t_loss = 0")
                else:
                    tl = "NUNCA PERDIDO" if r.get("nunca_perdido") else f"{r['t_loss_ms']:.0f} ms"
                    sat = "-" if r["sat_frac"] is None else f"{r['sat_frac']:.1%}"
                    print(f"  t_loss={tl}  entrega err={r['alpha_err_at_handoff_deg']:.1f} deg"
                          f"  ({r['trans_reason']})  sat={sat}  eff={r['t_loss_eff_ms']:.0f} ms")
                rows.append(r)
    finally:
        link.send({"m": 0})
        link.send({"tn": 155})  # dejar el firmware en su default

    (DATA / "tn_sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        veredicto(rows)


if __name__ == "__main__":
    main()
