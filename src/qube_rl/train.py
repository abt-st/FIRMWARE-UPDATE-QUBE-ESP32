"""Train a SAC agent to swing up and balance the QUBE Servo pendulum.

Usage::

    uv run python -m qube_rl.train
    uv run python -m qube_rl.train --timesteps 500000 --reward swingup_balance
    uv run python -m qube_rl.train --net-arch 64 --reward swingup_balance

The trained model is saved to ``models/qube_sac_sim.zip``.
TensorBoard logs are written to ``runs/``.

Default network size is [64, 64] — compatible with RLtools C++ inference
on ESP32 (~17 KB flash, ~1-2 KB RAM).  Use ``--net-arch`` to change.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import gymnasium as gym
import numpy as np

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def make_env(control_freq: int = 50, reward: str = "cos_alpha") -> gym.Env:
    """Build the simulation environment with standard wrappers (no real-time delay)."""
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import (
        DeadZone,
        GentlyTerminating,
        HistoryWrapper,
    )

    env = QubeSimEnv(
        control_freq=control_freq,
        reward=reward,
        angle_limits=[np.pi / 2, np.pi],  # theta ±90°, alpha ±180°
        speed_limits=[50.0, 400.0],
        encoders_cprs=None,  # continuous in initial training
        velocity_filter_order=2,
    )
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    # NOTE: ControlFrequency is NOT used in training — only for real-time inference
    return env


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train SAC on QUBE Servo simulation")
    parser.add_argument("--timesteps", type=int, default=200_000, help="Total training timesteps")
    parser.add_argument("--reward", default="swingup_balance", help="Reward function name")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=256, help="Batch size")
    parser.add_argument("--buffer-size", type=int, default=1_000_000, help="Replay buffer size")
    parser.add_argument("--freq", type=int, default=50, help="Control frequency (Hz)")
    parser.add_argument(
        "--net-arch", type=int, default=64, help="Network hidden layer size (default: 64 for RLtools/ESP32)"
    )
    parser.add_argument("--save-dir", default="models", help="Directory to save the model")
    parser.add_argument("--log-dir", default="runs", help="TensorBoard log directory")
    parser.add_argument("--verbose", type=int, default=1, help="SB3 verbosity (0/1/2)")
    args = parser.parse_args(argv)

    # Lazy imports — SB3 / torch are heavy
    from stable_baselines3 import SAC
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.vec_env import DummyVecEnv

    # Build environment
    raw_env = make_env(control_freq=args.freq, reward=args.reward)
    logger.info("Checking environment compatibility with SB3...")
    check_env(raw_env, warn=True)
    logger.info("Environment OK.")

    vec_env = DummyVecEnv([lambda: raw_env])

    # Build model
    model = SAC(
        "MlpPolicy",
        vec_env,
        learning_rate=args.lr,
        buffer_size=args.buffer_size,
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
        verbose=args.verbose,
        policy_kwargs=dict(
            net_arch=dict(pi=[args.net_arch, args.net_arch], qf=[args.net_arch, args.net_arch]),
        ),
    )

    logger.info("Starting training: %d timesteps", args.timesteps)
    logger.info(
        "  reward=%s  lr=%.1e  freq=%d Hz  net=[%d,%d]", args.reward, args.lr, args.freq, args.net_arch, args.net_arch
    )

    model.learn(total_timesteps=args.timesteps, progress_bar=True)

    # Save
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    model_path = save_dir / f"qube_sac_{args.net_arch}x2.zip"
    model.save(str(model_path))
    logger.info("Model saved to %s", model_path)


if __name__ == "__main__":
    main()
