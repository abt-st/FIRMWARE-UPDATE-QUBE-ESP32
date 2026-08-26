"""Finish R6 seed 2: last 100k from 400k + eval."""
from __future__ import annotations
import contextlib
import math
import sys
import time
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
MLFLOW_EXPERIMENT = "qube_r6_real_aligned"
THETA_RAD = math.radians(100.0)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def main() -> None:
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    cfg = SACConfig()
    set_global_seeds(2)
    env = DummyVecEnv([lambda: make_sim_env(reward="linear_alpha", near_upright_prob=0.4,
                                             angle_limits=[THETA_RAD, math.pi])])
    env.seed(2)

    ckpt = str(REPORT_DIR / "models/r6_theta100_s2_step400000")
    log(f"Loading: {ckpt}")
    model = SAC.load(ckpt, env=env)

    models_dir = REPORT_DIR / "models"
    params = build_params(seed=2, reward="linear_alpha", potential="None",
                          timesteps=500_000, net_arch=cfg.net_arch, run_name="theta100_s2")
    params["start_step"] = 400_000
    mlflow_kw = {"enabled": True, "uri": "sqlite:///mlflow.db", "experiment": MLFLOW_EXPERIMENT}
    t0 = time.time()

    with mlflow_run("theta100_s2_from400000", params, **mlflow_kw):
        log("  [s2] 400,000 to 500,000")
        model.learn(total_timesteps=100_000, reset_num_timesteps=False,
                    progress_bar=True, callback=make_metrics_callback(True, 500))

    model.save(str(models_dir / "r6_theta100_s2.zip"))
    log("Final model saved: r6_theta100_s2.zip")

    eval_env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
    balance = evaluate_balance(model, eval_env, n_episodes=30, control_freq=50)
    log(f"  Seed 2 FINAL: balance={balance['balance_rate']*100:.1f}% "
        f"upright={balance['upright_fraction']*100:.1f}% hold={balance['max_hold_s_best']:.2f}s")
    log(f"  Done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
