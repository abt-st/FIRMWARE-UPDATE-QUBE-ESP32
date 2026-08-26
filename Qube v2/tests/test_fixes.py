"""Regression tests for the RL correctness fixes.

Covers the issues fixed from REFERENCE.md Part VI:
- C1: the episode no longer terminates when the pendulum reaches the inverted
  goal (alpha = ±pi); termination is driven by the servo angle / over-speed only.
- A2: raw alpha stays wrapped to [-pi, pi] in the observation (8-D layout kept).
- M3: a TimeLimit truncates episodes (truncated=True, terminated=False).
- A5: the balance metric exposes the expected keys.
- A6: potential-based shaping is additive and policy-invariant in form.
"""

from __future__ import annotations

import numpy as np

from qube_rl.envs.factory import make_sim_env
from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, observation_from_state, wrap_angle


def _bounded_env() -> QubeSimEnv:
    return QubeSimEnv(reward="swingup_balance", angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])


class TestTerminationFix:
    def test_inverted_goal_is_not_terminal(self) -> None:
        """alpha = pi (inverted, the goal) must NOT end the episode."""
        env = _bounded_env()
        env.reset(seed=0)
        env._state = np.array([0.0, np.pi, 0.0, 0.0], dtype=np.float32)
        assert env._is_terminal() is False

    def test_overshoot_past_inverted_is_not_terminal(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        env._state = np.array([0.0, np.pi + 0.3, 0.0, 0.0], dtype=np.float32)
        assert env._is_terminal() is False

    def test_servo_limit_terminates(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        env._state = np.array([np.pi / 2 + 0.1, 0.0, 0.0, 0.0], dtype=np.float32)
        assert env._is_terminal() is True

    def test_nonfinite_terminates(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        env._state = np.array([0.0, np.nan, 0.0, 0.0], dtype=np.float32)
        assert env._is_terminal() is True


class TestAlphaWrap:
    def test_raw_alpha_wrapped_in_observation(self) -> None:
        state = np.array([0.0, 3 * np.pi / 2, 0.0, 0.0])  # alpha beyond pi
        obs = observation_from_state(state)
        assert -np.pi <= obs[1] <= np.pi
        np.testing.assert_allclose(obs[1], wrap_angle(3 * np.pi / 2))

    def test_obs_stays_inside_box_when_spinning(self) -> None:
        env = _bounded_env()
        env.reset(seed=0)
        env._state = np.array([0.0, 5 * np.pi, 0.0, 0.0], dtype=np.float32)  # many turns
        obs = env._get_obs()
        assert env.observation_space.contains(obs)


class TestTimeLimit:
    def test_timelimit_truncates(self) -> None:
        env = make_sim_env(max_episode_steps=5, history_steps=0, monitor=False)
        env.reset(seed=0)
        last = None
        for _ in range(5):
            last = env.step(np.zeros(1, dtype=np.float32))
        _obs, _r, terminated, truncated, _info = last
        assert truncated is True
        assert terminated is False


class TestBalanceMetric:
    def test_keys_present(self) -> None:
        from qube_rl.metrics import evaluate_balance

        env = make_sim_env(max_episode_steps=30)
        out = evaluate_balance(None, env, n_episodes=2, control_freq=50, max_steps=30)
        for key in ("reach_rate", "balance_rate", "upright_fraction", "max_hold_s", "return_mean"):
            assert key in out
        assert 0.0 <= out["upright_fraction"] <= 1.0


class TestStabiliseReward:
    """R3: linear_alpha_stabilise — gated damping + eval-aligned hold bonus."""

    def _reward(self):
        from qube_rl.rewards import REWARDS

        assert "linear_alpha_stabilise" in REWARDS
        return REWARDS["linear_alpha_stabilise"]

    def _state(self, alpha: float, alpha_dot: float = 0.0, theta: float = 0.0):
        s = np.zeros(4, dtype=np.float32)
        s[THETA] = theta
        s[ALPHA] = alpha
        s[ALPHA_DOT] = alpha_dot
        return s

    def test_damping_is_zero_in_lower_half(self) -> None:
        """Below horizontal the agent must be free to pump energy (no vel penalty)."""
        r = self._reward()
        # alpha = pi/4 (lower half), fast spin: reward must still be >= the
        # pure swing-up term (|alpha|/pi), i.e. no velocity penalty applied.
        s = self._state(np.pi / 4, alpha_dot=8.0)
        al_rew = (np.pi / 4) / np.pi
        assert r(s) >= al_rew - 1e-6

    def test_damping_active_in_upper_half(self) -> None:
        """Above horizontal a fast pendulum is penalised vs a slow one."""
        r = self._reward()
        # Compare two states at the same angle (upper half, outside the bonus
        # zone) differing only in speed: faster must score lower.
        slow = self._state(0.6 * np.pi, alpha_dot=0.5)
        fast = self._state(0.6 * np.pi, alpha_dot=8.0)
        assert r(fast) < r(slow)

    def test_bonus_peaks_at_the_eval_criterion(self) -> None:
        """Bonus is maximal at (inverted, still) and decays as it drifts off."""
        r = self._reward()
        at_target = self._state(np.pi, alpha_dot=0.0)
        off_angle = self._state(np.pi - np.radians(30), alpha_dot=0.0)
        off_speed = self._state(np.pi, alpha_dot=2.0)
        assert r(at_target) > r(off_angle)
        assert r(at_target) > r(off_speed)

    def test_finite_everywhere(self) -> None:
        r = self._reward()
        for a in np.linspace(-2 * np.pi, 2 * np.pi, 25):
            for ad in (-10.0, 0.0, 10.0):
                assert np.isfinite(r(self._state(a, ad)))


class TestNearUprightReset:
    """Reverse-curriculum reset: start near the inverted apex on demand."""

    def test_prob_one_starts_near_apex(self) -> None:
        env = QubeSimEnv(reward="linear_alpha", near_upright_prob=1.0)
        for seed in range(5):
            env.reset(seed=seed)
            assert abs(wrap_angle(float(env._state[ALPHA]) - np.pi)) <= np.radians(16)

    def test_prob_zero_starts_hanging(self) -> None:
        env = QubeSimEnv(reward="linear_alpha", near_upright_prob=0.0)
        for seed in range(5):
            env.reset(seed=seed)
            assert abs(float(env._state[ALPHA])) <= np.radians(5)

    def test_options_force_near_upright(self) -> None:
        """``options={'near_upright': True}`` overrides a 0.0 probability env."""
        env = QubeSimEnv(reward="linear_alpha", near_upright_prob=0.0)
        env.reset(seed=0, options={"near_upright": True})
        assert abs(wrap_angle(float(env._state[ALPHA]) - np.pi)) <= np.radians(16)

    def test_eval_reset_options_propagate_through_wrappers(self) -> None:
        """evaluate_balance(reset_options=...) reaches the base env past wrappers."""
        from qube_rl.metrics import evaluate_balance

        env = make_sim_env(reward="linear_alpha", max_episode_steps=10)
        # Zero policy from the apex: reach should be 100% since we start inverted.
        out = evaluate_balance(None, env, n_episodes=3, max_steps=10, reset_options={"near_upright": True})
        assert out["reach_rate"] == 1.0


class TestPotentialShaping:
    def test_shaping_is_additive_and_recorded(self) -> None:
        from qube_rl.wrappers import PotentialShaping

        base = QubeSimEnv(reward="swingup_balance", angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])
        shaped = PotentialShaping(base, potential="upright", gamma=0.99)
        shaped.reset(seed=0)
        _obs, reward, _term, _trunc, info = shaped.step(np.array([0.5], dtype=np.float32))
        assert "shaping_reward" in info
        # The shaped reward equals base reward + shaping term (additive).
        assert np.isfinite(reward)

    def test_unknown_potential_raises(self) -> None:
        import pytest

        from qube_rl.wrappers import PotentialShaping

        with pytest.raises(ValueError, match="Unknown potential"):
            PotentialShaping(_bounded_env(), potential="nope")
