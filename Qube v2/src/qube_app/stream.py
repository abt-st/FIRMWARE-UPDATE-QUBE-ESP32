"""Adquisición continua: pide bloques al ESP32 en un hilo y los publica en una cola.

Es la contraparte *incremental* de :meth:`qube_daq.client.DaqClient.record`, que bloquea
toda la duración de la captura y devuelve al final — útil para grabar, inútil para ver.
Aquí se reusan ``start`` / ``read_block`` / ``stop`` del mismo cliente y se encadena el
desenrollado de ``micros()`` bloque a bloque, que es lo que hace que una sesión de más de
71,6 minutos no invierta el tiempo.

**El sondeo tiene un techo duro.** El firmware sirve como mucho ``DAQ_MAX_BLOCK = 512``
muestras por respuesta: a 500 Hz eso es 1,02 s de datos. Sondear más lento pierde
muestras aunque el anillo de 2048 (4,1 s) esté lejos de llenarse. De ahí el default de
0,2 s, con factor 5 de margen. Lo que se pierda se cuenta —``dropped`` viaja acumulado en
cada cabecera— y se informa; nunca hay pérdida silenciosa.

**Un solo consumidor.** El firmware responde 503 si llega una segunda petición mientras
transmite. Mientras esta app adquiere, no se usa ``python -m qube_daq record``.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace

import numpy as np
import requests

from qube_daq.client import DaqClient
from qube_daq.protocol import Block, ProtocolError, unwrap_us
from qube_rl.config import DEFAULT_ESP32_IP

logger = logging.getLogger(__name__)

#: Muestras máximas por respuesta (``DAQ_MAX_BLOCK`` en el firmware).
DAQ_MAX_BLOCK = 512
#: Capacidad del anillo en la placa (``DAQ_CAPACITY``): 2048 muestras = 4,1 s a 500 Hz.
DAQ_CAPACITY = 2048
#: Período del lazo de control: 2000 µs.
CONTROL_HZ = 500.0


@dataclass(frozen=True)
class Chunk:
    """Un bloque ya decodificado, con el tiempo normalizado y la marca del PC."""

    t_s: np.ndarray
    """Segundos desde la primera muestra de la sesión, según el reloj del ESP32."""
    th_deg: np.ndarray
    al_deg: np.ndarray
    """Péndulo SIN envolver: envolver antes de derivar mete un pico de ±360°/dt."""
    pwm: np.ndarray
    mode: np.ndarray
    t_pc_s: float
    """``perf_counter`` de la llegada del bloque, relativo al inicio de la sesión."""
    t_now_us: int
    """``micros()`` del ESP32 al servir el bloque: permite estimar la deriva de reloj."""
    dropped_total: int

    def __len__(self) -> int:
        return len(self.t_s)


@dataclass
class StreamStats:
    """Lo que hace falta para confiar (o no) en lo que se está viendo."""

    samples: int = 0
    blocks: int = 0
    dropped: int = 0
    gaps: int = 0
    """Intervalos por encima de 1,5x la mediana nominal. Un hueco no es sólo pérdida:
    puede ser el lazo bloqueado por la radio. No se tapa — quien analice decide."""
    dt_max_ms: float = 0.0
    duration_s: float = 0.0
    errors: int = 0
    busy_503: int = 0
    last_error: str = ""
    running: bool = False

    @property
    def rate_hz(self) -> float:
        """Tasa EFECTIVA medida sobre las marcas del ESP32, no la nominal pedida."""
        return (self.samples - 1) / self.duration_s if self.duration_s > 0 and self.samples > 1 else 0.0


@dataclass
class _Unwrap:
    """Estado del desenrollado de ``micros()``, que debe encadenarse entre bloques."""

    wraps: int = 0
    last_raw_us: int | None = None
    origin_us: int | None = None
    last_t_us: int | None = None
    nominal_dt_us: float = field(default=2000.0)

    def apply(self, block: Block) -> np.ndarray:
        t_us, self.wraps = unwrap_us(block.samples["t_us"], self.last_raw_us, self.wraps)
        self.last_raw_us = int(block.samples["t_us"][-1])
        if self.origin_us is None:
            self.origin_us = int(t_us[0])
        return t_us


class DaqStream:
    """Sesión de adquisición continua sobre ``/daq``, en un hilo aparte.

    El hilo sólo hace I/O y publica en una cola; quien dibuje consume con
    :meth:`drain` desde su propio temporizador. Nunca al revés: un repintado por bloque
    ataría la interfaz al ritmo de la radio.
    """

    def __init__(
        self,
        ip: str = DEFAULT_ESP32_IP,
        *,
        decim: int = 1,
        poll_interval: float = 0.2,
        client: DaqClient | None = None,
        maxsize: int = 256,
    ) -> None:
        self.decim = max(1, int(decim))
        self.poll_interval = poll_interval
        self._client = client if client is not None else DaqClient(ip)
        self._queue: queue.Queue[Chunk] = queue.Queue(maxsize=maxsize)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stats = StreamStats()
        self._unwrap = _Unwrap(nominal_dt_us=1e6 / CONTROL_HZ * self.decim)

        if poll_interval * CONTROL_HZ / self.decim > DAQ_MAX_BLOCK:
            logger.warning(
                "poll_interval=%.2f s pide %.0f muestras por bloque, sobre el techo de %d: habrá pérdidas",
                poll_interval,
                poll_interval * CONTROL_HZ / self.decim,
                DAQ_MAX_BLOCK,
            )

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    @property
    def rate_hz(self) -> float:
        """Tasa nominal de la sesión según la decimación pedida."""
        return CONTROL_HZ / self.decim

    @property
    def stats(self) -> StreamStats:
        with self._lock:
            return replace(self._stats)  # copia: el hilo sigue escribiendo sobre el original

    def start(self) -> None:
        """Arranca la adquisición en la placa y el hilo que la consume."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._client.start(decim=self.decim)  # el firmware vacía el buffer al arrancar
        self._stop_event.clear()
        with self._lock:
            self._stats = StreamStats(running=True)
        self._unwrap = _Unwrap(nominal_dt_us=1e6 / CONTROL_HZ * self.decim)
        self._thread = threading.Thread(target=self._run, name="daq-stream", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Detiene el hilo y la adquisición. Seguro de llamar dos veces."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        try:
            self._client.stop()
        except requests.RequestException:
            # Dejarla corriendo llena el anillo y ensucia la sesión siguiente con
            # muestras huérfanas, pero no hay nada más que hacer desde aquí.
            logger.warning("no se pudo detener la adquisición; reintentar /daq?stop=1")
        with self._lock:
            self._stats.running = False

    # ── Consumo ───────────────────────────────────────────────────────────────

    def drain(self, max_chunks: int = 64) -> list[Chunk]:
        """Se lleva lo acumulado sin bloquear. Devuelve [] si no hay nada nuevo."""
        out: list[Chunk] = []
        for _ in range(max_chunks):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    # ── Hilo ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        t0_pc = time.perf_counter()
        while not self._stop_event.is_set():
            # `wait` en vez de `sleep`: un stop no espera al siguiente sondeo completo.
            if self._stop_event.wait(self.poll_interval):
                break
            self._poll_once(t0_pc)
        # Vaciar la cola del firmware: lo que quedó en el anillo es dato ya medido y
        # descartarlo recortaría el final de cada sesión, justo donde suele estar lo
        # interesante.
        for _ in range(16):
            if self._poll_once(t0_pc) == 0:
                break

    def _poll_once(self, t0_pc: float) -> int:
        """Lee un bloque y lo publica. Devuelve cuántas muestras trajo."""
        try:
            block = self._client.read_block(retries=1)
        except requests.RequestException as exc:
            with self._lock:
                self._stats.errors += 1
                self._stats.last_error = str(exc)
            return 0
        except ProtocolError as exc:
            # Un bloque que no es un bloque no debe matar el hilo en silencio: se cuenta
            # y se sigue. Pasó de verdad (2026-08-03): `/daq/read` devolvía el JSON de
            # `/daq` por una colisión de rutas en el firmware, y la excepción se llevaba
            # la adquisición entera dejando la interfaz viva pero muda.
            with self._lock:
                self._stats.errors += 1
                self._stats.last_error = f"bloque inválido: {exc}"
            return 0
        if block is None:
            with self._lock:
                self._stats.busy_503 += 1
            return 0
        if len(block) == 0:
            return 0

        t_pc = time.perf_counter() - t0_pc
        t_us = self._unwrap.apply(block)
        chunk = Chunk(
            t_s=(t_us - self._unwrap.origin_us) / 1e6,
            th_deg=block.samples["th_deg"].astype(np.float64),
            al_deg=block.samples["al_deg"].astype(np.float64),
            pwm=block.samples["pwm"].astype(np.int32),
            mode=block.samples["mode"].astype(np.int32),
            t_pc_s=t_pc,
            t_now_us=block.t_now_us,
            dropped_total=block.dropped_total,
        )
        self._update_stats(chunk, t_us)
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            # Si nadie consume, lo viejo pierde valor antes que lo nuevo.
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(chunk)
        return len(chunk)

    def _update_stats(self, chunk: Chunk, t_us: np.ndarray) -> None:
        # Los huecos se miden también ENTRE bloques: un corte de radio cae justo ahí.
        edges = t_us if self._unwrap.last_t_us is None else np.concatenate(([self._unwrap.last_t_us], t_us))
        dt_us = np.diff(edges) if len(edges) > 1 else np.zeros(0)
        self._unwrap.last_t_us = int(t_us[-1])
        with self._lock:
            self._stats.blocks += 1
            self._stats.samples += len(chunk)
            self._stats.dropped = chunk.dropped_total  # acumulado, no incremental
            self._stats.duration_s = float(chunk.t_s[-1])
            if len(dt_us):
                self._stats.dt_max_ms = max(self._stats.dt_max_ms, float(dt_us.max()) / 1000.0)
                self._stats.gaps += int(np.count_nonzero(dt_us > 1.5 * self._unwrap.nominal_dt_us))
