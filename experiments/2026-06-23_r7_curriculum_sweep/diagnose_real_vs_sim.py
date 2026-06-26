"""Run the SAME policy on the real rig and in sim, log per-step telemetry, and
report WHERE they diverge — the highest-leverage sim2real diagnostic.

The 100-ep re-eval showed sim balance is flat across friction, so sim can't tell
us if friction is the real-hold bottleneck. This script answers it empirically:

  - If the real rig reaches the apex but can't HOLD — action saturates and
    |alpha_dot| collapses near upright while sim holds fine — the gap is
    friction/torque (the friction-adaptation approach is justified → measure the
    multiplier with measure_friction_spindown.py).
  - If the real rig sends a DIFFERENT action than sim for the same state, or never
    reaches the apex though sim does, the gap is latency / sensor noise / actuator
    saturation / deadzone — and no friction sweep will fix it.

Logs raw state [theta, alpha, theta_dot, alpha_dot] (sim convention; the real env
already corrects the motor sign-flip and emits /rl_state in sim convention, pv=2),
the policy action (pre motor-sign, comparable to sim), and reward, for each step.
Saves one tidy CSV (source ∈ {real, sim, sim_frN}) and prints a comparison table.

Usage::

    uv run python .../diagnose_real_vs_sim.py --ip 192.168.4.1 \
        --model .../models/r7_cur0.3_s0_best.zip --episodes 3 --scale 0.85
    # add a friction-matched sim trace for a 3-way compare:
    uv run python .../diagnose_real_vs_sim.py ... --friction-mult 100
    # sim-only dry run (no hardware):
    uv run python .../diagnose_real_vs_sim.py --skip-real --episodes 5

Ctrl+C cuts the motor.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import math
import signal
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

THETA, ALPHA, THETA_DOT, ALPHA_DOT = 0, 1, 2, 3
THETA_LIMIT_DEG = 100.0
APEX_THRESH_RAD = math.radians(15.0)   # within 15° of upright counts as "at apex"
SAT_THRESH = 0.95                      # |action| above this = saturated


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _dist_upright(alpha: float) -> float:
    """Angular distance to the inverted equilibrium (alpha=±π), wrapped."""
    a = ((alpha + math.pi) % (2 * math.pi)) - math.pi
    return math.pi - abs(a)


def run_policy(env, model, *, n_episodes: int, max_steps: int, source: str,
               control_freq: int = 50) -> tuple[list[dict], dict]:
    """Roll the policy, returning per-step rows and aggregate stats."""
    rows: list[dict] = []
    per_ep = []
    for ep in range(n_episodes):
        obs, _ = env.reset()
        states, actions = [], []
        for _ in range(max_steps):
            action, _ = model.predict(obs, deterministic=True)
            obs, rwd, term, trunc, _ = env.step(action)
            st = np.asarray(env.unwrapped._state, dtype=float)
            a = float(np.asarray(action).reshape(-1)[0])
            states.append(st)
            actions.append(a)
            rows.append({
                "source": source, "episode": ep,
                "theta": st[THETA], "alpha": st[ALPHA],
                "theta_dot": st[THETA_DOT], "alpha_dot": st[ALPHA_DOT],
                "action": a, "reward": float(rwd),
                "dist_upright": _dist_upright(st[ALPHA]),
            })
            if term or trunc:
                break
        states = np.asarray(states)
        actions = np.asarray(actions)
        dist = np.array([_dist_upright(s[ALPHA]) for s in states])
        apex = dist < APEX_THRESH_RAD
        # Longest consecutive apex run -> hold seconds.
        best_run = run = 0
        for at in apex:
            run = run + 1 if at else 0
            best_run = max(best_run, run)
        ep_stat = {
            "reached_apex": bool(apex.any()),
            "min_dist_deg": float(math.degrees(dist.min())) if dist.size else float("nan"),
            "hold_s": best_run / control_freq,
            "apex_sat_frac": float(np.mean(np.abs(actions[apex]) > SAT_THRESH)) if apex.any() else float("nan"),
            "apex_ald_mean": float(np.mean(np.abs(states[apex, ALPHA_DOT]))) if apex.any() else float("nan"),
        }
        per_ep.append(ep_stat)
        log(f"  [{source}] ep {ep+1}/{n_episodes}: reach={ep_stat['reached_apex']} "
            f"min_dist={ep_stat['min_dist_deg']:.0f}° hold={ep_stat['hold_s']:.2f}s "
            f"apex_sat={ep_stat['apex_sat_frac']:.2f} apex|ald|={ep_stat['apex_ald_mean']:.1f}")

    def _agg(key: str) -> float:
        vals = [e[key] for e in per_ep if isinstance(e[key], float) and math.isfinite(e[key])]
        return float(np.mean(vals)) if vals else float("nan")

    stats = {
        "source": source,
        "reach_rate": float(np.mean([e["reached_apex"] for e in per_ep])) if per_ep else float("nan"),
        "min_dist_deg": _agg("min_dist_deg"),
        "hold_s": _agg("hold_s"),
        "apex_sat_frac": _agg("apex_sat_frac"),
        "apex_ald_mean": _agg("apex_ald_mean"),
    }
    return rows, stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ip", default="192.168.4.1", help="ESP32 IP (SoftAP default)")
    p.add_argument("--model", default=str(HERE / "models" / "r7_cur0.3_s0_best.zip"))
    p.add_argument("--episodes", type=int, default=3)
    p.add_argument("--max-steps", type=int, default=500, help="500 = 10s @ 50 Hz")
    p.add_argument("--scale", type=float, default=0.85, help="real torque cap (mode 6)")
    p.add_argument("--friction-mult", type=float, default=0.0,
                   help="if >0, also roll the policy in sim at this friction× (3-way compare)")
    p.add_argument("--skip-real", action="store_true", help="sim-only (no hardware)")
    p.add_argument("--skip-sim", action="store_true")
    p.add_argument("--out", default="", help="output CSV (default diagnose_<ts>.csv)")
    args = p.parse_args()

    import gymnasium as gym
    from stable_baselines3 import SAC

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: model not found: {model_path}")
        sys.exit(1)
    log(f"Loading {model_path.name}")
    model = SAC.load(str(model_path))

    theta_rad = math.radians(THETA_LIMIT_DEG)
    all_rows: list[dict] = []
    summaries: list[dict] = []

    class ActionScale(gym.Wrapper):
        """Cap real torque on the mode-6 HTTP path (mirrors finetune_real)."""
        def __init__(self, env, scale):
            super().__init__(env)
            self._scale = scale

        def step(self, action):
            return self.env.step(np.clip(np.asarray(action) * self._scale, -1.0, 1.0).astype(np.float32))

    real_env = None

    def _emergency_stop(*_a) -> None:
        log("Ctrl+C — emergency stop")
        with contextlib.suppress(Exception):
            import requests
            requests.get(f"http://{args.ip}/cmd", params={"m": "0"}, timeout=3)
        with contextlib.suppress(Exception):
            if real_env is not None:
                real_env.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _emergency_stop)

    # ── REAL ─────────────────────────────────────────────────────────────
    if not args.skip_real:
        import requests

        from qube_rl.envs.factory import make_real_env
        log(f"Setting torque scale={args.scale} on {args.ip}")
        with contextlib.suppress(Exception):
            requests.get(f"http://{args.ip}/rl_cmd", params={"scale": str(args.scale)}, timeout=3)
        real_env = ActionScale(
            make_real_env(esp32_ip=args.ip, reward="linear_alpha",
                          max_episode_steps=args.max_steps, auto_set_mode=True,
                          angle_limits=[theta_rad, math.pi]),
            scale=args.scale)
        log("Rolling policy on REAL rig…")
        try:
            rrows, rstats = run_policy(real_env, model, n_episodes=args.episodes,
                                       max_steps=args.max_steps, source="real")
            all_rows += rrows
            summaries.append(rstats)
        finally:
            with contextlib.suppress(Exception):
                requests.get(f"http://{args.ip}/cmd", params={"m": "0"}, timeout=3)
            with contextlib.suppress(Exception):
                real_env.close()

    # ── SIM (nominal) ────────────────────────────────────────────────────
    if not args.skip_sim:
        from qube_rl.envs.factory import make_sim_env
        sim_env = make_sim_env(reward="linear_alpha", control_freq=50,
                               angle_limits=[theta_rad, math.pi],
                               max_episode_steps=args.max_steps)
        log("Rolling policy in SIM (nominal friction)…")
        srows, sstats = run_policy(sim_env, model, n_episodes=args.episodes,
                                   max_steps=args.max_steps, source="sim")
        all_rows += srows
        summaries.append(sstats)
        with contextlib.suppress(Exception):
            sim_env.close()

    # ── SIM (friction-matched, optional) ─────────────────────────────────
    if args.friction_mult > 0:
        from train_overnight_friction import _make_env  # same builder as the sweep
        fenv = _make_env(args.friction_mult, train=False)
        label = f"sim_fr{int(args.friction_mult)}"
        log(f"Rolling policy in SIM at friction×{args.friction_mult:.0f}…")
        frows, fstats = run_policy(fenv, model, n_episodes=args.episodes,
                                   max_steps=args.max_steps, source=label)
        all_rows += frows
        summaries.append(fstats)
        with contextlib.suppress(Exception):
            fenv.close()

    # ── Persist + summarise ──────────────────────────────────────────────
    out = Path(args.out) if args.out else HERE / f"diagnose_{datetime.now():%Y%m%dT%H%M%S}.csv"
    if not out.is_absolute():
        out = HERE / out
    cols = ["source", "episode", "theta", "alpha", "theta_dot", "alpha_dot",
            "action", "reward", "dist_upright"]
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)
    log(f"Wrote {len(all_rows)} rows -> {out}")

    print(f"\n{'source':>10s} | {'reach%':>6s} {'min_dist°':>9s} {'hold(s)':>7s} "
          f"{'apex_sat':>8s} {'apex|ald|':>9s}", flush=True)
    print("-" * 60, flush=True)
    for s in summaries:
        print(f"{s['source']:>10s} | {s['reach_rate']*100:5.0f}% {s['min_dist_deg']:9.0f} "
              f"{s['hold_s']:7.2f} {s['apex_sat_frac']:8.2f} {s['apex_ald_mean']:9.1f}", flush=True)

    # ── Interpretation hint ──────────────────────────────────────────────
    real = next((s for s in summaries if s["source"] == "real"), None)
    sim = next((s for s in summaries if s["source"] == "sim"), None)
    if real and sim:
        print("\nInterpretacion:", flush=True)
        if real["reach_rate"] < 0.5 <= sim["reach_rate"]:
            print("  · Real NO llega al apex aunque sim si -> NO es solo friccion de hold: "
                  "revisar latencia/escala de torque/swing-up. Un sweep de friccion no lo arregla.",
                  flush=True)
        elif real["reach_rate"] >= 0.5 and real["hold_s"] < 0.5 * sim["hold_s"]:
            sat = real["apex_sat_frac"]
            print(f"  · Real llega al apex pero NO aguanta (hold {real['hold_s']:.2f}s vs "
                  f"sim {sim['hold_s']:.2f}s).", flush=True)
            if math.isfinite(sat) and sat > 0.5:
                print("    Accion saturada en el apex -> torque/friccion confirmado. "
                      "Medir el multiplicador (measure_friction_spindown.py).", flush=True)
            else:
                print("    Accion NO saturada -> mas probable sensor/velocidad/latencia que friccion pura.",
                      flush=True)
        else:
            print("  · Real y sim comparables — el gap puede estar en otro lado (revisar trazas CSV).",
                  flush=True)
        print("  Inspecciona el CSV (alpha/action/alpha_dot por step) para confirmar.", flush=True)


if __name__ == "__main__":
    main()
