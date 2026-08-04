"""Cliente de adquisición: pide bloques al ESP32 y reconstruye la serie temporal.

El reparto de trabajo es el punto de esta arquitectura: **el ESP32 muestrea y guarda,
el PC pide, reconstruye, interpreta y analiza**. El lazo de control sigue cerrado en la
placa a 500 Hz — moverlo aquí exigiría un round-trip por muestra, 16x por encima de lo
que el enlace sostiene (31 Hz medidos, CHANGELOG v1.50.0). La adquisición, en cambio,
está limitada por caudal: un bloque que tarde 30 ms en llegar no pierde información,
porque cada muestra viaja con la marca de tiempo del tick que la produjo.

Contrato de un solo consumidor: el firmware sirve ``/daq/read`` con un staging único y
responde 503 si llega una segunda petición mientras transmite. Este cliente reintenta.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import requests

from qube_daq.protocol import Block, decode_block, unwrap_us
from qube_rl.config import DEFAULT_ESP32_IP

logger = logging.getLogger(__name__)


@dataclass
class Acquisition:
    """Serie temporal reconstruida a partir de los bloques recibidos."""

    t_s: np.ndarray = field(default_factory=lambda: np.zeros(0))
    """Segundos desde la primera muestra, según el reloj del ESP32."""
    th_deg: np.ndarray = field(default_factory=lambda: np.zeros(0))
    al_deg: np.ndarray = field(default_factory=lambda: np.zeros(0))
    """Ángulo del péndulo SIN envolver, tal como lo emite el firmware."""
    pwm: np.ndarray = field(default_factory=lambda: np.zeros(0))
    mode: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dropped: int = 0
    """Muestras que el firmware descartó por buffer lleno. **Cero o se declara.**"""
    blocks: int = 0

    @property
    def n(self) -> int:
        return len(self.t_s)

    @property
    def duration_s(self) -> float:
        return float(self.t_s[-1] - self.t_s[0]) if self.n > 1 else 0.0

    @property
    def rate_hz(self) -> float:
        """Tasa EFECTIVA medida sobre las marcas del ESP32, no la nominal pedida."""
        return (self.n - 1) / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def alpha_wrapped_deg(self) -> np.ndarray:
        """``al_deg`` envuelto a [-180, 180). Para graficar, no para derivar."""
        return (self.al_deg + 180.0) % 360.0 - 180.0

    def gaps(self, tolerance: float = 1.5) -> np.ndarray:
        """Índices donde el intervalo supera ``tolerance`` veces la mediana.

        Un hueco no es necesariamente una muestra perdida: puede ser el lazo
        bloqueado por la radio. Lo que no se hace es taparlo — quien analice decide.
        """
        if self.n < 3:
            return np.zeros(0, dtype=int)
        dt = np.diff(self.t_s)
        return np.flatnonzero(dt > tolerance * float(np.median(dt)))


class DaqClient:
    """Controla una sesión de adquisición sobre el endpoint ``/daq`` del ESP32."""

    def __init__(self, ip: str = DEFAULT_ESP32_IP, timeout: float = 2.0) -> None:
        self.base_url = f"http://{ip}"
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Connection": "keep-alive"})
        # Estado del desenrollado de micros(), que debe encadenarse entre bloques.
        self._wraps = 0
        self._last_raw_us: int | None = None

    # ── Control de la sesión ──────────────────────────────────────────────────

    def status(self) -> dict:
        resp = self._session.get(f"{self.base_url}/daq", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def start(self, decim: int = 1) -> dict:
        """Arranca la adquisición. ``decim=1`` es 500 Hz; ``10``, 50 Hz.

        El firmware vacía el buffer al arrancar: nunca se mezclan dos sesiones.
        """
        self._wraps = 0
        self._last_raw_us = None
        resp = self._session.get(f"{self.base_url}/daq", params={"start": 1, "decim": decim}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def stop(self) -> dict:
        resp = self._session.get(f"{self.base_url}/daq", params={"stop": 1}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def read_block(self, retries: int = 3) -> Block | None:
        """Lee un bloque. Devuelve ``None`` si el firmware está ocupado (503)."""
        for _attempt in range(retries):
            resp = self._session.get(f"{self.base_url}/daq/read", timeout=self.timeout)
            if resp.status_code == 503:  # otro consumidor en curso
                time.sleep(0.05)
                continue
            resp.raise_for_status()
            return decode_block(resp.content)
        logger.warning("/daq/read ocupado tras %d intentos", retries)
        return None

    # ── Captura completa ──────────────────────────────────────────────────────

    def record(
        self,
        seconds: float,
        decim: int = 1,
        poll_interval: float = 0.25,
        on_block: object | None = None,
    ) -> Acquisition:
        """Adquiere durante ``seconds`` y devuelve la serie reconstruida.

        ``poll_interval`` debe mantenerse holgadamente por debajo de lo que tarda el
        buffer del firmware en llenarse (2048 muestras = 4,1 s a 500 Hz). Con el
        default de 0,25 s hay un factor 16 de margen; si el PC se atrasa igual, las
        muestras perdidas se cuentan y se informan, nunca se silencian.
        """
        self.start(decim=decim)
        chunks: list[np.ndarray] = []
        times: list[np.ndarray] = []
        dropped = 0
        blocks = 0
        t_end = time.perf_counter() + seconds
        try:
            while time.perf_counter() < t_end:
                time.sleep(poll_interval)
                block = self.read_block()
                if block is None or len(block) == 0:
                    continue
                t_us, self._wraps = unwrap_us(block.samples["t_us"], self._last_raw_us, self._wraps)
                self._last_raw_us = int(block.samples["t_us"][-1])
                times.append(t_us)
                chunks.append(block.samples)
                dropped = block.dropped_total  # acumulado, no incremental
                blocks += 1
                if callable(on_block):
                    on_block(block)
        finally:
            # Detener la adquisición pase lo que pase: dejarla corriendo llena el
            # buffer y ensucia la sesión siguiente con muestras huérfanas.
            try:
                self.stop()
            except requests.RequestException:
                logger.warning("no se pudo detener la adquisición; reintentar /daq?stop=1")

        # Vaciar la cola: lo que quedó en el buffer del firmware es dato válido ya
        # medido, y descartarlo recortaría el final de cada captura.
        for _ in range(16):
            block = self.read_block()
            if block is None or len(block) == 0:
                break
            t_us, self._wraps = unwrap_us(block.samples["t_us"], self._last_raw_us, self._wraps)
            self._last_raw_us = int(block.samples["t_us"][-1])
            times.append(t_us)
            chunks.append(block.samples)
            dropped = block.dropped_total
            blocks += 1

        if not chunks:
            return Acquisition(dropped=dropped, blocks=blocks)

        all_samples = np.concatenate(chunks)
        all_t = np.concatenate(times)
        return Acquisition(
            t_s=(all_t - all_t[0]) / 1e6,
            th_deg=all_samples["th_deg"].astype(np.float64),
            al_deg=all_samples["al_deg"].astype(np.float64),
            pwm=all_samples["pwm"].astype(np.int32),
            mode=all_samples["mode"].astype(np.int32),
            dropped=int(dropped),
            blocks=blocks,
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> DaqClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
