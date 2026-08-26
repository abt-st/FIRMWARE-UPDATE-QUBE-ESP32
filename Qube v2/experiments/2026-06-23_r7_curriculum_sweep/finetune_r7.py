"""R7 fine-tune: adjust sim friction to match real hardware, then continue training.

The R7 policy (95% balance in sim) gets trapped at θ≈-80°, α≈97° on hardware
because the real system has ~100× more friction than the sim.  This script:

1. Loads the R7 checkpoint (cur0.3_s0_best, 300k steps)
2. Creates a sim with friction 100× closer to real hardware
3. Fine-tunes for 200k steps with lower LR (3e-4 → 1e-4)
4. Evaluates with the standard balance metrics
5. Saves the best model for export

Usage::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/finetune_r7.py
"""
from __future__ import annotations

import contextlib
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = Path(__file__).resolve().parent
BASE_MODEL = REPORT_DIR / "models" / "r7_cur0.3_s0_best.zip"
OUT_DIR = REPORT_DIR / "models"

# ── Friction multipliers ──────────────────────────────────────────────────────
# Preliminary system ID (experiments/PROTOCOLO_IDENTIFICACION.md) shows Dp real
# is ~100× the nominal sim value.  We increase both Dr and Dp by 100× and widen
# the domain randomisation std to keep robustness.
FRICTION_MULT = 100.0


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def make_ftune_env(reward: str = "linear_alpha", near_upright_prob: float = 0.3) -> object:
    """Build sim env with adjusted friction matching real hardware."""
    from gymnasium.wrappers import TimeLimit
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_dynamics import QubeDynamics
    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

    # Create dynamics with 100× friction
    dyn = QubeDynamics(
        Dr=5e-6 * FRICTION_MULT,   # 5e-4 (was 5e-6)
        Dr_std=5e-6 * FRICTION_MULT,  # same ratio of std/mean
        Dp=1e-6 * FRICTION_MULT,   # 1e-4 (was 1e-6)
        Dp_std=5e-7 * FRICTION_MULT,  # same ratio
    )
    log(f"Dynamics: Dr={dyn.Dr:.2e} (±{dyn.Dr_std:.2e}), Dp={dyn.Dp:.2e} (±{dyn.Dp_std:.2e})")

    env: object = QubeSimEnv(
        dyn=dyn,
        control_freq=50,
        reward=reward,
        angle_limits=[100 * np.pi / 180, np.pi],  # match R7 training: theta=±100°
        speed_limits=[50.0, 400.0],
        velocity_filter_order=2,
        near_upright_prob=near_upright_prob,
    )
    env = TimeLimit(env, max_episode_steps=500)
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


def make_eval_env() -> object:
    """Sim env with adjusted friction for evaluation.

    Needs HistoryWrapper so model.predict() sees 36-dim obs.
    Metrics read _state directly from env.unwrapped._state.
    """
    from gymnasium.wrappers import TimeLimit
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_dynamics import QubeDynamics
    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

    dyn = QubeDynamics(
        Dr=5e-6 * FRICTION_MULT,
        Dr_std=5e-6 * FRICTION_MULT,
        Dp=1e-6 * FRICTION_MULT,
        Dp_std=5e-7 * FRICTION_MULT,
    )
    env: object = QubeSimEnv(
        dyn=dyn,
        control_freq=50,
        reward="linear_alpha",
        angle_limits=[100 * np.pi / 180, np.pi],
        speed_limits=[50.0, 400.0],
        velocity_filter_order=2,
    )
    env = TimeLimit(env, max_episode_steps=500)
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=False)
    return env


def evaluate_balance(model: object, n_episodes: int = 30) -> dict:
    """Evaluate swing-up + balance metrics (same as R7 sweep)."""
    from qube_rl.metrics import evaluate_balance as _eval

    eval_env = make_eval_env()
    try:
        return _eval(model, eval_env, n_episodes=n_episodes)
    finally:
        eval_env.close()


