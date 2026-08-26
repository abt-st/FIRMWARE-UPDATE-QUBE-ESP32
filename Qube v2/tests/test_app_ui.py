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
import re
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="requiere las dependencias de la app (uv sync --extra app)")
pytest.importorskip("pyqtgraph", reason="requiere las dependencias de la app (uv sync --extra app)")

from PySide6.QtWidgets import QApplication, QPushButton

from qube_app.ui.main_window import MainWindow
from qube_app.ui.panels import GAIN_GROUPS, AnalysisPanel, ControlPanel

FIRMWARE_INO = Path(__file__).resolve().parents[1] / "src" / "firmware" / "esp32_qube" / "esp32_qube.ino"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    """Preferencias en un archivo temporal: los tests no tocan el perfil del usuario."""
    from qube_app.settings import AppSettings

    return AppSettings(tmp_path / "settings.json")


@pytest.fixture
def window(app, settings):
    win = MainWindow(ip="0.0.0.0", fake=True, settings=settings)
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


# ── Comandos: que el botón mande lo que dice ──────────────────────────────────


def _button(parent, text: str) -> QPushButton:
    matches = [b for b in parent.findChildren(QPushButton) if b.text() == text]
    assert matches, f"no hay ningún botón «{text}»"
    return matches[0]


def test_apply_mode_sends_the_selected_mode(app):
    """El regresión que motivó todo esto.

    ``clicked`` emite ``checked=False`` y ``isinstance(False, int)`` es ``True`` en
    Python, así que el parámetro ``forced`` le ganaba al combo y **cualquier** modo
    seleccionado se enviaba como ``m=0``. El selector de modos no funcionaba en absoluto.
    """
    panel = ControlPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)

    panel.mode.setCurrentIndex(panel.mode.findData(4))  # LQR
    _button(panel, "Aplicar modo").click()

    assert sent == [{"m": 4}], "el botón debe mandar el modo del combo, no el `checked` del click"


def test_modes_that_move_to_stops_ask_before_sending(app, monkeypatch):
    """Homing y swing-up llevan el brazo contra los topes: no se disparan por accidente."""
    from qube_app.ui import panels

    panel = ControlPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)

    monkeypatch.setattr(panels.QMessageBox, "warning", lambda *_a, **_k: panels.QMessageBox.StandardButton.Cancel)
    panel.mode.setCurrentIndex(panel.mode.findData(5))  # swing-up
    _button(panel, "Aplicar modo").click()
    assert sent == [], "cancelar la confirmación no debe enviar nada"

    monkeypatch.setattr(panels.QMessageBox, "warning", lambda *_a, **_k: panels.QMessageBox.StandardButton.Yes)
    _button(panel, "Aplicar modo").click()
    assert sent == [{"m": 5}]


# ── Ganancias: los defaults son los del firmware, no inventados ───────────────


def _firmware_defaults() -> dict[str, float]:
    """Lee los valores iniciales del ``.ino``. Leerlos es lo que impide que diverjan."""
    source = FIRMWARE_INO.read_text(encoding="utf-8", errors="replace")
    out: dict[str, float] = {}
    for name in {spec.firmware_symbol for group in GAIN_GROUPS for spec in group.specs}:
        match = re.search(
            rf"^\s*(?:volatile\s+)?(?:float|int)\s+{re.escape(name)}\s*=\s*(-?[\d.]+)f?\s*;", source, re.M
        )
        assert match, f"no se encontró la definición de `{name}` en {FIRMWARE_INO.name}"
        out[name] = float(match.group(1))
    return out


def test_gain_defaults_match_the_firmware():
    """Un default equivocado no se ve: apretar «Enviar» reconfigura la placa en silencio.

    Pasó con los cinco campos de swing-up y PID (``kd`` 0.15 contra 0.45, ``sp`` 200
    contra 60 —que el firmware clampeaba a 100—, ``tn`` 175 contra 155).
    """
    firmware = _firmware_defaults()
    for group in GAIN_GROUPS:
        for spec in group.specs:
            assert spec.default == pytest.approx(firmware[spec.firmware_symbol]), (
                f"`{spec.param}` arranca en {spec.default} y el firmware en "
                f"{firmware[spec.firmware_symbol]} ({spec.firmware_symbol})"
            )


