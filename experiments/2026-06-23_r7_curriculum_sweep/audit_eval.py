"""One-off audit: measure the ACTUAL balance of R4/R5/R6 candidates in sim.

Read-only. Resolves the contradiction between R6's HANDOFF ("50% balance") and
R5's FINAL_REPORT ("R1-R4: 0%"). Evaluates each model in the SAME sim env
(linear_alpha, theta=+/-100 deg) with both the standard reset (swing-up from
hanging) and the apex reset (stabilisation-only diagnostic).
"""
from __future__ import annotations

import contextlib
import math
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
THETA_RAD = math.radians(100.0)
N_EP = 15

CANDIDATES = [
    ("R6 s0 final(500k)", "experiments/2026-06-22_r6_real_aligned/models/r6_theta100_s0.zip"),
    ("R6 s0 step400k",    "experiments/2026-06-22_r6_real_aligned/models/r6_theta100_s0_step400000.zip"),
    ("R6 s0 step300k",    "experiments/2026-06-22_r6_real_aligned/models/r6_theta100_s0_step300000.zip"),
    ("R5 apex_anneal s0", "experiments/2026-06-22_r5_pbrs_curriculum/models/r5_01_apex_anneal_s0.zip"),
    ("R5 apex_anneal s1", "experiments/2026-06-22_r5_pbrs_curriculum/models/r5_01_apex_anneal_s1.zip"),
    ("R5 apex_anneal s2", "experiments/2026-06-22_r5_pbrs_curriculum/models/r5_01_apex_anneal_s2.zip"),
    ("R4_real s1 final",  "experiments/2026-06-22_r4_real/models/r4_real_s1_final.zip"),
]


def main() -> None:
    from stable_baselines3 import SAC

    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance

    hdr = f"{'model':22s} | {'std bal':>7s} {'reach':>6s} {'upr':>5s} {'hold*':>6s} | {'apex bal':>8s} {'apex hold*':>10s}"
    print(hdr)
    print("-" * len(hdr))
    for label, rel in CANDIDATES:
        path = ROOT / rel
        if not path.exists():
            print(f"{label:22s} | (missing)")
            continue
        try:
            model = SAC.load(str(path))
        except Exception as exc:  # noqa: BLE001
            print(f"{label:22s} | LOAD ERROR: {exc}")
            continue
        env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
        std = evaluate_balance(model, env, n_episodes=N_EP, control_freq=50)
        apex = {"balance_rate": float("nan"), "max_hold_s_best": float("nan")}
        with contextlib.suppress(Exception):
            aenv = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
            apex = evaluate_balance(model, aenv, n_episodes=N_EP, control_freq=50,
                                    reset_options={"near_upright": True})
        print(f"{label:22s} | {std['balance_rate']*100:6.1f}% {std['reach_rate']*100:5.0f}% "
              f"{std['upright_fraction']*100:4.0f}% {std['max_hold_s_best']:5.2f} | "
              f"{apex['balance_rate']*100:7.1f}% {apex['max_hold_s_best']:9.2f}")


if __name__ == "__main__":
    main()
