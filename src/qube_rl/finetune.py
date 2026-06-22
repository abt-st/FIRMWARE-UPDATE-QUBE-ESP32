"""Fine-tune a sim-trained SAC agent on real QUBE Servo hardware.

Usage::

    uv run python -m qube_rl.finetune
    uv run python -m qube_rl.finetune --model models/qube_sac_sim.zip --timesteps 50000
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import gymnasium as gym

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def make_real_env(esp32_ip: str = "192.168.4.1", control_freq: int = 50, http_timeout: float = 1.0) -> gym.Env:
    """Build the real-hardware fine-tuning environment (delegates to the factory)."""
    from qube_rl.config import WrapperConfig
    from qube_rl.envs.factory import make_real_env as _make_real_env

    return _make_real_env(
        esp32_ip=esp32_ip,
        control_freq=control_freq,
        http_timeout=http_timeout,
        use_continuity_cost=WrapperConfig().use_continuity_cost,
    )


def main(argv: list[str] | None = None) -> None:
    from qube_rl.config import DEFAULT_SEED, EnvConfig, set_global_seeds

    train_freq = EnvConfig().control_freq

    parser = argparse.ArgumentParser(description="Fine-tune SAC on real QUBE Servo")
    parser.add_argument("--model", default="models/qube_sac_sim.zip", help="Pre-trained model path (.zip)")
    parser.add_argument("--ip", default="192.168.4.1", help="ESP32 IP address")
    parser.add_argument("--timesteps", type=int, default=100_000, help="Fine-tuning timesteps")
    parser.add_argument("--lr", type=float, default=1e-4, help="New learning rate")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed (omit for non-deterministic)")
    parser.add_argument("--save-dir", default="models", help="Directory to save the fine-tuned model")
    parser.add_argument(
        "--freq",
        type=int,
        default=train_freq,
        help="Control frequency (Hz). MUST match the training frequency: the "
        "HistoryWrapper stacks a fixed number of steps, so a different rate "
        "changes the policy's temporal context (e.g. 80 ms at 50 Hz vs 400 ms at 10 Hz).",
    )
    parser.add_argument("--timeout", type=float, default=1.0, help="HTTP timeout (seconds)")
    parser.add_argument("--mlflow", action="store_true", help="Track this run with MLflow (params, metrics, artifact)")
    parser.add_argument(
        "--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite:///mlflow.db or env var)"
    )
    parser.add_argument("--mlflow-experiment", default="qube_sac", help="MLflow experiment name")
    args = parser.parse_args(argv)

    set_global_seeds(args.seed)

    if args.freq != train_freq:
        logger.warning(
            "Fine-tuning frequency (%d Hz) differs from the training frequency (%d Hz). "
            "The HistoryWrapper temporal context will not match the sim-trained policy, "
            "degrading sim-to-real transfer. Re-train the sim policy at %d Hz instead.",
            args.freq,
            train_freq,
            args.freq,
        )

    # Lazy imports — SB3 / torch are heavy
    from stable_baselines3 import SAC

    model_path = Path(args.model)
    if not model_path.exists():
        logger.error("Model file not found: %s", model_path)
        return

    logger.info("Loading pre-trained model from %s", model_path)
    model = SAC.load(str(model_path))

    # Adjust learning rate for fine-tuning
    model.learning_rate = args.lr
    logger.info("Learning rate set to %.1e", args.lr)

    # Build real environment
    env = make_real_env(esp32_ip=args.ip, control_freq=args.freq, http_timeout=args.timeout)
    model.set_env(env)
    logger.info("Starting fine-tuning: %d timesteps on real hardware", args.timesteps)

    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    params = build_params(seed=args.seed, base_model=args.model, timesteps=args.timesteps, lr=args.lr, freq=args.freq)

    with mlflow_run(
        "finetune", params, enabled=args.mlflow, uri=args.mlflow_uri, experiment=args.mlflow_experiment
    ) as run:
        try:
            model.learn(
                total_timesteps=args.timesteps,
                reset_num_timesteps=False,
                progress_bar=True,
                callback=make_metrics_callback(enabled=args.mlflow),
            )
        finally:
            # Save before closing in case of interruption
            save_dir = Path(args.save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / "qube_sac_finetuned.zip"
            model.save(str(save_path))
            logger.info("Fine-tuned model saved to %s", save_path)
            if run:
                run.log_artifact(str(save_path))

            env.close()
            logger.info("Environment closed (motor killed).")


if __name__ == "__main__":
    main()
