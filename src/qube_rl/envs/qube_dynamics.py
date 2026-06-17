"""Analytical dynamics model for the QUBE Servo rotary inverted pendulum.

Solves the equations of motion  M(q) q_dd + C(q, q_d) = tau  for q_dd,
where q = [theta, alpha].  Ported from Armandpl/furuta with QUBE-specific
default parameters.

Domain randomisation: call ``randomize()`` before each training episode to
sample physical parameters from Gaussian distributions, making the learned
policy robust to modelling errors (key technique for sim-to-real transfer).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class QubeDynamics:
    """Equations of motion for a rotary inverted pendulum (Furuta / QUBE).

    Physical parameter defaults correspond to the QUBE Servo hardware built
    with ESP32 + BTS7960 + Premotec motor.  The ``*_std`` fields control the
    spread of the Gaussian used by :meth:`randomize` for domain randomisation.
    """

    g: float = 9.81  # gravitational acceleration [m/s^2]

    # --- Motor (BTS7960 + Premotec 9904 120 16913) ---
    Rm: float = 8.4  # terminal resistance [Ohm]
    Rm_std: float = 1.5
    V: float = 12.0  # nominal voltage [V]
    reduction_ratio: float = 1.0  # gear ratio (1 = direct drive)
    stall_torque: float = 0.16  # stall torque [N*m]
    km: float = 0.042  # back-emf constant [V*s/rad]
    km_std: float = 0.01

    # --- Rotary arm (servo) ---
    Mr: float = 0.095  # mass [kg]
    Mr_std: float = 0.02
    Lr: float = 0.085  # length [m]
    Lr_std: float = 0.01
    Dr: float = 5e-6  # viscous friction [N*m*s/rad]
    Dr_std: float = 5e-6

    # --- Pendulum link ---
    Mp: float = 0.024  # mass [kg]
    Mp_std: float = 0.003
    Lp: float = 0.129  # length [m]
    Lp_std: float = 0.010
    Dp: float = 1e-6  # viscous friction [N*m*s/rad]
    Dp_std: float = 5e-7

    # --- Precomputed constants (populated by _init_const) ---
    _c: np.ndarray = field(default_factory=lambda: np.zeros(5), repr=False)

    def __post_init__(self) -> None:
        self.randomize()

    # ------------------------------------------------------------------
    # Domain randomisation
    # ------------------------------------------------------------------

    def randomize(self) -> None:
        """Sample physical parameters from their Gaussian distributions."""
        self.Rm = float(np.random.normal(self.Rm, self.Rm_std))
        self.km = float(np.random.normal(self.km, self.km_std))
        self.Mr = float(np.random.normal(self.Mr, self.Mr_std))
        self.Lr = float(np.random.normal(self.Lr, self.Lr_std))
        self.Dr = float(np.random.normal(self.Dr, self.Dr_std))
        self.Mp = float(np.random.normal(self.Mp, self.Mp_std))
        self.Lp = float(np.random.normal(self.Lp, self.Lp_std))
        self.Dp = float(np.random.normal(self.Dp, self.Dp_std))
        self._init_const()

    # ------------------------------------------------------------------
    # Precomputed constants
    # ------------------------------------------------------------------

    def _init_const(self) -> None:
        """Compute composite inertia constants used in the EOM."""
        jr = self.Mr * self.Lr**2 / 12  # arm inertia about COM
        jp = self.Mp * self.Lp**2 / 12  # pendulum inertia about COM

        self._c = np.zeros(5)
        self._c[0] = jr + self.Mp * self.Lr**2
        self._c[1] = 0.25 * self.Mp * self.Lp**2
        self._c[2] = 0.5 * self.Mp * self.Lp * self.Lr
        self._c[3] = jp + self._c[1]
        self._c[4] = 0.5 * self.Mp * self.Lp * self.g

    # ------------------------------------------------------------------
    # Equations of motion
    # ------------------------------------------------------------------

    def __call__(self, state: np.ndarray, action: float) -> tuple[float, float]:
        """Compute angular accelerations for the current state and action.

        Parameters
        ----------
        state : np.ndarray
            ``[theta, alpha, theta_dot, alpha_dot]``
        action : float
            Normalised voltage in [-1, 1], mapped to ``[-V, +V]``.

        Returns
        -------
        tuple[float, float]
            ``(theta_dd, alpha_dd)``
        """
        _th, al, thd, ald = state
        voltage = action * self.V

        sin_al = np.sin(al)
        sin_2al = np.sin(2 * al)
        cos_al = np.cos(al)

        # Mass matrix  M = [[a, b], [b, c]]
        a = self._c[0] + self._c[1] * sin_al**2
        b = self._c[2] * cos_al
        c = self._c[3]
        d = a * c - b * b  # det(M)

        # Motor torque (steady-state DC motor model)
        trq = self.reduction_ratio * self.km * (voltage - self.km * thd * self.reduction_ratio) / self.Rm
        trq = np.clip(trq, -self.stall_torque, self.stall_torque)

        # Coriolis / centrifugal terms
        c0 = self._c[1] * sin_2al * thd * ald - self._c[2] * sin_al * ald * ald
        c1 = -0.5 * self._c[1] * sin_2al * thd * thd + self._c[4] * sin_al

        # tau - C(q, qd)
        x = trq - self.Dr * thd - c0
        y = -self.Dp * ald - c1

        # M^{-1} @ [x, y]
        thdd = (c * x - b * y) / d
        aldd = (a * y - b * x) / d

        return float(thdd), float(aldd)
