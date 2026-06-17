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


def make_real_env(esp32_ip: str = "192.168.4.1", control_freq: int = 10, http_timeout: float = 1.0) -> gym.Env:
    """Build the real-hardware environment with standard wrappers for fine-tuning."""
    from qube_rl.envs.qube_real import QubeRealEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

    env = QubeRealEnv(esp32_ip=esp32_ip, control_freq=control_freq, http_timeout=http_timeout)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fine-tune SAC on real QUBE Servo")
    parser.add_argument("--model", default="models/qube_sac_sim.zip", help="Pre-trained model path (.zip)")
    parser.add_argument("--ip", default="192.168.4.1", help="ESP32 IP address")
    parser.add_argument("--timesteps", type=int, default=100_000, help="Fine-tuning timesteps")
    parser.add_argument("--lr", type=float, default=1e-4, help="New learning rate")
    parser.add_argument("--save-dir", default="models", help="Directory to save the fine-tuned model")
    parser.add_argument("--log-dir", default="runs", help="TensorBoard log directory")
    parser.add_argument("--freq", type=int, default=10, help="Control frequency (Hz) — lower for WiFi reliability")
    parser.add_argument("--timeout", type=float, default=1.0, help="HTTP timeout (seconds)")
    args = parser.parse_args(argv)

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
    try:
        model.learn(
            total_timesteps=args.timesteps,
            reset_num_timesteps=False,
            tb_log_name="finetune",
            progress_bar=True,
        )
    finally:
        # Save before closing in case of interruption
        save_dir = Path(args.save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / "qube_sac_finetuned.zip"
        model.save(str(save_path))
        logger.info("Fine-tuned model saved to %s", save_path)

        env.close()
        logger.info("Environment closed (motor killed).")


if __name__ == "__main__":
    main()
