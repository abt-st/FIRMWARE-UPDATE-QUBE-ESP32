"""Single source of truth for building QUBE RL environments.

Previously every entry point (``train``, ``fast_train``, ``auto_train``,
``finetune``, ``inference``) defined its own ``make_env``/``make_real_env`` with
slightly different — and sometimes inconsistent — wrapper stacks (hardcoded
dead-zones, missing ``HistoryWrapper``, no episode time limit).  These helpers
consolidate that logic so the simulation, real-hardware and (after history
stacking) firmware observation contracts can never silently diverge.

Wrapper order (inner -> outer)::

    QubeSimEnv -> TimeLimit -> Monitor -> GentlyTerminating -> DeadZone
                -> HistoryWrapper -> [PotentialShaping]

``TimeLimit`` sits *inside* ``Monitor`` so the monitor records the episode when
the time limit truncates it.  ``Monitor`` records the **base** reward (it is
inside the reward-modifying wrappers), so the continuity cost and any
potential-based shaping do not pollute the reported ``ep_rew_mean``.
"""

from __future__ import annotations

import gymnasium as gym

from qube_rl.config import DEFAULT_ESP32_IP, EnvConfig, WrapperConfig


def make_sim_env(
    control_freq: int | None = None,
    reward: str | None = None,
    angle_limits: list[float] | None = None,
    speed_limits: list[float] | None = None,
    encoders_cprs: list[float | None] | None = None,
    velocity_filter_order: int | None = None,
    max_episode_steps: int | None = None,
    history_steps: int | None = None,
    use_continuity_cost: bool | None = None,
    deadzone: float | None = None,
    deadzone_center: float | None = None,
    deadzone_max_act: float | None = None,
    monitor: bool = True,
    potential: str | None = None,
    potential_gamma: float = 0.99,
    potential_scale: float = 1.0,
    potential_energy_weight: float = 1.0,
    near_upright_prob: float | None = None,
) -> gym.Env:
    """Build the simulation environment with the standard wrapper stack.

    Any argument left as ``None`` falls back to :class:`EnvConfig` /
    :class:`WrapperConfig` defaults.  Set ``max_episode_steps=0`` to disable the
    ``TimeLimit`` and ``history_steps=0`` to disable the ``HistoryWrapper``.
    Pass ``potential="upright"`` to add policy-invariant PBRS shaping.
    """
    from gymnasium.wrappers import TimeLimit
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper, PotentialShaping

    ecfg = EnvConfig()
    wcfg = WrapperConfig()
    control_freq = ecfg.control_freq if control_freq is None else control_freq
    reward = ecfg.reward if reward is None else reward
    angle_limits = ecfg.angle_limits if angle_limits is None else angle_limits
    speed_limits = ecfg.speed_limits if speed_limits is None else speed_limits
    velocity_filter_order = ecfg.velocity_filter_order if velocity_filter_order is None else velocity_filter_order
    max_episode_steps = ecfg.max_episode_steps if max_episode_steps is None else max_episode_steps
    history_steps = wcfg.history_steps if history_steps is None else history_steps
    use_continuity_cost = wcfg.use_continuity_cost if use_continuity_cost is None else use_continuity_cost
    deadzone = wcfg.deadzone if deadzone is None else deadzone
    deadzone_center = wcfg.deadzone_center if deadzone_center is None else deadzone_center
    deadzone_max_act = wcfg.deadzone_max_act if deadzone_max_act is None else deadzone_max_act
    near_upright_prob = ecfg.near_upright_prob if near_upright_prob is None else near_upright_prob

    env: gym.Env = QubeSimEnv(
        control_freq=control_freq,
        reward=reward,
        angle_limits=angle_limits,
        speed_limits=speed_limits,
        encoders_cprs=encoders_cprs,
        velocity_filter_order=velocity_filter_order,
        near_upright_prob=near_upright_prob,
    )
    if max_episode_steps:
        env = TimeLimit(env, max_episode_steps=max_episode_steps)
    if monitor:
        env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=deadzone, center=deadzone_center, max_act=deadzone_max_act)
    if history_steps:
        env = HistoryWrapper(env, steps=history_steps, use_continuity_cost=use_continuity_cost)
    if potential:
        env = PotentialShaping(
            env,
            potential=potential,
            gamma=potential_gamma,
            scale=potential_scale,
            energy_weight=potential_energy_weight,
        )
    return env


def make_real_env(
    esp32_ip: str = DEFAULT_ESP32_IP,
    control_freq: int | None = None,
    reward: str = "cos_alpha",
    http_timeout: float = 5.0,
    max_episode_steps: int | None = None,
    history_steps: int | None = None,
    use_continuity_cost: bool = False,
    monitor: bool = False,
    auto_set_mode: bool = True,
    invert_action: bool = True,
    invert_alpha: bool = True,
    angle_limits: list[float] | None = None,
    homing_every: int | None = None,
    homing_on_start: bool = False,
) -> gym.Env:
    """Build the real-hardware (ESP32 over HTTP) environment.

    Mirrors :func:`make_sim_env`'s wrapper stack (minus the simulator) so a
    policy trained in sim sees the same observation layout on hardware.

    ``homing_every`` / ``homing_on_start`` se agregaron el 2026-08-04: existian en
    ``QubeRealEnv`` pero esta factory no los pasaba, asi que **por aca el homing era
    inalcanzable** y todo evaluador construido con ella arrancaba los episodios con el
    brazo donde hubiera quedado la corrida anterior.

    Por que importa: la escalera de seguridad del firmware abraza la accion del modo 6
    a partir de |theta| = 80 grados y hace setMode(0) a los 95. Si el brazo arranca
    pasado ese punto, el episodio muere en el primer paso — y como
    ``updateRlObservation`` solo corre en los modos 6 y 7, ``/rl_state`` queda
    CONGELADO en el ultimo valor en vez de fallar. La politica sigue "corriendo" cientos
    de pasos contra una observacion muerta y el resultado parece una brecha sim2real
    catastrofica. Medido asi el 2026-08-04: 3 episodios arrancando en 91-94 grados,
    reach=0%, theta constante en las 1500 muestras.
    """
    from gymnasium.wrappers import TimeLimit
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_real import QubeRealEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

    ecfg = EnvConfig()
    wcfg = WrapperConfig()
    control_freq = ecfg.control_freq if control_freq is None else control_freq
    max_episode_steps = ecfg.max_episode_steps if max_episode_steps is None else max_episode_steps
    history_steps = wcfg.history_steps if history_steps is None else history_steps

    env: gym.Env = QubeRealEnv(
        esp32_ip=esp32_ip,
        control_freq=control_freq,
        reward=reward,
        http_timeout=http_timeout,
        auto_set_mode=auto_set_mode,
        invert_action=invert_action,
        invert_alpha=invert_alpha,
        angle_limits=angle_limits,
        homing_every=homing_every,
        homing_on_start=homing_on_start,
    )
    if max_episode_steps:
        env = TimeLimit(env, max_episode_steps=max_episode_steps)
    if monitor:
        env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=wcfg.deadzone, center=wcfg.deadzone_center, max_act=wcfg.deadzone_max_act)
    if history_steps:
        env = HistoryWrapper(env, steps=history_steps, use_continuity_cost=use_continuity_cost)
    return env
