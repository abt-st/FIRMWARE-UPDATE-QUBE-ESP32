"""Continue R6 seed 2 from 300k (200k remaining)."""
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

    ckpt = str(REPORT_DIR / "models/r6_theta100_s2_step300000")
    log(f"Loading: {ckpt}")
    model = SAC.load(ckpt, env=env)

    models_dir = REPORT_DIR / "models"
    params = build_params(seed=2, reward="linear_alpha", potential="None",
                          timesteps=500_000, net_arch=cfg.net_arch, run_name="theta100_s2")
    params["start_step"] = 300_000
    mlflow_kw = {"enabled": True, "uri": "sqlite:///mlflow.db", "experiment": MLFLOW_EXPERIMENT}
    t0 = time.time()

    with mlflow_run("theta100_s2_from300000", params, **mlflow_kw):
        done = 0
        while done < 200_000:
            chunk = min(50_000, 200_000 - done)
            step = 300_000 + done
            log(f"  [s2] {step:,} to {step + chunk:,}")
            model.learn(total_timesteps=chunk, reset_num_timesteps=False,
                        progress_bar=True, callback=make_metrics_callback(True, 500))
            done += chunk
            model.save(str(models_dir / f"r6_theta100_s2_step{300_000 + done}.zip"))
            log(f"  Checkpoint: r6_theta100_s2_step{300_000 + done}.zip")

    model.save(str(models_dir / "r6_theta100_s2.zip"))
    log("Final model saved")

    eval_env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
    balance = evaluate_balance(model, eval_env, n_episodes=30, control_freq=50)
    log(f"  Seed 2 FINAL: balance={balance['balance_rate']*100:.1f}% "
        f"upright={balance['upright_fraction']*100:.1f}% hold={balance['max_hold_s_best']:.2f}s")
    log(f"  Done in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
