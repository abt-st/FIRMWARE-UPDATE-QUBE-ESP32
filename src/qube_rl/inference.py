"""Run a trained SAC agent on the real QUBE Servo hardware.

Usage::

    uv run python -m qube_rl.inference
    uv run python -m qube_rl.inference --model models/qube_sac_sim.zip --episodes 20
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import gymnasium as gym

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def make_real_env(esp32_ip: str = "192.168.4.1", control_freq: int = 50) -> gym.Env:
    """Build the real-hardware environment (delegates to the env factory)."""
    from qube_rl.envs.factory import make_real_env as _make_real_env

    return _make_real_env(esp32_ip=esp32_ip, control_freq=control_freq, use_continuity_cost=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run trained SAC on real QUBE Servo")
    parser.add_argument("--model", default="models/qube_sac_sim.zip", help="Path to trained model (.zip)")
    parser.add_argument("--ip", default="192.168.4.1", help="ESP32 IP address")
    parser.add_argument("--episodes", type=int, default=10, help="Number of episodes to run")
    parser.add_argument("--freq", type=int, default=50, help="Control frequency (Hz)")
    args = parser.parse_args(argv)

    # Lazy imports — SB3 / torch are heavy
    from stable_baselines3 import SAC

    model_path = Path(args.model)
    if not model_path.exists():
        logger.error("Model file not found: %s", model_path)
        return

    logger.info("Loading model from %s", model_path)
    model = SAC.load(str(model_path))

    env = make_real_env(esp32_ip=args.ip, control_freq=args.freq)

    try:
        for ep in range(1, args.episodes + 1):
            obs, _info = env.reset()
            ep_reward = 0.0
            steps = 0
            t_start = time.monotonic()

            while True:
                action, _states = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, _info = env.step(action)
                ep_reward += reward
                steps += 1
                if terminated or truncated:
                    break

            duration = time.monotonic() - t_start
            logger.info(
                "Episode %d/%d — reward: %.2f | steps: %d | duration: %.1fs",
                ep,
                args.episodes,
                ep_reward,
                steps,
                duration,
            )
    finally:
        env.close()
        logger.info("Environment closed (motor killed).")


if __name__ == "__main__":
    main()
