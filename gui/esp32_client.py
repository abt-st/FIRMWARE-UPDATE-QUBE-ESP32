"""
Cliente HTTP para el ESP32 QUBE-Servo.
Maneja polling de /state y envío de comandos a /cmd.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests


@dataclass
class QubeState:
    """Snapshot del estado del sistema tal como viene del JSON /state."""

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

    @staticmethod
    def from_dict(d: dict, ts: float) -> QubeState:
        s = QubeState()
        s.timestamp = ts
        s.mode = int(d.get("mode", 0))
        s.count = int(d.get("count", 0))
        s.enc_a = int(d.get("enc_a", 0))
        s.enc_b = int(d.get("enc_b", 0))
        s.encoder_dir = int(d.get("encoder_dir", 1))
        s.counts_per_rev = float(d.get("counts_per_rev", 2048.0))
        s.raw_position_deg = float(d.get("raw_position_deg", 0.0))
        s.position_deg = float(d.get("position_deg", 0.0))
        s.offset_deg = float(d.get("offset_deg", 0.0))
        s.setpoint_deg = float(d.get("setpoint_deg", 0.0))
        s.error_deg = float(d.get("error_deg", 0.0))
        s.pwm = int(d.get("pwm", 0))
        s.ina_ok = bool(d.get("ina_ok", False))
        s.v_bus = float(d.get("v_bus", 0.0))
        s.v_shunt_mv = float(d.get("v_shunt_mv", 0.0))
        s.i_ma = float(d.get("i_ma", 0.0))
        s.p_mw = float(d.get("p_mw", 0.0))
        return s


class ESP32Client:
    """
    Hilo de fondo que hace polling periódico a /state.
    Llama on_update(QubeState) en cada lectura exitosa.
    Llama on_error(str) ante fallo de conexión.
    """

    DEFAULT_IP = "192.168.4.1"
    DEFAULT_POLL_MS = 100  # 10 Hz; bajar a 50 para 20 Hz si la red lo permite

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        poll_ms: int = DEFAULT_POLL_MS,
        on_update: Callable[[QubeState], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.ip = ip
        self.poll_ms = poll_ms
        self.on_update = on_update
        self.on_error = on_error
        self._running = False
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_latency_ms: float = 0.0

    # ------------------------------------------------------------------ #
    #  Control del hilo                                                    #
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    #  Polling loop                                                        #
    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._running:
            t0 = time.perf_counter()
            self._poll_once()
            elapsed = (time.perf_counter() - t0) * 1000
            sleep_ms = max(0.0, self.poll_ms - elapsed)
            time.sleep(sleep_ms / 1000.0)

    def _poll_once(self):
        url = f"http://{self.ip}/state"
        try:
            t0 = time.perf_counter()
            resp = requests.get(url, timeout=1.0)
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                state = QubeState.from_dict(data, time.time())
                self.connected = True
                if self.on_update:
                    self.on_update(state)
            else:
                self._handle_error(f"HTTP {resp.status_code}")
        except requests.exceptions.ConnectionError:
            self._handle_error("Sin conexión — ¿ESP32 encendido?")
        except requests.exceptions.Timeout:
            self._handle_error("Timeout")
        except Exception as exc:
            self._handle_error(str(exc))

    def _handle_error(self, msg: str):
        self.connected = False
        if self.on_error:
            self.on_error(msg)

    # ------------------------------------------------------------------ #
    #  Envío de comandos                                                   #
    # ------------------------------------------------------------------ #

    def send_cmd(self, **kwargs) -> bool:
        """
        Envía parámetros como query string a /cmd.
        Ejemplo: send_cmd(m=2, s=45)
        Retorna True si el ESP32 respondió OK.
        """
        if not kwargs:
            return False
        url = f"http://{self.ip}/cmd"
        try:
            resp = requests.get(url, params=kwargs, timeout=1.0)
            return resp.status_code == 200
        except Exception:
            return False

    def stop_motor(self):
        self.send_cmd(x=1)

    def set_mode(self, mode: int):
        self.send_cmd(m=mode)

    def set_setpoint(self, deg: float):
        self.send_cmd(s=round(deg, 2))

    def set_pwm(self, pwm: int):
        self.send_cmd(p=int(pwm))

    def set_pid(self, kp: float, ki: float, kd: float):
        self.send_cmd(kp=kp, ki=ki, kd=kd)

    def zero_here(self):
        self.send_cmd(z=1)

    def set_cpr(self, cpr: float):
        self.send_cmd(cpr=round(cpr, 1))

    def set_encoder_dir(self, direction: int):
        self.send_cmd(ed=direction)
