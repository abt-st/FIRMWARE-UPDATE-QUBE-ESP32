"""Fine-tune the best R4 model (01_curriculum04_s1) with 500k more steps.

The model already achieves 93% balance / 4.43s hold at 500k steps.
This script continues training with a lower LR to extend hold time
without catastrophic forgetting.

Usage::

    uv run python experiments/2026-06-22_r4_finetune_s1/run_finetune.py
    uv run python experiments/2026-06-22_r4_finetune_s1/run_finetune.py --timesteps 1000000
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# Windows consoles default to cp1252 and crash on non-ASCII; emit UTF-8 instead.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
REPO_ROOT = REPORT_DIR.parent.parent
BASE_MODEL = REPO_ROOT / "experiments/2026-06-19_r4_curriculum/models/r3_01_curriculum04_s1.zip"
MLFLOW_EXPERIMENT = "qube_r4_finetune"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def main() -> None:
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    parser = argparse.ArgumentParser(description="Fine-tune R4 best model (500k more steps)")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL), help="Base model to fine-tune")
    parser.add_argument("--timesteps", type=int, default=500_000, help="Additional timesteps")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate (lower for fine-tuning)")
    parser.add_argument("--seed", type=int, default=1, help="Seed (match base model)")
    parser.add_argument("--near-upright-prob", type=float, default=0.4, help="Curriculum prob (same as R4 best)")
    parser.add_argument("--mlflow", action="store_true", default=True, help="Track with MLflow")
    parser.add_argument("--mlflow-uri", type=str, default=None, help="MLflow tracking URI")
    parser.add_argument("--mlflow-experiment", type=str, default=MLFLOW_EXPERIMENT)
    parser.add_argument("--eval-episodes", type=int, default=30, help="Episodes for final eval")
    args = parser.parse_args()

    set_global_seeds(args.seed)

    # ── Load pre-trained model ──────────────────────────────────────────
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        return

    log(f"Loading base model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr
    log(f"LR set to {args.lr:.1e} (was 3e-4)")

    # ── Build training env ──────────────────────────────────────────────
    def _make():
        return make_sim_env(
            reward="linear_alpha",
            potential=None,
            near_upright_prob=args.near_upright_prob,
        )

    train_env = DummyVecEnv([_make])
    train_env.seed(args.seed)
    model.set_env(train_env)

    # ── Output paths ────────────────────────────────────────────────────
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_out = models_dir / f"r4_finetune_s{args.seed}_1m.zip"

    # ── MLflow ──────────────────────────────────────────────────────────
    cfg = SACConfig()
    params = build_params(
        seed=args.seed, reward="linear_alpha", potential="None",
        timesteps=args.timesteps, net_arch=64, run_name=f"finetune_s{args.seed}",
    )
    params["base_model"] = str(model_path)
    params["lr_finetune"] = args.lr
    params["lr_original"] = cfg.learning_rate
    params["near_upright_prob"] = args.near_upright_prob
    params["total_timesteps"] = "1M (500k base + 500k ft)"
    mlflow_kw = {"enabled": args.mlflow, "uri": args.mlflow_uri, "experiment": args.mlflow_experiment}
    cb_metrics = make_metrics_callback(enabled=args.mlflow)

    # ── Train ───────────────────────────────────────────────────────────
    log(f"Fine-tuning: {args.timesteps:,} steps, LR={args.lr:.1e}, seed={args.seed}")
    t0 = time.time()
    with mlflow_run(f"finetune_s{args.seed}", params, **mlflow_kw) as run:
        model.learn(
            total_timesteps=args.timesteps,
            progress_bar=True,
            callback=cb_metrics,
        )
        elapsed = time.time() - t0
        model.save(str(model_out))
        log(f"Model saved: {model_out}")

        # ── Final eval ──────────────────────────────────────────────────
        from qube_rl.metrics import evaluate_balance

        eval_env = make_sim_env(reward="linear_alpha")
        balance = evaluate_balance(model, eval_env, n_episodes=args.eval_episodes, control_freq=50)

        log("═══ FINAL EVAL (clean env, hanging reset) ═══")
        for k, v in balance.items():
            log(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

        if run:
            for k, v in balance.items():
                if isinstance(v, (int, float)):
                    run.log_metric(f"final/{k}", float(v))
            run.log_metric("final/fps", float(len(model.ep_info_buffer) / elapsed) if elapsed else 0)
            with contextlib.suppress(Exception):
                run.log_artifact(str(model_out))

    log(f"Done in {elapsed:.0f}s ({elapsed/3600:.1f}h)")


if __name__ == "__main__":
    main()
