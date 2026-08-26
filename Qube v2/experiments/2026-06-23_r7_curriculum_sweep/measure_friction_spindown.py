"""Measure the REAL pendulum's viscous friction by free spin-down, and map it to
the sweep's `friction×N` multiplier by matching the decay against the simulator.

Why: the overnight sweep guessed the friction multiplier (20–130×) and the 100-ep
re-eval showed sim balance is FLAT across that range — sim can't tell you which N
is real. A spin-down measures it directly. Instead of doing the full pendulum-
inertia physics, we match a model-free decay metric (envelope half-life) between
the real trace and a sim free-decay swept over Dp, so the answer is exactly the
`friction×N` knob `train_overnight_friction.py` parameterises.

Two subcommands:

  capture  — talk to the ESP32 (mode 6, action=0 ⇒ 0 PWM coast), poll /rl_state and
             log (t, theta, alpha, theta_dot, alpha_dot) to CSV while you let the
             pendulum swing down from a small offset. Mode 6 keeps /rl_state fresh
             (updateRlObservation runs only in modes 6 & 7) and a=0 means no torque;
             we re-send a=0 every loop so the mode-6 command timeout never trips.
  analyze  — fit the real envelope half-life, sweep sim Dp multipliers, report the N
             whose sim free-decay best matches the real one.

Usage::

    uv run python .../measure_friction_spindown.py capture --ip 192.168.4.1 --duration 12 --out spindown_real.csv
    uv run python .../measure_friction_spindown.py analyze --csv spindown_real.csv --dp-mults 1 10 20 40 70 100 130

Run capture 3+ times and average (the earlier system-ID was n=1 and "inflated by
arm coupling"). Ctrl+C cuts the motor.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
# Sim nominal friction (QubeDynamics defaults); the sweep scales these.
DR_NOMINAL = 5e-6
DP_NOMINAL = 1e-6


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# capture
# ----------------------------------------------------------------------------

def cmd_capture(args: argparse.Namespace) -> None:
    import requests

    base = f"http://{args.ip}"
    sess = requests.Session()

    def _safe_stop() -> None:
        with contextlib.suppress(Exception):
            sess.get(f"{base}/rl_cmd", params={"a": "0.0"}, timeout=2)
        with contextlib.suppress(Exception):
            sess.get(f"{base}/cmd", params={"m": "0"}, timeout=2)

    try:
        log(f"Switching {args.ip} to mode 6 (HTTP RL, 0 PWM = coast)…")
        sess.get(f"{base}/cmd", params={"m": "6"}, timeout=3)
        time.sleep(0.2)
        sess.get(f"{base}/rl_cmd", params={"a": "0.0"}, timeout=3)

        # Protocol sanity (same handshake qube_real.py enforces).
        with contextlib.suppress(Exception):
            pv = sess.get(f"{base}/rl_state", timeout=3).json().get("pv")
            if pv is not None and int(pv) != 2:
                log(f"WARNING: /rl_state pv={pv} != 2 — firmware/convention mismatch.")

        print("\n  >>> Levanta el pendulo a ~45 grados desde la posicion colgando "
              "y MANTENLO.", flush=True)
        for k in range(args.countdown, 0, -1):
            print(f"      soltar en {k}…", flush=True)
            sess.get(f"{base}/rl_cmd", params={"a": "0.0"}, timeout=3)  # keep-alive
            time.sleep(1.0)
        print("  >>> GO — SUELTA AHORA. Capturando…\n", flush=True)

        period = 1.0 / args.rate
        rows: list[tuple] = []
        t0 = time.time()
        next_t = t0
        while time.time() - t0 < args.duration:
            # Keep mode 6 alive with 0 torque, then read the fresh observation.
            with contextlib.suppress(Exception):
                sess.get(f"{base}/rl_cmd", params={"a": "0.0"}, timeout=2)
            try:
                d = sess.get(f"{base}/rl_state", timeout=2).json()
                t = time.time() - t0
                rows.append((t, float(d["th"]), float(d["al"]),
                             float(d["thd"]), float(d["ald"])))
            except Exception as exc:  # noqa: BLE001
                log(f"  read failed: {exc}")
            next_t += period
            sleep = next_t - time.time()
            if sleep > 0:
                time.sleep(sleep)

        out = Path(args.out)
        if not out.is_absolute():
            out = HERE / out
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "theta", "alpha", "theta_dot", "alpha_dot"])
            w.writerows(rows)
        eff_rate = len(rows) / max(1e-6, rows[-1][0]) if rows else 0.0
        log(f"Captured {len(rows)} samples over {args.duration:.0f}s "
            f"(~{eff_rate:.0f} Hz effective) -> {out}")
    except KeyboardInterrupt:
        log("Ctrl+C — stopping.")
    finally:
        _safe_stop()
        sess.close()


# ----------------------------------------------------------------------------
# analyze
# ----------------------------------------------------------------------------

def _envelope_half_life(t: np.ndarray, al: np.ndarray) -> tuple[float, int]:
    """Half-life (s) of the oscillation envelope of a damped free swing.

    Uses the analytic (Hilbert) envelope of the de-trended swing, which is far
    more robust than counting local extrema at 50 Hz with sensor noise. The
    envelope of a lightly-damped oscillation decays as A0·exp(-λt); we fit
    log(envelope) vs t by least squares over the clean window (envelope above a
    floor) and return t_half = ln2/λ. λ is in 1/s, so the result is independent
    of the sampling rate — real (≈50 Hz) and sim (2 kHz) traces are comparable.
    Returns (t_half, n_points_fit); t_half = inf if no decay could be fit.
    """
    from scipy.signal import hilbert

    a = al - float(np.mean(al))           # de-trend by the hanging equilibrium
    if a.size < 8:
        return math.inf, 0
    env = np.abs(hilbert(a))
    # Smooth the envelope (~1/10 of the span) to suppress ripple.
    win = max(3, (a.size // 20) | 1)      # odd window
    env = np.convolve(env, np.ones(win) / win, mode="same")
    # Fit window: drop the smoothing transients at both ends, keep where the
    # envelope is still well above the noise floor (> 12% of its peak).
    pad = win
    t_f, env_f = t[pad:-pad], env[pad:-pad]
    if t_f.size < 5:
        return math.inf, int(t_f.size)
    floor = 0.12 * float(env_f.max())
    keep = env_f > floor
    t_f, env_f = t_f[keep], env_f[keep]
    if t_f.size < 5:
        return math.inf, int(t_f.size)
    slope, _ = np.polyfit(t_f - t_f[0], np.log(env_f), 1)
    lam = -slope
    if lam <= 0:
        return math.inf, int(t_f.size)
    return float(math.log(2.0) / lam), int(t_f.size)


def _sim_free_decay(dp_mult: float, al0: float, duration: float, dt: float = 5e-4,
                    lock_arm: bool = False):
    """Integrate the QUBE dynamics with zero action (free swing) at Dp×mult.

    All *_std set to 0 so QubeDynamics stays at deterministic nominal values
    (its __post_init__ randomize() then reproduces the means exactly).
    Semi-implicit (symplectic) Euler: viscous damping dominates, energy drift
    from the integrator is negligible at dt=5e-4.

    `lock_arm` mantiene theta fijo en 0 (brazo sujeto), y existe porque el
    docstring de este script afirmaba que en el real la accion 0 deja el motor en
    *coast*. **En este hardware es falso**: `setMotorDirect` pone duty 0 en IN1 y
    en IN2 a la vez, y un L298N con ENA en alto e IN1=IN2=LOW cortocircuita los
    bornes — freno dinamico. O sea que el brazo real esta frenado mientras el
    brazo simulado se mueve casi libre (Dr=5e-6), y el acoplamiento brazo-pendulo
    es un canal de perdida: el Dp que salga del match absorbe esa diferencia en
    vez de medir la friccion del pendulo.

    La salida limpia es eliminar el canal en los DOS lados: sujetar el brazo con
    la mano durante la captura y bloquear theta aca. Con el brazo sujeto deja de
    importar si el motor frena o no.
    """
    from qube_rl.envs.qube_dynamics import QubeDynamics

    dyn = QubeDynamics(
        Dr=DR_NOMINAL, Dr_std=0.0, Dp=DP_NOMINAL * dp_mult, Dp_std=0.0,
        Rm_std=0.0, km_std=0.0, Mr_std=0.0, Lr_std=0.0, Mp_std=0.0, Lp_std=0.0,
    )
    state = np.array([0.0, float(al0), 0.0, 0.0], dtype=float)
    n = int(duration / dt)
    ts = np.empty(n)
    als = np.empty(n)
    t = 0.0
    for i in range(n):
        if lock_arm:
            # Brazo sujeto: una fuerza externa impone thdd = 0, asi que NO se puede
            # usar el aldd de la matriz de masa acoplada — ese supone el brazo libre
            # de acelerar. La ecuacion restringida sale de la segunda fila del sistema
            # con thd = thdd = 0:  Jp*aldd = -Dp*ald - c4*sin(al).
            #
            # (Primera version de esto ponia theta/theta_dot en cero DESPUES de
            # integrar pero seguia tomando aldd del modelo acoplado: daba 12,09 rad/s
            # donde la analitica sqrt(c4/Jp) da 10,68. El real midio 10,46.)
            aldd = (-dyn.Dp * state[3] - dyn._c[4] * math.sin(state[1])) / dyn._c[3]
            state[3] += aldd * dt
            state[1] += state[3] * dt
        else:
            thdd, aldd = dyn(state, 0.0)
            state[3] += aldd * dt
            state[1] += state[3] * dt
            state[2] += thdd * dt
            state[0] += state[2] * dt
        ts[i] = t
        als[i] = state[1]
        t += dt
    return ts, als


def cmd_analyze(args: argparse.Namespace) -> None:
    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = HERE / csv_path
    data = np.genfromtxt(csv_path, delimiter=",", names=True)
    t = np.asarray(data["t"], dtype=float)
    al = np.asarray(data["alpha"], dtype=float)
    if t.size < 8:
        log(f"ERROR: only {t.size} samples in {csv_path} — capture longer.")
        sys.exit(1)

    real_th, real_n = _envelope_half_life(t, al)
    # Initial swing amplitude (max deviation from the hanging mean) for the sim IC.
    al0 = float(np.max(np.abs(al - np.mean(al))))
    duration = float(t[-1])
    log(f"Real: {t.size} samples, {real_n} envelope-fit pts, swing amp≈{math.degrees(al0):.0f}°, "
        f"t_half={real_th:.2f}s over {duration:.1f}s")
    if not math.isfinite(real_th):
        log("ERROR: could not fit a decay from the real trace (too few clean swings). "
            "Recapture with a bigger release angle / longer duration.")
        sys.exit(1)

    print(f"\n{'Dp mult':>8s} | {'sim t_half(s)':>13s} | {'|Δ| vs real':>11s}", flush=True)
    print("-" * 38, flush=True)
    results = []
    if args.lock_arm:
        log("Brazo BLOQUEADO en la sim (theta=0): comparar solo contra capturas "
            "hechas sujetando el brazo con la mano.")
    for mult in args.dp_mults:
        sts, sals = _sim_free_decay(mult, al0, duration, lock_arm=args.lock_arm)
        sth, _ = _envelope_half_life(sts, sals)
        diff = abs(sth - real_th) if math.isfinite(sth) else math.inf
        results.append((mult, sth, diff))
        sth_s = f"{sth:.2f}" if math.isfinite(sth) else "inf"
        print(f"{mult:>8.0f} | {sth_s:>13s} | {diff:>11.2f}", flush=True)

    finite = [r for r in results if math.isfinite(r[1])]
    if not finite:
        log("No sim multiplier produced a finite decay — widen --dp-mults.")
        return
    best = min(finite, key=lambda r: r[2])
    # Linear interpolation between the two bracketing mults for a finer estimate.
    finite.sort(key=lambda r: r[1])  # by sim t_half (monotone ↓ in mult)
    est = best[0]
    for (m_lo, th_lo, _), (m_hi, th_hi, _) in zip(finite, finite[1:]):
        if (th_lo - real_th) * (th_hi - real_th) <= 0 and th_lo != th_hi:
            frac = (real_th - th_lo) / (th_hi - th_lo)
            est = m_lo + frac * (m_hi - m_lo)
            break
    print("", flush=True)
    log(f"Closest grid multiplier: friction×{best[0]:.0f} "
        f"(sim t_half={best[1]:.2f}s vs real {real_th:.2f}s)")
    log(f"Interpolated estimate:   friction×{est:.0f}")
    log("Repeat capture 3+ times and average before committing to a fine-tune target.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("capture", help="record a real free spin-down to CSV")
    pc.add_argument("--ip", default="192.168.4.1", help="ESP32 IP (SoftAP default)")
    pc.add_argument("--duration", type=float, default=12.0, help="capture seconds")
    pc.add_argument("--rate", type=float, default=50.0, help="target poll Hz")
    pc.add_argument("--countdown", type=int, default=5, help="seconds before GO")
    pc.add_argument("--out", default="spindown_real.csv", help="output CSV")
    pc.set_defaults(func=cmd_capture)

    pa = sub.add_parser("analyze", help="fit real decay + match sim Dp multiplier")
    pa.add_argument("--csv", required=True, help="CSV from `capture`")
    pa.add_argument("--dp-mults", type=float, nargs="+",
                    default=[1, 10, 20, 40, 70, 100, 130],
                    help="sim Dp multipliers to sweep")
    pa.add_argument("--lock-arm", action="store_true",
                    help="bloquea theta=0 en la sim; usar SOLO con capturas hechas "
                         "sujetando el brazo (ver _sim_free_decay: con accion 0 el "
                         "L298N FRENA el brazo real, no lo deja en coast)")
    pa.set_defaults(func=cmd_analyze)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
