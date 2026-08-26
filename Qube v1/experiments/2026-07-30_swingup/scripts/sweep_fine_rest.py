"""P2 — Barrido fino de `swingupPwmMax` CON condicion inicial controlada.

El barrido anterior quedo invalidado por un confundente: el homing entre corridas no
disipa la energia del pendulo, la agita. Las corridas que arrancaban energizadas
alcanzaban el umbral en 1-2 s en vez de los ~8 s que toma bombear desde reposo, asi
que su `alpha` maximo no era atribuible al parametro sino a la herencia.

Aca se EXIGE reposo antes de cada corrida: se espera a que |alpha| se mantenga bajo
un umbral durante una ventana, con timeout. `t_bombeo` queda como verificacion
independiente — una corrida que traspasa en 2 s no arranco desde reposo, y se marca.

Metrica principal: `alpha_max` alcanzado y si llego a la vertical (180 deg). La
"meseta" no sirve cuando la corrida termina pronto por traspaso: promediaria tres
picos y no significaria nada.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import DATA, SAMPLE_DT, Qube  # noqa: E402

# Reposo = alpha NO CAMBIA, no alpha cerca de cero. El swing-up llama a
# resetPendulumOffsetHere() al detectar giro, asi que el cero del pendulo se redefine
# en silencio y "colgando" deja de ser 0 deg. Un criterio de proximidad a cero no
# pasaba nunca aunque el pendulo estuviera perfectamente quieto (ver P13).
REST_PP_DEG = 1.5     # variacion pico-a-pico maxima en la ventana
REST_HOLD_S = 2.5     # sostenido este tiempo
REST_TIMEOUT_S = 45.0
VERTICAL_DEG = 170.0  # se considera "llego arriba" (vertical = 180)


def wait_rest(q: Qube) -> tuple[bool, float]:
    """Espera reposo real del pendulo. Devuelve (logrado, segundos esperados)."""
    q.cmd(m=0)
    t0, win = time.monotonic(), []
    while time.monotonic() - t0 < REST_TIMEOUT_S:
        win.append((time.monotonic(), float(q.state()["pend_position_deg"])))
        win = [(t, a) for t, a in win if time.monotonic() - t <= REST_HOLD_S]
        if len(win) >= 12 and (max(a for _, a in win) - min(a for _, a in win)) < REST_PP_DEG:
            return True, round(time.monotonic() - t0, 1)
        time.sleep(0.1)
    return False, REST_TIMEOUT_S


def run(q: Qube, sp: int, rep: int, secs: float) -> tuple[dict, list[dict]]:
    q.homing()
    rest_ok, rest_s = wait_rest(q)
    # RE-CERO del pendulo con el mecanismo verificadamente quieto. Imprescindible:
    # resetPendulumOffsetHere() corrompe el offset durante el swing-up (P13), y se
    # midio un pendulo colgando e inmovil leyendo 98 deg. Con ese sesgo, |pendPos|
    # ya supera el umbral de traspaso al arrancar y la corrida "traspasa" en 1 s sin
    # haber bombeado — y `alpha_max` mide el sesgo, no el angulo real.
    # Colgando en reposo ES el cero fisico, asi que zp=1 aca es correcto por definicion.
    q.cmd(zp=1)
    st0 = q.state()
    off = float(st0["pend_offset_deg"])
    w0 = int(st0.get("pend_wraps", 0))
    q.cmd(pl=0, pc=0, pr=70, sp=sp)
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic() - t0) < secs:
        try:
            d = q.state()
        except Exception:  # noqa: BLE001
            time.sleep(SAMPLE_DT)
            continue
        rows.append({"t_s": round(t, 4), "mode": d.get("mode"),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"), "pwm": d.get("pwm")})
        if d.get("mode") == 0:
            break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    w1 = int(q.state().get("pend_wraps", 0))
    inm = [r for r in rows if r["mode"] == 5]
    al = [abs(float(r["alpha_deg"])) for r in rows]
    amax = max(al, default=0.0)
    t_pump = round(float(inm[-1]["t_s"]), 1) if inm else 0.0
    modos = sorted({r["mode"] for r in rows})
    return {
        "sp": sp, "rep": rep,
        "reposo_ok": rest_ok, "espera_s": rest_s, "offset_tras_cero": round(off, 2),
        "alpha_max": round(amax, 1),
        "llego_vertical": amax > VERTICAL_DEG,
        "t_bombeo": t_pump,
        # Heuristica RETIRADA: se uso un umbral de t_bombeo < 5 s como proxy de
        # "arranco energizado", calibrado sobre sp=50. Pero a sp=60 el bombeo crece
        # mas rapido y alcanza 157 deg en 4.3 s de forma legitima, con lo que el
        # filtro descartaba justamente las corridas buenas. Ahora el reposo se
        # VERIFICA (wait_rest) y el cero se re-fija (zp=1), asi que la condicion
        # inicial esta controlada de verdad y el proxy sobra.
        "arranque_sospechoso": False,
        "traspaso": 4 in [int(m) for m in modos if m],
        "theta_max": round(max(abs(float(r["theta_deg"])) for r in rows), 1),
        "murio": 0 in [int(m) for m in modos if m is not None],
    }, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--values", default="50,55,57,59,60")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--secs", type=float, default=25.0)
    args = ap.parse_args()

    q = Qube(args.ip)
    DATA.mkdir(parents=True, exist_ok=True)
    vals = [int(x) for x in args.values.split(",")]
    out: list[dict] = []
    # Intercalado: todas las sp en la rep 1, luego rep 2... En vez de agotar una sp
    # antes de pasar a la siguiente, para que una deriva lenta afecte a todas por igual.
    for rep in range(1, args.reps + 1):
        for sp in vals:
            print(f"\n--- sp={sp} rep {rep} ---")
            try:
                s, rows = run(q, sp, rep, args.secs)
            except Exception as exc:  # noqa: BLE001
                print(f"    ERROR: {exc}")
                q.cmd(m=0)
                continue
            with (DATA / f"rest_sp{sp}_r{rep}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print("    " + json.dumps(s))
            out.append(s)
            (DATA / "sweep_fine_rest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    q.cmd(m=0, sp=50)
    print("\n=== resumen (solo corridas con reposo verificado) ===")
    print(f"{'sp':>4} {'n':>3} {'alpha max':>22} {'llego a 180':>12} {'t bombeo':>10}")
    for sp in vals:
        g = [r for r in out if r["sp"] == sp and r["reposo_ok"] and not r["arranque_sospechoso"]]
        if not g:
            print(f"{sp:>4} {0:>3}  (sin corridas validas)")
            continue
        am = [r["alpha_max"] for r in g]
        print(f"{sp:>4} {len(g):>3} {min(am):>8.1f}–{max(am):<8.1f} med={statistics.median(am):5.1f}"
              f" {sum(r['llego_vertical'] for r in g):>7}/{len(g):<4}"
              f" {statistics.mean(r['t_bombeo'] for r in g):>10.1f}")
    desc = [r for r in out if not r["reposo_ok"] or r["arranque_sospechoso"]]
    if desc:
        print(f"\n{len(desc)} corridas descartadas (sin reposo verificado o arranque sospechoso)")


if __name__ == "__main__":
    main()
