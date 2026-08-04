"""Sondeo de ``/state`` y ejecución de comandos, fuera del hilo de la interfaz.

Todo el I/O con la placa pasa por aquí: la GUI nunca llama a ``requests`` en su hilo.
Un comando con reintentos puede tardar segundos cuando la radio le roba tiempo al lazo,
y una interfaz congelada en medio de un swing-up es peor que inútil.

De ``/state`` salen las cosas que el flujo binario del DAQ **no** trae: potencia del
INA219, fase del homing, salud del lazo (``loop_*``) y —clave— los valores latcheados
del traspaso del swing-up (``swing_trans_*``). Esos últimos se leen, no se reconstruyen:
muestrear el modo desde el cliente llega tarde y da otro ángulo.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import requests

from qube_app.link import QubeLink

logger = logging.getLogger(__name__)

#: Cada cuánto despierta el hilo. Fija la latencia máxima del paro de emergencia.
TICK_S = 0.1


@dataclass
class _Command:
    params: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: Exception | None = None


class StatePoller:
    """Lee ``/state`` periódicamente y ejecuta comandos en un hilo propio."""

    def __init__(self, link: QubeLink, period_s: float = 0.5) -> None:
        self.link = link
        self.period_s = period_s
        self._stop_event = threading.Event()
        self._estop = threading.Event()
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: dict = {}
        self._latest_at: float = 0.0
        self._errors = 0
        self._last_error = ""

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="state-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    # ── Lectura ───────────────────────────────────────────────────────────────

    @property
    def latest(self) -> dict:
        """Último ``/state`` leído. Diccionario vacío si aún no hubo ninguno."""
        with self._lock:
            return dict(self._latest)

    @property
    def age_s(self) -> float:
        """Antigüedad del último estado. Crece sin techo si el enlace murió."""
        with self._lock:
            return float("inf") if not self._latest_at else time.monotonic() - self._latest_at

    @property
    def health(self) -> dict:
        """Resumen de salud: lo del enlace y lo del lazo, junto."""
        st = self.latest
        with self._lock:
            errors, last_error = self._errors, self._last_error
        return {
            "rtt_ms": self.link.last_rtt_ms,
            "age_s": self.age_s,
            "errors": errors,
            "last_error": last_error,
            "loop_dt_max_us": st.get("loop_dt_max_us"),
            "loop_overruns": st.get("loop_overruns"),
            "loop_dt_nom_us": st.get("loop_dt_nom_us"),
            "ina_ok": st.get("ina_ok"),
        }

    # ── Escritura ─────────────────────────────────────────────────────────────

    def submit(self, **params: object) -> _Command:
        """Encola un comando. No bloquea; el llamador puede esperar en ``cmd.done``."""
        cmd = _Command(params=params)
        self._commands.put(cmd)
        return cmd

    def request_stop(self) -> None:
        """Paro de emergencia: se atiende antes que cualquier comando encolado."""
        self._estop.set()

    # ── Hilo ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        next_poll = 0.0
        while not self._stop_event.is_set():
            if self._estop.is_set():
                self._estop.clear()
                self.link.stop_motor()
            self._drain_commands()
            if time.monotonic() >= next_poll:
                self._poll_state()
                next_poll = time.monotonic() + self.period_s
            self._stop_event.wait(TICK_S)

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                cmd.result = self.link.send(cmd.params)
            # Amplio a propósito: el error se le entrega al llamador en `cmd.error`, no
            # se traga, y un fallo de un comando no puede matar el hilo del sondeo.
            except Exception as exc:
                cmd.error = exc
                logger.warning("comando %s falló: %s", cmd.params, exc)
            finally:
                cmd.done.set()

    def _poll_state(self) -> None:
        try:
            data = self.link.state(retries=1)
        except requests.RequestException as exc:
            with self._lock:
                self._errors += 1
                self._last_error = str(exc)
            return
        with self._lock:
            self._latest = data
            self._latest_at = time.monotonic()
