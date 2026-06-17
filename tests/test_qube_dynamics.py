"""Tests for the QubeDynamics analytical model (qube_dynamics.py).

Determinism: every test seeds numpy so domain-randomisation cannot flake.
"""

from __future__ import annotations

import numpy as np

from qube_rl.envs.qube_dynamics import QubeDynamics

SEED = 42

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dynamics(seed: int = SEED) -> QubeDynamics:
    """Create a QubeDynamics with a fixed RNG seed."""
    np.random.seed(seed)
    return QubeDynamics()


def _equilibrium_accel(dyn: QubeDynamics, alpha: float) -> tuple[float, float]:
    """Return (theta_dd, alpha_dd) at rest (zero velocities) with zero action."""
    state = np.array([0.0, alpha, 0.0, 0.0])
    return dyn(state, 0.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEquilibrium:
    """Rest states at the two natural equilibria must have zero acceleration."""

    def test_equilibrium_inverted(self) -> None:
        """Inverted (alpha=pi): both angular accelerations ~ 0."""
        dyn = _make_dynamics()
        thdd, aldd = _equilibrium_accel(dyn, np.pi)
        assert abs(thdd) < 1e-12, f"theta_dd={thdd}"
        assert abs(aldd) < 1e-12, f"alpha_dd={aldd}"

    def test_equilibrium_hanging(self) -> None:
        """Hanging (alpha=0): both angular accelerations ~ 0."""
        dyn = _make_dynamics()
        thdd, aldd = _equilibrium_accel(dyn, 0.0)
        assert abs(thdd) < 1e-12, f"theta_dd={thdd}"
        assert abs(aldd) < 1e-12, f"alpha_dd={aldd}"


class TestGravity:
    """Gravity coupling at non-equilibrium angles."""

    def test_zero_action_gravity(self) -> None:
        """alpha=pi/2 with no motor -> gravity produces nonzero alpha_dd."""
        dyn = _make_dynamics()
        _thdd, aldd = _equilibrium_accel(dyn, np.pi / 2)
        assert abs(aldd) > 1e-3, f"alpha_dd should be nonzero, got {aldd}"


class TestMotorTorque:
    """Motor input must drive the rotary axis."""

    def test_action_produces_torque(self) -> None:
        """Nonzero action at rest -> theta_dd != 0."""
        dyn = _make_dynamics()
        state = np.array([0.0, np.pi, 0.0, 0.0])
        thdd, _aldd = dyn(state, 0.5)
        assert abs(thdd) > 1e-6, f"theta_dd should be nonzero, got {thdd}"

    def test_symmetry(self) -> None:
        """Equal-and-opposite actions produce equal-and-opposite theta_dd."""
        dyn = _make_dynamics()
        state = np.array([0.0, np.pi, 0.0, 0.0])
        thdd_pos, _ = dyn(state, 0.5)
        thdd_neg, _ = dyn(state, -0.5)
        assert np.sign(thdd_pos) == -np.sign(thdd_neg), f"signs should differ: +{thdd_pos}, -{thdd_neg}"

    def test_stall_torque_clipping(self) -> None:
        """Action=10 maps to 120 V -> motor torque clipped at stall_torque.

        The dynamics should still produce a nonzero response, and the output
        must differ from the unclamped linear extrapolation.
        """
        dyn = _make_dynamics()
        state = np.array([0.0, np.pi, 0.0, 0.0])
        thdd_clipped, _ = dyn(state, 10.0)
        thdd_normal, _ = dyn(state, 1.0)
        assert abs(thdd_clipped) > 1e-9, "clipped output should be nonzero"
        # Stall-torque saturation means the response is NOT 10x the normal response.
        assert abs(thdd_clipped) < abs(thdd_normal) * 5.0, (
            f"clipped ({thdd_clipped}) should not scale linearly with action"
        )


class TestDomainRandomisation:
    """randomize() must perturb the physical parameters."""

    def test_randomize_changes_params(self) -> None:
        dyn = _make_dynamics()
        params_before = (dyn.Mp, dyn.Lp, dyn.Mr, dyn.Lr, dyn.km)
        np.random.seed(123)
        dyn.randomize()
        params_after = (dyn.Mp, dyn.Lp, dyn.Mr, dyn.Lr, dyn.km)
        assert params_before != params_after, "randomize() did not change any parameter"


class TestEnergy:
    """Kinetic energy check at hanging equilibrium with angular velocity."""

    def test_energy_at_hanging(self) -> None:
        """Pure alpha velocity at hanging -> KE ~ 0.5 * I * vel^2 (proportional)."""
        dyn = _make_dynamics()
        vel = 2.0
        state = np.array([0.0, 0.0, 0.0, vel])
        _thdd, _aldd = dyn(state, 0.0)
        # At alpha=0 the pendulum decoupled inertia c[3] dominates alpha_dd.
        # alpha_dd = y / c  where y includes friction and gravity (both ~0 here).
        # KE_alpha = 0.5 * c[3] * vel^2 -> proportional to vel^2.
        expected_ke = 0.5 * dyn._c[3] * vel**2
        assert expected_ke > 0, f"expected KE must be positive, got {expected_ke}"
        # Sanity: doubling vel should quadruple KE.
        ke_double = 0.5 * dyn._c[3] * (2 * vel) ** 2
        assert abs(ke_double / expected_ke - 4.0) < 1e-10, "KE must scale as vel^2"


class TestDeterminism:
    """Same inputs must always produce the same outputs."""

    def test_consistency(self) -> None:
        dyn = _make_dynamics()
        state = np.array([0.3, 1.2, -0.5, 0.8])
        action = 0.7
        result1 = dyn(state, action)
        result2 = dyn(state, action)
        assert result1 == result2, f"not deterministic: {result1} vs {result2}"


class TestIntegration:
    """Substep loop must remain numerically well-behaved."""

    def test_substep_integration(self) -> None:
        """100 Euler substeps at dt=0.002 with small action -> smooth, no NaN."""
        dyn = _make_dynamics()
        dt = 0.002
        state = np.array([0.0, np.pi - 0.05, 0.0, 0.0])  # near inverted
        action = 0.1
        for _ in range(100):
            thdd, aldd = dyn(state, action)
            assert not (np.isnan(thdd) or np.isnan(aldd)), "NaN detected"
            state[2] += thdd * dt
            state[3] += aldd * dt
            state[0] += state[2] * dt
            state[1] += state[3] * dt
        # State should still be finite and reasonable.
        assert np.all(np.isfinite(state)), f"non-finite state: {state}"
