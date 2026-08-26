"""Placa simulada: bloques DAQ y ``/state`` sintéticos en tiempo real, sin hardware.

Sirve para dos cosas distintas y ambas importan: probar el camino completo de la app
—hilo, desenrollado, anillos, análisis— en ``pytest`` sin placa, y poder abrir la GUI en
el escritorio para trabajar en ella cuando el banco no está disponible.

Genera el bloque **con la misma función que decodifica el cliente real**
(:func:`qube_daq.protocol.decode_block`), así que si el formato cambia, esto se rompe
igual que se rompería el enlace de verdad. Un simulador que no comparte el codificador
con el firmware no prueba nada.

**El DAQ y ``/state`` salen del mismo estado** (:class:`FakeBoard`). Antes sólo estaba
simulado el DAQ y el modo simulado dejaba muertos la salud del enlace, el escalón, el
traspaso, la potencia y el indicador de modo: la mitad de la interfaz no se podía ni
mirar sin ir al laboratorio, que es justo cuando uno quiere trabajarla.
"""

from __future__ import annotations

import math
import struct
import time

from qube_app.link import ReadOnlyError
from qube_app.stream import CONTROL_HZ, DAQ_CAPACITY, DAQ_MAX_BLOCK
from qube_daq.client import DaqClient
from qube_daq.protocol import DAQ_MAGIC, DAQ_PROTO_VERSION, HEADER_FORMAT, SAMPLE_BYTES, Block, decode_block

#: Frecuencia del péndulo simulado [Hz]. No pretende ser la planta real: pretende
#: producir un α que cruce la vertical, un θ acotado y un PWM que se correlacione con
#: los dos, que es lo que hace falta para mirar la interfaz.
SIM_HZ = 0.7
#: |α| a partir del cual el swing-up simulado latchea el traspaso, como ``swingupCatchDeg``.
SIM_CATCH_DEG = 155.0


def simulated_signals(secs: float, mode: int = 5, manual_pwm: int = 0) -> tuple[float, float, int]:
    """θ, α (sin envolver) y PWM en un instante. Única fuente de la simulación.

    La comparten el generador de bloques y ``/state``: si cada uno tuviera su propia
    fórmula, el número del encabezado no coincidiría con la traza que está debajo. Pasó:
    con la placa en modo 0 el encabezado decía «PWM +0» mientras la traza dibujaba ±120,
    porque el bloque ignoraba el modo. Un simulador incoherente enseña a desconfiar de la
    interfaz, que es lo contrario de para lo que existe.
    """
    phase = 2 * math.pi * SIM_HZ * secs
    alpha = 170.0 * math.sin(phase)
    theta = 25.0 * math.sin(phase + 0.4)
    if mode == 0:
        pwm = 0
    elif mode == 1:
        pwm = int(manual_pwm)
    else:
        pwm = int(120 * math.cos(phase))
    return theta, alpha, pwm


def make_block(
    t0_us: int,
    n: int,
    period_us: int = 2000,
    dropped: int = 0,
    mode: int = 5,
    manual_pwm: int = 0,
) -> Block:
    """Un bloque con un péndulo oscilando y un PWM de bombeo, listo para decodificar."""
    payload = struct.pack(HEADER_FORMAT, DAQ_MAGIC, DAQ_PROTO_VERSION, SAMPLE_BYTES, n, dropped, t0_us % (1 << 32))
    for i in range(n):
        t = (t0_us + i * period_us) % (1 << 32)
        theta, alpha, pwm = simulated_signals((t0_us + i * period_us) / 1e6, mode, manual_pwm)
        payload += struct.pack("<IffhBB", t, theta, alpha, pwm, mode, 1)
    return decode_block(payload)


