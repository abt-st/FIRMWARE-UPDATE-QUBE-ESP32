"""P4/H2 + H6: barrido de la ventana del catch del LQR.

Mide cuanto sobrevive el LQR en funcion de dos variables que hasta ahora estaban
soldadas en el firmware:

  - `lc` (LQR_CATCH_MS): ms de frenado inicial durante los cuales el LQR NO corre,
    porque la rama del catch termina en `return`. Con w_n = 14,34 rad/s (medida, P5)
    una desviacion de la vertical crece como cosh(w_n*t): x155 en 400 ms. Esa es H2.
  - `cg` (centering grace): el firmware decia "centering solo 2+ s despues del catch"
    pero leia un timestamp ya puesto a cero, asi que el centering entraba a ganancia
    plena en el primer tick. `cg=1` activa el periodo de gracia documentado. Esa es H6.

Los defaults del firmware (`lc=400`, `cg=0`) reproducen el comportamiento historico,
asi que la condicion `(400, 0)` es el CONTROL y tiene que reproducir las
supervivencias del 2026-08-03: 0,48 / 0,55 / 3,33 s.

Metodo. Las condiciones van INTERCALADAS, no en bloques: la campana de P15 dejo claro
que una sesion de banco deriva (temperatura, holgura, carga de la fuente) y medir
todas las repeticiones de una condicion seguidas confunde la deriva con el efecto.

La supervivencia se lee de `lqr_alive_ms`, latcheado por el firmware, y NO se infiere
del muestreo del modo: a 25 Hz de HTTP "sobrevivio 0,3 s" son 7 muestras.

Uso:
    uv run python catch_sweep.py --reps 4
    uv run python catch_sweep.py --reps 4 --conditions 400:0,400:1,0:1
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SAMPLE_DT = 0.04  # 25 Hz: ver el caveat de AsyncTCP en swingup_attempt.py
REASON_BITS = {0x01: "near+slow", 0x02: "peak", 0x04: "forced", 0x08: "energy"}

# Condiciones por defecto. El CONTROL va primero a proposito: si no reproduce el
# historico, el banco cambio y no hay nada que comparar (misma logica que el paso 4.1
# de PLAN_TRABAJO_V2.md).
DEFAULT_CONDITIONS = [
    (400, 0),  # control: comportamiento historico
    (400, 1),  # solo H6: aparece el periodo de gracia del centering
    (100, 0),  # solo H2: catch corto
    (0, 0),  # solo H2: sin catch, el LQR corre desde el primer tick
    (0, 1),  # H2 + H6 juntos
]


def decode_reason(mask: int) -> str:
    if not mask:
        return "-"
    return "+".join(name for bit, name in REASON_BITS.items() if mask & bit)


class Qube:
    def __init__(self, ip: str) -> None:
        self.base = f"http://{ip}"
        self.s = requests.Session()
        self.s.headers.update({"Connection": "keep-alive"})
        self.s.mount("http://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=4))

    def cmd(self, **p) -> dict:
        r = self.s.get(f"{self.base}/cmd", params=p, timeout=3)
        r.raise_for_status()
        return r.json()

    def state(self, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                r = self.s.get(f"{self.base}/state", timeout=2)
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(0.15)
        raise RuntimeError("unreachable")

    def wait_pendulum_rest(self, timeout: float = 25.0, tol_deg: float = 0.5) -> None:
        """Espera a que el pendulo deje de moverse ANTES del homing.

        No es celo: en el bring-up del 2026-08-03 la corrida 1 encadeno 5 fallas de
        homing que empiezan exactamente donde el pendulo quedo girando (547 deg), y la
        corrida 2, con el pendulo quieto, dio 0 fallas. La hipotesis (n=2) es que la
        energia residual falsea la deteccion de calado.
        """
        self.cmd(m=0)
        deadline = time.monotonic() + timeout
        prev = None
        stable = 0
        while time.monotonic() < deadline:
            a = float(self.state().get("pend_position_deg", 0.0))
            if prev is not None and abs(a - prev) < tol_deg:
                stable += 1
                if stable >= 8:  # ~1,2 s quieto
                    return
            else:
                stable = 0
            prev = a
            time.sleep(0.15)
        print("    aviso: el pendulo no llego a reposo dentro del timeout")

    def homing(self, timeout: float = 30.0) -> dict:
        self.cmd(m=3)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self.state()
            if d.get("homing_phase") == "DONE":
                return d
            if d.get("homing_phase") == "FAIL":
                raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
            time.sleep(0.2)
        raise RuntimeError("homing timeout")


def attempt(q: Qube, lc: int, cg: int, idx: int, max_s: float) -> tuple[dict, list[dict]]:
    q.wait_pendulum_rest()
    h = q.homing()
    q.cmd(lc=lc, cg=cg)

    # Verificar que la placa ACEPTO la condicion. Un barrido que en realidad corrio
    # todo con el mismo valor es el modo de fallo clasico de estas campanas.
    st = q.state()
    got = (int(st.get("lqr_catch_ms", -1)), int(st.get("lqr_centering_grace", -1)))
    if got != (lc, cg):
        raise RuntimeError(f"la placa reporta lc={got[0]} cg={got[1]}, se pidio lc={lc} cg={cg}")

    q.cmd(m=5)
    rows: list[dict] = []
    t0 = time.monotonic()
    prev_mode = 5
    handoff_t = None
    lost_t = None
    while (t := time.monotonic() - t0) < max_s:
        try:
            d = q.state()
        except requests.RequestException:
            time.sleep(SAMPLE_DT)
            continue
        mode = d.get("mode")
        rows.append(
            {
                "t_s": round(t, 4),
                "mode": mode,
                "alpha_deg": d.get("pend_position_deg"),
                "theta_deg": d.get("position_deg"),
                "pwm": d.get("pwm"),
                "i_ma": d.get("i_ma"),
                "lqr_alive_ms": d.get("lqr_alive_ms"),
            }
        )
        if mode != prev_mode:
            if prev_mode == 5 and mode == 4:
                handoff_t = t
            if prev_mode == 4 and mode != 4:
                lost_t = t
            prev_mode = mode
            if mode == 0:
                break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    d = q.state()
    trans = {}
    if d.get("swing_trans_reason") is not None:
        mask = int(d["swing_trans_reason"])
        trans = {
            "reason": decode_reason(mask),
            "alpha_deg": float(d["swing_trans_alpha"]),
            "vel_dps": float(d["swing_trans_vel"]),
            "energy_ratio": float(d["swing_trans_energy"]),
        }

    # El dato principal: latcheado por el firmware, no muestreado.
    alive_ms = int(d.get("lqr_alive_ms", 0)) if handoff_t is not None else 0
    thetas = [abs(float(r["theta_deg"])) for r in rows if r["theta_deg"] is not None]

    summary = {
        "rep": idx,
        "lc": lc,
        "cg": cg,
        "homing_range": round(float(h.get("homing_range", 0.0)), 2),
        "handoff": handoff_t is not None,
        "handoff_t_s": round(handoff_t, 2) if handoff_t is not None else None,
        "alive_ms": alive_ms,
        "alive_s": round(alive_ms / 1000.0, 3),
        "lost_t_s": round(lost_t, 2) if lost_t is not None else None,
        "theta_abs_max_deg": round(max(thetas, default=0.0), 2),
        "pend_wraps": d.get("pend_wraps"),
        "ceiling_hits": d.get("swing_ceiling_hits"),
        "transition": trans or None,
    }
    return summary, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1", help="SoftAP puro desde v1.56.0")
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--max-s", type=float, default=25.0)
    ap.add_argument(
        "--conditions",
        default=None,
        help="lista lc:cg separada por comas, ej '400:0,0:1'. Por defecto, las 5 del barrido.",
    )
    args = ap.parse_args()

    if args.conditions:
        conditions = []
        for tok in args.conditions.split(","):
            lc_s, cg_s = tok.split(":")
            conditions.append((int(lc_s), int(cg_s)))
    else:
        conditions = DEFAULT_CONDITIONS

    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if d.get("lqr_alive_ms") is None:
        raise SystemExit("Firmware sin `lqr_alive_ms`: hay que flashear >= v1.58.5.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    # Intercaladas: rep externo, condicion interno.
    for rep in range(1, args.reps + 1):
        for lc, cg in conditions:
            print(f"\n--- rep {rep}  lc={lc} cg={cg} ---")
            try:
                summary, rows = attempt(q, lc, cg, rep, args.max_s)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                q.cmd(m=0)
                continue
            if rows:
                name = f"lc{lc}_cg{cg}_rep{rep:02d}.csv"
                with (DATA_DIR / name).open("w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
            tr = summary["transition"]
            entrega = (
                f"entrega alpha={tr['alpha_deg']:.1f} vel={tr['vel_dps']:.0f} E/E*={tr['energy_ratio']:.3f}"
                if tr
                else "SIN TRASPASO"
            )
            print(f"  alive={summary['alive_s']:.3f} s   {entrega}")
            results.append(summary)

    q.cmd(m=0)
    (DATA_DIR / "sweep.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n=== resumen (solo intentos CON traspaso) ===")
    print(f"{'lc':>5} {'cg':>3} {'n':>3} {'alive medio':>12} {'mediana':>9} {'min':>7} {'max':>7}")
    for lc, cg in conditions:
        vals = [r["alive_s"] for r in results if r["lc"] == lc and r["cg"] == cg and r["handoff"]]
        if not vals:
            print(f"{lc:>5} {cg:>3} {0:>3}   — sin traspasos, no evaluable")
            continue
        print(
            f"{lc:>5} {cg:>3} {len(vals):>3} {statistics.mean(vals):>11.3f}s "
            f"{statistics.median(vals):>8.3f}s {min(vals):>6.3f}s {max(vals):>6.3f}s"
        )
    no_handoff = sum(1 for r in results if not r["handoff"])
    if no_handoff:
        print(f"\n{no_handoff} de {len(results)} intentos NO traspasaron: esos no dicen nada del LQR.")


if __name__ == "__main__":
    main()