def main() -> None:
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import set_global_seeds

    set_global_seeds(0)

    if not BASE_MODEL.exists():
        log(f"ERROR: Base model not found: {BASE_MODEL}")
        sys.exit(1)

    log(f"Loading base model: {BASE_MODEL}")
    model = SAC.load(str(BASE_MODEL))

    # Create fine-tuning env with adjusted friction
    log("Creating fine-tuning env with 100× friction...")
    env = DummyVecEnv([lambda: make_ftune_env(reward="linear_alpha", near_upright_prob=0.3)])

    # Set the model's env and reduce learning rate for fine-tuning
    model.set_env(env)
    model.learning_rate = 1e-4  # lower LR for fine-tuning (was 3e-4)
    model.batch_size = 256

    log(f"Fine-tuning: 200k steps, LR={model.learning_rate:.0e}, friction_mult={FRICTION_MULT}x")
    log("Starting from step ~300k (R7 cur0.3_s0)")

    # Pre-fine-tune evaluation
    log("Pre-fine-tune evaluation (baseline)...")
    pre = evaluate_balance(model, n_episodes=20)
    log(f"  Baseline: balance={pre['balance_rate']*100:.0f}%, "
        f"upright={pre['upright_fraction']*100:.0f}%, "
        f"hold_best={pre['max_hold_s_best']:.2f}s")

    # Fine-tune
    t0 = time.time()
    best_balance = pre["balance_rate"]
    best_path: Path | None = None

    for chunk in range(4):  # 4 × 50k = 200k steps
        model.learn(total_timesteps=50_000, progress_bar=False, reset_num_timesteps=False)
        elapsed = time.time() - t0

        # Evaluate after each chunk
        metrics = evaluate_balance(model, n_episodes=20)
        log(f"  Chunk {chunk+1}/4 ({(chunk+1)*50}k): "
            f"balance={metrics['balance_rate']*100:.0f}%, "
            f"upright={metrics['upright_fraction']*100:.0f}%, "
            f"hold_best={metrics['max_hold_s_best']:.2f}s "
            f"({elapsed/3600:.1f}h)")

        # Save best
        if metrics["balance_rate"] > best_balance:
            best_balance = metrics["balance_rate"]
            best_path = OUT_DIR / f"r7_finetune_friction{FRICTION_MULT:.0f}x_best.zip"
            model.save(str(best_path))
            log(f"  ★ New best saved: {best_path}")

    # Save final
    final_path = OUT_DIR / f"r7_finetune_friction{FRICTION_MULT:.0f}x_final.zip"
    model.save(str(final_path))
    log(f"Final model saved: {final_path}")

    # Post-fine-tune evaluation (more episodes)
    log("Post-fine-tune evaluation (50 episodes)...")
    post = evaluate_balance(model, n_episodes=50)
    log(f"  Result: balance={post['balance_rate']*100:.0f}%, "
        f"upright={post['upright_fraction']*100:.0f}%, "
        f"hold_best={post['max_hold_s_best']:.2f}s")

    # Summary
    elapsed = time.time() - t0
    log(f"\n{'='*60}")
    log(f"FINE-TUNE COMPLETE ({elapsed/3600:.1f}h)")
    log(f"  Base (R7):     balance={pre['balance_rate']*100:.0f}%, hold={pre['max_hold_s_best']:.2f}s")
    log(f"  Fine-tuned:    balance={post['balance_rate']*100:.0f}%, hold={post['max_hold_s_best']:.2f}s")
    log(f"  Friction mult: {FRICTION_MULT}x")
    log(f"  Best model:    {best_path or '(no improvement)'}")
    log(f"  Final model:   {final_path}")
    log("Next: export -> flash -> test on hardware")
    log(f"  uv run python -m qube_rl.export_rltools --model {best_path or final_path} "
        f"--output src/firmware/esp32_qube/policy_weights.h")

    env.close()


if __name__ == "__main__":
    main()
