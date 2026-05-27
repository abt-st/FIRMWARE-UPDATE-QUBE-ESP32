"""ESP32 HTTP client for QUBE Servo communication."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)

DEFAULT_IP = "192.168.4.1"
DEFAULT_PORT = 80
TIMEOUT_SECS = 5


@dataclass
class QubeState:
    """Estado del QUBE Servo recibido desde el ESP32."""

    timestamp: float = 0.0
    mode: int = 0
    count: int = 0
    enc_a: int = 0
    enc_b: int = 0
    encoder_dir: int = 1
    counts_per_rev: float = 2048.0
    raw_position_deg: float = 0.0
    position_deg: float = 0.0
    offset_deg: float = 0.0
    setpoint_deg: float = 0.0
    error_deg: float = 0.0
    pwm: int = 0
    ina_ok: bool = False
    v_bus: float = 0.0
    v_shunt_mv: float = 0.0
    i_ma: float = 0.0
    p_mw: float = 0.0
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any], ts: float | None = None) -> QubeState:
        """Create QubeState from a JSON dict."""
        known_fields = {
            "mode",
            "count",
            "enc_a",
            "enc_b",
            "encoder_dir",
            "counts_per_rev",
            "raw_position_deg",
            "position_deg",
            "offset_deg",
            "setpoint_deg",
            "error_deg",
            "pwm",
            "ina_ok",
            "v_bus",
            "v_shunt_mv",
            "i_ma",
            "p_mw",
        }
        state = cls()
        state.timestamp = ts if ts is not None else time.time()
        for k, v in data.items():
            if k in known_fields and hasattr(state, k):
                setattr(state, k, v)
            elif k not in known_fields:
                state.extra[k] = v
        return state


class ESP32Client:
    """HTTP client for communicating with the QUBE ESP32.

    Supports both direct calls and background polling.
    """

    DEFAULT_POLL_MS = 100  # 10 Hz

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        port: int = DEFAULT_PORT,
        poll_ms: int = DEFAULT_POLL_MS,
        on_update: Callable[[QubeState], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.ip = ip
        self.port = port
        self.poll_ms = poll_ms
        self.on_update = on_update
        self.on_error = on_error
        self._base_url = f"http://{ip}:{port}"
        self._running = False
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_latency_ms: float = 0.0

    # ------------------------------------------------------------------ #
    #  Polling control                                                     #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop background polling thread."""
        self._running = False

    def _loop(self) -> None:
        """Background polling loop."""
        while self._running:
            t0 = time.perf_counter()
            self._poll_once()
            elapsed = (time.perf_counter() - t0) * 1000
            sleep_ms = max(0.0, self.poll_ms - elapsed)
            time.sleep(sleep_ms / 1000.0)

    def _poll_once(self) -> None:
        """Poll /state once."""
        try:
            t0 = time.perf_counter()
            state = self.get_state()
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            self.connected = True
            if self.on_update:
                self.on_update(state)
        except Exception as exc:
            self.connected = False
            if self.on_error:
                self.on_error(str(exc))

    # ------------------------------------------------------------------ #
    #  Direct API calls                                                    #
    # ------------------------------------------------------------------ #

    def get_state(self) -> QubeState:
        """Fetch the current state from /state endpoint."""
        url = f"{self._base_url}/state"
        try:
            with urlopen(url, timeout=TIMEOUT_SECS) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode())
            return QubeState.from_json(data, time.time())
        except (URLError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to fetch state from %s: %s", url, exc)
            raise

    def send_cmd(self, **params: Any) -> bool:
        """Send a command to /cmd endpoint with query parameters."""
        if not params:
            return False
        qs = urlencode({k: str(v) for k, v in params.items()})
        url = f"{self._base_url}/cmd?{qs}"
        try:
            with urlopen(url, timeout=TIMEOUT_SECS) as resp:
                return resp.status == 200
        except (URLError, OSError) as exc:
            logger.warning("Failed to send cmd to %s: %s", url, exc)
            return False

    def set_mode(self, mode: int) -> bool:
        """Set operation mode (0=STOP, 1=PWM, 2=PID)."""
        return self.send_cmd(m=mode)

    def set_setpoint(self, degrees: float) -> bool:
        """Set PID setpoint in degrees."""
        return self.send_cmd(s=f"{degrees:.2f}")

    def set_pwm(self, value: int) -> bool:
        """Set manual PWM value (-255 to 255)."""
        return self.send_cmd(p=value)

    def set_pid(self, kp: float, ki: float, kd: float) -> bool:
        """Set PID gains."""
        return self.send_cmd(kp=kp, ki=ki, kd=kd)

    def set_pid_gains(self, kp: float, ki: float, kd: float) -> bool:
        """Set PID gains (alias for set_pid)."""
        return self.set_pid(kp, ki, kd)

    def set_cpr(self, cpr: float) -> bool:
        """Set encoder counts per revolution."""
        return self.send_cmd(cpr=f"{cpr:.1f}")

    def set_encoder_dir(self, direction: int) -> bool:
        """Set encoder direction multiplier (+1 or -1)."""
        return self.send_cmd(ed=direction)

    def zero_here(self) -> bool:
        """Zero the current position."""
        return self.send_cmd(z=1)

    def zero_position(self) -> bool:
        """Zero the current position (alias for zero_here)."""
        return self.zero_here()

    def stop_motor(self) -> bool:
        """Emergency stop."""
        return self.send_cmd(x=1)

    def emergency_stop(self) -> bool:
        """Emergency stop (alias for stop_motor)."""
        return self.stop_motor()
