"""Energy-based swing-up + LQR balance controller for QUBE Servo.

Bang-bang parametric excitation:
    Arm oscillates between ±theta_limit. Direction reverses when EITHER:
    1. Arm approaches theta limit (physical constraint)
    2. Pendulum velocity crosses zero (energy injection timing)

    This synchronizes arm motion with the pendulum, injecting energy
    each cycle until the pendulum reaches the upper region.

LQR handoff:
    When pendulum is near inverted AND slow → LQR stabilizes.

Reference:
    Wiklund et al., "A new strategy for swing up a pendulum", Automatica, 1993.
"""

from __future__ import annotations

import numpy as np

from qube_rl.lqr import LQRBalance


class EnergySwingUp:
    """Bang-bang energy swing-up with LQR handoff.

    Returns (action, phase) from step(state).
    """

    def __init__(
        self,
        switch_angle_deg: float = 155.0,
        theta_limit_deg: float = 80.0,
        theta_soft_deg: float = 70.0,
        max_action: float = 0.75,
    ) -> None:
        self.switch_angle = np.radians(switch_angle_deg)
        self.theta_limit = np.radians(theta_limit_deg)
        self.theta_soft = np.radians(theta_soft_deg)
        self.max_action = max_action

        self.lqr = LQRBalance()

        self.arm_dir = 1.0
        self.prev_alpha_dot = 0.0
        self.phase = "swingup"

    def step(self, state: np.ndarray) -> tuple[float, str]:
        th, al, _thd, ald = state

        # Check LQR handoff: near inverted AND slow
        if abs(al) > self.switch_angle and abs(ald) < 1.5:
            self.phase = "balance"
            self.prev_alpha_dot = ald
            return float(self.lqr.control(state)), "balance"

        self.phase = "swingup"

        # ── Arm direction reversal logic ──
        # Reverse when alpha_dot crosses zero (pump energy)
        alpha_dot_crossed = self.prev_alpha_dot * ald < 0
        # Reverse when theta approaches limit (prevent hitting wall)
        theta_near_limit = abs(th) > self.theta_soft

        if alpha_dot_crossed or theta_near_limit:
            self.arm_dir *= -1.0

        self.prev_alpha_dot = ald

        # ── Bang-bang action ──
        action = self.arm_dir * self.max_action

        # Reduce amplitude when pendulum is near vertical
        # (pumping is most effective at 45°-135° from top)
        effective_pumping = abs(np.sin(al))
        if effective_pumping < 0.3:
            action *= 0.5

        # ── Hard theta limit ──
        if abs(th) > self.theta_limit:
            action = -np.sign(th) * self.max_action

        # Deadzone
        if abs(action) < 0.15:
            action = np.sign(action) * 0.15 if action != 0 else 0.0

        return float(np.clip(action, -self.max_action, self.max_action)), self.phase

    def reset(self) -> None:
        self.arm_dir = 1.0
        self.prev_alpha_dot = 0.0
        self.phase = "swingup"


def run_simulation(
    ctrl: EnergySwingUp | None = None,
    max_steps: int = 500,
    verbose: bool = True,
) -> dict:
    """Run swing-up + LQR in the QUBE simulation."""
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating

    def _make():
        env = QubeSimEnv(
            control_freq=50,
            reward="linear_alpha",
            angle_limits=[np.pi / 2, np.pi],
            speed_limits=[50.0, 400.0],
            encoders_cprs=None,
            velocity_filter_order=2,
        )
        env = Monitor(env)
        env = GentlyTerminating(env)
        env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
        return env

    if ctrl is None:
        ctrl = EnergySwingUp()

    vec_env = DummyVecEnv([_make])
    obs = vec_env.reset()
    ctrl.reset()

    reached_top = False
    balanced_steps = 0
    phases = []
    alphas = []

    for _ in range(max_steps):
        state = obs[0][:4].astype(np.float64)
        action, phase = ctrl.step(state)
        phases.append(phase)
        alphas.append(np.degrees(state[1]))
        obs, _, done, _ = vec_env.step(np.array([[action]]))

        if abs(np.degrees(state[1])) > 150:
            reached_top = True
        if reached_top and phase == "balance":
            balanced_steps += 1
        if done[0]:
            break

    n = len(phases)
    bal_ratio = balanced_steps / max(1, n)
    last_q = alphas[-n // 4 :] if n > 4 else []
    stayed = all(abs(a) > 150 for a in last_q) if last_q else False

    result = {
        "reached_top": reached_top,
        "balanced_steps": balanced_steps,
        "total_steps": n,
        "balance_ratio": bal_ratio,
        "stayed_up": stayed,
        "final_alpha": alphas[-1] if alphas else 0,
    }

    if verbose:
        print(
            f"Steps: {n}  Reached: {reached_top}  Balanced: {balanced_steps} ({bal_ratio * 100:.0f}%)  Stayed: {stayed}"
        )

    return result
