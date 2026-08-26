"""LQR balance controller for the QUBE Servo rotary inverted pendulum.

Linearises the dynamics around the inverted equilibrium (alpha = pi)
and computes the optimal state-feedback gain via the continuous-time
algebraic Riccati equation (CARE).

The controller is designed to stabilise the pendulum near the upright
position once SAC has achieved swing-up.
"""

from __future__ import annotations

import numpy as np
from scipy import linalg

from qube_rl.envs.qube_dynamics import QubeDynamics


def linearise_inverted(dyn: QubeDynamics | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Linearise dynamics around alpha = pi (inverted equilibrium).

    Returns (A, B) where dx/dt = A @ x + B @ u, with
    x = [theta, alpha - pi, theta_dot, alpha_dot] and u in [-1, 1].
    """
    if dyn is None:
        dyn = QubeDynamics()

    al = np.pi  # inverted equilibrium (theta = thd = ald = 0)

    # Physical constants at equilibrium
    sin_al = np.sin(al)  # 0
    cos_al = np.cos(al)  # -1

    a = dyn._c[0] + dyn._c[1] * sin_al**2  # _c[0]
    b = dyn._c[2] * cos_al  # -_c[2]
    c = dyn._c[3]
    d = a * c - b * b  # det(M)
    if abs(d) < 1e-12:
        raise ValueError(
            f"Singular mass matrix at the inverted equilibrium (det(M)={d:.3e}); "
            "check the physical parameters of the dynamics model."
        )

    # Jacobian of EOM w.r.t. state [th, al, thd, ald]
    # d(thdd)/d(al) = (c * d(tau)/d(al) - b * d(y)/d(al)) / d
    # Since tau doesn't depend on al, d(tau)/d(al) = 0
    # d(y)/d(al) = -d(Dp*ald)/d(al) - d(c1)/d(al)
    # c1 = -0.5*_c[1]*sin_2al*thd^2 + _c[4]*sin_al
    # d(c1)/d(al) = -_c[1]*cos_2al*thd^2 + _c[4]*cos_al = _c[4]*(-1) = -_c[4]
    # d(y)/d(al) = _c[4]

    # d(thdd)/d(th) = 0
    # d(thdd)/d(thd) = (c * d(tau)/d(thd)) / d
    # tau = km/V * (V*u - km*thd) / Rm = km*u/Rm - km^2*thd/(V*Rm)
    # Actually: trq = reduction * km * (V*u - km*thd*reduction) / Rm
    # d(trq)/d(thd) = -reduction^2 * km^2 / Rm
    d_trq_d_thd = -(dyn.reduction_ratio**2) * dyn.km**2 / dyn.Rm
    d_trq_d_u = dyn.reduction_ratio * dyn.km * dyn.V / dyn.Rm

    # d(thdd)/d(thd) = (c * d_trq_d_thd - c * Dr) / d
    d_thdd_d_thd = (c * (d_trq_d_thd - dyn.Dr)) / d
    # d(thdd)/d(ald) = -b * (-Dp) / d = b * Dp / d
    d_thdd_d_ald = (b * dyn.Dp) / d

    # d(aldd)/d(al) = (a * _c[4] - b * 0) / d = a * _c[4] / d
    d_aldd_d_al = a * dyn._c[4] / d
    # d(aldd)/d(thd) = (a * 0 - b * d_trq_d_thd) / d = -b * d_trq_d_thd / d
    d_aldd_d_thd = -b * d_trq_d_thd / d
    # d(aldd)/d(ald) = (-a * Dp) / d
    d_aldd_d_ald = -a * dyn.Dp / d

    A = np.array(
        [
            [0, 0, 1, 0],
            [0, 0, 0, 1],
            [0, 0, d_thdd_d_thd, d_thdd_d_ald],
            [0, d_aldd_d_al, d_aldd_d_thd, d_aldd_d_ald],
        ]
    )

    # d(thdd)/d(u) = c * d_trq_d_u / d
    d_thdd_d_u = c * d_trq_d_u / d
    # d(aldd)/d(u) = -b * d_trq_d_u / d
    d_aldd_d_u = -b * d_trq_d_u / d

    B = np.array([[0], [0], [d_thdd_d_u], [d_aldd_d_u]])

    return A, B


def compute_lqr_gain(
    dyn: QubeDynamics | None = None,
    Q: np.ndarray | None = None,
    R: float = 1.0,
) -> np.ndarray:
    """Compute LQR gain K for the inverted equilibrium.

    Parameters
    ----------
    dyn : QubeDynamics, optional
        Dynamics model.  If None, uses default parameters.
    Q : np.ndarray (4x4), optional
        State cost matrix.  Diagonal: [theta_cost, alpha_cost, thetadot_cost, alphadot_cost].
    R : float
        Control cost.

    Returns
    -------
    np.ndarray (1, 4)
        Optimal gain K such that u = -K @ x.
    """
    if dyn is None:
        dyn = QubeDynamics()

    A, B = linearise_inverted(dyn)

    if Q is None:
        # Penalise angular deviations and velocities
        Q = np.diag([1.0, 10.0, 1.0, 5.0])

    # Solve continuous-time algebraic Riccati equation
    # A^T P + P A - P B R^{-1} B^T P + Q = 0
    S = linalg.solve_continuous_are(A, B, Q, np.atleast_2d(R))

    # Optimal gain: K = R^{-1} B^T P
    K = (1.0 / R) * B.T @ S

    return K.astype(np.float32)


class LQRBalance:
    """LQR controller for balancing near the inverted equilibrium.

    Usage::

        lqr = LQRBalance()
        action = lqr.control(state)  # state = [theta, alpha, theta_dot, alpha_dot]
    """

    def __init__(
        self,
        dyn: QubeDynamics | None = None,
        Q: np.ndarray | None = None,
        R: float = 1.0,
        switch_angle: float = np.radians(150),
    ) -> None:
        self.dyn = dyn or QubeDynamics()
        self.K = compute_lqr_gain(self.dyn, Q, R)
        self.switch_angle = switch_angle  # alpha threshold to activate LQR

    def should_activate(self, alpha: float) -> bool:
        """Check if the pendulum is close enough to inverted for LQR."""
        return abs(alpha) > self.switch_angle

    def control(self, state: np.ndarray) -> float:
        """Compute LQR action from state [theta, alpha, theta_dot, alpha_dot].

        The state is relative to the inverted equilibrium:
        x = [theta, alpha - pi, theta_dot, alpha_dot]
        """
        th, al, thd, ald = state

        # Convert to error relative to inverted position
        x = np.array(
            [
                th,
                al - np.pi * np.sign(al),  # wrap to [-pi, pi] around pi
                thd,
                ald,
            ]
        )

        # Handle alpha wrapping: find shortest path to pi
        al_err = al - np.pi
        if al_err > np.pi:
            al_err -= 2 * np.pi
        elif al_err < -np.pi:
            al_err += 2 * np.pi
        x[1] = al_err

        action = -float((self.K @ x).item())

        # Clip to valid action range
        return float(np.clip(action, -1.0, 1.0))
