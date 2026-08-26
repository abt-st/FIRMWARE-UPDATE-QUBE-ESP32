"""Sim ↔ real ↔ firmware observation-contract tests.

The sim-trained policy is deployed on real hardware and (after history
stacking) on the ESP32.  These tests pin the observation layout so the three
can never silently diverge — a divergence would break sim-to-real transfer.
"""

from __future__ import annotations

import numpy as np

from qube_rl.envs.qube_real import QubeRealEnv
from qube_rl.envs.qube_sim import QubeSimEnv

# Single source of truth, not a third copy of the literal 36.  This constant used to be
# spelled out independently here, in ``export_rltools`` and in the ``.ino``; none derived
# from the others, so changing ``RL_HISTORY_STEPS`` in the firmware broke nothing in CI
# while the exported header kept declaring 36 inputs.  ``export_rltools`` is now checked
# against the firmware itself in ``test_firmware_contract.py``.
from qube_rl.export_rltools import FIRMWARE_INPUT_DIM
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, observation_from_state

# Per-step features fed to the policy: 8 observation values + 1 last action.
FEATURES_PER_STEP = 9
HISTORY_STEPS = 4

assert FIRMWARE_INPUT_DIM == FEATURES_PER_STEP * HISTORY_STEPS


def test_observation_from_state_layout() -> None:
    state = np.array([0.1, 0.2, 0.3, 0.4])
    obs = observation_from_state(state)
    assert obs.shape == (8,)
    np.testing.assert_allclose(obs[0], state[THETA])
    np.testing.assert_allclose(obs[1], state[ALPHA])
    np.testing.assert_allclose(obs[2], np.cos(state[THETA]))
    np.testing.assert_allclose(obs[3], np.sin(state[THETA]))
    np.testing.assert_allclose(obs[4], np.cos(state[ALPHA]))
    np.testing.assert_allclose(obs[5], np.sin(state[ALPHA]))
    np.testing.assert_allclose(obs[6], state[THETA_DOT])
    np.testing.assert_allclose(obs[7], state[ALPHA_DOT])


def test_sim_and_real_share_observation_layout() -> None:
    """Bounded sim env and real env must emit the same 8-D layout."""
    sim = QubeSimEnv(angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])
    real = QubeRealEnv(auto_set_mode=False)  # constructor does no HTTP I/O
    assert sim.observation_space.shape == real.observation_space.shape == (8,)

    state = np.array([0.1, 0.2, 0.3, 0.4])
    sim._state = state.astype(np.float32)
    real._state = state.astype(np.float32)
    np.testing.assert_allclose(sim._get_obs(), real._get_obs())


def test_history_stack_matches_firmware_input_dim() -> None:
    from qube_rl.wrappers import HistoryWrapper

    env = QubeSimEnv(angle_limits=[np.pi / 2, np.pi], speed_limits=[50.0, 400.0])
    env = HistoryWrapper(env, steps=HISTORY_STEPS, use_continuity_cost=True)
    assert env.observation_space.shape == (FIRMWARE_INPUT_DIM,)
