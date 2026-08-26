"""Gymnasium environment that controls the physical QUBE Servo via HTTP.

Talks to the ESP32's ``/rl_state`` and ``/rl_cmd`` endpoints at 50 Hz.
Compatible with concurrent MCP usage (separate HTTP connections, no shared state).

Concurrency contract:
    - The ESP32 async web server handles concurrent HTTP requests natively.
    - ``QubeRealEnv`` uses its own ``requests.Session`` (connection pooling).
    - MCP tools use separate ``requests.get()`` calls (no session).
    - Both can read ``/state`` or ``/rl_state`` simultaneously without conflict.
    - **Writing** (``/cmd``, ``/rl_cmd``) from both simultaneously is undefined:
      last-write-wins. The RL agent should be the sole writer when active.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, ClassVar

import gymnasium as gym
import numpy as np
import requests
from gymnasium.spaces import Box

from qube_rl.config import DEFAULT_ESP32_IP, MAX_VELOCITY
from qube_rl.rewards import REWARDS
from qube_rl.utils import ALPHA, ALPHA_DOT, THETA, THETA_DOT, Timing, observation_from_state

logger = logging.getLogger(__name__)

# /rl_state protocol version this env expects. MUST match RL_PROTO_VERSION in the
# firmware (src/firmware/esp32_qube/esp32_qube.ino). The firmware reports it as the
# "pv" field and reset() asserts it, so a firmware/Python mismatch fails loudly
# instead of training on wrong-signed observations (the sim2real critical caveat).
# BUMP BOTH SIDES TOGETHER whenever the /rl_state convention changes.
# v3 adds the combined GET /rl_step?a=X endpoint (set action + return state in one
# round-trip); step() below requires it, so the assert in reset() makes an old
# firmware (no /rl_step) fail loudly instead of 404'ing mid-episode.
EXPECTED_RL_PROTO = 3


class QubeRealEnv(gym.Env):
    """Gymnasium environment for the real QUBE Servo (ESP32 over WiFi).

    Observation space (8-D, see :func:`qube_rl.utils.observation_from_state`)::

        [theta, alpha, cos(theta), sin(theta), cos(alpha), sin(alpha), theta_dot, alpha_dot]

    Action space (1-D)::

        [-1.0, 1.0]  ->  sent to ESP32 as ``/rl_cmd?a=<value>``

    Endpoints used:
        - ``GET /rl_state`` -> ``{th, al, thd, ald}`` (rad, rad/s)
        - ``GET /rl_cmd?a=X`` -> apply action
        - ``GET /rl_cmd?r=1`` -> reset encoders + state
        - ``GET /cmd?m=6`` -> switch to RL mode
        - ``GET /cmd?m=3`` -> homing (see below); ``GET /state`` -> its telemetry
        - ``GET /cmd?m=2`` -> position PID, used to centre the arm after homing

    Homing:
        The arm encoder is incremental and loses its zero on every ESP32 reset. Mode
        3 recovers it by touching both mechanical end-stops and taking the midpoint.
        It is **opt-in** (``homing_every``, ``homing_on_start``) because it drives
        the arm into both stops, and it takes ~10 s.

        A run REDEFINES theta=0. ``reset()`` reports ``info["zero_epoch"]`` on every
        reset so trajectories recorded either side of a homing are never pooled as
        one reference frame, and ``info["homing"]`` with the measured geometry on the
        resets that ran one. A failed homing RAISES rather than continuing against an
        unknown zero.
    """

    metadata: ClassVar[dict[str, Any]] = {"render_modes": [], "render_fps": 50}

    def __init__(
        self,
        esp32_ip: str = DEFAULT_ESP32_IP,
        control_freq: int = 50,
        reward: str = "cos_alpha",
        # Short timeout: at 50 Hz a lost packet must retry within a step, not freeze
        # the loop. The old 5.0 s (x3 retries) could stall the controller ~15 s on a
        # single dropped request — fatal for a real inverted-pendulum episode.
        http_timeout: float = 0.4,
        reset_settle_time: float = 3.0,
        auto_set_mode: bool = True,
        invert_action: bool = True,
        invert_alpha: bool = True,
        angle_limits: list[float] | None = None,
        # ── Homing (firmware mode 3) ──────────────────────────────────────────
        # OPT-IN a proposito. El homing mueve el brazo contra AMBOS topes
        # mecanicos; no es algo que deba pasar por sorpresa en un banco
        # desatendido que el usuario creia en reposo.
        homing_every: int | None = None,
        homing_on_limit: bool = True,
        homing_on_start: bool = False,
        homing_timeout: float = 30.0,
        homing_settle_time: float = 0.0,
        center_after_homing: bool = True,
    ) -> None:
        super().__init__()
        self.esp32_ip = esp32_ip
        self.timing = Timing(control_freq)
        self.http_timeout = http_timeout
        self.reset_settle_time = reset_settle_time
        self.auto_set_mode = auto_set_mode
        # Bench bring-up (2026-06-22) found the real motor torque is sign-flipped
        # vs the simulator: a +action drove theta NEGATIVE on hardware but POSITIVE
        # in sim, while theta/alpha encoders matched sim convention (the alpha
        # coupling -theta<->+alpha held on both).  So only the motor is mirrored;
        # negate the command at the hardware boundary (AFTER the wrappers, so the
        # action history the policy sees stays in sim convention).
        self._action_sign = -1.0 if invert_action else 1.0
        # The pendulum encoder reads with the opposite sign vs sim (clear -56deg
        # under a real swing pump on 2026-06-22). That flip — plus the velocity
        # sign and the 50 Hz velocity filter — now lives in the FIRMWARE: /rl_state
        # emits the sim convention directly (the same one mode 7 feeds the on-device
        # net), so the reads in step()/reset() are PASS-THROUGH. ``invert_alpha`` is
        # retained for API compatibility and recorded here for introspection;
        # against LEGACY firmware that still emits raw alpha you must reflash, not
        # toggle this flag. Firmware and this file must be deployed together.
        self._invert_alpha = invert_alpha

        # Reward
        if reward not in REWARDS:
            raise ValueError(f"Unknown reward '{reward}'. Choose from {list(REWARDS)}")
        self._reward_func = REWARDS[reward]
        # Spaces — bounds mirror the 8-D observation layout; the theta bound
        # and velocity bound (MAX_VELOCITY) match the simulator so the
        # sim and real observation spaces agree.
        ecfg_th = 2 * np.pi / 3  # default ±120°, matches EnvConfig
        th_max = np.float32(angle_limits[0] if angle_limits else ecfg_th)
        pi = np.float32(np.pi)
        v = np.float32(MAX_VELOCITY)
        self.observation_space = Box(
            low=np.array([-th_max, -pi, -1, -1, -1, -1, -v, -v], dtype=np.float32),
            high=np.array([th_max, pi, 1, 1, 1, 1, v, v], dtype=np.float32),
            dtype=np.float32,
        )
        self.action_space = Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)

        # HTTP session (connection pooling for 50Hz). A keep-alive adapter reuses one
        # TCP connection across steps so we pay the handshake once, not per request —
        # the ESP32's single-radio AsyncTCP stack is sensitive to connection churn.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=4)
        self._session.mount("http://", adapter)
        self._session.headers.update({"Connection": "keep-alive"})
        self._base_url = f"http://{esp32_ip}"

        # Internal state
        self._state = np.zeros(4, dtype=np.float32)

        # Homing config + bookkeeping
        self.homing_every = homing_every
        self.homing_on_limit = homing_on_limit
        self.homing_on_start = homing_on_start
        self.homing_timeout = homing_timeout
        # 0 por defecto: el firmware ya espera quietud internamente (fase WAIT_QUIET,
        # hasta 20 s, y falla con código 5 si no se aquieta). Se probó que esperar
        # desde el cliente NO cambia la tasa de fallo — la causa era mecánica, no de
        # inercia residual. Se conserva el parámetro por si un montaje distinto lo
        # necesita, pero pagar la espera por defecto sería costo sin beneficio.
        self.homing_settle_time = homing_settle_time
        self.center_after_homing = center_after_homing
        self._reset_count = 0
        self._needs_homing = bool(homing_on_start)
        # Every homing REDEFINES theta=0. Episodes recorded before and after one are
        # expressed in DIFFERENT reference frames and must never be pooled as if they
        # were the same. ``zero_epoch`` goes out in the reset ``info`` on EVERY reset
        # (not only the homing ones) so a downstream logger can always tag which
        # frame a trajectory belongs to.
        self._zero_epoch = 0

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get_rl_state(self) -> dict[str, Any]:
        """Read state from ``/rl_state`` endpoint with retry."""
        for attempt in range(3):
            try:
                resp = self._session.get(
                    f"{self._base_url}/rl_state",
                    timeout=self.http_timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        raise RuntimeError("unreachable")  # pragma: no cover

    def _send_rl_action(self, action: float) -> None:
        """Send action to ``/rl_cmd?a=<value>`` with retry."""
        for attempt in range(3):
            try:
                self._session.get(
                    f"{self._base_url}/rl_cmd",
                    params={"a": f"{action:.4f}"},
                    timeout=self.http_timeout,
                )
                return
            except requests.RequestException:
                if attempt == 2:
                    logger.warning("rl_cmd failed after 3 attempts")
                    return  # best-effort, don't crash training
                time.sleep(0.05)

    def _rl_step(self, action: float) -> dict[str, Any]:
        """Set action AND read the resulting state in ONE round-trip via ``/rl_step``.

        Halves the per-step WiFi latency vs the old ``/rl_cmd`` + ``/rl_state`` pair
        (2 RTT ≈ 71 ms → ~1 RTT). Retries like ``_get_rl_state``; on total failure it
        raises so ``step`` can fall back to the last known state.
        """
        for attempt in range(3):
            try:
                resp = self._session.get(
                    f"{self._base_url}/rl_step",
                    params={"a": f"{action:.4f}"},
                    timeout=self.http_timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.05)
        raise RuntimeError("unreachable")  # pragma: no cover

    def _send_rl_reset(self) -> None:
        """Reset encoders and state via ``/rl_cmd?r=1``."""
        self._session.get(
            f"{self._base_url}/rl_cmd",
            params={"r": "1"},
            timeout=self.http_timeout,
        )

    def _set_mode(self, mode: int) -> None:
        """Switch ESP32 mode via ``/cmd?m=<mode>``."""
        self._session.get(
            f"{self._base_url}/cmd",
            params={"m": str(mode)},
            timeout=self.http_timeout,
        )

    # ------------------------------------------------------------------
    # Homing (firmware mode 3) — recover the arm's zero reference
    # ------------------------------------------------------------------

    def _get_full_state(self) -> dict[str, Any]:
        """Read the full ``/state`` endpoint (homing telemetry lives here, not ``/rl_state``).

        Uses a longer timeout than the 50 Hz control path: ``/state`` is a much
        bigger JSON and this is never called inside a control loop.
        """
        for attempt in range(3):
            try:
                resp = self._session.get(f"{self._base_url}/state", timeout=1.5)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.1)
        raise RuntimeError("unreachable")  # pragma: no cover

    def _start_homing(self) -> None:
        """Trigger the homing routine (``/cmd?m=3``).

        Returns as soon as the ESP32 acknowledges. The routine is asynchronous by
        necessity: the firmware runs a 500 Hz control loop and blocking an
        ESPAsyncWebServer callback for the ~10 s the routine takes would trip the
        watchdog. Poll with :meth:`_wait_homing`.

        No start/poll race to worry about: the firmware's ``setMode(3)`` clears
        ``homing_ok`` and moves the phase off ``IDLE`` synchronously inside the HTTP
        callback, so by the time this returns a stale ``DONE`` from a previous run is
        already gone.
        """
        self._set_mode(3)

    def _wait_homing(self, timeout: float) -> dict[str, Any]:
        """Poll ``/state`` until the homing routine reaches a terminal phase.

        Returns the homing telemetry on success. Raises on failure or timeout —
        deliberately: a failed homing means the arm's zero is UNKNOWN, and training
        against an unknown reference silently corrupts every theta in the dataset.
        Crashing is the cheaper outcome.
        """
        fail_reasons = {
            1: "recorrido medido fuera de tolerancia (acople suelto o encoder que no cuenta)",
            2: "timeout buscando el tope positivo",
            3: "timeout buscando el tope negativo",
            4: "timeout centrando el brazo",
            5: "el mecanismo no se aquietó: hay inercia residual del episodio anterior",
        }
        deadline = time.monotonic() + timeout
        phase = "?"
        while time.monotonic() < deadline:
            data = self._get_full_state()
            phase = str(data.get("homing_phase", "?"))
            if phase == "DONE":
                telemetry = {
                    "range_deg": float(data.get("homing_range", 0.0)),
                    "center_raw_deg": float(data.get("homing_center", 0.0)),
                    "stop_pos_deg": float(data.get("homing_stop_pos", 0.0)),
                    "stop_neg_deg": float(data.get("homing_stop_neg", 0.0)),
                }
                logger.info(
                    "Homing OK: recorrido=%.2f deg, centro=%.2f deg (topes %.2f / %.2f)",
                    telemetry["range_deg"],
                    telemetry["center_raw_deg"],
                    telemetry["stop_pos_deg"],
                    telemetry["stop_neg_deg"],
                )
                return telemetry
            if phase == "FAIL":
                code = int(data.get("homing_fail", 0))
                raise RuntimeError(
                    f"Homing FALLO (code={code}): {fail_reasons.get(code, 'desconocido')}. "
                    f"Recorrido medido {float(data.get('homing_range', 0.0)):.2f} deg. "
                    "El cero del brazo NO es confiable; revisar el mecanismo antes de entrenar."
                )
            time.sleep(0.2)
        raise RuntimeError(
            f"Homing no termino en {timeout:.1f} s (ultima fase: {phase}). "
            "El brazo puede haber quedado contra un tope; revisar antes de reintentar."
        )

    def _center_arm(self, timeout: float = 6.0, tol_deg: float = 2.0) -> float:
        """Drive the arm to theta=0 with the firmware position PID (mode 2).

        Homing guarantees the ZERO but not where the arm ends up parked: the L298N
        is left coasting (not braking) when the routine finishes, and the pendulum's
        residual swing back-drives the arm — it is direct-drive. One bench run
        parked 19.5 deg off centre. This does not affect calibration (the offset is
        the measured geometric centre regardless), but an episode should not start
        with a large theta offset, so chain the position PID, which is only
        legitimate now that the zero exists.

        Best-effort: returns the final |theta| in degrees and does NOT raise. An
        off-centre arm is a worse starting state, not a corrupt reference.
        """
        self._set_mode(2)
        deadline = time.monotonic() + timeout
        pos = float("nan")
        while time.monotonic() < deadline:
            pos = float(self._get_full_state().get("position_deg", 0.0))
            if abs(pos) <= tol_deg:
                break
            time.sleep(0.2)
        self._set_mode(0)
        if abs(pos) > tol_deg:
            logger.warning("Centrado incompleto: theta=%.2f deg (tolerancia %.1f)", pos, tol_deg)
        return abs(pos)

    def run_homing(self) -> dict[str, Any]:
        """Run the full homing sequence and re-establish the arm's zero.

        Public so it can be driven manually from a notebook or a recovery script,
        not just from :meth:`reset`. Raises if the routine fails.
        """
        # Espera de asentamiento ANTES de disparar. El homing detecta los topes por
        # calado del encoder, así que inercia residual del episodio anterior —brazo o
        # péndulo todavía en movimiento— se lee como tope y produce un cero corrido.
        # Medido: lanzándolo enseguida tras un swing-up, 3 de 24 corridas detectaron
        # el tope 19° antes del real. El firmware ahora falla con código 5 en vez de
        # arrancar a ciegas, así que sin esta espera el homing simplemente no corre.
        if self.homing_settle_time > 0:
            logger.info("Homing: esperando %.1fs a que se asiente el mecanismo...",
                        self.homing_settle_time)
            self._send_rl_action(0.0)
            time.sleep(self.homing_settle_time)

        logger.info("Homing: buscando los topes mecanicos para recuperar el cero...")
        self._start_homing()
        telemetry = self._wait_homing(self.homing_timeout)
        if self.center_after_homing:
            telemetry["park_error_deg"] = self._center_arm()
        self._zero_epoch += 1
        self._needs_homing = False
        telemetry["zero_epoch"] = self._zero_epoch
        return telemetry

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        # Set the action (sign-corrected for the mirrored real motor) AND read the
        # resulting state in a SINGLE round-trip (/rl_step), instead of a separate
        # /rl_cmd write + /rl_state read. The firmware's 500 Hz loop applies the new
        # PWM within ~2 ms, so no client-side settle sleep is needed here.
        # NOTE: ``/rl_step`` returns the SIM-CONVENTION observation in radians /
        # rad·s⁻¹ already (firmware ``updateRlObservation``: theta as-is; alpha
        # flipped + wrapped to [-π, π]; positive-finite-difference velocities at
        # 50 Hz).  Read PASS-THROUGH — do NOT call ``np.radians`` (that double
        # conversion was the r4_real root cause), re-flip alpha, or negate the
        # velocities (the old /rl_state exported the inverted LQR-EMA sign).
        # On a failed round-trip, keep the last known state (best-effort).
        try:
            data = self._rl_step(self._action_sign * float(action[0]))
            self._state[THETA] = float(data["th"])
            self._state[ALPHA] = float(data["al"])
            self._state[THETA_DOT] = float(data["thd"])
            self._state[ALPHA_DOT] = float(data["ald"])
        except requests.RequestException:
            logger.warning("rl_step failed, using last known state")

        # Build observation
        obs = self._get_obs()
        rwd = float(self._reward_func(self._state))

        # Termination: only the servo (arm) hitting its mechanical limit ends an
        # episode.  We deliberately do NOT terminate on the pendulum angle: the
        # inverted goal is alpha = ±pi, so terminating near ±pi (the previous
        # ``abs(alpha) > 0.95*pi`` check, ~171°) ended the episode exactly when
        # the agent reached the target — making balancing impossible.  Episode
        # length is instead bounded by the ``TimeLimit`` wrapper (env factory).
        # Servo limit ±100°: a deliberate safety margin, ~20° tighter than the
        # sim's ±120° termination (EnvConfig.angle_limit_theta) to keep the real
        # arm clear of its mechanical end-stops. NOT meant to "match" the sim.
        terminated = bool(abs(self._state[THETA]) > np.radians(100.0))
        if terminated:
            logger.info("Episode terminated: servo limit, theta=%.1f", np.degrees(self._state[THETA]))
            # Reaching the servo limit is the signature of a drifted or lost zero:
            # either the arm really walked to its end-stop, or theta=0 is no longer
            # where we think it is. Both are fixed by re-homing, and both poison the
            # episodes that follow if left alone. Queue it for the next reset — never
            # here, since the arm is at its limit and the caller still owns the loop.
            if self.homing_on_limit:
                self._needs_homing = True

        return obs, rwd, terminated, False, {}

    def _should_home(self, options: dict | None) -> bool:
        """Decide whether this reset should re-establish the arm's zero.

        ``options={"homing": True/False}`` overrides everything, so a caller can force
        or suppress a run for one episode without reconfiguring the env.
        """
        if options is not None and "homing" in options:
            return bool(options["homing"])
        if self._needs_homing:
            return True
        return bool(self.homing_every) and self._reset_count % self.homing_every == 0

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed, options=options)

        info: dict[str, Any] = {}
        # Homing FIRST: it redefines theta=0, so it has to happen before the state
        # read below, and before mode 6 takes over (the routine drives the arm into
        # both stops and would fight an active RL policy).
        if self._should_home(options):
            info["homing"] = self.run_homing()
        self._reset_count += 1
        info["zero_epoch"] = self._zero_epoch

        # Switch to RL mode if requested
        if self.auto_set_mode:
            self._set_mode(6)
            time.sleep(0.1)

        # Kill motor, wait for pendulum to settle (NO encoder reset — keeps physical reference)
        self._send_rl_action(0.0)
        logger.info("Reset: waiting %.1fs for pendulum to settle...", self.reset_settle_time)
        time.sleep(self.reset_settle_time)

        # Read initial state (sim-convention radians already — see note in ``step``).
        data = self._get_rl_state()
        self._assert_protocol(data)
        self._state[THETA] = float(data["th"])
        self._state[ALPHA] = float(data["al"])
        self._state[THETA_DOT] = float(data["thd"])
        self._state[ALPHA_DOT] = float(data["ald"])

        return self._get_obs(), info

    def close(self) -> None:
        """Kill motor and close HTTP session."""
        with contextlib.suppress(Exception):
            self._send_rl_action(0.0)
        self._session.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _assert_protocol(self, data: dict[str, Any]) -> None:
        """Fail loudly if the firmware /rl_state convention mismatches this env.

        Enforces the sim2real critical caveat: firmware and ``qube_real.py`` must be
        deployed together. Without this, a stale firmware (raw alpha / inverted
        velocity sign) would silently feed the policy wrong-signed observations.
        """
        pv = data.get("pv")
        if pv is None:
            raise RuntimeError(
                "ESP32 /rl_state has no 'pv' field: the firmware predates the "
                "sim-convention unification. Reflash src/firmware/esp32_qube "
                f"(RL_PROTO_VERSION={EXPECTED_RL_PROTO}) before training over HTTP."
            )
        if int(pv) != EXPECTED_RL_PROTO:
            raise RuntimeError(
                f"ESP32 /rl_state protocol v{pv} != expected v{EXPECTED_RL_PROTO}. "
                "Firmware and qube_real.py are out of sync — deploy them together "
                "(sim-convention caveat). Reflash the ESP32 or update the env."
            )

    def _get_obs(self) -> np.ndarray:
        return observation_from_state(self._state, include_raw_theta=True, include_raw_alpha=True)
