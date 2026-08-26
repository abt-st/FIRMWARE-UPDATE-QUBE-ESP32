"""Adquisición de datos por bloques desde el ESP32 del QUBE.

El ESP32 muestrea a la tasa del lazo (500 Hz) en un buffer circular; el PC se lleva
bloques, reconstruye la serie y analiza. El lazo de control **no** se mueve al PC:
ver ``docs/research/adquisicion_por_bloques.md`` para el porqué, con las cifras.
"""

from qube_daq.client import Acquisition, DaqClient
from qube_daq.protocol import Block, ProtocolError, decode_block, unwrap_us

__all__ = ["Acquisition", "Block", "DaqClient", "ProtocolError", "decode_block", "unwrap_us"]
