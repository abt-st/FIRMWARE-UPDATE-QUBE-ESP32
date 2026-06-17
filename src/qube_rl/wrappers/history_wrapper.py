"""Stack recent observations so the agent sees temporal context."""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium.spaces import Box


class HistoryWrapper(gym.Wrapper):
    """Concatenate the last *steps* (observation, action) pairs.

    A rotary pendulum is a second-order system.  With only the current
    observation the agent cannot estimate acceleration or friction.
    Stacking 4 steps of [obs, action] gives implicit temporal context.

    Optionally adds a *continuity cost* to the reward that penalises large
    action changes, encouraging smoother control.
    """

    def __init__(self, env: gym.Env, steps: int = 4, use_continuity_cost: bool = True) -> None:
        super().__init__(env)
        assert steps > 1, "steps must be > 1"
        self.steps = steps
        self.use_continuity_cost = use_continuity_cost

        # One step = obs + action
        step_low = np.concatenate([self.observation_space.low, self.action_space.low])
        step_high = np.concatenate([self.observation_space.high, self.action_space.high])

        obs_low = np.tile(step_low, (self.steps,)).ravel()
        obs_high = np.tile(step_high, (self.steps,)).ravel()
        self.observation_space = Box(low=obs_low, high=obs_high, dtype=np.float32)

        self.history: list[np.ndarray] = self._make_history()

    def _make_history(self) -> list[np.ndarray]:
        return [np.zeros(self.observation_space.shape[0] // self.steps, dtype=np.float32) for _ in range(self.steps)]

    def _continuity_cost(self, obs_flat: np.ndarray) -> float:
        """Penalise difference between current and previous action."""
        step_size = self.observation_space.shape[0] // self.steps
        current_action = obs_flat[-step_size:][-self.action_space.shape[0] :]
        prev_action = obs_flat[-2 * step_size : -step_size][-self.action_space.shape[0] :]
        return float(np.sum((current_action - prev_action) ** 2))

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self.history.pop(0)
        step = np.concatenate([obs, np.asarray(action, dtype=np.float32).ravel()])
        self.history.append(step)
        stacked = np.concatenate(self.history).astype(np.float32)

        if self.use_continuity_cost:
            cc = self._continuity_cost(stacked)
            reward -= cc
            info["continuity_cost"] = cc

        return stacked, reward, terminated, truncated, info

    def reset(self, **kwargs):
        self.history = self._make_history()
        obs, info = self.env.reset(**kwargs)
        step = np.concatenate([obs, np.zeros(self.action_space.shape[0], dtype=np.float32)])
        self.history[-1] = step
        stacked = np.concatenate(self.history).astype(np.float32)
        return stacked, info
