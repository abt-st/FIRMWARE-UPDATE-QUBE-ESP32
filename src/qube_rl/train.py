"""Train a SAC agent to swing up and balance the QUBE Servo pendulum.

Usage::

    uv run python -m qube_rl.train
    uv run python -m qube_rl.train --timesteps 500000 --reward swingup_balance
    uv run python -m qube_rl.train --net-arch 64 --reward swingup_balance

The trained model is saved to ``models/qube_sac_sim.zip``.
Pass ``--mlflow`` to track metrics, losses and the model artifact with MLflow.

Default network size is [64, 64] — compatible with RLtools C++ inference
on ESP32 (~17 KB flash, ~1-2 KB RAM).  Use ``--net-arch`` to change.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import gymnasium as gym

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def make_env(control_freq: int = 50, reward: str = "cos_alpha") -> gym.Env:
    """Build the simulation environment with standard wrappers (no real-time delay)."""
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.config import EnvConfig, WrapperConfig
    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import (
        DeadZone,
        GentlyTerminating,
        HistoryWrapper,
    )

    env_cfg = EnvConfig(control_freq=control_freq, reward=reward)
    wrap_cfg = WrapperConfig()

    env = QubeSimEnv(
        control_freq=env_cfg.control_freq,
        reward=env_cfg.reward,
        angle_limits=env_cfg.angle_limits,  # theta ±90°, alpha ±180°
        speed_limits=env_cfg.speed_limits,
        encoders_cprs=None,  # continuous in initial training
        velocity_filter_order=env_cfg.velocity_filter_order,
    )
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=wrap_cfg.deadzone, center=wrap_cfg.deadzone_center, max_act=wrap_cfg.deadzone_max_act)
    env = HistoryWrapper(env, steps=wrap_cfg.history_steps, use_continuity_cost=wrap_cfg.use_continuity_cost)
    # NOTE: ControlFrequency is NOT used in training — only for real-time inference
    return env


def main(argv: list[str] | None = None) -> None:
    from qube_rl.config import DEFAULT_SEED, SACConfig, set_global_seeds

    sac_cfg = SACConfig()

    parser = argparse.ArgumentParser(description="Train SAC on QUBE Servo simulation")
    parser.add_argument("--timesteps", type=int, default=200_000, help="Total training timesteps")
    parser.add_argument("--reward", default="swingup_balance", help="Reward function name")
    parser.add_argument("--lr", type=float, default=sac_cfg.learning_rate, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=sac_cfg.batch_size, help="Batch size")
    parser.add_argument("--buffer-size", type=int, default=sac_cfg.buffer_size, help="Replay buffer size")
    parser.add_argument("--freq", type=int, default=50, help="Control frequency (Hz)")
    parser.add_argument(
        "--net-arch", type=int, default=sac_cfg.net_arch, help="Network hidden layer size (default: 64 for ESP32)"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed (omit for non-deterministic)")
    parser.add_argument("--save-dir", default="models", help="Directory to save the model")
    parser.add_argument("--verbose", type=int, default=1, help="SB3 verbosity (0/1/2)")
    parser.add_argument("--mlflow", action="store_true", help="Track this run with MLflow (params, metrics, artifact)")
    parser.add_argument(
        "--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite:///mlflow.db or env var)"
    )
    parser.add_argument("--mlflow-experiment", default="qube_sac", help="MLflow experiment name")
    parser.add_argument("--run-name", default=None, help="MLflow run name")
    args = parser.parse_args(argv)

    set_global_seeds(args.seed)

    # Lazy imports — SB3 / torch are heavy
    from stable_baselines3 import SAC
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.vec_env import DummyVecEnv

    # Build environment
    raw_env = make_env(control_freq=args.freq, reward=args.reward)
    if args.seed is not None:
        raw_env.reset(seed=args.seed)
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
        tau=sac_cfg.tau,
        gamma=sac_cfg.gamma,
        use_sde=sac_cfg.use_sde,
        use_sde_at_warmup=sac_cfg.use_sde_at_warmup,
        sde_sample_freq=sac_cfg.sde_sample_freq,
        train_freq=sac_cfg.train_freq,
        gradient_steps=sac_cfg.gradient_steps,
        learning_starts=sac_cfg.learning_starts,
        seed=args.seed,
        verbose=args.verbose,
        policy_kwargs=dict(
            net_arch=dict(pi=[args.net_arch, args.net_arch], qf=[args.net_arch, args.net_arch]),
        ),
    )

    logger.info("Starting training: %d timesteps", args.timesteps)
    logger.info(
        "  reward=%s  lr=%.1e  freq=%d Hz  net=[%d,%d]", args.reward, args.lr, args.freq, args.net_arch, args.net_arch
    )

    from qube_rl.config import EnvConfig
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    run_name = args.run_name or f"train_{args.reward}_{args.net_arch}x2"
    params = build_params(
        seed=args.seed,
        sac=sac_cfg,
        env=EnvConfig(control_freq=args.freq, reward=args.reward),
        timesteps=args.timesteps,
        reward=args.reward,
        net_arch=args.net_arch,
    )

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    model_path = save_dir / f"qube_sac_{args.net_arch}x2.zip"

    with mlflow_run(
        run_name, params, enabled=args.mlflow, uri=args.mlflow_uri, experiment=args.mlflow_experiment
    ) as run:
        model.learn(
            total_timesteps=args.timesteps,
            progress_bar=True,
            callback=make_metrics_callback(enabled=args.mlflow),
        )
        model.save(str(model_path))
        logger.info("Model saved to %s", model_path)
        if run:
            run.log_artifact(str(model_path))


if __name__ == "__main__":
    main()
