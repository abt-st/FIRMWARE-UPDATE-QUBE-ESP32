"""Prueba de humo de la interfaz, sin pantalla y sin placa.

No pretende verificar el dibujo —para eso está mirar la ventana— sino lo que sí se
puede romper en silencio: que la ventana se arme, que el ciclo de dibujo consuma de la
cola de adquisición y que cerrarla deje todo detenido. Corre con el backend *offscreen*
de Qt, así que no necesita servidor gráfico.

Se salta entero si la app no está instalada (``uv sync --extra app``): el núcleo y el
resto de la suite no dependen de Qt.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="requiere las dependencias de la app (uv sync --extra app)")
pytest.importorskip("pyqtgraph", reason="requiere las dependencias de la app (uv sync --extra app)")

from PySide6.QtWidgets import QApplication

from qube_app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    win = MainWindow(ip="0.0.0.0", fake=True)
    yield win
    win.close()


def test_window_builds_without_a_board(window):
    assert window.stream is None, "no se adquiere hasta que alguien lo pida"
    assert window.session.btn_stream.isChecked() is False


def test_streaming_fills_the_store_and_stopping_leaves_it(window):
    window.session.btn_stream.setChecked(True)
    assert window.stream is not None

    # El hilo produce en tiempo real: se espera a que llegue el primer bloque en vez de
    # asumir un tiempo fijo, que en una máquina cargada sería una prueba intermitente.
    deadline = time.monotonic() + 4.0
    while not len(window.store) and time.monotonic() < deadline:
        QApplication.processEvents()
        window._on_draw()
        time.sleep(0.02)

    assert len(window.store) > 0, "el ciclo de dibujo debe consumir de la cola del stream"

    window.session.btn_stream.setChecked(False)
    assert window.stream is None
    assert len(window.store) > 0, "detener no borra lo ya capturado"


def test_read_only_disables_the_control_panels(window):
    window.session.read_only.setChecked(True)
    assert window.link.read_only is True
    assert window.control.isEnabled() is False
    assert window.gains.isEnabled() is False

    window.session.read_only.setChecked(False)
    assert window.link.read_only is False
    assert window.control.isEnabled() is True


def test_closing_stops_acquisition(window):
    window.session.btn_stream.setChecked(True)
    window.close()
    assert window.stream is None or not window.stream.stats.running
