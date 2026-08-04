"""Grabación a CSV con doble marca de tiempo.

Se escribe **a medida que llegan los bloques**, no al final: una sesión larga no tiene por
qué caber en memoria, y una app que se cierra mal no debería llevarse la captura.

El esquema es el canónico del proyecto (el mismo de ``qube_daq/__main__.py`` y de
``src/firmware/capture.py``) con dos columnas **al final**, donde no estorban a ningún
lector existente:

``t_pc_block_s``
    Reloj del PC al llegar el bloque que contiene la muestra. Es del **bloque**, no de la
    muestra —todas las de un bloque comparten valor— y el nombre lo dice para que nadie
    lo confunda con una marca por muestra. Contra ``t_s``, que es del tick que produjo el
    dato, permite separar después el retardo de transporte del retardo real del sistema.
    Con una sola marca esa distinción se pierde para siempre.
``t_now_us``
    ``micros()`` del ESP32 al servir el bloque. Contra ``t_s`` da la deriva entre relojes.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from qube_app.analysis import wrap_deg
from qube_app.stream import Chunk
from qube_daq.__main__ import CSV_FIELDS as CANONICAL_FIELDS

#: Esquema canónico **derivado del que ya define el CLI del DAQ**, más las dos columnas
#: de instrumentación al final. Derivarlo en vez de copiarlo es lo que garantiza que
#: `qube_daq plot` siga leyendo estos archivos si alguna vez cambia el esquema.
CSV_FIELDS = (*CANONICAL_FIELDS, "t_pc_block_s", "t_now_us")


class Recorder:
    """Vuelca los bloques a CSV mientras la sesión corre."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.rows = 0
        self.started_at: float | None = None
        self._fh = None
        self._writer = None

    @property
    def is_open(self) -> bool:
        return self._fh is not None

    def open(self) -> None:
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(CSV_FIELDS)
        self.rows = 0
        self.started_at = time.time()

    def write(self, chunk: Chunk) -> int:
        """Escribe un bloque. Devuelve cuántas filas agregó."""
        if self._writer is None:
            raise RuntimeError("el grabador está cerrado: llamar open() primero")
        wrapped = wrap_deg(chunk.al_deg)
        self._writer.writerows(
            [
                f"{chunk.t_s[i]:.6f}",
                f"{chunk.th_deg[i]:.4f}",
                f"{wrapped[i]:.4f}",
                f"{chunk.al_deg[i]:.4f}",
                int(chunk.pwm[i]),
                int(chunk.mode[i]),
                f"{chunk.t_pc_s:.6f}",
                chunk.t_now_us,
            ]
            for i in range(len(chunk))
        )
        self.rows += len(chunk)
        return len(chunk)

    def close(self) -> Path | None:
        """Cierra el archivo y devuelve su ruta, o ``None`` si no se grabó nada."""
        if self._fh is None:
            return None
        self._fh.close()
        self._fh = None
        self._writer = None
        return self.path

    def __enter__(self) -> Recorder:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
