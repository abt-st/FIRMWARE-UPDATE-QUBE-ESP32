"""Finish R6 seed 1 eval from 450k, then run seed 2."""
from __future__ import annotations
import contextlib
import math
import sys
import time
from datetime import datetime
from pathlib import Path
import traceback

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
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance

    cfg = SACConfig()
    models_dir = REPORT_DIR / "models"

    # Seed 1: load from 450k checkpoint, save final, eval
    log("--- Seed 1: eval from 450k checkpoint ---")
    set_global_seeds(1)
    ckpt = str(REPORT_DIR / "models/r6_theta100_s1_step450000")
    log(f"Loading: {ckpt}")
    model = SAC.load(ckpt)
    model.save(str(models_dir / "r6_theta100_s1.zip"))
    log("Final model saved: r6_theta100_s1.zip")

    eval_env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
    balance = evaluate_balance(model, eval_env, n_episodes=30, control_freq=50)
    log(f"  Seed 1 FINAL: balance={balance['balance_rate']*100:.1f}% "
        f"upright={balance['upright_fraction']*100:.1f}% hold={balance['max_hold_s_best']:.2f}s")

    # Seed 2: from scratch
    log("\n--- Seed 2: from scratch ---")
    from stable_baselines3.common.vec_env import DummyVecEnv
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    set_global_seeds(2)
    env = DummyVecEnv([lambda: make_sim_env(reward="linear_alpha", near_upright_prob=0.4,
                                             angle_limits=[THETA_RAD, math.pi])])
    env.seed(2)
    model2 = SAC("MlpPolicy", env, learning_rate=cfg.learning_rate, buffer_size=cfg.buffer_size,
                  batch_size=cfg.batch_size, tau=cfg.tau, gamma=cfg.gamma, use_sde=cfg.use_sde,
                  use_sde_at_warmup=cfg.use_sde_at_warmup, sde_sample_freq=cfg.sde_sample_freq,
                  train_freq=cfg.train_freq, gradient_steps=cfg.gradient_steps,
                  learning_starts=cfg.learning_starts, seed=2, verbose=0,
                  policy_kwargs=dict(net_arch=dict(pi=[cfg.net_arch, cfg.net_arch],
                                                   qf=[cfg.net_arch, cfg.net_arch])))

    params = build_params(seed=2, reward="linear_alpha", potential="None",
                          timesteps=500_000, net_arch=cfg.net_arch, run_name="theta100_s2")
    params["start_step"] = 0
    mlflow_kw = {"enabled": True, "uri": "sqlite:///mlflow.db", "experiment": MLFLOW_EXPERIMENT}
    t0 = time.time()

    with mlflow_run("theta100_s2_from0", params, **mlflow_kw):
        done = 0
        remaining = 500_000
        while done < remaining:
            chunk = min(50_000, remaining - done)
            step = done
            log(f"  [s2] {step:,} to {step + chunk:,}")
            model2.learn(total_timesteps=chunk, reset_num_timesteps=(done == 0),
                         progress_bar=True, callback=make_metrics_callback(True, 500))
            done += chunk
            model2.save(str(models_dir / f"r6_theta100_s2_step{done}.zip"))
            log(f"  Checkpoint: r6_theta100_s2_step{done}.zip")

    model2.save(str(models_dir / "r6_theta100_s2.zip"))
    log(f"  Seed 2 done in {(time.time()-t0)/60:.1f} min")

    balance2 = evaluate_balance(model2, make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi]),
                                 n_episodes=30, control_freq=50)
    log(f"  Seed 2 FINAL: balance={balance2['balance_rate']*100:.1f}% "
        f"upright={balance2['upright_fraction']*100:.1f}% hold={balance2['max_hold_s_best']:.2f}s")

    log("ALL DONE")


if __name__ == "__main__":
    main()
