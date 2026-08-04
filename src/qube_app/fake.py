"""Placa simulada: bloques DAQ sintéticos en tiempo real, sin hardware.

Sirve para dos cosas distintas y ambas importan: probar el camino completo de la app
—hilo, desenrollado, anillos, análisis— en ``pytest`` sin placa, y poder abrir la GUI en
el escritorio para trabajar en ella cuando el banco no está disponible.

Genera el bloque **con la misma función que decodifica el cliente real**
(:func:`qube_daq.protocol.decode_block`), así que si el formato cambia, esto se rompe
igual que se rompería el enlace de verdad. Un simulador que no comparte el codificador
con el firmware no prueba nada.
"""

from __future__ import annotations

import math
import struct
import time

from qube_app.stream import CONTROL_HZ, DAQ_CAPACITY, DAQ_MAX_BLOCK
from qube_daq.client import DaqClient
from qube_daq.protocol import DAQ_MAGIC, DAQ_PROTO_VERSION, HEADER_FORMAT, SAMPLE_BYTES, Block, decode_block


def make_block(t0_us: int, n: int, period_us: int = 2000, dropped: int = 0, mode: int = 5) -> Block:
    """Un bloque con un péndulo oscilando y un PWM de bombeo, listo para decodificar."""
    payload = struct.pack(HEADER_FORMAT, DAQ_MAGIC, DAQ_PROTO_VERSION, SAMPLE_BYTES, n, dropped, t0_us % (1 << 32))
    for i in range(n):
        t = (t0_us + i * period_us) % (1 << 32)
        secs = (t0_us + i * period_us) / 1e6
        alpha = 170.0 * math.sin(2 * math.pi * 0.7 * secs)
        theta = 25.0 * math.sin(2 * math.pi * 0.7 * secs + 0.4)
        pwm = int(120 * math.cos(2 * math.pi * 0.7 * secs))
        payload += struct.pack("<IffhBB", t, theta, alpha, pwm, mode, 1)
    return decode_block(payload)


class FakeDaqClient(DaqClient):
    """``DaqClient`` con el transporte sustituido por un generador en tiempo real.

    Emite sólo las muestras que *ya habrían ocurrido* desde la lectura anterior, con el
    techo de ``DAQ_MAX_BLOCK`` del firmware: sondear demasiado lento pierde muestras aquí
    igual que las perdería contra la placa, y esa es justamente la falla que conviene
    poder reproducir en el escritorio.
    """

    def __init__(self, ip: str = "0.0.0.0", mode: int = 5) -> None:
        super().__init__(ip=ip)
        self.mode = mode
        self._decim = 1
        self._t0: float | None = None
        self._emitted = 0
        self._dropped = 0

    @property
    def _period_us(self) -> int:
        return int(1e6 / CONTROL_HZ * self._decim)

    def status(self) -> dict:
        return {"running": self._t0 is not None, "decim": self._decim, "rate_hz": CONTROL_HZ / self._decim}

    def start(self, decim: int = 1) -> dict:
        self._decim = max(1, decim)
        self._t0 = time.perf_counter()
        self._emitted = 0
        self._dropped = 0
        return self.status()

    def stop(self) -> dict:
        self._t0 = None
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
        block = make_block(self._emitted * self._period_us, n, self._period_us, self._dropped, self.mode)
        self._emitted += n
        return block
