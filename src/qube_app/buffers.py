"""Anillos preasignados para dibujar sin copiar en cada cuadro.

A 500 Hz una ventana de 60 s son 30.000 puntos por traza. Reconstruir esa serie con
``np.concatenate`` en cada repintado sería tirar a la basura la ventaja de pyqtgraph, así
que se usa el truco del búfer doble: se reserva ``2N``, se escribe hacia adelante y cuando
se llega al final se copian los últimos ``N`` al principio. :meth:`RingBuffer.view`
devuelve entonces una **vista contigua** —sin copia— con las muestras en orden.

Cada traza guarda el tipo más chico que la representa sin pérdida: sólo ``t_s`` necesita
``float64`` (es tiempo absoluto y se le sacan diferencias), los ángulos van en ``float32``
—muy por encima de los 0,176° que resuelve el encoder— y el PWM y el modo son enteros.
"""

from __future__ import annotations

import numpy as np

from qube_app.stream import Chunk

#: Traza -> tipo del anillo. La potencia NO está: la muestra binaria de 16 B no lleva
#: INA219, y meter una transacción I²C en el tick de 500 Hz es exactamente lo que el
#: diseño del DAQ evitó. Viene de ``/state`` a 2 Hz.
TRACE_DTYPES: dict[str, type] = {
    "t_s": np.float64,
    "th_deg": np.float32,
    "al_deg": np.float32,
    "pwm": np.int16,
    "mode": np.int8,
}


class RingBuffer:
    """Cola de tamaño fijo sobre numpy: entra por el final, cae por el principio."""

    def __init__(self, capacity: int, dtype: type = np.float64) -> None:
        if capacity < 1:
            raise ValueError("la capacidad debe ser al menos 1")
        self.capacity = int(capacity)
        self._buf = np.zeros(2 * self.capacity, dtype=dtype)
        self._end = 0  # una pasada el final de la muestra más nueva
        self._n = 0

    def __len__(self) -> int:
        return self._n

    def extend(self, values: np.ndarray) -> None:
        values = np.asarray(values)
        if values.size == 0:
            return
        # Un lote mayor que la capacidad: sólo la cola sobrevive de todas formas.
        if values.size >= self.capacity:
            values = values[-self.capacity :]
        if self._end + values.size > self._buf.size:
            # Compactar: los últimos `n` pasan al principio y se sigue escribiendo.
            keep = min(self._n, self.capacity)
            self._buf[:keep] = self._buf[self._end - keep : self._end]
            self._end = keep
        self._buf[self._end : self._end + values.size] = values
        self._end += values.size
        self._n = min(self._n + values.size, self.capacity)

    def view(self) -> np.ndarray:
        """Vista contigua de las muestras vivas, de la más vieja a la más nueva."""
        return self._buf[self._end - self._n : self._end]


class TraceStore:
    """Las trazas del DAQ en anillos paralelos, alimentadas por :class:`Chunk`."""

    def __init__(self, window_s: float = 60.0, rate_hz: float = 500.0) -> None:
        capacity = max(2, int(window_s * rate_hz))
        self._buffers = {name: RingBuffer(capacity, dtype) for name, dtype in TRACE_DTYPES.items()}

    def __len__(self) -> int:
        return len(self._buffers["t_s"])

    def __getitem__(self, name: str) -> np.ndarray:
        return self._buffers[name].view()

    def extend(self, chunk: Chunk) -> None:
        for name in TRACE_DTYPES:
            self._buffers[name].extend(getattr(chunk, name))