def test_gain_ranges_fit_inside_the_firmware_constrain():
    """Un rango más ancho que el ``constrain`` del firmware miente: el valor se clampea.

    El ``continue`` que este test tenía cuando el patrón no coincidía lo volvía un
    criterio que no podía fallar: bastaba reformatear el ``.ino`` —partir la línea, poner
    el ``constrain`` en otro orden— para que dejara de verificar nada y siguiera en verde.
    Ahora se distingue *el firmware no acota este parámetro*, que es legítimo, de *acota y
    el patrón no lo encontró*, que es el test podrido.
    """
    source = FIRMWARE_INO.read_text(encoding="utf-8", errors="replace")
    for group in GAIN_GROUPS:
        for spec in group.specs:
            match = re.search(
                rf'getParam\("{re.escape(spec.param)}"\)->value\(\)\.to\w+\(\)\s*,\s*(-?[\d.]+)f?\s*,\s*(-?[\d.]+)f?\s*\)',
                source,
            )
            if match is None:
                # ¿de verdad no lo acota, o el patrón quedó viejo? El bloque del parámetro
                # es la ventana entre su `hasParam` y el cierre de la sentencia siguiente.
                inicio = source.find(f'hasParam("{spec.param}")')
                assert inicio != -1, f"el firmware no acepta `{spec.param}`"
                bloque = source[inicio : inicio + 400]
                bloque = bloque[: bloque.find("hasParam(", 20) if bloque.find("hasParam(", 20) != -1 else None]
                assert "constrain(" not in bloque, (
                    f"`{spec.param}` sí se acota en el firmware pero el patrón de este test no "
                    f"lo reconoció — el test dejó de verificar sin avisar. Bloque:\n{bloque.strip()}"
                )
                continue
            low, high = float(match.group(1)), float(match.group(2))
            assert spec.minimum >= low and spec.maximum <= high, (
                f"`{spec.param}` acepta [{spec.minimum}, {spec.maximum}] pero el firmware clampea a [{low}, {high}]"
            )


def test_every_gain_param_exists_in_the_firmware():
    """`bt` viajaba en cada envío de swing-up y el firmware nunca lo leyó."""
    source = FIRMWARE_INO.read_text(encoding="utf-8", errors="replace")
    for group in GAIN_GROUPS:
        for spec in group.specs:
            assert f'hasParam("{spec.param}")' in source, f"el firmware no acepta `{spec.param}`"


def test_gains_panel_only_sends_what_changed(app):
    """Cambiar `kp` no debe reescribir `ki` y `kd` de paso."""
    from qube_app.ui.panels import GainsPanel

    panel = GainsPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)

    panel.fields["kp"].setValue(panel.fields["kp"].value() + 1.0)
    _button(panel, "Enviar").click()  # el primero es el del grupo PID
    assert sent == [{"kp": pytest.approx(panel.fields["kp"].value())}]

    sent.clear()
    _button(panel, "Enviar").click()
    assert sent == [], "sin cambios no hay nada que enviar"


# ── Robustez de los paneles ante un /state parcial ────────────────────────────


def test_handoff_tolerates_a_partial_state(app):
    """Un `/state` sin `swing_trans_alpha` no puede tumbar el ciclo de análisis.

    El formateo iba directo a `f"{valor:+.2f}"`, así que un `None` lanzaba **dentro de un
    slot de QTimer** y se perdía la actualización entera.
    """
    from qube_app.analysis import transition_summary

    panel = AnalysisPanel()
    panel.update_handoff(transition_summary({"swing_trans_reason": 2}))
    assert panel.fields["handoff"].text()  # no lanzó y dijo algo


def test_health_tolerates_a_state_without_loop_metrics(app):
    from qube_app.ui.panels import HealthPanel

    panel = HealthPanel()
    panel.update_health({"rtt_ms": None, "age_s": float("inf")})
    assert panel.fields["link"].text()


# ── Sesión ────────────────────────────────────────────────────────────────────


