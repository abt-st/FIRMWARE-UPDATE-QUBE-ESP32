"""Compensate the motor dead-zone caused by static friction."""

from __future__ import annotations

import gymnasium as gym
import numpy as np


class DeadZone(gym.Wrapper):
    """Map small actions to zero and rescale the rest to [deadzone, max_act].

    On the real robot a small PWM value does not overcome static friction.
    Without this wrapper the agent would learn that tiny actions have no
    effect, which hurts exploration (especially with gSDE).

    Parameters
    ----------
    deadzone : float
        Minimum absolute action magnitude that produces movement.
    center : float
        Actions with |a| <= center are mapped to zero.
    max_act : float
        Maximum absolute action the robot can handle safely.
    """

    def __init__(self, env: gym.Env, deadzone: float = 0.2, center: float = 0.01, max_act: float = 0.75) -> None:
        super().__init__(env)
        self.deadzone = deadzone
        self.center = center
        self.max_act = max_act

    def step(self, action):
        a = np.asarray(action)
        mask = np.abs(a) > self.center
        a = np.where(mask, np.sign(a) * (np.abs(a) * (self.max_act - self.deadzone) + self.deadzone), 0.0)
        return self.env.step(a)
