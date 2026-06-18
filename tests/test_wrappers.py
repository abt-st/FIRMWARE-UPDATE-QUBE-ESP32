"""Tests for the RL environment wrappers (deadzone, history)."""

from __future__ import annotations

import numpy as np

from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import DeadZone, HistoryWrapper


def _base_env() -> QubeSimEnv:
    return QubeSimEnv(angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])


def _deadzone_map(dz: DeadZone, a: np.ndarray) -> np.ndarray:
    """Replicate DeadZone's action transform (mirrors DeadZone.step)."""
    mask = np.abs(a) > dz.center
    return np.where(mask, np.sign(a) * (np.abs(a) * (dz.max_act - dz.deadzone) + dz.deadzone), 0.0)


class TestDeadZone:
    def test_small_action_mapped_to_zero(self) -> None:
        dz = DeadZone(_base_env(), deadzone=0.2, center=0.01, max_act=0.75)
        assert _deadzone_map(dz, np.array([0.005]))[0] == 0.0

    def test_action_rescaled_into_band(self) -> None:
        dz = DeadZone(_base_env(), deadzone=0.2, center=0.01, max_act=0.75)
        mapped = _deadzone_map(dz, np.array([0.5]))
        assert dz.deadzone <= abs(mapped[0]) <= dz.max_act

    def test_step_runs(self) -> None:
        dz = DeadZone(_base_env(), deadzone=0.2, center=0.01, max_act=0.75)
        dz.reset(seed=0)
        obs, reward, _term, _trunc, _info = dz.step(np.array([0.5], dtype=np.float32))
        assert obs.shape == (8,)
        assert np.isfinite(reward)


class TestHistoryWrapper:
    def test_stacked_dimension(self) -> None:
        env = HistoryWrapper(_base_env(), steps=4, use_continuity_cost=True)
        # 8 obs + 1 action = 9 per step, x 4 steps = 36.
        assert env.observation_space.shape == (36,)

    def test_reset_and_step_shapes(self) -> None:
        env = HistoryWrapper(_base_env(), steps=4, use_continuity_cost=True)
        obs, _ = env.reset(seed=0)
        assert obs.shape == (36,)
        obs2, reward, _term, _trunc, info = env.step(np.array([0.5], dtype=np.float32))
        assert obs2.shape == (36,)
        assert "continuity_cost" in info
        assert np.isfinite(reward)

    def test_continuity_cost_zero_for_constant_action(self) -> None:
        env = HistoryWrapper(_base_env(), steps=4, use_continuity_cost=True)
        env.reset(seed=0)
        env.step(np.array([0.3], dtype=np.float32))
        _obs, _r, _t, _tr, info = env.step(np.array([0.3], dtype=np.float32))
        assert info["continuity_cost"] == 0.0
