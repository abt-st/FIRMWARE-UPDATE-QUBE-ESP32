"""Send a zero command to the robot when an episode ends."""

from __future__ import annotations

import logging

import gymnasium as gym

logger = logging.getLogger(__name__)


class GentlyTerminating(gym.Wrapper):
    """Kill the motor when an episode terminates or is truncated.

    Prevents the robot from continuing at full power after the agent loses
    control — critical for hardware safety.
    """

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        if terminated or truncated:
            logger.info("Episode done — killing motor.")
            # If the env wraps a real robot, send zero action
            if hasattr(self.unwrapped, "robot"):
                self.unwrapped.robot.step(0.0)
        return observation, reward, terminated, truncated, info