def test_cli_rate_and_poll_reach_the_widgets(app, settings):
    """`--hz 250 --poll 0.5` se guardaba en dos atributos que nadie leía."""
    win = MainWindow(ip="0.0.0.0", fake=True, poll_interval=0.5, hz=250.0, settings=settings)
    try:
        assert win.session.hz.currentData() == 250
        assert win.session.poll.value() == pytest.approx(0.5)
    finally:
        win.close()


def test_the_simulated_board_answers_state_and_obeys_commands(window):
    """Sin `/state` simulado, medio interfaz quedaba muerta en `--fake`.

    Salud del enlace, escalón, traspaso, potencia e indicador de modo salen todos del
    sondeo: con la placa simulada respondiendo sólo bloques del DAQ no había forma de
    trabajar la interfaz sin ir al banco.
    """
    deadline = time.monotonic() + 4.0
    while not window.poller.latest and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)

    state = window.poller.latest
    assert state, "el sondeo debe funcionar también contra la placa simulada"
    for key in ("mode", "position_deg", "pend_position_deg", "pwm", "p_mw", "ina_ok", "loop_dt_max_us"):
        assert key in state, f"a `/state` simulado le falta `{key}`"

    window.link.send({"m": 4})
    assert window.link.state()["mode"] == 4, "un comando debe verse en el estado simulado"


def test_emergency_stop_that_fails_says_so(window, monkeypatch):
    """«PARO enviado» se escribía aunque `stop_motor` hubiera fallado sus 15 intentos."""
    monkeypatch.setattr(window.link, "stop_motor", lambda _retries=15: False)
    window._emergency_stop()

    deadline = time.monotonic() + 4.0
    while window.poller.estop_ok is None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)

    assert window.poller.estop_ok is False
    window._on_slow()
    assert "SIN CONFIRMAR" in window.estop_status.text()


def test_emergency_stop_result_survives_the_next_status_message(window):
    """El paro cambia el modo a 0, y el aviso de cambio de modo pisaba su resultado.

    Los dos mensajes salían por la misma línea de estado y el del modo llegaba en la
    misma pasada de `_on_slow`: el resultado del paro duraba menos que un ciclo. Por eso
    tiene ranura propia.
    """
    window._emergency_stop()
    deadline = time.monotonic() + 4.0
    while window.poller.estop_ok is None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)

    assert window.poller.estop_ok is True
    window._on_slow()
    window._say("cualquier otro mensaje de rutina")
    assert "confirmado" in window.estop_status.text()
    assert window.link.state()["mode"] == 0, "el paro deja la planta en modo libre"


def test_mode_segments_split_on_every_change():
    """La cinta de modos sale de `store[\"mode\"]`, que nunca se dibujaba."""
    import numpy as np

    from qube_app.ui.plots import _mode_segments

    t = np.arange(6) * 0.002
    mode = np.array([5, 5, 5, 4, 4, 4])
    assert _mode_segments(t, mode) == [(0.0, 0.004, 5), (0.006, 0.010, 4)]
    assert _mode_segments(np.zeros(0), np.zeros(0)) == []


def test_mode_ribbon_restyles_only_when_the_structure_changes(app):
    """La ventana se corre en cada cuadro; los modos no.

    Comparando los tramos enteros —cuyos bordes exteriores son los de la ventana— la
    firma no coincidía nunca y se reaplicaba pincel y visibilidad sobre todo el pool
    cinco veces por segundo.
    """
    import numpy as np

    from qube_app.ui.plots import ModeRibbon

    ribbon = ModeRibbon()
    t = np.arange(100) * 0.002
    mode = np.full(100, 5)
    ribbon.update_modes(t, mode)
    signature = ribbon._signature

    # La ventana avanzó: mismos modos, otro tramo de tiempo.
    ribbon.update_modes(t + 3.0, mode)
    assert ribbon._signature == signature, "correr la ventana no cambia la estructura"

    mode[60:] = 4
    ribbon.update_modes(t + 3.0, mode)
    assert ribbon._signature != signature, "un cambio de modo sí tiene que reestilar"


