"""Tests de la reconstrucción de la serie temporal, sin hardware.

Se sustituye el transporte por bloques sintéticos: lo que se verifica es el trabajo
que hace el PC —encadenar bloques, normalizar el tiempo, medir la tasa efectiva,
detectar huecos y no perder la cola de la captura— que es precisamente la parte que
justifica mover el análisis al computador.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from qube_daq.client import Acquisition, DaqClient
from qube_daq.protocol import DAQ_MAGIC, DAQ_PROTO_VERSION, HEADER_FORMAT, SAMPLE_BYTES, decode_block


def block_from(t0_us: int, n: int, period_us: int = 2000, dropped: int = 0, mode: int = 4):
    payload = struct.pack(HEADER_FORMAT, DAQ_MAGIC, DAQ_PROTO_VERSION, SAMPLE_BYTES, n, dropped, t0_us)
    for i in range(n):
        t = (t0_us + i * period_us) % (1 << 32)
        payload += struct.pack("<IffhBB", t, float(i), float(-i), i % 200, mode, 1)
    return decode_block(payload)


class FakeClient(DaqClient):
    """DaqClient con el transporte reemplazado por una lista de bloques."""

    def __init__(self, blocks):
        super().__init__(ip="0.0.0.0")
        self._blocks = list(blocks)
        self.started = False
        self.stopped = False

    def start(self, decim: int = 1):
        self.started = True
        self._wraps = 0
        self._last_raw_us = None
        return {"running": True, "decim": decim}

    def stop(self):
        self.stopped = True
        return {"running": False}

    def read_block(self, retries: int = 3):  # noqa: ARG002 — firma del padre
        return self._blocks.pop(0) if self._blocks else None


def test_record_concatenates_blocks_in_order():
    client = FakeClient([block_from(10_000, 3), block_from(16_000, 3)])
    acq = client.record(seconds=0.0, poll_interval=0.0)

    assert acq.n == 6
    assert acq.blocks == 2
    assert acq.t_s[0] == 0.0  # el tiempo se normaliza a la primera muestra
    assert np.all(np.diff(acq.t_s) > 0)
    assert acq.t_s[-1] == pytest.approx(0.010)  # 5 intervalos de 2 ms


def test_record_drains_the_buffer_after_stopping():
    # Las muestras que quedaron en el firmware al detener son dato válido: recortarlas
    # cortaría el final de toda captura, justo donde suele estar lo interesante.
    client = FakeClient([block_from(0, 2), block_from(4_000, 2), block_from(8_000, 2)])
    acq = client.record(seconds=0.0, poll_interval=0.0)

    assert client.started and client.stopped
    assert acq.n == 6


def test_record_reports_dropped_samples():
    client = FakeClient([block_from(0, 2, dropped=0), block_from(4_000, 2, dropped=13)])
    acq = client.record(seconds=0.0, poll_interval=0.0)
    # `dropped` viaja acumulado en cada bloque: vale el último, no la suma.
    assert acq.dropped == 13


def test_record_survives_a_wrap_between_blocks():
    from qube_daq.protocol import US_WRAP

    client = FakeClient([block_from(US_WRAP - 4_000, 2), block_from(0, 2)])
    acq = client.record(seconds=0.0, poll_interval=0.0)

    assert acq.n == 4
    assert np.all(np.diff(acq.t_s) > 0), "el desbordamiento de micros() no debe invertir el tiempo"


def test_record_with_no_data_returns_empty_not_crash():
    acq = FakeClient([]).record(seconds=0.0, poll_interval=0.0)
    assert acq.n == 0
    assert acq.duration_s == 0.0
    assert acq.rate_hz == 0.0


def test_effective_rate_is_measured_not_assumed():
    acq = FakeClient([block_from(0, 501, period_us=2000)]).record(seconds=0.0, poll_interval=0.0)
    assert acq.rate_hz == pytest.approx(500.0, rel=1e-6)
    assert acq.duration_s == pytest.approx(1.0, rel=1e-6)


def test_alpha_is_transported_unwrapped_and_wrapped_only_on_demand():
    acq = Acquisition(
        t_s=np.array([0.0, 0.002]),
        th_deg=np.array([0.0, 0.0]),
        al_deg=np.array([190.0, -370.0]),  # crudo, fuera de [-180, 180)
        pwm=np.array([0, 0]),
        mode=np.array([5, 5]),
    )
    assert acq.al_deg.tolist() == [190.0, -370.0]
    assert acq.alpha_wrapped_deg == pytest.approx([-170.0, -10.0])


def test_gaps_flags_the_hole_and_nothing_else():
    t = np.array([0.0, 0.002, 0.004, 0.050, 0.052])  # un salto de 46 ms
    acq = Acquisition(t_s=t, th_deg=np.zeros(5), al_deg=np.zeros(5), pwm=np.zeros(5), mode=np.zeros(5))
    assert acq.gaps().tolist() == [2]
