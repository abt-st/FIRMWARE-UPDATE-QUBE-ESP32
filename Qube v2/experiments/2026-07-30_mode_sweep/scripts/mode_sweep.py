"""Barrido funcional de todos los modos del firmware, con homing como red de seguridad.

Objetivo: verificar que cada modo `m0..m7` hace lo que dice, despues de la
reasignacion de `m3` a homing (v1.53.x) y del gancho en `QubeRealEnv` (v1.54.0).

Lo que hace posible correr esto desatendido es el homing: hasta ahora, un modo que
derivara el brazo al tope dejaba el banco trabado (|servo| > 95 deg activa
`safeStop()` en TODOS los modos y ninguno lo revierte). Ahora `m3` esta exento de ese
chequeo, asi que la campania se puede recuperar sola entre modos.

NO es una medida de desempenio de control. Los modos de vertical (m4/m5/m7) se
prueban con el pendulo colgando, que no es su punto de operacion: aca solo se
comprueba que responden, mueven el motor y terminan de forma limpia.

Uso:
    python mode_sweep.py --ip 192.168.100.50
    python mode_sweep.py --ip 192.168.100.50 --only 0,1,2,3
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Limite blando del firmware. Cruzarlo dispara safeStop() y, antes de v1.53.0,
# dejaba el brazo sin forma de volver por software.
SERVO_HARD_LIMIT_DEG = 95.0

MODES = {
    0: "STOP",
    1: "PWM manual",
    2: "PID servo",
    3: "Homing",
    4: "LQR",
    5: "Swing-up",
    6: "Deep RL (HTTP)",
    7: "Deep RL (on-chip)",
}


class Qube:
    def __init__(self, ip: str) -> None:
        self.base = f"http://{ip}"
        self.s = requests.Session()

    def cmd(self, **params) -> dict:
        r = self.s.get(f"{self.base}/cmd", params=params, timeout=3)
        r.raise_for_status()
        return r.json()

    def state(self) -> dict:
        r = self.s.get(f"{self.base}/state", timeout=3)
        r.raise_for_status()
        return r.json()

    def stop(self) -> None:
        self.cmd(m=0)

    # ---- homing -------------------------------------------------------
    def homing(self, timeout=30.0, settle=0.0):
        """Recupera el cero. Levanta si falla: sin cero valido, todo lo que sigue
        se mide contra una referencia desconocida y no vale nada."""
        # Espera opcional antes de disparar. Por defecto 0: el firmware ya espera
        # quietud en la fase WAIT_QUIET. Se midio que esperar desde el cliente NO
        # cambia la tasa de fallo — la causa del fallo intermitente era un punto duro
        # mecanico, no inercia residual (ver docs/REGISTRO_PROBLEMAS.md, P3).
        if settle > 0:
            self.cmd(m=0)
            time.sleep(settle)
        self.cmd(m=3)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self.state()
            ph = d.get("homing_phase")
            if ph == "DONE":
                return d
            if ph == "FAIL":
                raise RuntimeError(f"homing FAIL code={d.get('homing_fail')} range={d.get('homing_range')}")
            time.sleep(0.2)
        raise RuntimeError(f"homing timeout tras {timeout}s")

    # ---- captura ------------------------------------------------------
    def record(self, seconds: float, hz: float = 20.0) -> list[dict]:
        """Muestrea /state durante `seconds`. Devuelve las filas crudas."""
        rows, t0, dt = [], time.monotonic(), 1.0 / hz
        while (t := time.monotonic() - t0) < seconds:
            try:
                d = self.state()
            except requests.RequestException:
                time.sleep(dt)
                continue
            rows.append(
                {
                    "t_s": round(t, 3),
                    "mode": d.get("mode"),
                    "position_deg": d.get("position_deg"),
                    "setpoint_deg": d.get("setpoint_deg"),
                    "pend_position_deg": d.get("pend_position_deg"),
                    "pwm": d.get("pwm"),
                    "v_bus": d.get("v_bus"),
                    "i_ma": d.get("i_ma"),
                }
            )
            time.sleep(dt)
        return rows


def summarize(rows: list[dict], expected_mode: int) -> dict:
    """Extrae los hechos que distinguen 'el modo funciona' de 'el modo no hace nada'."""
    if not rows:
        return {"samples": 0}

    def col(name: str) -> list[float]:
        return [float(r[name]) for r in rows if r.get(name) is not None]

    pos, pwm, pend = col("position_deg"), col("pwm"), col("pend_position_deg")
    modes_seen = {r["mode"] for r in rows if r.get("mode") is not None}
    # Que el firmware haya vuelto a 0 solo se cuenta si ANTES estuvo en el modo
    # pedido: si nunca entro, es otro problema (comando rechazado, no safeStop).
    entered = expected_mode in modes_seen
    dropped = entered and 0 in modes_seen and expected_mode != 0
    return {
        "samples": len(rows),
        "entered_mode": entered,
        "dropped_to_stop": dropped,
        "modes_seen": sorted(modes_seen),
        "pwm_nonzero_frac": round(sum(1 for p in pwm if abs(p) > 1) / len(pwm), 3) if pwm else None,
        "pwm_abs_max": round(max((abs(p) for p in pwm), default=0.0), 1),
        "theta_min_deg": round(min(pos), 2) if pos else None,
        "theta_max_deg": round(max(pos), 2) if pos else None,
        "theta_abs_max_deg": round(max((abs(p) for p in pos), default=0.0), 2),
        "hit_soft_limit": bool(pos) and max(abs(p) for p in pos) > SERVO_HARD_LIMIT_DEG,
        "alpha_abs_max_deg": round(max((abs(p) for p in pend), default=0.0), 2),
    }


def annotate(summary: dict) -> dict:
    """Corrige las banderas que solo tienen sentido segun el modo.

    `hit_soft_limit` y `dropped_to_stop` son sintomas de falla en casi todos los
    modos, pero en m3 son el comportamiento ESPERADO: el homing esta exento del
    fin de carrera justamente para poder alcanzar los topes, y termina solo en m0.
    Dejarlas crudas haria leer como defecto lo que es la especificacion.
    """
    if summary.get("mode") == 3:
        summary["limit_exempt_by_design"] = True
        summary["hit_soft_limit"] = False
        summary["self_terminated"] = summary.pop("dropped_to_stop", None)
    return summary


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run_mode(q: Qube, mode: int, dwell: float) -> tuple[dict, list[dict]]:
    """Corre un modo y devuelve (resumen, filas). Deja SIEMPRE la placa en m0."""
    print(f"\n=== m{mode}  {MODES[mode]} " + "=" * 30)

    # Cero valido antes de cada modo que mueva el brazo: sin el, `position_deg` no
    # es comparable entre modos y el limite blando se evalua contra basura.
    # m3 se excluye porque ES el homing: pre-homearlo grabaria solo el reposo
    # posterior, que fue el error de la primera pasada de esta campania.
    pre_homing: dict | None = None
    if mode not in (0, 3):
        h = q.homing()
        # Se guardan los topes crudos, no solo recorrido/centro: mientras no haya
        # reset de por medio comparten marco `raw`, y ahi se ve que la dispersion
        # entre corridas NO se reparte entre los dos topes.
        pre_homing = {
            "range": h["homing_range"],
            "center": h["homing_center"],
            "stop_pos": h["homing_stop_pos"],
            "stop_neg": h["homing_stop_neg"],
        }
        print(f"  homing: recorrido={h['homing_range']:.2f} centro={h['homing_center']:.2f}")

    rows: list[dict] = []
    try:
        if mode == 3:
            q.cmd(m=3)
            # Cubre la rutina completa (9-13 s medidos) mas margen. La propia
            # rutina vuelve a m0 al terminar, asi que la traza incluye el cierre.
            rows = q.record(18.0)
            h = q.state()
            print(f"  homing: recorrido={h['homing_range']:.2f} centro={h['homing_center']:.2f} ok={h['homing_ok']}")
        elif mode == 1:
            # Ida y vuelta, no PWM sostenido: a 60 el brazo alcanza un tope en ~2 s y
            # el resto del dwell seria el motor empujando contra el fin de carrera.
            q.cmd(m=1)
            for pwm_val, secs in ((60, 1.5), (0, 1.0), (-60, 1.5), (0, 1.0)):
                q.cmd(p=pwm_val)
                rows += q.record(secs)
        elif mode == 2:
            q.cmd(m=2, s=25)
            rows = q.record(dwell / 2)
            q.cmd(s=0)
            rows += q.record(dwell / 2)
        elif mode == 6:
            q.cmd(m=6)
            # Sin agente entrenado en el lazo: se comprueba el round-trip del
            # protocolo, que es lo unico atribuible sin una politica cargada.
            q.s.get(f"{q.base}/rl_cmd", params={"a": "0.0"}, timeout=3)
            rows = q.record(dwell)
        else:
            q.cmd(m=mode)
            rows = q.record(dwell)
    finally:
        q.stop()

    summary = summarize(rows, mode)
    summary["mode"] = mode
    summary["name"] = MODES[mode]
    if pre_homing:
        summary["pre_homing"] = pre_homing
    return annotate(summary), rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--dwell", type=float, default=8.0, help="segundos por modo")
    ap.add_argument("--only", default="", help="lista de modos, ej '0,1,2'")
    args = ap.parse_args()

    modes = [int(x) for x in args.only.split(",")] if args.only else sorted(MODES)
    q = Qube(args.ip)

    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        # La proteccion por calado esta gateada por inaOk; sin INA219 no se energiza.
        raise SystemExit("INA219 no responde: no se energiza el motor sin proteccion por calado.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for m in modes:
        try:
            summary, rows = run_mode(q, m, args.dwell)
        except Exception as exc:  # noqa: BLE001 - un modo no debe abortar la campania
            print(f"  ERROR en m{m}: {exc}")
            q.stop()
            summaries.append({"mode": m, "name": MODES[m], "error": str(exc)})
            continue
        write_csv(rows, DATA_DIR / f"m{m}_{MODES[m].split()[0].lower()}.csv")
        print("  " + json.dumps({k: v for k, v in summary.items() if k not in ("mode", "name")}))
        summaries.append(summary)

    (DATA_DIR / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    q.stop()
    print(f"\nResumen -> {DATA_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
