"""R4 fine-tune v2: save model BEFORE eval to prevent data loss.

The v1 script lost the model because evaluate_balance() crashed inside
the mlflow_run() context, preventing model.save() from flushing.

Usage::

    uv run python experiments/2026-06-22_r4_finetune_s1/run_finetune_v2.py
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


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def main() -> None:
    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env

    parser = argparse.ArgumentParser(description="R4 fine-tune v2 (save-then-eval)")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL))
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--near-upright-prob", type=float, default=0.4)
    parser.add_argument("--eval-episodes", type=int, default=30)
    args = parser.parse_args()

    set_global_seeds(args.seed)

    # ── Load model ──────────────────────────────────────────────────────
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        return

    log(f"Loading base model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr
    log(f"LR set to {args.lr:.1e}")

    # ── Build env ───────────────────────────────────────────────────────
    def _make():
        return make_sim_env(
            reward="linear_alpha",
            potential=None,
            near_upright_prob=args.near_upright_prob,
        )

    train_env = DummyVecEnv([_make])
    train_env.seed(args.seed)
    model.set_env(train_env)

    # ── Output path ─────────────────────────────────────────────────────
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_out = models_dir / f"r4_finetune_s{args.seed}_1m.zip"

    # ── Train ───────────────────────────────────────────────────────────
    log(f"Fine-tuning: {args.timesteps:,} steps, LR={args.lr:.1e}, seed={args.seed}")
    t0 = time.time()
    model.learn(
        total_timesteps=args.timesteps,
        progress_bar=True,
    )
    elapsed = time.time() - t0

    # ── SAVE FIRST (before any eval) ────────────────────────────────────
    model.save(str(model_out))
    log(f"Model saved: {model_out} ({elapsed:.0f}s)")

    # ── Eval separately (can fail without losing model) ─────────────────
    try:
        from qube_rl.metrics import evaluate_balance

        eval_env = make_sim_env(reward="linear_alpha")
        balance = evaluate_balance(model, eval_env, n_episodes=args.eval_episodes, control_freq=50)

        log("═══ FINAL EVAL (clean env, hanging reset) ═══")
        for k, v in balance.items():
            log(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    except Exception as exc:
        log(f"EVAL FAILED (model still saved): {exc}")

    log(f"Done in {elapsed:.0f}s ({elapsed / 3600:.1f}h)")


if __name__ == "__main__":
    main()