def test_mode_ribbon_shares_the_left_margin_with_the_traces(app):
    """La cinta se lee en vertical contra las trazas: desalineada no sirve para nada.

    El margen izquierdo tiene que sumar lo mismo en las dos: en las trazas lo aporta el
    eje vertical, en la cinta el rótulo «modo».
    """
    from qube_app.ui.plots import AXIS_WIDTH, LivePlots

    plots = LivePlots()
    # Se comprueba el ancho *pedido*, no el de la geometría: sin mostrar la ventana, Qt
    # todavía no repartió el espacio y `width()` devuelve el valor automático.
    assert plots.theta.plot.getAxis("left").minimumWidth() == AXIS_WIDTH
    assert plots.ribbon.caption.minimumWidth() == AXIS_WIDTH
    assert plots.ribbon.plot.getAxis("left").fixedWidth == 0, "sumaría dos veces el margen"


def test_step_detector_resets_between_sessions(window):
    """El reloj del DAQ vuelve a cero en cada captura: un escalón viejo se mide de nuevo.

    Sin reinicio, `searchsorted` devolvía 0 y el panel informaba un escalón fantasma
    desde el inicio de la traza nueva, con el setpoint de la sesión anterior.
    """
    window.detector.update(0.0, 0.0)
    window.detector.update(20.0, 3.0)
    assert window.detector.t_step_s is not None

    window.session.btn_stream.setChecked(True)
    assert window.detector.t_step_s is None, "arrancar una captura debe olvidar el escalón anterior"
    window.session.btn_stream.setChecked(False)


# ── Compuertas de entrada a modo: el defecto que dejaba «Aplicar modo» inerte ─


def _gate_exclusions(flag: str, ok: str) -> set[int]:
    """Modos que el ``.ino`` deja pasar por una compuerta de ``setMode()``.

    Se lee del firmware por la misma razón que los defaults de las ganancias: si allá se
    agrega o se quita un modo de la compuerta y en la app no, la app vuelve a ofrecer un
    botón que la placa descarta y a no tener nada que decir sobre por qué.
    """
    source = FIRMWARE_INO.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"if \({flag} && !{ok} &&([^)]*)\) \{{", source)
    assert match, f"no se encontró la compuerta `{flag}` en {FIRMWARE_INO.name}"
    return {int(n) for n in re.findall(r"newMode != (\d+)", match.group(1))}


def test_gated_modes_match_the_firmware():
    """La lista de la app sale del ``setMode()`` del firmware, no de la memoria de nadie.

    Desde v1.60.0 el firmware rechaza 2/4/5/6/7 sin homing (`hr=1`) y 1/2/4/5/6/7 con el
    INA219 caído (`sf=1`). La app no lo sabía: apretar «Aplicar modo» mandaba el `GET`,
    `setMode()` retornaba sin hacer nada, el único aviso salía por Serial —que en este
    banco no se puede abrir sin reiniciar la placa— y la pantalla no decía nada.
    """
    from qube_app.link import MODES_REQUIRING_HOMING, MODES_REQUIRING_INA

    todos = set(range(8))
    assert set(MODES_REQUIRING_HOMING) == todos - _gate_exclusions("homingRequired", "homing_ok")
    assert set(MODES_REQUIRING_INA) == todos - _gate_exclusions("inaRequired", "inaOk")


def test_mode_reject_codes_match_the_firmware():
    """Los códigos de ``mode_reject`` son los del ``.ino``, con su significado."""
    from qube_app.link import MODE_REJECT_REASONS

    source = FIRMWARE_INO.read_text(encoding="utf-8", errors="replace")
    codigos = {int(n) for n in re.findall(r"mode_rejectReason = (\d+);", source)}
    assert codigos <= set(MODE_REJECT_REASONS), "el firmware rechaza con un código que la app no sabe explicar"
    for codigo in codigos - {0}:
        assert MODE_REJECT_REASONS[codigo], f"el código {codigo} no tiene explicación"


