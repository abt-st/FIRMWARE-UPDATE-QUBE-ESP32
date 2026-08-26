"""Continue R6 from latest checkpoints."""
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


def train_seed(seed: int, remaining: int, start_step: int, ckpt: str | None = None) -> None:
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    cfg = SACConfig()
    set_global_seeds(seed)
    env = DummyVecEnv([lambda: make_sim_env(reward="linear_alpha", near_upright_prob=0.4,
                                             angle_limits=[THETA_RAD, math.pi])])
    env.seed(seed)

    if ckpt:
        load_path = ckpt.removesuffix(".zip")
        log(f"Loading: {load_path}")
        model = SAC.load(load_path, env=env)
    else:
        model = SAC("MlpPolicy", env, learning_rate=cfg.learning_rate, buffer_size=cfg.buffer_size,
                     batch_size=cfg.batch_size, tau=cfg.tau, gamma=cfg.gamma, use_sde=cfg.use_sde,
                     use_sde_at_warmup=cfg.use_sde_at_warmup, sde_sample_freq=cfg.sde_sample_freq,
                     train_freq=cfg.train_freq, gradient_steps=cfg.gradient_steps,
                     learning_starts=cfg.learning_starts, seed=seed, verbose=0,
                     policy_kwargs=dict(net_arch=dict(pi=[cfg.net_arch, cfg.net_arch],
                                                      qf=[cfg.net_arch, cfg.net_arch])))

    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    name = f"theta100_s{seed}"
    params = build_params(seed=seed, reward="linear_alpha", potential="None",
                          timesteps=500_000, net_arch=cfg.net_arch, run_name=name)
    params["start_step"] = start_step
    mlflow_kw = {"enabled": True, "uri": "sqlite:///mlflow.db", "experiment": MLFLOW_EXPERIMENT}
    t0 = time.time()

    with mlflow_run(f"{name}_from{start_step}", params, **mlflow_kw):
        done = 0
        while done < remaining:
            chunk = min(50_000, remaining - done)
            step = start_step + done
            log(f"  [{name}] {step:,} to {step + chunk:,}")
            model.learn(total_timesteps=chunk, reset_num_timesteps=False,
                        progress_bar=True, callback=make_metrics_callback(True, 500))
            done += chunk
            model.save(str(models_dir / f"r6_{name}_step{start_step + done}.zip"))

    model.save(str(models_dir / f"r6_{name}.zip"))
    log(f"  [{name}] Done {done:,} steps in {(time.time()-t0)/60:.1f} min")


def main() -> None:
    log("R6 CONTINUE")
    # Seed 0: 300k done, 200k remaining
    log("\n--- Seed 0: from 300k ---")
    try:
        train_seed(0, 200_000, 300_000, str(REPORT_DIR / "models/r6_theta100_s0_step300000.zip"))
    except Exception as exc:
        log(f"Seed 0 ERROR: {exc}")
        traceback.print_exc()

    # Seed 1: 50k done, 450k remaining
    log("\n--- Seed 1: from 50k ---")
    try:
        train_seed(1, 450_000, 50_000, str(REPORT_DIR / "models/r6_theta100_s1_step50000.zip"))
    except Exception as exc:
        log(f"Seed 1 ERROR: {exc}")
        traceback.print_exc()

    # Seed 2: from scratch
    log("\n--- Seed 2: from scratch ---")
    try:
        train_seed(2, 500_000, 0, None)
    except Exception as exc:
        log(f"Seed 2 ERROR: {exc}")
        traceback.print_exc()

    log("ALL DONE")


if __name__ == "__main__":
    main()
