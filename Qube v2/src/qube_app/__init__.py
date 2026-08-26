"""App de escritorio del QUBE: telemetría a 500 Hz, control y análisis en vivo.

El núcleo —enlace HTTP, adquisición, anillos y análisis— **no depende de Qt**: se puede
correr sin GUI con ``python -m qube_app --selftest``, que es como se estrena el DAQ en
banco sin arriesgar una interfaz a medio hacer. La GUI (``qube_app.ui``) es una capa
encima que consume las mismas colas.
"""

from qube_app.buffers import RingBuffer
from qube_app.link import QubeLink, ReadOnlyError
from qube_app.poller import StatePoller
from qube_app.stream import DaqStream, StreamStats

__all__ = ["DaqStream", "QubeLink", "ReadOnlyError", "RingBuffer", "StatePoller", "StreamStats"]