def test_a_gated_mode_warns_before_sending(app, monkeypatch):
    """Sin homing, el modo 4 avisa antes de salir: la placa lo va a descartar."""
    from qube_app.ui import panels

    panel = ControlPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)
    panel.update_state({"homing_ok": False, "homing_required": True, "ina_ok": True, "mode": 0})
    panel.mode.setCurrentIndex(panel.mode.findData(4))

    monkeypatch.setattr(panels.QMessageBox, "warning", lambda *_a, **_k: panels.QMessageBox.StandardButton.Cancel)
    _button(panel, "Aplicar modo").click()
    assert sent == [], "cancelar el aviso no debe enviar nada"

    # Se puede mandar igual: la autoridad sobre la compuerta es el firmware, y `/state`
    # con un segundo de antigüedad puede no reflejar un homing recién terminado.
    monkeypatch.setattr(panels.QMessageBox, "warning", lambda *_a, **_k: panels.QMessageBox.StandardButton.Yes)
    _button(panel, "Aplicar modo").click()
    assert sent == [{"m": 4}]


def test_an_open_gate_does_not_warn(app, monkeypatch):
    """Con homing válido no hay aviso: un bloqueo falso sería peor que el silencio."""
    from qube_app.ui import panels

    panel = ControlPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)
    panel.update_state({"homing_ok": True, "homing_required": True, "ina_ok": True, "mode": 0})
    panel.mode.setCurrentIndex(panel.mode.findData(4))

    def _no_deberia(*_a, **_k):
        raise AssertionError("no corresponde advertir con la compuerta abierta")

    monkeypatch.setattr(panels.QMessageBox, "warning", _no_deberia)
    _button(panel, "Aplicar modo").click()
    assert sent == [{"m": 4}]


def test_unknown_state_never_blocks(app, monkeypatch):
    """Sin lectura de ``/state`` no se advierte nada: no saber no es saber que no.

    Es el criterio que impide que esta corrección se convierta en el defecto simétrico —
    una app que estorba comandos legítimos porque el sondeo todavía no llegó.
    """
    from qube_app.ui import panels

    panel = ControlPanel()
    sent: list[dict] = []
    panel.command.connect(sent.append)

    def _no_deberia(*_a, **_k):
        raise AssertionError("no corresponde advertir sin datos")

    monkeypatch.setattr(panels.QMessageBox, "warning", _no_deberia)
    panel.mode.setCurrentIndex(panel.mode.findData(4))
    _button(panel, "Aplicar modo").click()
    assert sent == [{"m": 4}]
    assert panel.blocked_reason(4) == ""


def test_fake_board_enforces_the_same_gates():
    """La placa simulada rechaza lo mismo que la real.

    Un simulador más permisivo que el firmware no prueba la app, la aprueba: la placa
    simulada aceptaba cualquier `m=` y por eso el defecto no se veía en `--fake`.
    """
    from qube_app.fake import FakeBoard, FakeLink

    board = FakeBoard(homed=False)
    assert board.mode == 0, "una placa sin homing en modo 5 es un estado que el firmware no produce"
    assert board.set_mode(4) is False
    assert board.mode_reject == 2 and board.mode == 0

    link = FakeLink(board)
    respuesta = link.send({"m": 5})
    assert respuesta["ok"] is False and respuesta["mode"] == 0

    # El homing abre la compuerta, y `hr=0` también: las dos salidas del firmware.
    assert board.set_mode(3) is True
    assert board.set_mode(4) is True and board.mode_reject == 0

    otra = FakeBoard(homed=False)
    FakeLink(otra).send({"hr": 0})
    assert otra.set_mode(4) is True


def test_window_announces_a_rejected_mode(app, settings):
    """El aviso llega a la pantalla, que es lo único que el operador mira."""
    from qube_app.fake import FakeBoard

    win = MainWindow(ip="0.0.0.0", fake=True, settings=settings)
    try:
        win.board = FakeBoard(homed=False)
        win.link.board = win.board
        win.poller.link.board = win.board
        assert win.link.send({"m": 4})["ok"] is False

        win._on_slow()  # el primer sondeo puede no haber llegado todavía
        deadline = time.monotonic() + 4.0
        while "RECHAZADO" not in win.status.text() and time.monotonic() < deadline:
            QApplication.processEvents()
            win._on_slow()
            time.sleep(0.05)
        assert "RECHAZADO" in win.status.text(), f"la línea de estado dice «{win.status.text()}»"
        assert "homing" in win.status.text()
    finally:
        win.close()
