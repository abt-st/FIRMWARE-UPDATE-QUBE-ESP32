"""Gray-box system identification for the QUBE Servo digital twin (Fase 1).

This module turns recorded :class:`~qube_analysis.dataset.QubeRun` captures into
physical parameters of :class:`qube_rl.envs.qube_dynamics.QubeDynamics`.  It is
the reproducible *script de identificación* called for by Fase 1 of
``docs/research/ai_research/plan_gemelo_digital_drl.md``.

What it identifies and how
==========================

**Pendulum free-decay** (motor off, pendulum released and left to swing down).
The small-oscillation dynamics about the hanging equilibrium, with the arm
fixed, are a damped linear oscillator::

    alpha_ddot + (Dp / J) alpha_dot + (omega_n^2) alpha = 0
    omega_n^2 = Mp g (Lp/2) / J,    J = Mp Lp^2 / 3   (uniform rod about pivot)

Substituting ``J`` makes ``omega_n`` depend on ``Lp`` *only* (not ``Mp``)::

    omega_n = sqrt(3 g / (2 Lp))   ==>   Lp = 3 g / (2 omega_n^2)
    Dp = 2 zeta J omega_n = 2 zeta (Mp Lp^2 / 3) omega_n

These relations are *exactly* the ones encoded in ``QubeDynamics._init_const``
(``omega_n^2 = c[4] / c[3]``), so a fit feeds straight back into the twin.
``Lp`` comes from the oscillation *period* alone; ``Dp`` additionally needs the
pendulum mass ``Mp`` (cheap to measure on a scale).

**Actuator dead-zone** (motor mode 1, slow PWM staircase).  The smallest ``|PWM|``
that still produces no arm motion — the static-friction / driver threshold.

Caveats (be honest in the thesis)
=================================
* The fixed-base small-angle relation assumes the *arm is clamped*.  In an
  opportunistic coast-down where the arm also swings, ``omega_n`` is the coupled
  mode and ``Lp`` is biased; use a clamped-arm capture (see
  ``experiments/PROTOCOLO_IDENTIFICACION.md``) for the reportable value.
* Host-polled logging tops out near ~30 Hz, so estimates of fast actuator
  dynamics are coarse.  Pendulum identification (~2 Hz) is well sampled.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dataset import QubeRun

G = 9.81  # gravitational acceleration [m/s^2]


# ---------------------------------------------------------------------------
# Damped-oscillation fit (the numerical core)
# ---------------------------------------------------------------------------


@dataclass
class DampedFit:
    """Result of fitting ``A e^{-zeta wn t} cos(wd t + phi) + offset`` to a signal.

    Attributes:
        omega_n: Undamped natural frequency [rad/s].
        zeta: Dimensionless damping ratio.
        omega_d: Damped frequency ``wn sqrt(1 - zeta^2)`` [rad/s].
        amplitude: Initial oscillation amplitude (same units as the signal).
        offset: Equilibrium offset (the hanging angle).
        phase: Phase [rad].
        r2: Coefficient of determination of the fit (1.0 = perfect).
        n: Number of samples used.
    """

    omega_n: float
    zeta: float
    omega_d: float
    amplitude: float
    offset: float
    phase: float
    r2: float
    n: int

    @property
    def period(self) -> float:
        """Damped oscillation period [s]."""
        return float(2 * np.pi / self.omega_d) if self.omega_d > 0 else float("nan")

    @property
    def freq_hz(self) -> float:
        """Damped frequency [Hz]."""
        return float(self.omega_d / (2 * np.pi))


def _initial_frequency(t: np.ndarray, x: np.ndarray) -> float:
    """Rough natural-frequency guess [rad/s] from the dominant FFT bin."""
    x = x - np.mean(x)
    dt = float(np.median(np.diff(t)))
    if not np.isfinite(dt) or dt <= 0 or len(x) < 4:
        return 2 * np.pi  # 1 Hz fallback
    # Uniformly resample onto the median grid so np.fft is meaningful.
    grid = np.arange(t[0], t[-1], dt)
    xr = np.interp(grid, t, x)
    spec = np.abs(np.fft.rfft(xr * np.hanning(len(xr))))
    freqs = np.fft.rfftfreq(len(xr), dt)
    spec[0] = 0.0  # ignore DC
    f_peak = freqs[int(np.argmax(spec))]
    return float(2 * np.pi * f_peak) if f_peak > 0 else 2 * np.pi


def fit_damped_oscillation(t: np.ndarray, x: np.ndarray) -> DampedFit:
    """Fit a decaying sinusoid to ``x(t)`` and return its modal parameters.

    Uses an FFT-seeded non-linear least squares (``scipy.optimize.curve_fit``)
    so it is robust to the unknown phase, offset and decay.  ``t`` need not be
    uniformly sampled.

    Raises:
        ValueError: If fewer than 6 finite samples are available.
    """
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    mask = np.isfinite(t) & np.isfinite(x)
    t, x = t[mask], x[mask]
    if len(t) < 6:
        raise ValueError(f"need >=6 finite samples, got {len(t)}")
    t = t - t[0]

    from scipy.optimize import curve_fit  # lazy: keeps import-time light

    def model(tt, amp, zeta, wn, phi, off):
        wd = wn * np.sqrt(max(1e-9, 1.0 - zeta**2))
        return amp * np.exp(-zeta * wn * tt) * np.cos(wd * tt + phi) + off

    wn0 = _initial_frequency(t, x)
    amp0 = float((np.nanmax(x) - np.nanmin(x)) / 2) or 1.0
    p0 = [amp0, 0.02, wn0, 0.0, float(np.mean(x))]
    bounds = (
        [-10 * abs(amp0) - 1, 0.0, 0.1 * wn0, -2 * np.pi, np.min(x) - abs(amp0)],
        [10 * abs(amp0) + 1, 0.999, 10 * wn0, 2 * np.pi, np.max(x) + abs(amp0)],
    )
    popt, _ = curve_fit(model, t, x, p0=p0, bounds=bounds, maxfev=20000)
    amp, zeta, wn, phi, off = popt

    resid = x - model(t, *popt)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((x - np.mean(x)) ** 2))
    # A (near-)flat signal has no variance to explain: its "perfect" fit is
    # meaningless, so report r2=0 rather than a spurious 1.0.
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

    wd = wn * np.sqrt(max(0.0, 1.0 - zeta**2))
    return DampedFit(
        omega_n=float(wn), zeta=float(zeta), omega_d=float(wd),
        amplitude=float(abs(amp)), offset=float(off), phase=float(phi),
        r2=float(r2), n=int(len(t)),
    )


# ---------------------------------------------------------------------------
# Mapping a fit -> physical pendulum parameters
# ---------------------------------------------------------------------------


@dataclass
class PendulumParams:
    """Identified pendulum parameters with their source fit.

    ``Lp`` follows from the period only; ``Dp`` also needs the measured mass
    ``Mp``.  See module docstring for the (fixed-base, small-angle) assumptions.
    """

    Lp: float           # pendulum length [m]
    Dp: float           # viscous friction [N*m*s/rad]
    omega_n: float      # natural frequency [rad/s]
    zeta: float         # damping ratio
    Mp: float           # mass used for Dp [kg] (an input, echoed for the record)
    r2: float           # quality of the underlying damped-sine fit


def identify_pendulum(fit: DampedFit, *, Mp: float, g: float = G) -> PendulumParams:
    """Map a free-decay :class:`DampedFit` to ``Lp`` and ``Dp``.

    Args:
        fit: Result of :func:`fit_damped_oscillation` on the pendulum angle.
        Mp: Pendulum mass [kg] (measure on a scale — ``Dp`` scales with it).
        g: Gravitational acceleration [m/s^2].
    """
    wn = fit.omega_n
    Lp = 3.0 * g / (2.0 * wn**2)
    J = Mp * Lp**2 / 3.0  # inertia about the pivot (uniform rod)
    Dp = 2.0 * fit.zeta * J * wn
    return PendulumParams(Lp=Lp, Dp=Dp, omega_n=wn, zeta=fit.zeta, Mp=Mp, r2=fit.r2)


def identify_pendulum_from_runs(
    runs: list[QubeRun],
    *,
    Mp: float,
    angle: str = "alpha_deg",
    min_r2: float = 0.8,
    g: float = G,
) -> tuple[PendulumParams | None, list[PendulumParams]]:
    """Identify the pendulum from several free-decay runs and aggregate.

    Each run is fitted independently; fits below ``min_r2`` are discarded.  The
    aggregate uses the per-run median (robust to one bad capture) and the std
    across runs is the empirical uncertainty to feed back into ``*_std`` for
    domain randomisation.

    Returns:
        ``(aggregate, per_run)``.  ``aggregate`` is ``None`` if no run qualified;
        its ``r2`` field carries the across-run std of ``Lp`` as a rough spread
        indicator, and ``per_run`` keeps every accepted estimate.
    """
    accepted: list[PendulumParams] = []
    for r in runs:
        if angle not in r.data:
            continue
        try:
            fit = fit_damped_oscillation(r.data["t_s"], np.deg2rad(r.data[angle]))
        except (ValueError, RuntimeError):
            continue
        if fit.r2 >= min_r2 and fit.zeta < 0.9:
            accepted.append(identify_pendulum(fit, Mp=Mp, g=g))

    if not accepted:
        return None, []

    lp = float(np.median([p.Lp for p in accepted]))
    dp = float(np.median([p.Dp for p in accepted]))
    wn = float(np.median([p.omega_n for p in accepted]))
    ze = float(np.median([p.zeta for p in accepted]))
    spread = float(np.std([p.Lp for p in accepted]))
    agg = PendulumParams(Lp=lp, Dp=dp, omega_n=wn, zeta=ze, Mp=Mp, r2=spread)
    return agg, accepted


# ---------------------------------------------------------------------------
# Actuator dead-zone
# ---------------------------------------------------------------------------


@dataclass
class DeadzoneResult:
    """Identified actuator dead-zone (PWM threshold for motion onset)."""

    pwm_threshold: float   # largest |PWM| that still produced no motion
    pwm_moving: float      # smallest |PWM| that produced motion (NaN if none)
    speed_noise: float     # arm-speed noise floor [deg/s] used as the cutoff


def estimate_deadzone(
    run: QubeRun,
    *,
    angle: str = "theta_deg",
    speed_factor: float = 3.0,
) -> DeadzoneResult:
    """Estimate the PWM dead-zone from a slow PWM staircase capture.

    Bins samples by their (rounded) PWM level and finds where the arm speed
    ``|d(angle)/dt|`` rises above ``speed_factor`` times its at-rest noise.

    Args:
        run: A mode-1 capture sweeping PWM slowly through the threshold.
        angle: Position signal whose derivative is the speed (the arm,
            ``theta_deg``, is the cleanest).
        speed_factor: Multiple of the rest-noise speed counted as "moving".

    Raises:
        ValueError: If ``pwm`` or ``angle`` is missing.
    """
    if "pwm" not in run.data or angle not in run.data:
        raise ValueError(f"run needs 'pwm' and '{angle}'")
    t = run.data["t_s"]
    pwm = run.data["pwm"]
    pos = run.data[angle]
    dt = np.diff(t)
    speed = np.abs(np.diff(pos) / np.where(dt > 0, dt, np.nan))
    apwm = np.abs(pwm[1:])

    at_rest = speed[apwm <= 1]
    noise = float(np.nanmedian(at_rest)) if at_rest.size else 0.0
    cutoff = speed_factor * max(noise, 1e-6)

    moving = apwm[speed > cutoff]
    still = apwm[(speed <= cutoff) & (apwm > 1)]
    return DeadzoneResult(
        pwm_threshold=float(np.nanmax(still)) if still.size else 0.0,
        pwm_moving=float(np.nanmin(moving)) if moving.size else float("nan"),
        speed_noise=noise,
    )
