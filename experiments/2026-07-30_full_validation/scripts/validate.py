"""Validacion exhaustiva de los 8 modos, con repeticiones y criterios explicitos.

A diferencia del barrido del mismo dia (2026-07-30_mode_sweep), aca cada modo se
corre N veces y cada uno tiene un CRITERIO DE APROBACION escrito: "funciona bien" es
una condicion evaluable, no una impresion mirando numeros.

Cada repeticion arranca con homing, asi que `position_deg` es comparable entre
repeticiones y entre modos. El homing reintenta una vez: su modo de falla conocido
(fail=1, recorrido fuera de tolerancia) tambien aparece cuando la mecanica se traba
de verdad, y ahi hay que parar, no insistir.

Uso:
    python validate.py --ip 192.168.100.50 --reps 3
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

SAMPLE_DT = 0.04          # ~25 Hz; sin pausa el AsyncTCP del ESP32 se cae
SERVO_LIMIT_DEG = 95.0
RANGE_NOM = 269.65        # medido en banco 2026-07-30
RANGE_TOL = 3.0
MODE1_DEADMAN_S = 2.5     # el modo 1 tiene deadman corto: pasos < 2 s

MODES = {
    0: "STOP", 1: "PWM manual", 2: "PID servo", 3: "Homing",
    4: "LQR", 5: "Swing-up", 6: "Deep RL (HTTP)", 7: "Deep RL (chip)",
}
REASON_BITS = {0x01: "near+slow", 0x02: "peak", 0x04: "forced", 0x08: "energy"}


def decode_reason(mask: int) -> str:
    if not mask:
        return "-"
    return "+".join(n for b, n in REASON_BITS.items() if mask & b)


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

    def raw(self, path: str, **p):
        return self.s.get(f"{self.base}{path}", params=p, timeout=3)

    def state(self, retries: int = 3) -> dict:
        for i in range(retries):
            try:
                r = self.s.get(f"{self.base}/state", timeout=2)
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if i == retries - 1:
                    raise
                time.sleep(0.15)
        raise RuntimeError("unreachable")

    def homing(self, timeout=30.0, settle=0.0):
        # Espera opcional antes de disparar. Por defecto 0: el firmware ya espera
        # quietud en la fase WAIT_QUIET. Se midio que esperar desde el cliente NO
        # cambia la tasa de fallo — la causa del fallo intermitente era un punto duro
        # mecanico, no inercia residual (ver docs/REGISTRO_PROBLEMAS.md, P3).
        if settle > 0:
            self.cmd(m=0)
            time.sleep(settle)
        self.cmd(m=3)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            d = self.state()
            ph = d.get("homing_phase")
            if ph == "DONE":
                return d
            if ph == "FAIL":
                raise RuntimeError(f"homing FAIL code={d.get('homing_fail')} range={d.get('homing_range')}")
            time.sleep(0.2)
        raise RuntimeError("homing timeout")

    def homing_retry(self) -> dict:
        try:
            return self.homing()
        except RuntimeError as first:
            print(f"    homing falló ({first}); reintento único…")
            time.sleep(2.0)
            return self.homing()

    def record(self, seconds: float) -> list[dict]:
        rows, t0 = [], time.monotonic()
        while (t := time.monotonic() - t0) < seconds:
            try:
                d = self.state()
            except requests.RequestException:
                time.sleep(SAMPLE_DT)
                continue
            rows.append({
                "t_s": round(t, 4), "mode": d.get("mode"),
                "theta_deg": d.get("position_deg"), "setpoint_deg": d.get("setpoint_deg"),
                "alpha_deg": d.get("pend_position_deg"), "pwm": d.get("pwm"),
                "i_ma": d.get("i_ma"), "v_bus": d.get("v_bus"),
            })
            time.sleep(SAMPLE_DT)
        return rows


def f(rows, key):
    return [float(r[key]) for r in rows if r.get(key) is not None]


def step_overshoot(seg: list[dict], sp: float) -> float | None:
    """Sobrepaso en % del TAMANO DEL ESCALON, medido tras el primer cruce.

    La version original normalizaba por |sp| y tomaba max(|theta|) de todo el
    segmento, transitorio de entrada incluido. En un escalon que cruza el cero eso
    da el doble: el +20 -> -20 del protocolo (theta_0 = 17.7, pico -34.9) daba
    74.5% cuando el sobrepaso clasico es 39.5%. Se conserva la cifra vieja aparte
    (`overshoot_pct_max_legacy`) para poder comparar con las tandas de 2026-07-30.
    """
    th = [float(r["theta_deg"]) for r in seg]
    if not th:
        return None
    step = sp - th[0]
    if abs(step) < 1.0:      # sin escalon no hay sobrepaso que medir
        return None
    up = step > 0
    # Primer cruce del setpoint EN LA DIRECCION del escalon.
    cross = next((i for i, v in enumerate(th) if (v >= sp if up else v <= sp)), None)
    if cross is None:        # nunca llego: no sobrepaso, quedo corto
        return 0.0
    peak = max(th[cross:]) if up else min(th[cross:])
    return round((peak - sp) / step * 100, 1)


# ── protocolos por modo ────────────────────────────────────────────────────────
def run_rep(q: Qube, mode: int, rep: int) -> dict:
    pre = None
    if mode != 3:
        h = q.homing_retry()
        pre = {"range": h["homing_range"], "center": h["homing_center"],
               "stop_pos": h["homing_stop_pos"], "stop_neg": h["homing_stop_neg"]}

    rows: list[dict] = []
    extra: dict = {}
    try:
        if mode == 0:
            q.cmd(m=0)
            rows = q.record(5.0)

        elif mode == 1:
            q.cmd(m=1)
            steps = [(50, 1.2), (0, 0.8), (-50, 1.2), (0, 0.8)]
            for pwm_val, secs in steps:
                assert secs < MODE1_DEADMAN_S
                q.cmd(p=pwm_val)
                seg = q.record(secs)
                for r in seg:
                    r["cmd_pwm"] = pwm_val
                rows += seg
            # Fidelidad de comando: |pwm reportado - pwm pedido| en regimen.
            errs = [abs(float(r["pwm"]) - r["cmd_pwm"]) for r in rows
                    if r.get("cmd_pwm") and r.get("pwm") is not None and r["mode"] == 1]
            extra["pwm_track_err_max"] = round(max(errs), 1) if errs else None
            th = f(rows, "theta_deg")
            extra["moved_both_ways"] = bool(th) and (max(th) - min(th) > 20.0)

        elif mode == 2:
            for sp in (20.0, -20.0, 0.0):
                q.cmd(m=2, s=sp)
                seg = q.record(3.5)
                for r in seg:
                    r["cmd_sp"] = sp
                rows += seg
            # Error en regimen: ultimo 30% de cada escalon.
            sse, ov, ov_legacy = [], [], []
            for sp in (20.0, -20.0, 0.0):
                seg = [r for r in rows if r.get("cmd_sp") == sp and r.get("theta_deg") is not None]
                if not seg:
                    continue
                tail = seg[int(len(seg) * 0.7):]
                if tail:
                    sse.append(abs(statistics.mean(float(r["theta_deg"]) for r in tail) - sp))
                o = step_overshoot(seg, sp)
                if o is not None:
                    ov.append(o)
                # Metrica vieja, solo para comparar contra las tandas de 2026-07-30.
                peak = max((abs(float(r["theta_deg"])) for r in seg), default=0.0)
                if abs(sp) > 1:
                    ov_legacy.append(round((peak - abs(sp)) / abs(sp) * 100, 1))
            extra["sse_max_deg"] = round(max(sse), 2) if sse else None
            extra["overshoot_pct_max"] = max(ov) if ov else None
            extra["overshoot_pct_max_legacy"] = max(ov_legacy) if ov_legacy else None

        elif mode == 3:
            q.cmd(m=3)
            rows = q.record(18.0)
            d = q.state()
            extra["homing_ok"] = bool(d.get("homing_ok"))
            extra["range"] = float(d.get("homing_range", 0))
            extra["center"] = float(d.get("homing_center", 0))
            extra["stop_pos"] = float(d.get("homing_stop_pos", 0))
            extra["stop_neg"] = float(d.get("homing_stop_neg", 0))

        elif mode in (4, 5):
            q.cmd(m=mode)
            rows = q.record(10.0)
            d = q.state()
            if mode == 5:
                mask = int(d.get("swing_trans_reason", 0))
                extra["trans_reason"] = decode_reason(mask)
                extra["trans_mask"] = mask
                extra["trans_alpha"] = float(d.get("swing_trans_alpha", 0))
                extra["trans_vel"] = float(d.get("swing_trans_vel", 0))
                extra["trans_energy"] = float(d.get("swing_trans_energy", 0))
                extra["alpha_peak"] = round(max((abs(x) for x in f(rows, "alpha_deg")), default=0.0), 2)

        elif mode == 6:
            q.cmd(m=6)
            # Prueba REAL del lazo: acciones no nulas alternadas, verificando que el
            # PWM responde. Mandar solo 0.0 comprueba el transporte, no el actuador.
            for a in (0.35, -0.35, 0.0):
                q.raw("/rl_cmd", a=f"{a:.2f}")
                seg = q.record(1.6)
                for r in seg:
                    r["cmd_action"] = a
                rows += seg
            resp = [abs(float(r["pwm"])) for r in rows
                    if r.get("cmd_action") not in (None, 0.0) and r.get("pwm") is not None]
            extra["pwm_resp_max"] = round(max(resp), 1) if resp else 0.0
            extra["action_moved_motor"] = bool(resp) and max(resp) > 5

        elif mode == 7:
            q.cmd(m=7)
            rows = q.record(10.0)
            pwms = f(rows, "pwm")
            extra["pwm_std"] = round(statistics.pstdev(pwms), 1) if len(pwms) > 1 else 0.0
            extra["inference_active"] = bool(pwms) and statistics.pstdev(pwms) > 5
    finally:
        q.cmd(m=0)

    # Actividad DENTRO del modo, no sobre la ventana completa. Los modos que cruzan
    # el limite blando mueren en fracciones de segundo y el resto de la ventana es
    # post-safeStop con PWM 0: medir sobre todo daba "motor inactivo" para un
    # controlador que en realidad accionaba el 100% del tiempo que estuvo vivo.
    in_mode = [r for r in rows if r.get("mode") == mode]
    pw_in = [float(r["pwm"]) for r in in_mode if r.get("pwm") is not None]
    extra["pwm_active_frac_inmode"] = round(sum(1 for x in pw_in if abs(x) > 1) / len(pw_in), 3) if pw_in else 0.0
    extra["time_in_mode_s"] = round(float(in_mode[-1]["t_s"]) - float(in_mode[0]["t_s"]), 2) if in_mode else 0.0

    th, pw = f(rows, "theta_deg"), f(rows, "pwm")
    al = f(rows, "alpha_deg")
    modes_seen = sorted({r["mode"] for r in rows if r.get("mode") is not None})
    out = {
        "mode": mode, "rep": rep, "samples": len(rows),
        "sample_hz": round(len(rows) / rows[-1]["t_s"], 1) if rows and rows[-1]["t_s"] else None,
        "entered": mode in modes_seen or (mode == 3 and 3 in modes_seen),
        "modes_seen": modes_seen,
        "theta_abs_max": round(max((abs(x) for x in th), default=0.0), 2),
        "alpha_abs_max": round(max((abs(x) for x in al), default=0.0), 2),
        "pwm_abs_max": round(max((abs(x) for x in pw), default=0.0), 1),
        "pwm_active_frac": round(sum(1 for x in pw if abs(x) > 1) / len(pw), 3) if pw else 0.0,
        "hit_limit": bool(th) and max(abs(x) for x in th) > SERVO_LIMIT_DEG,
        "dropped_to_stop": bool(modes_seen) and 0 in modes_seen and mode != 0,
        "pre_homing": pre,
    }
    out.update(extra)
    return out, rows


# ── criterios de aprobacion ───────────────────────────────────────────────────
def verdict(mode: int, reps: list[dict]) -> dict:
    """Cada modo con su criterio explicito. Devuelve pass/fail + motivo."""
    if not reps:
        return {"pass": False, "reason": "sin repeticiones"}
    ok = lambda k: all(r.get(k) for r in reps)  # noqa: E731

    if not ok("entered"):
        return {"pass": False, "reason": "no entro al modo en alguna repeticion"}

    if mode == 0:
        bad = [r for r in reps if r["pwm_abs_max"] > 0]
        return {"pass": not bad, "reason": "PWM debe ser 0" if bad else "motor inerte, como debe"}
    if mode == 1:
        errs = [r.get("pwm_track_err_max") or 0 for r in reps]
        good = ok("moved_both_ways") and max(errs) <= 2
        return {"pass": good, "reason": f"seguimiento de PWM err_max={max(errs)}, movio en ambos sentidos={ok('moved_both_ways')}"}
    if mode == 2:
        sse = [r.get("sse_max_deg") or 99 for r in reps]
        good = max(sse) < 8.0 and not any(r["hit_limit"] for r in reps)
        return {"pass": good, "reason": f"error en regimen max={max(sse):.2f} deg (umbral 8)"}
    if mode == 3:
        rng = [r.get("range") or 0 for r in reps]
        good = ok("homing_ok") and all(abs(x - RANGE_NOM) < RANGE_TOL for x in rng)
        return {"pass": good, "reason": f"recorrido {min(rng):.2f}–{max(rng):.2f} (nom {RANGE_NOM}±{RANGE_TOL})"}
    if mode in (4, 7):
        # Sobre la ventana COMPLETA esto daba falso negativo en m4: sobrevive 0.3 s
        # y el resto es post-safeStop. Lo que se valida aca es que el controlador
        # accione mientras esta vigente, no cuanto aguanta — eso es desempenio.
        fr = [r.get("pwm_active_frac_inmode", 0) for r in reps]
        secs = [r.get("time_in_mode_s", 0) for r in reps]
        good = all(x > 0.5 for x in fr)
        return {"pass": good,
                "reason": f"acciona el motor {min(fr):.0%}–{max(fr):.0%} del tiempo en modo; "
                          f"sobrevive {min(secs):.1f}–{max(secs):.1f} s"}
    if mode == 5:
        good = all(r.get("trans_mask") for r in reps)
        reasons = {r.get("trans_reason") for r in reps}
        return {"pass": good, "reason": f"traspaso a LQR en todas; criterio={reasons}"}
    if mode == 6:
        good = ok("action_moved_motor")
        return {"pass": good, "reason": "una accion no nula mueve el motor" if good else "la accion no llego al actuador"}
    return {"pass": True, "reason": "-"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.100.50")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    modes = [int(x) for x in args.only.split(",")] if args.only else sorted(MODES)
    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_reps: dict[int, list[dict]] = {}
    for m in modes:
        all_reps[m] = []
        for rep in range(1, args.reps + 1):
            print(f"\n=== m{m} {MODES[m]} — rep {rep}/{args.reps} ===")
            try:
                summary, rows = run_rep(q, m, rep)
            except Exception as exc:  # noqa: BLE001
                print(f"    ERROR: {exc}")
                q.cmd(m=0)
                all_reps[m].append({"mode": m, "rep": rep, "error": str(exc), "entered": False})
                continue
            if rows:
                p = DATA_DIR / f"m{m}_rep{rep}.csv"
                with p.open("w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
                    w.writeheader()
                    w.writerows(rows)
            all_reps[m].append(summary)
            print("    " + json.dumps({k: v for k, v in summary.items()
                                       if k not in ("mode", "rep", "modes_seen", "pre_homing")}))
        # Guardado incremental: una campania de 20+ min no puede perderse por un corte.
        (DATA_DIR / "reps.json").write_text(json.dumps(all_reps, indent=2), encoding="utf-8")

    verdicts = {m: verdict(m, [r for r in reps if "error" not in r]) for m, reps in all_reps.items()}
    (DATA_DIR / "verdicts.json").write_text(json.dumps(verdicts, indent=2), encoding="utf-8")
    q.cmd(m=0)

    print("\n" + "=" * 64)
    for m in modes:
        v = verdicts[m]
        print(f"  m{m} {MODES[m]:<18} {'PASS' if v['pass'] else 'FAIL'}  {v['reason']}")


if __name__ == "__main__":
    main()
