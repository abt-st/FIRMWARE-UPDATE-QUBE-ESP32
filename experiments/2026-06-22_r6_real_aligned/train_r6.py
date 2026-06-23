"""R6: Sim training aligned with real hardware limits.

Key difference from R4: theta_limit = ±100° (matches real firmware brake).
R4 used ±120° which caused sim→real transfer failure (servo hit mechanical stop).

Config: linear_alpha reward, near_upright_prob=0.4, 500k steps, 3 seeds.

Usage::

    uv run python experiments/2026-06-22_r6_real_aligned/train_r6.py
    uv run python experiments/2026-06-22_r6_real_aligned/train_r6.py --timesteps 500000 --seeds 0 1 2
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
    seed: int,
    timesteps: int,
    theta_limit_deg: float,
    near_upright_prob: float,
    run_name: str,
    mlflow_kw: dict,
) -> dict:
    """Train SAC for a single seed with aligned theta limit."""
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run
    from qube_rl.metrics import evaluate_balance
    import mlflow

    set_global_seeds(seed)
    cfg = SACConfig()

    # Build env with custom theta limit
    theta_limit_rad = math.radians(theta_limit_deg)

    def _make():
        return make_sim_env(
            reward="linear_alpha",
            potential=None,
            near_upright_prob=near_upright_prob,
            angle_limits=[theta_limit_rad, math.pi],
        )

    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    train_env = DummyVecEnv([_make])
    train_env.seed(seed)

    model = SAC(
        "MlpPolicy",
        train_env,
        learning_rate=cfg.learning_rate,
        buffer_size=cfg.buffer_size,
        batch_size=cfg.batch_size,
        gamma=cfg.gamma,
        tau=cfg.tau,
        use_sde=cfg.use_sde,
        use_sde_at_warmup=cfg.use_sde_at_warmup,
        sde_sample_freq=cfg.sde_sample_freq,
        train_freq=cfg.train_freq,
        gradient_steps=cfg.gradient_steps,
        learning_starts=cfg.learning_starts,
        policy_kwargs=dict(net_arch=[cfg.net_arch, cfg.net_arch]),
        verbose=0,
        seed=seed,
    )

    params = build_params(
        seed=seed,
        reward="linear_alpha",
        potential="None",
        timesteps=timesteps,
        net_arch=cfg.net_arch,
        run_name=run_name,
    )
    params["theta_limit_deg"] = theta_limit_deg
    params["near_upright_prob"] = near_upright_prob
    cb_metrics = make_metrics_callback(enabled=mlflow_kw.get("enabled", True))

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw):
        model.learn(
            total_timesteps=timesteps,
            progress_bar=True,
            callback=cb_metrics,
        )
        elapsed = time.time() - t0

    # Save model
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / f"r6_{run_name}.zip"
    model.save(str(model_path))
    log(f"Model saved: {model_path}")

    # Eval
    eval_env = make_sim_env(
        reward="linear_alpha",
        angle_limits=[theta_limit_rad, math.pi],
    )
    balance = evaluate_balance(model, eval_env, n_episodes=30, control_freq=50)

    result = {
        "seed": seed,
        "elapsed_s": elapsed,
        "model_path": str(model_path),
        **balance,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="R6 sim training: real-aligned limits")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--theta-limit", type=float, default=100.0,
                        help="Servo angle limit in degrees (matches real firmware)")
    parser.add_argument("--near-upright-prob", type=float, default=0.4)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    args = parser.parse_args()

    mlflow_kw = {"enabled": True, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}

    log("=" * 60)
    log("R6: Sim training aligned with real hardware")
    log(f"  theta_limit: ±{args.theta_limit}°")
    log(f"  timesteps: {args.timesteps:,}")
    log(f"  seeds: {args.seeds}")
    log(f"  near_upright_prob: {args.near_upright_prob}")
    log("=" * 60)

    results = []
    for seed in args.seeds:
        run_name = f"theta{args.theta_limit:.0f}_s{seed}"
        log(f"\n--- Training {run_name} ---")
        try:
            r = train_one_seed(
                seed=seed,
                timesteps=args.timesteps,
                theta_limit_deg=args.theta_limit,
                near_upright_prob=args.near_upright_prob,
                run_name=run_name,
                mlflow_kw=mlflow_kw,
            )
            results.append(r)
            log(f"  Done: balance={r.get('balance_rate', 0)*100:.1f}% "
                f"upright={r.get('upright_fraction', 0)*100:.1f}% "
                f"hold={r.get('max_hold_s_best', 0):.2f}s")
        except Exception as exc:
            log(f"  ERROR: {exc}")
            traceback.print_exc()

    # Summary
    if results:
        log("\n" + "=" * 60)
        log("RESULTS:")
        for r in results:
            log(f"  seed={r['seed']}: balance={r.get('balance_rate',0)*100:.1f}% "
                f"upright={r.get('upright_fraction',0)*100:.1f}% "
                f"hold={r.get('max_hold_s_best',0):.2f}s "
                f"({r['elapsed_s']/60:.1f} min)")
        avg_balance = sum(r.get('balance_rate', 0) for r in results) / len(results)
        log(f"  AVG balance: {avg_balance*100:.1f}%")
        log("=" * 60)

    log("ALL DONE")


if __name__ == "__main__":
    main()
