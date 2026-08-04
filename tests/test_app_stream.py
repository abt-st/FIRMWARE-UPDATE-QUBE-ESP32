"""Tests de la adquisición continua y de los anillos de dibujo, sin hardware.

Lo que se verifica es el trabajo del PC en el camino *en vivo*: encadenar bloques sin
perder la marca de tiempo, contabilizar lo perdido, ver el hueco que queda ENTRE dos
bloques —donde cae un corte de radio— y mantener una ventana deslizante sin desordenar
las muestras. Es la parte que ``qube_daq`` no cubre, porque allí la captura se arma
entera al final.
"""

from __future__ import annotations

import struct
import time

import numpy as np
import pytest

from qube_app.analysis import wrap_deg
from qube_app.buffers import RingBuffer, TraceStore
from qube_app.link import QubeLink, ReadOnlyError
from qube_app.stream import Chunk, DaqStream
from qube_daq.client import DaqClient
from qube_daq.protocol import DAQ_MAGIC, DAQ_PROTO_VERSION, HEADER_FORMAT, SAMPLE_BYTES, US_WRAP, decode_block


def block_from(t0_us: int, n: int, period_us: int = 2000, dropped: int = 0, mode: int = 4):
    payload = struct.pack(HEADER_FORMAT, DAQ_MAGIC, DAQ_PROTO_VERSION, SAMPLE_BYTES, n, dropped, t0_us % (1 << 32))
    for i in range(n):
        t = (t0_us + i * period_us) % (1 << 32)
        payload += struct.pack("<IffhBB", t, float(i), float(-i), i % 200, mode, 1)
    return decode_block(payload)


class ScriptedClient(DaqClient):
    """Entrega una lista fija de bloques y después nada. Sin red de por medio."""

    def __init__(self, blocks):
        super().__init__(ip="0.0.0.0")
        self._blocks = list(blocks)
        self.started = False
        self.stopped = False

    def start(self, decim: int = 1):
        self.started = True
        return {"running": True, "decim": decim}

    def stop(self):
        self.stopped = True
        return {"running": False}

    def read_block(self, retries: int = 3):  # noqa: ARG002 — firma del padre
        return self._blocks.pop(0) if self._blocks else None


def run_stream(blocks, poll_interval: float = 0.01) -> tuple[DaqStream, list]:
    """Corre el hilo hasta agotar los bloques y devuelve lo que llegó a la cola."""
    stream = DaqStream(decim=1, poll_interval=poll_interval, client=ScriptedClient(blocks))
    stream.start()
    deadline = time.perf_counter() + 2.0
    while stream.stats.blocks < len(blocks) and time.perf_counter() < deadline:
        time.sleep(0.01)
    stream.stop()
    return stream, stream.drain()


# ── Adquisición continua ──────────────────────────────────────────────────────


def test_chunks_arrive_in_order_with_a_shared_time_origin():
    _, chunks = run_stream([block_from(10_000, 3), block_from(16_000, 3)])
    t = np.concatenate([c.t_s for c in chunks])

    assert len(t) == 6
    assert t[0] == 0.0, "el origen es la primera muestra de la sesión, no la de cada bloque"
    assert np.all(np.diff(t) > 0)
    assert t[-1] == pytest.approx(0.010)  # 5 intervalos de 2 ms


def test_time_does_not_go_backwards_across_a_micros_wrap():
    # micros() da la vuelta cada 71,6 min: sin desenrollar, la serie se ordena mal y el
    # salto hacia atrás parece un dato real.
    _, chunks = run_stream([block_from(US_WRAP - 4_000, 2), block_from(0, 2)])
    t = np.concatenate([c.t_s for c in chunks])

    assert len(t) == 4
    assert np.all(np.diff(t) > 0)


def test_dropped_is_reported_as_the_running_total_not_a_sum():
    stream, chunks = run_stream([block_from(0, 2, dropped=0), block_from(4_000, 2, dropped=13)])

    assert chunks[-1].dropped_total == 13
    assert stream.stats.dropped == 13, "viaja acumulado en cada cabecera: vale el último"


def test_a_hole_between_two_blocks_is_counted():
    # El corte de radio cae justo en la juntura: si sólo se miraran los intervalos
    # dentro de cada bloque, ese hueco sería invisible.
    stream, _ = run_stream([block_from(0, 3), block_from(50_000, 3)])

    assert stream.stats.gaps == 1
    assert stream.stats.dt_max_ms == pytest.approx(46.0)


