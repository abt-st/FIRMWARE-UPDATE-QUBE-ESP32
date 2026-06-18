"""Tests for the QubeSimEnv simulation environment (qube_sim.py).

Covers Gymnasium-API compliance, the observation layout, the reward-timing
fix (reward/observation must describe the post-action state) and seed-based
reproducibility.
"""

from __future__ import annotations

import numpy as np

from qube_rl.config import MAX_VELOCITY
from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.utils import observation_from_state


def _bounded_env() -> QubeSimEnv:
    """Env with finite angle limits → 8-D observation (the training layout)."""
    return QubeSimEnv(reward="swingup_balance", angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])


def _unbounded_env() -> QubeSimEnv:
    """Env with infinite angle limits → 6-D observation."""
    return QubeSimEnv(reward="swingup_balance", angle_limits=[np.inf, np.inf], speed_limits=[50.0, 50.0])


class TestSpaces:
    def test_bounded_observation_is_8d(self) -> None:
        env = _bounded_env()
        assert env.observation_space.shape == (8,)

    def test_unbounded_observation_is_6d(self) -> None:
        env = _unbounded_env()
        assert env.observation_space.shape == (6,)

    def test_velocity_bound_matches_clamp(self) -> None:
        """Declared obs velocity bound must equal the integration clamp."""
        env = _bounded_env()
        assert env.observation_space.high[-1] == np.float32(MAX_VELOCITY)
        assert env.observation_space.high[-2] == np.float32(MAX_VELOCITY)

    def test_action_space(self) -> None:
        env = _bounded_env()
        assert env.action_space.shape == (1,)
        assert env.action_space.low[0] == -1.0
        assert env.action_space.high[0] == 1.0


class TestSb3Compliance:
    def test_check_env_passes(self) -> None:
        from stable_baselines3.common.env_checker import check_env

        check_env(_bounded_env(), warn=True)


class TestRewardTiming:
    """After the off-by-one fix, step() must report the POST-action state."""

    def test_obs_reflects_post_action_state(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        obs, _reward, _term, _trunc, _info = env.step(np.array([1.0], dtype=np.float32))
        expected = observation_from_state(env._state, include_raw_theta=True, include_raw_alpha=True)
        np.testing.assert_allclose(obs, expected, rtol=0, atol=0)

    def test_action_changes_observation(self) -> None:
        env = _bounded_env()
        obs0, _ = env.reset(seed=0)
        obs1, *_ = env.step(np.array([1.0], dtype=np.float32))
        # A full-throttle action must move the state away from the reset obs.
        assert not np.allclose(obs0, obs1)


class TestReproducibility:
    def test_same_seed_same_rollout(self) -> None:
        actions = [np.array([a], dtype=np.float32) for a in (1.0, -1.0, 0.5, -0.5, 0.0)]

        def rollout() -> list[np.ndarray]:
            env = _bounded_env()
            env.reset(seed=123)
            out = []
            for a in actions:
                obs, *_ = env.step(a)
                out.append(obs.copy())
            return out

        r1, r2 = rollout(), rollout()
        for o1, o2 in zip(r1, r2, strict=True):
            np.testing.assert_array_equal(o1, o2)

    def test_different_seed_different_rollout(self) -> None:
        def first_obs(seed: int) -> np.ndarray:
            env = _bounded_env()
            obs, _ = env.reset(seed=seed)
            return obs

        assert not np.array_equal(first_obs(1), first_obs(2))


class TestIntegration:
    def test_velocities_respect_clamp(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        for _ in range(200):
            env.step(np.array([1.0], dtype=np.float32))
            if not np.all(np.isfinite(env._state)):
                break
            assert abs(env._state[2]) <= MAX_VELOCITY + 1e-3
            assert abs(env._state[3]) <= MAX_VELOCITY + 1e-3
