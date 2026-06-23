"""R6: Run R4-style training with theta_limit=100° (aligned with real hardware).

Reuses the proven R4 infrastructure (run_r4.py) but with aligned limits.
Saves checkpoints every 50k steps for resumability.

Usage::

    uv run python experiments/2026-06-22_r6_real_aligned/run_r6.py --timesteps 500000 --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
REPO_ROOT = REPORT_DIR.parent.parent
MLFLOW_EXPERIMENT = "qube_r6_real_aligned"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def train_one_seed(
    *,
    reward: str,
    near_upright_prob: float,
    seed: int,
    timesteps: int,
    theta_limit_deg: float,
    run_name: str,
    mlflow_kw: dict,
    eval_episodes: int,
    checkpoint_every: int,
) -> dict:
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    cfg = SACConfig()
    set_global_seeds(seed)

    theta_limit_rad = math.radians(theta_limit_deg)

    train_env = DummyVecEnv(
        [lambda: make_sim_env(
            reward=reward,
            near_upright_prob=near_upright_prob,
            angle_limits=[theta_limit_rad, math.pi],
        )]
    )
    train_env.seed(seed)

    model = SAC(
        "MlpPolicy",
        train_env,
        learning_rate=cfg.learning_rate,
        buffer_size=cfg.buffer_size,
        batch_size=cfg.batch_size,
        tau=cfg.tau,
        gamma=cfg.gamma,
        use_sde=cfg.use_sde,
        use_sde_at_warmup=cfg.use_sde_at_warmup,
        sde_sample_freq=cfg.sde_sample_freq,
        train_freq=cfg.train_freq,
        gradient_steps=cfg.gradient_steps,
        learning_starts=cfg.learning_starts,
        seed=seed,
        verbose=0,
        policy_kwargs=dict(net_arch=dict(pi=[cfg.net_arch, cfg.net_arch], qf=[cfg.net_arch, cfg.net_arch])),
    )

    params = build_params(
        seed=seed, reward=reward, potential="None", timesteps=timesteps,
        net_arch=cfg.net_arch, run_name=run_name,
    )
    params["near_upright_prob"] = near_upright_prob
    params["theta_limit_deg"] = theta_limit_deg
    params["gamma"] = cfg.gamma
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / f"r6_{run_name}.zip"

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw):
        # Train with periodic checkpoints
        remaining = timesteps
        step_done = 0
        while remaining > 0:
            chunk = min(checkpoint_every, remaining)
            log(f"  Training {step_done:,} to {step_done + chunk:,} ...")
            model.learn(
                total_timesteps=chunk,
                reset_num_timesteps=(step_done == 0),
                progress_bar=True,
                callback=make_metrics_callback(enabled=mlflow_kw["enabled"], log_freq=500),
            )
            step_done += chunk
            remaining -= chunk
            ckpt_path = models_dir / f"r6_{run_name}_step{step_done}.zip"
            model.save(str(ckpt_path))
            log(f"  Checkpoint: {ckpt_path.name}")

        elapsed = time.time() - t0
        model.save(str(model_path))

        ep_infos = list(model.ep_info_buffer or [])
        ep_rewards = [ep["r"] for ep in ep_infos]
        ep_lengths = [ep["l"] for ep in ep_infos]

        eval_env = make_sim_env(
            reward=reward,
            angle_limits=[theta_limit_rad, math.pi],
        )
        balance = evaluate_balance(model, eval_env, n_episodes=eval_episodes, control_freq=50)

        result = {
            "run_name": run_name,
            "seed": seed,
            "timesteps": timesteps,
            "elapsed_s": elapsed,
            "fps": timesteps / elapsed if elapsed > 0 else 0.0,
            "ep_rew_mean": float(np.mean(ep_rewards)) if ep_rewards else 0.0,
            "ep_len_mean": float(np.mean(ep_lengths)) if ep_lengths else 0.0,
            "reach_rate": balance["reach_rate"],
            "balance_rate": balance["balance_rate"],
            "upright_fraction": balance["upright_fraction"],
            "max_hold_s": balance["max_hold_s"],
            "max_hold_s_best": balance["max_hold_s_best"],
            "model_path": str(model_path),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="R6: sim training aligned with real hardware")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--theta-limit", type=float, default=100.0)
    parser.add_argument("--near-upright-prob", type=float, default=0.4)
    parser.add_argument("--checkpoint-every", type=int, default=50_000)
    parser.add_argument("--eval-episodes", type=int, default=30)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    args = parser.parse_args()

    mlflow_kw = {"enabled": True, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}

    log("=" * 60)
    log("R6: Sim training aligned with real hardware")
    log(f"  theta_limit: ±{args.theta_limit}°")
    log(f"  timesteps/seed: {args.timesteps:,}")
    log(f"  seeds: {args.seeds}")
    log(f"  near_upright_prob: {args.near_upright_prob}")
    log(f"  checkpoint every: {args.checkpoint_every:,}")
    log("=" * 60)

    all_results = []
    started = time.time()

    for seed in args.seeds:
        run_name = f"theta{args.theta_limit:.0f}_s{seed}"
        log(f"\n=== Training {run_name} ===")
        try:
            r = train_one_seed(
                reward="linear_alpha",
                near_upright_prob=args.near_upright_prob,
                seed=seed,
                timesteps=args.timesteps,
                theta_limit_deg=args.theta_limit,
                run_name=run_name,
                mlflow_kw=mlflow_kw,
                eval_episodes=args.eval_episodes,
                checkpoint_every=args.checkpoint_every,
            )
            all_results.append(r)
            log(f"  Done: balance={r['balance_rate']*100:.1f}% "
                f"upright={r['upright_fraction']*100:.1f}% "
                f"hold={r['max_hold_s_best']:.2f}s ({r['elapsed_s']/60:.1f} min)")
        except Exception as exc:
            log(f"  ERROR: {exc}")
            traceback.print_exc()

    if all_results:
        log("\n" + "=" * 60)
        log("RESULTS:")
        for r in all_results:
            log(f"  seed={r['seed']}: balance={r['balance_rate']*100:.1f}% "
                f"upright={r['upright_fraction']*100:.1f}% "
                f"hold={r['max_hold_s_best']:.2f}s ({r['elapsed_s']/60:.1f} min)")
        avg_b = sum(r['balance_rate'] for r in all_results) / len(all_results)
        log(f"  AVG balance: {avg_b*100:.1f}%")
        log("=" * 60)

    log(f"ALL DONE in {(time.time()-started)/60:.1f} min")


if __name__ == "__main__":
    main()
