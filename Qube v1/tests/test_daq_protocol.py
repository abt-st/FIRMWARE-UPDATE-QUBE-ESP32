"""Tests del protocolo de adquisición por bloques.

Se verifican contra bloques sintéticos construidos con el MISMO layout que emite el
firmware. No reemplazan una prueba en banco —el firmware no corre aquí— pero sí
cubren lo que puede fallar en silencio y arruinar una serie: el desajuste de versión,
un bloque truncado, y el desbordamiento de ``micros()`` cada 71,6 minutos.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from qube_daq.protocol import (
    DAQ_MAGIC,
    DAQ_PROTO_VERSION,
    HEADER_FORMAT,
    SAMPLE_BYTES,
    US_WRAP,
    ProtocolError,
    decode_block,
    unwrap_us,
)


def make_block(
    samples: list[tuple[int, float, float, int, int, int]],
    *,
    magic: int = DAQ_MAGIC,
    pv: int = DAQ_PROTO_VERSION,
    sample_bytes: int = SAMPLE_BYTES,
    dropped: int = 0,
    t_now: int = 123456,
    n_override: int | None = None,
) -> bytes:
    """Arma un bloque binario como lo haría ``handleDaqRead()``."""
    n = len(samples) if n_override is None else n_override
    payload = struct.pack(HEADER_FORMAT, magic, pv, sample_bytes, n, dropped, t_now)
    for t_us, th, al, pwm, mode, flags in samples:
        payload += struct.pack("<IffhBB", t_us, th, al, pwm, mode, flags)
    return payload


# ── Decodificación ────────────────────────────────────────────────────────────


def test_decode_recovers_every_field():
    block = make_block([(2000, 12.5, -170.25, -128, 5, 1), (4000, 12.75, -169.0, 127, 5, 1)], dropped=7)
    decoded = decode_block(block)

    assert len(decoded) == 2
    assert decoded.dropped_total == 7
    assert decoded.samples["t_us"].tolist() == [2000, 4000]
    assert decoded.samples["th_deg"] == pytest.approx([12.5, 12.75])
    assert decoded.samples["al_deg"] == pytest.approx([-170.25, -169.0])
    assert decoded.samples["pwm"].tolist() == [-128, 127]
    assert decoded.samples["mode"].tolist() == [5, 5]


def test_empty_block_is_valid_not_an_error():
    # El PC preguntó antes de que hubiera muestras nuevas: es normal, no una falla.
    decoded = decode_block(make_block([]))
    assert len(decoded) == 0
    assert decoded.dropped_total == 0


def test_wrong_magic_is_rejected():
    with pytest.raises(ProtocolError, match="magic"):
        decode_block(make_block([], magic=0xDEADBEEF))


def test_protocol_mismatch_fails_loudly():
    # Es el caso que importa: un firmware viejo con campos corridos produciría una
    # serie plausible pero incorrecta. Tiene que romper, no adivinar.
    with pytest.raises(ProtocolError, match="deben desplegarse juntos"):
        decode_block(make_block([], pv=DAQ_PROTO_VERSION + 1))


def test_sample_size_mismatch_is_rejected():
    with pytest.raises(ProtocolError, match="se esperaban"):
        decode_block(make_block([], sample_bytes=20))


def test_truncated_block_is_rejected():
    # Cabecera que promete 4 muestras pero sólo trae una.
    with pytest.raises(ProtocolError, match="truncado"):
        decode_block(make_block([(1000, 0.0, 0.0, 0, 0, 0)], n_override=4))


def test_header_only_garbage_is_rejected():
    with pytest.raises(ProtocolError, match="cabecera"):
        decode_block(b"\x00\x01\x02")


# ── Desbordamiento de micros() ────────────────────────────────────────────────


def test_unwrap_without_wrap_is_identity():
    raw = np.array([1000, 3000, 5000], dtype=np.uint32)
    out, wraps = unwrap_us(raw)
    assert out.tolist() == [1000, 3000, 5000]
    assert wraps == 0


def test_unwrap_detects_wrap_inside_a_block():
    # micros() da la vuelta a mitad del bloque: sin corregir, el tiempo iría hacia
    # atrás y la serie quedaría desordenada sin que nada lo denuncie.
    raw = np.array([US_WRAP - 2000, US_WRAP - 1000, 0, 1000], dtype=np.uint32)
    out, wraps = unwrap_us(raw)
    assert np.all(np.diff(out) > 0)
    assert out[2] - out[1] == 1000
    assert wraps == 1


def test_unwrap_chains_across_blocks():
    first = np.array([US_WRAP - 1000], dtype=np.uint32)
    out1, wraps1 = unwrap_us(first)
    second = np.array([0, 2000], dtype=np.uint32)
    out2, wraps2 = unwrap_us(second, previous_last=int(first[-1]), wraps=wraps1)

    assert wraps1 == 0
    assert wraps2 == 1
    assert out2[0] - out1[-1] == 1000  # continuidad a través del corte


def test_unwrap_empty_block_keeps_state():
    out, wraps = unwrap_us(np.zeros(0, dtype=np.uint32), previous_last=42, wraps=3)
    assert len(out) == 0
    assert wraps == 3
