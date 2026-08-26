"""Sondeo de ``/state``, comandos y tareas de I/O, fuera del hilo de la interfaz.

Todo el I/O con la placa pasa por aquí: la GUI nunca llama a ``requests`` en su hilo.
Un comando con reintentos puede tardar segundos cuando la radio le roba tiempo al lazo,
y una interfaz congelada en medio de un swing-up es peor que inútil.

De ``/state`` salen las cosas que el flujo binario del DAQ **no** trae: potencia del
INA219, fase del homing, salud del lazo (``loop_*``) y —clave— los valores latcheados
del traspaso del swing-up (``swing_trans_*``). Esos últimos se leen, no se reconstruyen:
muestrear el modo desde el cliente llega tarde y da otro ángulo.

Además del sondeo y de los comandos, el hilo acepta **tareas** (:meth:`submit_task`).
Existen porque arrancar y detener la adquisición también son I/O —``/daq?start``,
``/daq?stop``, ``rj=1``— y se estaban haciendo desde el hilo de Qt, donde con la placa
muda congelaban la ventana hasta medio minuto. La ventana encola la tarea y consulta el
resultado desde su propio temporizador; nunca espera.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class Task:
    """Trabajo arbitrario de I/O encolado al hilo del sondeo."""

    fn: Callable[[], Any]
    label: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.done.is_set() and self.error is None


class StatePoller:
    """Lee ``/state`` periódicamente y ejecuta comandos y tareas en un hilo propio."""

    def __init__(self, link: QubeLink, period_s: float = 0.5) -> None:
        self.link = link
        self.period_s = period_s
        self._stop_event = threading.Event()
        self._estop = threading.Event()
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._tasks: queue.Queue[Task] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: dict = {}
        self._latest_at: float = 0.0
        self._errors = 0
        self._last_error = ""
        self._estop_ok: bool | None = None
        self._estop_at: float = 0.0

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

    @property
    def running(self) -> bool:
        """Si el hilo está vivo. Quien espere una confirmación necesita saberlo antes."""
        return self._thread is not None and self._thread.is_alive()

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
    def estop_ok(self) -> bool | None:
        """Resultado del último paro: ``None`` si nunca se pidió, ``False`` si no pasó.

        Existe porque la ventana informaba "PARO enviado" incondicionalmente, aunque
        ``stop_motor`` hubiera fallado sus quince intentos. Es el peor lugar posible para
        un mensaje optimista: si el paro no llegó, hay que ir a cortar la alimentación.
        """
        with self._lock:
            return self._estop_ok

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
            # La capa de seguridad del firmware. `safety_action` se limpia al tick
            # siguiente, así que los dos contadores son lo que sobrevive al sondeo a
            # 2 Hz: sin ellos un derate por tensión no deja rastro en ninguna parte.
            "safety_action": st.get("safety_action"),
            "safety_cuts": st.get("safety_cuts"),
            "safety_derates": st.get("safety_derates"),
        }

    # ── Escritura ─────────────────────────────────────────────────────────────

    def submit(self, **params: object) -> _Command:
        """Encola un comando. No bloquea; el llamador puede esperar en ``cmd.done``."""
        cmd = _Command(params=params)
        self._commands.put(cmd)
        return cmd

    def submit_task(self, fn: Callable[[], Any], label: str = "") -> Task:
        """Encola I/O arbitrario (arrancar/detener el DAQ). No bloquea."""
        task = Task(fn=fn, label=label)
        self._tasks.put(task)
        return task

    def request_stop(self) -> None:
        """Paro de emergencia: se atiende antes que cualquier comando encolado."""
        with self._lock:
            self._estop_ok = None
        self._estop.set()

    # ── Hilo ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        next_poll = 0.0
        while not self._stop_event.is_set():
            self._serve_estop()
            self._drain_commands()
            self._drain_tasks()
            if time.monotonic() >= next_poll:
                self._poll_state()
                next_poll = time.monotonic() + self.period_s
            self._stop_event.wait(TICK_S)
        # Un paro pedido justo antes de cerrar tiene que salir igual: es la última orden
        # que importa y la cola no se atiende una vez que el bucle terminó.
        self._serve_estop()
        self._drain_tasks()

    def _serve_estop(self) -> None:
        if not self._estop.is_set():
            return
        self._estop.clear()
        ok = self.link.stop_motor()
        with self._lock:
            self._estop_ok = ok
            self._estop_at = time.monotonic()
        if not ok:
            logger.error("PARO DE EMERGENCIA SIN CONFIRMAR — cortar la alimentación")

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

    def _drain_tasks(self) -> None:
        while True:
            try:
                task = self._tasks.get_nowait()
            except queue.Empty:
                return
            try:
                task.result = task.fn()
            except Exception as exc:  # ídem: el fallo viaja en la tarea, no mata el hilo
                task.error = exc
                logger.warning("tarea %s falló: %s", task.label or task.fn, exc)
            finally:
                task.done.set()

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
