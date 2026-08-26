"""Standalone balance eval for R6 checkpoints (the eval the crashed runs never reached).

Evaluates each on-disk r6 checkpoint with the SAME env as training:
linear_alpha reward, theta_limit = +/-100 deg. Read-only; safe to run alongside training.
"""
from __future__ import annotations

import contextlib
import math
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
THETA_RAD = math.radians(100.0)


def main() -> None:
    from stable_baselines3 import SAC

    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance

    ckpts = [
        "r6_theta100_s0_step150000.zip",
        "r6_theta100_s0_step200000.zip",
        "r6_theta100_s0_step250000.zip",
        "r6_theta100_s1_step50000.zip",
    ]

    print(f"{'checkpoint':38s} {'balance':>8s} {'reach':>7s} {'upright':>8s} {'hold_s':>7s} {'hold_best':>9s} {'ret':>8s}")
    print("-" * 92)
    for name in ckpts:
        path = REPORT_DIR / "models" / name
        if not path.exists():
            print(f"{name:38s}  (missing)")
            continue
        model = SAC.load(str(path))
        env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
        m = evaluate_balance(model, env, n_episodes=30, control_freq=50)
        print(f"{name:38s} {m['balance_rate']*100:7.1f}% {m['reach_rate']*100:6.0f}% "
              f"{m['upright_fraction']*100:7.1f}% {m.get('max_hold_s',0):6.2f} "
              f"{m.get('max_hold_s_best',0):8.2f} {m.get('return_mean',0):8.1f}")


if __name__ == "__main__":
    main()
