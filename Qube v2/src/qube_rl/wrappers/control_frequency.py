"""Enforce a fixed control frequency between steps."""

from __future__ import annotations

import logging
import time

import gymnasium as gym

logger = logging.getLogger(__name__)


class ControlFrequency(gym.Wrapper):
    """Sleep between steps so that the real-time loop matches the target dt."""

    def __init__(self, env: gym.Env, log_freq: int = 3000) -> None:
        super().__init__(env)
        self.dt: float = env.unwrapped.timing.dt
        self.last: float | None = None
        self.log_freq: int = log_freq
        self.nb_steps: int = 0

    def step(self, action):
        self.nb_steps += 1
        current = time.time()
        loop_time = 0.0
        if self.last is not None:
            loop_time = current - self.last
            sleeping_time = self.dt - loop_time
            if self.nb_steps % self.log_freq == 0:
                logger.info("control freq: %.1f Hz", 1 / loop_time)
            if sleeping_time > 0:
                time.sleep(sleeping_time)
            else:
                logger.warning("loop time %.4f s > dt %.4f s", loop_time, self.dt)

        obs, reward, terminated, truncated, info = self.env.step(action)
        self.last = time.time()
        return obs, reward, terminated, truncated, info

    def reset(self, **kwargs):
        self.last = None
        return self.env.reset(**kwargs)
