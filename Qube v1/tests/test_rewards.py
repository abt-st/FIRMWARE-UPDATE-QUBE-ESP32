"""Tests for the reward functions (rewards.py).

Verifies the registry is well-formed, every reward returns a finite scalar,
and key qualitative properties hold (upright is rewarded over hanging).
"""

from __future__ import annotations

import numpy as np
import pytest

from qube_rl.rewards import REWARDS

# state = [theta, alpha, theta_dot, alpha_dot]; alpha=pi is inverted, 0 is hanging.
_HANGING = np.array([0.0, 0.0, 0.0, 0.0])
_INVERTED = np.array([0.0, np.pi, 0.0, 0.0])


@pytest.mark.parametrize("name", list(REWARDS))
class TestRewardContract:
    def test_returns_finite_scalar(self, name: str) -> None:
        r = REWARDS[name](_INVERTED)
        assert np.isscalar(r) or np.ndim(r) == 0
        assert np.isfinite(r)

    def test_upright_beats_hanging(self, name: str) -> None:
        """Every reward should prefer the inverted pose to the hanging one."""
        assert REWARDS[name](_INVERTED) > REWARDS[name](_HANGING)


def test_registry_values_callable() -> None:
    assert all(callable(fn) for fn in REWARDS.values())


def test_arm_offset_penalised() -> None:
    """Rewards with a centering term should penalise an off-centre arm."""
    centered = np.array([0.0, np.pi, 0.0, 0.0])
    offset = np.array([np.pi / 2, np.pi, 0.0, 0.0])
    for name in ("cos_alpha_centered", "swingup_balance", "linear_alpha"):
        assert REWARDS[name](offset) < REWARDS[name](centered)