class FakeBoard:
    """Estado compartido por el DAQ simulado y el ``/state`` simulado.

    Los comandos que llegan por :class:`FakeLink` cambian este estado y el cambio se ve
    en las dos vías, igual que en la placa: cambiar de modo repinta las bandas de las
    trazas, y `m5` limpia el latch del traspaso como hace ``setMode(5)`` en el firmware.
    """

    def __init__(self, mode: int = 5, homed: bool = True) -> None:
        # Arranca en swing-up, no en libre: es el modo con algo que mirar (bandas de
        # modo, traspaso latcheado, potencia que varía), y quien abre `--fake` lo hace
        # justamente para ver la interfaz trabajando.
        self._t0 = time.perf_counter()
        self.daq_t0: float | None = None
        self.mode = mode
        self.setpoint_deg = 0.0
        self.manual_pwm = 0
        self.gains: dict[str, float] = {}
        self.loop_reset_at = time.perf_counter()
        self._trans: dict | None = None
        self._trans_at: float | None = None

        # ── Compuertas de entrada a modo ─────────────────────────────────────
        # Esto NO estaba simulado y es exactamente por dónde se coló el defecto: la
        # placa simulada aceptaba cualquier `m=` y la real rechaza 2/4/5/6/7 sin homing
        # desde v1.60.0. Un simulador más permisivo que el firmware no prueba la app,
        # la aprueba. Por eso ahora replica `setMode()`, compuertas incluidas.
        #
        # `homed=True` por omisión para que `--fake` siga abriendo con algo que mirar;
        # los tests que ejercitan la compuerta construyen la placa con `homed=False`,
        # que es como arranca una ESP32 recién encendida.
        self.homing_required = True
        self.ina_required = True
        self.ina_ok = True
        self.homing_ok = homed
        self.mode_reject = 0
        self.safety_action = 0
        self.safety_cuts = 0
        self.safety_derates = 0
        if not self.homing_ok and self.mode in self.GATED_BY_HOMING:
            # Una placa sin homing en modo 5 es un estado que el firmware no puede
            # producir. Simularlo enseñaría a leer mal la interfaz.
            self.mode = 0

    # ── Reloj ─────────────────────────────────────────────────────────────────

    def elapsed_s(self) -> float:
        """Segundos en la base de tiempo que está viendo el DAQ, si está corriendo."""
        return time.perf_counter() - (self.daq_t0 if self.daq_t0 is not None else self._t0)

    # ── Simulación ────────────────────────────────────────────────────────────

    def sample(self) -> tuple[float, float, int]:
        return simulated_signals(self.elapsed_s(), self.mode, self.manual_pwm)

    def _tick_transition(self, alpha: float) -> None:
        """Latchea el traspaso al pasar cerca de la vertical, como hace el firmware."""
        if self.mode != 5 or self._trans is not None:
            return
        wrapped = (alpha + 180.0) % 360.0 - 180.0
        if abs(wrapped) < SIM_CATCH_DEG:
            return
        # Derivada analítica de α, que es de lo que se trata el criterio de traspaso.
        vel = 170.0 * 2 * math.pi * SIM_HZ * math.cos(2 * math.pi * SIM_HZ * self.elapsed_s())
        self._trans = {
            "swing_trans_reason": 2,  # "peak"
            "swing_trans_alpha": round(wrapped, 2),
            "swing_trans_vel": round(abs(vel), 1),
            "swing_trans_energy": 0.96,
        }
        self._trans_at = time.perf_counter()

    #: Modos gateados por el homing en el firmware (0, 1 y el homing mismo quedan fuera).
    GATED_BY_HOMING = (2, 4, 5, 6, 7)
    #: Modos gateados por el INA219 (0 y 3 quedan fuera).
    GATED_BY_INA = (1, 2, 4, 5, 6, 7)

    def set_mode(self, mode: int) -> bool:
        """Réplica de ``setMode()``: **puede rechazar**. Devuelve si el modo cambió.

        Las tres razones de ``mode_reject`` son las del ``.ino`` y en el mismo orden:
        1 fuera de rango · 2 falta homing · 3 INA219 caído.
        """
        mode = int(mode)
        if mode < 0 or mode > 7:
            self.mode_reject = 1
            return False
        if self.homing_required and not self.homing_ok and mode in self.GATED_BY_HOMING:
            self.mode_reject = 2
            return False
        if self.ina_required and not self.ina_ok and mode in self.GATED_BY_INA:
            self.mode_reject = 3
            return False

        self.mode_reject = 0
        self.mode = mode
        if mode == 3:
            # El homing simulado no tiene fases: termina bien y de inmediato. Lo que la
            # app necesita poder mostrar es el resultado —recorrido, centro, signo
            # medido— y que la compuerta se abra, no la coreografía de los topes.
            self.homing_ok = True
        if mode == 5:  # `setMode(5)` limpia el latch en el firmware
            self._trans = None
            self._trans_at = None
        return True

    # ── /state ────────────────────────────────────────────────────────────────

    def state(self) -> dict:
        theta, alpha, pwm = self.sample()
        self._tick_transition(alpha)
        since_reset_ms = (time.perf_counter() - self.loop_reset_at) * 1000.0
        state = {
            "mode": self.mode,
            "position_deg": round(theta, 3),
            "raw_position_deg": round(theta, 3),
            "pend_position_deg": round(alpha, 3),
            "setpoint_deg": round(self.setpoint_deg, 3),
            "pwm": int(pwm),
            # Potencia coherente con el PWM: sirve para ver que la traza de potencia se
            # dibuja alineada y a su propia tasa, que es lo único que se puede verificar
            # sin un INA219 de verdad.
            "p_mw": round(320.0 + 9.5 * abs(pwm), 1),
            "i_ma": round(60.0 + 1.8 * abs(pwm), 1),
            "v_bus": 5.02,
            "ina_ok": True,
            "loop_dt_nom_us": int(1e6 / CONTROL_HZ),
            "loop_dt_max_us": int(2100 + 40 * math.sin(since_reset_ms / 900.0)),
            "loop_overruns": 0,
            "daq_running": self.daq_t0 is not None,
            # Homing y compuertas, como los publica el firmware desde v1.60.0. El valor
            # anterior —`homing_ok` clavado en False y `homing_phase` en 0, un int donde
            # el firmware manda una cadena— describía una placa que no existe.
            "homing_ok": self.homing_ok,
            "homing_phase": "DONE" if self.homing_ok else "IDLE",
            "homing_required": self.homing_required,
            "homing_fail": 0,
            # 270° es el recorrido medido en banco; el centro y el signo, lo que se
            # publica tras un homing válido. `homing_pwm_sign` = 0 sin homing.
            "homing_range": 270.0 if self.homing_ok else 0.0,
            "homing_center": 135.0 if self.homing_ok else 0.0,
            "homing_pwm_sign": -1 if self.homing_ok else 0,
            "ina_required": self.ina_required,
            "mode_reject": self.mode_reject,
            "safety_action": self.safety_action,
            "safety_cuts": self.safety_cuts,
            "safety_derates": self.safety_derates,
            # Reintento del swing-up (v1.63.0). Sin fallas en la simulación: la placa
            # simulada no se cae, y anunciar una falla que no ocurrió sería peor que
            # no anunciar nada.
            "swing_retry_enabled": True,
            "swing_retry_count": 0,
            "swing_retry_max": 3,
            "swing_fail_reason": 0,
            "swing_recenter_phase": 0,
            "swing_zero_enabled": True,
            "swing_zero_phase": 0,
            "swing_zero_ok": True,
            "ke_gain": self.gains.get("ke", 0.75),
            "ke_override": self.gains.get("ke", -1.0),
        }
        if self._trans is not None and self._trans_at is not None:
            state.update(self._trans)
            state["swing_trans_ms_ago"] = int((time.perf_counter() - self._trans_at) * 1000)
        return state


