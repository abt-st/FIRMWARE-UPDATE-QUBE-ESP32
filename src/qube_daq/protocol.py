"""Decodificador del protocolo binario de adquisición por bloques del ESP32.

Contraparte de ``handleDaqRead()`` en ``src/firmware/esp32_qube/esp32_qube.ino``.
**Firmware y este módulo se despliegan juntos**: la versión de protocolo viaja en la
cabecera y :func:`decode_block` la valida, de modo que un desajuste falla de inmediato
en vez de producir una serie temporal con campos corridos —que es exactamente el tipo
de dato contaminado que este proyecto ya pagó caro una vez.

Formato del bloque (todo little-endian):

===========  =====  ====================================================
Cabecera     bytes  contenido
===========  =====  ====================================================
magic        4      ``0x51414451`` (``QDAQ``)
pv           1      versión de protocolo
sample_bytes 1      tamaño de cada muestra (16)
n            2      número de muestras en el bloque
dropped      4      muestras perdidas ACUMULADAS desde el último ``start``
t_now        4      ``micros()`` al servir el bloque
===========  =====  ====================================================

Cada muestra (16 B): ``t_us`` u32, ``th_deg`` f32, ``al_deg`` f32, ``pwm`` i16,
``mode`` u8, ``flags`` u8.

``al_deg`` llega **sin envolver** a propósito: el salto de ±180° destruye cualquier
derivada numérica, así que envolver es decisión del análisis, no del transporte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

DAQ_MAGIC = 0x51414451
DAQ_PROTO_VERSION = 1
HEADER_FORMAT = "<IBBHII"
HEADER_BYTES = struct.calcsize(HEADER_FORMAT)
SAMPLE_BYTES = 16

#: ``micros()`` del ESP32 es un ``uint32``: da la vuelta cada 2**32 us ~= 71,6 min.
US_WRAP = 1 << 32

SAMPLE_DTYPE = np.dtype(
    [
        ("t_us", "<u4"),
        ("th_deg", "<f4"),
        ("al_deg", "<f4"),
        ("pwm", "<i2"),
        ("mode", "u1"),
        ("flags", "u1"),
    ]
)
assert SAMPLE_DTYPE.itemsize == SAMPLE_BYTES, "el dtype debe calzar con el struct del firmware"


class ProtocolError(ValueError):
    """El bloque no es un bloque DAQ válido de la versión esperada."""


@dataclass(frozen=True)
class Block:
    """Un bloque decodificado, tal como lo entregó el firmware."""

    proto_version: int
    dropped_total: int
    """Perdidas acumuladas desde el ``start``, no las de este bloque."""
    t_now_us: int
    """``micros()`` del ESP32 al servir: permite estimar la deriva de reloj PC↔ESP32."""
    samples: np.ndarray
    """Array estructurado con :data:`SAMPLE_DTYPE`."""

    def __len__(self) -> int:
        return len(self.samples)


def decode_block(payload: bytes) -> Block:
    """Decodifica un bloque binario. Lanza :class:`ProtocolError` si no calza.

    Un bloque vacío (``n == 0``) es legítimo: significa que el PC preguntó antes de
    que hubiera muestras nuevas, no que algo haya fallado.
    """
    if len(payload) < HEADER_BYTES:
        raise ProtocolError(f"bloque de {len(payload)} B: no alcanza ni para la cabecera de {HEADER_BYTES} B")

    magic, pv, sample_bytes, n, dropped, t_now = struct.unpack_from(HEADER_FORMAT, payload, 0)
    if magic != DAQ_MAGIC:
        raise ProtocolError(f"magic {magic:#010x} != {DAQ_MAGIC:#010x}: esto no es un bloque DAQ")
    if pv != DAQ_PROTO_VERSION:
        raise ProtocolError(
            f"protocolo DAQ v{pv} en el firmware, v{DAQ_PROTO_VERSION} esperada aquí. "
            "Reflashear la placa o actualizar qube_daq — deben desplegarse juntos."
        )
    if sample_bytes != SAMPLE_BYTES:
        raise ProtocolError(f"muestras de {sample_bytes} B, se esperaban {SAMPLE_BYTES} B")

    expected = HEADER_BYTES + n * SAMPLE_BYTES
    if len(payload) < expected:
        raise ProtocolError(f"bloque truncado: {len(payload)} B para {n} muestras (se esperaban {expected} B)")

    samples = np.frombuffer(payload, dtype=SAMPLE_DTYPE, count=n, offset=HEADER_BYTES)
    return Block(proto_version=pv, dropped_total=dropped, t_now_us=t_now, samples=samples)


def unwrap_us(t_us: np.ndarray, previous_last: int | None = None, wraps: int = 0) -> tuple[np.ndarray, int]:
    """Deshace el desbordamiento de ``micros()`` y devuelve microsegundos monotónicos.

    Sin esto, una captura de más de 71,6 minutos produce un salto hacia atrás que
    parece un dato real —y peor: una serie que ordena mal—. Devuelve el array
    corregido y el contador de vueltas acumulado, para encadenar bloque a bloque.

    Args:
        t_us: marcas de tiempo crudas del bloque.
        previous_last: última marca CRUDA del bloque anterior, o ``None`` si es el primero.
        wraps: vueltas acumuladas hasta el bloque anterior.
    """
    if len(t_us) == 0:
        return np.zeros(0, dtype=np.int64), wraps

    raw = t_us.astype(np.int64)
    # Una marca menor que la anterior sólo puede significar desbordamiento: el
    # firmware las emite en orden estricto (una por tick del lazo).
    steps = np.zeros(len(raw), dtype=np.int64)
    if previous_last is not None and raw[0] < previous_last:
        steps[0] = 1
    steps[1:] = (np.diff(raw) < 0).astype(np.int64)
    total_wraps = wraps + np.cumsum(steps)
    return raw + total_wraps * US_WRAP, int(total_wraps[-1])
