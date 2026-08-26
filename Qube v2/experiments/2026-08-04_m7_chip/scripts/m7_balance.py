"""m7 — mide si la inferencia en chip BALANCEA, no solo si mueve el motor.

El criterio que traia `validate.py` para el modo 7 era `pwm_std > 5`: señal de vida. Esto
mide contra el criterio de `../README.md`, escrito antes de medir:

  1. alcanza |alpha - 180| < 15 en >= 3 de 5 intentos
  2. lo SOSTIENE >= 3 s continuos en >= 3 de 5
  3. loop_overruns = 0 (la inferencia on-chip no puede romper los 500 Hz)

A/B sobre `he` (umbral del traspaso al LQR):
  he=165 (default) -> la politica sube y el LQR del modo 4 balancea
  he=179           -> el traspaso casi no dispara y la politica balancea sola

Sin ese A/B, medir m7 vuelve a medir P4 en vez de la politica.

Uso:
    uv run python m7_balance.py --reps 5
    uv run python m7_balance.py --reps 5 --he 179
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

UPRIGHT_DEG = 180.0
TOL_DEG = 15.0  # |alpha - 180| < 15 cuenta como vertical
HOLD_S = 3.0  # sostener esto es el criterio 2
SAMPLE_DT = 0.04  # 25 Hz: ver el caveat de AsyncTCP en swingup_attempt.py


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
        """Reposo del pendulo antes del homing (ver el bring-up del 2026-08-03)."""
        self.cmd(m=0)
        deadline = time.monotonic() + timeout
        prev, stable = None, 0
        while time.monotonic() < deadline:
            a = float(self.state().get("pend_position_deg", 0.0))
            if prev is not None and abs(a - prev) < tol_deg:
                stable += 1
                if stable >= 8:
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


def longest_hold(rows: list[dict]) -> tuple[float, bool]:
    """Tramo continuo mas largo con |alpha - 180| < TOL, en segundos."""
    best = cur = 0.0
    start = None
    reached = False
    for r in rows:
        a = r["alpha_deg"]
        if a is None:
            continue
        if abs(abs(a) - UPRIGHT_DEG) < TOL_DEG:
            reached = True
            if start is None:
                start = r["t_s"]
            cur = r["t_s"] - start
            best = max(best, cur)
        else:
            start = None
            cur = 0.0
    return best, reached


def attempt(q: Qube, he: float, idx: int, max_s: float) -> tuple[dict, list[dict]]:
    q.wait_pendulum_rest()
    h = q.homing()
    q.cmd(he=he)
    q.cmd(rj=1)  # reinicia loop_dt_max_us / loop_overruns: el criterio 3 es de ESTE intento

    st = q.state()
    got = float(st.get("hybrid_enter_deg", -1))
    if abs(got - he) > 0.6:
        raise RuntimeError(f"la placa reporta he={got}, se pidio {he}")

    q.cmd(m=7)
    rows: list[dict] = []
    t0 = time.monotonic()
    used_lqr = False
    while (t := time.monotonic() - t0) < max_s:
        try:
            d = q.state()
        except requests.RequestException:
            time.sleep(SAMPLE_DT)
            continue
        if d.get("hybrid_lqr"):
            used_lqr = True
        rows.append(
            {
                "t_s": round(t, 4),
                "mode": d.get("mode"),
                "alpha_deg": d.get("pend_position_deg"),
                "theta_deg": d.get("position_deg"),
                "hybrid_lqr": d.get("hybrid_lqr"),
                "pwm": d.get("pwm"),
            }
        )
        if d.get("mode") == 0:
            break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)

    hold, reached = longest_hold(rows)
    d = q.state()
    return (
        {
            "rep": idx,
            "he": he,
            "homing_range": round(float(h.get("homing_range", 0.0)), 2),
            "reached": reached,
            "hold_s": round(hold, 2),
            "used_lqr": used_lqr,
            "loop_dt_max_us": d.get("loop_dt_max_us"),
            "loop_overruns": d.get("loop_overruns"),
            "pend_wraps": d.get("pend_wraps"),
            "ceiling_hits": d.get("swing_ceiling_hits"),
            "ended_in_stop": rows[-1]["mode"] == 0 if rows else None,
        },
        rows,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--he", type=float, default=165.0, help="165=hibrido (LQR balancea); 179=politica sola")
    ap.add_argument("--max-s", type=float, default=25.0)
    args = ap.parse_args()

    q = Qube(args.ip)
    d = q.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if d.get("hybrid_enter_deg") is None:
        raise SystemExit("Firmware sin `hybrid_enter_deg` en /state: hay que flashear >= v1.58.6.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for i in range(1, args.reps + 1):
        print(f"\n--- intento {i}/{args.reps}  he={args.he} ---")
        try:
            summary, rows = attempt(q, args.he, i, args.max_s)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            q.cmd(m=0)
            continue
        if rows:
            name = f"m7_he{int(args.he)}_rep{i:02d}.csv"
            with (DATA_DIR / name).open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        print(
            f"  vertical={'si' if summary['reached'] else 'NO'}  hold={summary['hold_s']:.2f}s"
            f"  balanceo={'LQR' if summary['used_lqr'] else 'politica'}"
            f"  overruns={summary['loop_overruns']}"
        )
        results.append(summary)

    q.cmd(m=0, he=165.0)  # restaurar el default del firmware
    (DATA_DIR / f"m7_he{int(args.he)}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    if results:
        n = len(results)
        c1 = sum(r["reached"] for r in results)
        c2 = sum(r["hold_s"] >= HOLD_S for r in results)
        c3 = all((r["loop_overruns"] or 0) == 0 for r in results)
        print(f"\n=== criterio (he={args.he}, n={n}) ===")
        print(f"  1. alcanza la vertical:       {c1}/{n}   {'PASS' if c1 >= 3 else 'FAIL'} (exige >=3/5)")
        print(f"  2. sostiene >= {HOLD_S:.0f}s:          {c2}/{n}   {'PASS' if c2 >= 3 else 'FAIL'} (exige >=3/5)")
        print(f"  3. lazo sin overruns:         {'PASS' if c3 else 'FAIL'}")
        holds = sorted(r["hold_s"] for r in results)
        print(f"  holds: {holds}")
        lqr = sum(r["used_lqr"] for r in results)
        print(f"  balanceo por LQR en {lqr}/{n} intentos (el resto, la politica)")


if __name__ == "__main__":
    main()
