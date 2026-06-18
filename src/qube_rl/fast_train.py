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
import logging
import time
from pathlib import Path

from stable_baselines3 import SAC
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.config import DEFAULT_SEED, EnvConfig, SACConfig, WrapperConfig, set_global_seeds
from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def make_env(reward: str = "swingup_balance") -> object:
    """Build environment for fast training with standard wrappers."""
    env_cfg = EnvConfig(reward=reward)
    wrap_cfg = WrapperConfig()
    env = QubeSimEnv(
        control_freq=env_cfg.control_freq,
        reward=env_cfg.reward,
        angle_limits=env_cfg.angle_limits,
        speed_limits=env_cfg.speed_limits,
        encoders_cprs=None,
        velocity_filter_order=env_cfg.velocity_filter_order,
    )
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=wrap_cfg.deadzone, center=wrap_cfg.deadzone_center, max_act=wrap_cfg.deadzone_max_act)
    env = HistoryWrapper(env, steps=wrap_cfg.history_steps, use_continuity_cost=wrap_cfg.use_continuity_cost)
    return env


def main(argv: list[str] | None = None) -> None:
    sac_cfg = SACConfig()

    parser = argparse.ArgumentParser(description="Fast chunked SAC training for QUBE")
    parser.add_argument("--steps", type=int, default=50_000, help="Total training timesteps")
    parser.add_argument("--chunk", type=int, default=10_000, help="Steps per checkpoint chunk")
    parser.add_argument("--reward", default="swingup_balance", help="Reward function name")
    parser.add_argument("--net-arch", type=int, default=sac_cfg.net_arch, help="Network hidden layer size")
    parser.add_argument("--lr", type=float, default=sac_cfg.learning_rate, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=sac_cfg.batch_size, help="Batch size")
    parser.add_argument("--buffer-size", type=int, default=sac_cfg.buffer_size, help="Replay buffer size")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed (omit for non-deterministic)")
    parser.add_argument("--save-dir", default="models", help="Directory to save models")
    parser.add_argument("--log-dir", default="runs", help="TensorBoard log directory")
    parser.add_argument("--exp-name", default="fast", help="Experiment name for TensorBoard")
    parser.add_argument("--mlflow", action="store_true", help="Log this run to MLflow (in addition to TensorBoard)")
    parser.add_argument(
        "--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite:///mlflow.db or env var)"
    )
    parser.add_argument("--mlflow-experiment", default="qube_sac", help="MLflow experiment name")
    args = parser.parse_args(argv)

    set_global_seeds(args.seed)

    vec_env = DummyVecEnv([lambda: make_env(reward=args.reward)])

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
        tensorboard_log=args.log_dir,
        verbose=1,
        policy_kwargs=dict(net_arch=dict(pi=[args.net_arch, args.net_arch], qf=[args.net_arch, args.net_arch])),
    )

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    n_chunks = max(1, args.steps // args.chunk)
    t0 = time.time()

    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    params = build_params(
        seed=args.seed,
        sac=SACConfig(
            net_arch=args.net_arch, learning_rate=args.lr, batch_size=args.batch_size, buffer_size=args.buffer_size
        ),
        env=EnvConfig(reward=args.reward),
        steps=args.steps,
        chunk=args.chunk,
        reward=args.reward,
    )
    callback = make_metrics_callback(enabled=args.mlflow)

    with mlflow_run(
        args.exp_name, params, enabled=args.mlflow, uri=args.mlflow_uri, experiment=args.mlflow_experiment
    ) as run:
        for chunk in range(1, n_chunks + 1):
            logger.info("=== CHUNK %d/%d ===", chunk, n_chunks)
            model.learn(
                total_timesteps=args.chunk,
                reset_num_timesteps=False,
                tb_log_name=f"{args.exp_name}_c{chunk}",
                progress_bar=False,
                callback=callback,
            )
            save_path = save_dir / f"qube_sac_{args.exp_name}_c{chunk}.zip"
            model.save(str(save_path))
            logger.info("Saved %s (%.0fs elapsed)", save_path, time.time() - t0)

        final_path = save_dir / f"qube_sac_{args.exp_name}.zip"
        model.save(str(final_path))
        if run:
            run.log_artifact(str(final_path))
        logger.info("Final model saved to %s", final_path)
        logger.info("Total time: %.0fs", time.time() - t0)
        logger.info("Network: [%d, %d] — RLtools ESP32 compatible", args.net_arch, args.net_arch)
        logger.info("To export for ESP32: uv run python -m qube_rl.export_rltools --model %s", final_path)


if __name__ == "__main__":
    main()