class FakeLink:
    """``QubeLink`` sin red, contra un :class:`FakeBoard`.

    Implementa la misma superficie que usa la app (``send`` / ``state`` / ``stop_motor``
    / ``reset_loop_metrics`` / ``close``), incluido el ``read_only``, para que la ventana
    no necesite ni una rama ``if self.fake`` en la ruta de comandos. Antes las tenía, y
    una rama que sólo corre en simulación es una rama que nadie prueba.
    """

    def __init__(self, board: FakeBoard | None = None, latency_ms: float = 6.0) -> None:
        self.board = board if board is not None else FakeBoard()
        self.ip = "simulado"
        self.base_url = "sim://qube"
        self.read_only = False
        self.last_rtt_ms: float | None = None
        self._latency_ms = latency_ms

    def send(self, params: dict, retries: int = 5, force: bool = False) -> dict:  # noqa: ARG002
        if self.read_only and not force:
            raise ReadOnlyError(f"enlace en sólo lectura: no se envió {params}")
        board = self.board
        accepted = True
        if "x" in params:
            board.set_mode(0)  # el paro nunca se rechaza: el modo 0 no está gateado
        if "m" in params:
            accepted = board.set_mode(int(params["m"]))
        if "s" in params:
            board.setpoint_deg = float(params["s"])
        if "p" in params:
            board.manual_pwm = int(params["p"])
        if "rj" in params:
            board.loop_reset_at = time.perf_counter()
        # Las compuertas se sueltan por HTTP igual que en la placa. Sin esto, `hr=0`
        # —la salida documentada para trabajo de banco— no se podía ni probar en seco.
        if "hr" in params:
            board.homing_required = bool(int(params["hr"]))
        if "sf" in params:
            board.ina_required = bool(int(params["sf"]))
        ignored = {"m", "s", "p", "x", "z", "zp", "rj", "hr", "sf"}
        board.gains.update({k: float(v) for k, v in params.items() if k not in ignored})
        # El firmware responde con el modo REAL, no con el pedido: un `?m=` rechazado
        # devuelve el modo anterior. Devolver el pedido sería la misma mentira que la
        # app estaba mostrando en pantalla.
        return {"ok": accepted, "mode": board.mode, "mode_reject": board.mode_reject}

    def cmd(self, **params: object) -> dict:
        return self.send(params)

    def stop_motor(self, retries: int = 15) -> bool:  # noqa: ARG002
        self.board.set_mode(0)
        return True

    def reset_loop_metrics(self) -> dict:
        return self.send({"rj": 1}, force=True)

    def state(self, retries: int = 3) -> dict:  # noqa: ARG002
        self.last_rtt_ms = self._latency_ms
        return self.board.state()

    def close(self) -> None:
        return None


