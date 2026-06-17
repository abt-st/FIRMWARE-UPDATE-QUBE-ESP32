"""Fast chunked training with RLtools-compatible network architecture.

Uses [64, 64] hidden layers (default) for direct ESP32 deployment via
RLtools C++ inference (~17 KB flash, ~1-2 KB RAM).  Saves checkpoints
after each chunk for progress monitoring.

Usage::

    uv run python -m qube_rl.fast_train
    uv run python -m qube_rl.fast_train --steps 100000 --chunk 20000
    uv run python -m qube_rl.fast_train --reward swingup_balance --net-arch 64
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper


def make_env(reward: str = "swingup_balance", angle_limit: float = np.pi / 2) -> object:
    """Build environment for fast training with standard wrappers."""
    env = QubeSimEnv(
        control_freq=50,
        reward=reward,
        angle_limits=[angle_limit, np.pi],
        speed_limits=[50.0, 400.0],
        encoders_cprs=None,
        velocity_filter_order=2,
    )
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fast chunked SAC training for QUBE")
    parser.add_argument("--steps", type=int, default=50_000, help="Total training timesteps")
    parser.add_argument("--chunk", type=int, default=10_000, help="Steps per checkpoint chunk")
    parser.add_argument("--reward", default="swingup_balance", help="Reward function name")
    parser.add_argument("--net-arch", type=int, default=64, help="Network hidden layer size")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
    parser.add_argument("--save-dir", default="models", help="Directory to save models")
    parser.add_argument("--log-dir", default="runs", help="TensorBoard log directory")
    parser.add_argument("--exp-name", default="fast", help="Experiment name for TensorBoard")
    args = parser.parse_args(argv)

    vec_env = DummyVecEnv([lambda: make_env(reward=args.reward)])

    model = SAC(
        "MlpPolicy",
        vec_env,
        learning_rate=args.lr,
        buffer_size=50_000,
        batch_size=args.batch_size,
        tau=0.005,
        gamma=0.99,
        use_sde=True,
        use_sde_at_warmup=True,
        sde_sample_freq=64,
        train_freq=1,
        gradient_steps=1,
        learning_starts=1000,
        tensorboard_log=args.log_dir,
        verbose=1,
        policy_kwargs=dict(net_arch=dict(pi=[args.net_arch, args.net_arch], qf=[args.net_arch, args.net_arch])),
    )

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    n_chunks = max(1, args.steps // args.chunk)
    t0 = time.time()

    for chunk in range(1, n_chunks + 1):
        print(f"\n=== CHUNK {chunk}/{n_chunks} ===")
        model.learn(
            total_timesteps=args.chunk,
            reset_num_timesteps=False,
            tb_log_name=f"{args.exp_name}_c{chunk}",
            progress_bar=False,
        )
        save_path = save_dir / f"qube_sac_{args.exp_name}_c{chunk}.zip"
        model.save(str(save_path))
        elapsed = time.time() - t0
        print(f"Saved {save_path} ({elapsed:.0f}s elapsed)")

    final_path = save_dir / f"qube_sac_{args.exp_name}.zip"
    model.save(str(final_path))
    print(f"\nFinal model saved to {final_path}")
    print(f"Total time: {time.time() - t0:.0f}s")
    print(f"Network: [{args.net_arch}, {args.net_arch}] — RLtools ESP32 compatible")
    print(f"To export for ESP32: uv run python -m qube_rl.export_rltools --model {final_path}")


if __name__ == "__main__":
    main()