def test_stopping_drains_what_stayed_in_the_firmware_buffer():
    # Lo que quedó en el anillo al detener es dato ya medido; descartarlo recorta el
    # final de cada sesión, justo donde suele estar lo interesante.
    stream, chunks = run_stream([block_from(0, 2), block_from(4_000, 2), block_from(8_000, 2)])

    assert stream.stats.samples == 6
    assert sum(len(c) for c in chunks) == 6


def test_effective_rate_is_measured_not_assumed():
    stream, _ = run_stream([block_from(0, 501, period_us=2000)])
    assert stream.stats.rate_hz == pytest.approx(500.0, rel=1e-3)


def test_empty_session_reports_zero_instead_of_crashing():
    stream, chunks = run_stream([])
    assert chunks == []
    assert stream.stats.samples == 0
    assert stream.stats.rate_hz == 0.0


def test_alpha_travels_unwrapped():
    # Envolver es decisión del análisis, no del transporte: el salto de ±180° destruye
    # cualquier derivada numérica.
    _, chunks = run_stream([block_from(0, 4)])
    assert chunks[0].al_deg.tolist() == [0.0, -1.0, -2.0, -3.0]


# ── Anillos de dibujo ─────────────────────────────────────────────────────────


def test_ring_buffer_keeps_the_newest_and_stays_ordered():
    buf = RingBuffer(capacity=4)
    for i in range(10):
        buf.extend(np.array([float(i)]))

    assert len(buf) == 4
    assert buf.view().tolist() == [6.0, 7.0, 8.0, 9.0]


def test_ring_buffer_survives_a_batch_larger_than_its_capacity():
    buf = RingBuffer(capacity=3)
    buf.extend(np.arange(10.0))
    assert buf.view().tolist() == [7.0, 8.0, 9.0]


def test_ring_buffer_view_is_contiguous_after_compacting():
    # El dibujo depende de que `view()` sea una vista contigua y no una copia armada
    # en cada cuadro; si dejara de serlo, el costo aparecería recién a 500 Hz.
    buf = RingBuffer(capacity=8)
    for _ in range(20):
        buf.extend(np.arange(5.0))
    assert buf.view().flags["C_CONTIGUOUS"]
    assert len(buf) == 8


def test_trace_store_wraps_alpha_only_for_plotting():
    store = TraceStore(window_s=1.0, rate_hz=500.0)
    store.extend(
        Chunk(
            t_s=np.array([0.0, 0.002]),
            th_deg=np.zeros(2),
            al_deg=np.array([190.0, -370.0]),  # crudo, fuera de [-180, 180)
            pwm=np.zeros(2),
            mode=np.full(2, 5),
            t_pc_s=0.0,
            t_now_us=0,
            dropped_total=0,
        )
    )

    # El anillo guarda el crudo; envolver es cosa del dibujo, sobre la ventana visible.
    assert store["al_deg"].tolist() == [190.0, -370.0]
    assert wrap_deg(store["al_deg"]) == pytest.approx([-170.0, -10.0])


def test_trace_store_holds_exactly_the_window():
    store = TraceStore(window_s=0.02, rate_hz=500.0)  # 10 muestras
    _, chunks = run_stream([block_from(0, 50)])
    for chunk in chunks:
        store.extend(chunk)

    assert len(store) == 10
    assert store["t_s"][-1] == pytest.approx(0.098)  # la muestra 49, a 2 ms


# ── Enlace ────────────────────────────────────────────────────────────────────


def test_read_only_blocks_commands_but_never_the_emergency_stop(monkeypatch):
    link = QubeLink(ip="0.0.0.0")
    link.read_only = True
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params or {})

        class R:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"ok": True}

        return R()

    monkeypatch.setattr(link._session, "get", fake_get)

    with pytest.raises(ReadOnlyError):
        link.cmd(m=5)
    assert calls == [], "en sólo lectura no se toca la placa"

    assert link.stop_motor() is True
    assert calls == [{"x": 1}], "el paro pasa igual: es la última orden que importa"


def test_emergency_stop_reports_failure_instead_of_raising(monkeypatch):
    import requests

    link = QubeLink(ip="0.0.0.0")

    def always_fail(*_a, **_k):
        raise requests.RequestException("sin red")

    monkeypatch.setattr(link._session, "get", always_fail)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    assert link.stop_motor(retries=2) is False