class FakeDaqClient(DaqClient):
    """``DaqClient`` con el transporte sustituido por un generador en tiempo real.

    Emite sólo las muestras que *ya habrían ocurrido* desde la lectura anterior, con el
    techo de ``DAQ_MAX_BLOCK`` del firmware: sondear demasiado lento pierde muestras aquí
    igual que las perdería contra la placa, y esa es justamente la falla que conviene
    poder reproducir en el escritorio.
    """

    def __init__(self, ip: str = "0.0.0.0", mode: int = 5, board: FakeBoard | None = None) -> None:
        super().__init__(ip=ip)
        self.board = board
        self.mode = mode
        self._decim = 1
        self._t0: float | None = None
        self._emitted = 0
        self._dropped = 0

    @property
    def _period_us(self) -> int:
        return int(1e6 / CONTROL_HZ * self._decim)

    @property
    def _mode(self) -> int:
        """El modo lo manda la placa simulada si la hay: así los comandos se ven en la traza."""
        return self.board.mode if self.board is not None else self.mode

    def status(self) -> dict:
        return {"running": self._t0 is not None, "decim": self._decim, "rate_hz": CONTROL_HZ / self._decim}

    def start(self, decim: int = 1) -> dict:
        self._decim = max(1, decim)
        self._t0 = time.perf_counter()
        self._emitted = 0
        self._dropped = 0
        if self.board is not None:
            # El DAQ define la base de tiempo: `/state` se cuelga de ella para que el
            # número del encabezado y la traza de abajo cuenten lo mismo.
            self.board.daq_t0 = self._t0
        return self.status()

    def stop(self) -> dict:
        self._t0 = None
        if self.board is not None:
            self.board.daq_t0 = None
        return self.status()

    def read_block(self, retries: int = 3) -> Block | None:  # noqa: ARG002 — firma del padre
        if self._t0 is None:
            return None
        due = int((time.perf_counter() - self._t0) * CONTROL_HZ / self._decim)
        backlog = max(0, due - self._emitted)
        # El anillo del firmware guarda 2048 muestras (4,1 s a 500 Hz). Lo que se acumule
        # por encima se descarta y se cuenta: se descarta la muestra NUEVA, pero para el
        # consumidor el efecto es el mismo hueco contabilizado.
        if backlog > DAQ_CAPACITY:
            excess = backlog - DAQ_CAPACITY
            self._dropped += excess
            self._emitted += excess
            backlog = DAQ_CAPACITY
        n = min(backlog, DAQ_MAX_BLOCK)
        manual = self.board.manual_pwm if self.board is not None else 0
        block = make_block(self._emitted * self._period_us, n, self._period_us, self._dropped, self._mode, manual)
        self._emitted += n
        return block
