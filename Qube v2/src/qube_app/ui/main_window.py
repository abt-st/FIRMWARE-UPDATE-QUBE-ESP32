"""Ventana principal: ata la adquisición, el sondeo, el dibujo y el análisis.

Reparto de hilos, que es la decisión estructural de todo esto:

- ``DaqStream`` pide bloques y los deja en una cola;
- ``StatePoller`` sondea ``/state`` y ejecuta **todo el I/O**: comandos, el paro y también
  arrancar y detener la adquisición;
- la ventana **sólo dibuja**, en un temporizador propio a ~20 Hz que se lleva lo
  acumulado. Nunca un repintado por bloque: eso ataría la interfaz al ritmo de la radio.

El paro de emergencia no pasa por la cola de comandos: tiene su propia bandera, que el
hilo del sondeo atiende antes que nada, y su resultado vuelve a la pantalla. Un "paro
enviado" que en realidad falló es el peor mensaje que puede dar esta app.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qube_app.analysis import (
    StepDetector,
    derive_velocity,
    phase_portrait,
    transition_summary,
    upright_stats,
    wrap_deg,
)
from qube_app.buffers import TraceStore
from qube_app.link import MODE_NAMES, MODE_REJECT_REASONS, QubeLink
from qube_app.poller import StatePoller, Task
from qube_app.recorder import Recorder
from qube_app.settings import AppSettings
from qube_app.stream import CONTROL_HZ, DaqStream
from qube_app.ui.header import HeaderBar
from qube_app.ui.panels import (
    AnalysisPanel,
    ControlPanel,
    GainsPanel,
    HealthPanel,
    SessionPanel,
    StatusBanner,
)
from qube_app.ui.plots import LivePlots, PhasePlot
from qube_app.ui.theme import COLOR_BAD, COLOR_DIM, COLOR_GOOD, COLOR_WARN, ESTOP_STYLE, MONO, STYLESHEET

logger = logging.getLogger(__name__)

#: Capacidad de las trazas, independiente de la ventana visible: cambiar el zoom no
#: debe tirar historia que ya se pagó por radio. 60 s a 500 Hz son 30.000 muestras.
HISTORY_S = 60.0
#: Cada cuánto se mira la cola del DAQ. Es un techo, no un ritmo: si no llegó nada, el
#: ciclo devuelve de inmediato y no se repinta. Los bloques llegan a ~5 Hz.
DRAW_MS = 50
#: Análisis y salud. Más rápido que el sondeo de `/state` sería recalcular sobre el
#: mismo dato.
SLOW_MS = 300
#: Silencio del DAQ, con errores contándose, a partir del cual se reintenta solo.
RECONNECT_AFTER_S = 4.0
#: Techo de la espera al cerrar. Sin techo, ``stop_motor`` con la placa muda son quince
#: reintentos por dos segundos de timeout: media ventana congelada durante ~33 s.
CLOSE_TIMEOUT_S = 4.0


class MainWindow(QMainWindow):
    def __init__(
        self,
        ip: str,
        fake: bool = False,
        poll_interval: float = 0.2,
        hz: float = 500.0,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"QUBE · telemetría y análisis en vivo — {'SIMULADO' if fake else ip}")
        self.resize(1560, 960)
        self.fake = fake
        self.ip = ip
        # Inyectable para que los tests no escriban en el perfil del usuario.
        self.settings = settings if settings is not None else AppSettings()

        self.board = None
        if fake:
            from qube_app.fake import FakeBoard, FakeLink

            # La placa simulada implementa la misma superficie que `QubeLink`, así que la
            # ventana no lleva una sola rama `if self.fake` en la ruta de comandos: una
            # rama que sólo corre en simulación es una rama que nadie prueba.
            self.board = FakeBoard()
            self.link: QubeLink = FakeLink(self.board)  # type: ignore[assignment]
        else:
            self.link = QubeLink(ip)

        self.poller = StatePoller(self.link, period_s=0.5)
        self.stream: DaqStream | None = None
        self.recorder: Recorder | None = None
        self.store = TraceStore(window_s=HISTORY_S, rate_hz=CONTROL_HZ)
        self.power: deque[tuple[float, float]] = deque(maxlen=2000)
        self.detector = StepDetector()
        self._last_mode: int | None = None
        #: Último `mode_reject` informado. El firmware lo deja puesto hasta el siguiente
        #: `setMode()` exitoso, así que se avisa por flanco: repetir el mismo rechazo en
        #: cada pasada de `_on_slow` pisaría cualquier otro mensaje de la línea de estado.
        self._last_reject: int | None = None
        self._pending: list[tuple[Task, Callable[[Task], None]]] = []
        self._last_chunk_at = time.monotonic()
        self._reconnects = 0
        self._estop_pending = False
        self._closed = False

        self._build_ui(poll_interval=poll_interval, hz=hz)
        # También en simulado: `FakeLink` responde `/state` y sin el sondeo la mitad de la
        # interfaz (salud, escalón, traspaso, potencia, modo) queda muerta.
        self.poller.start()

        self.timer_draw = QTimer(self)
        self.timer_draw.timeout.connect(self._on_draw)
        self.timer_draw.start(DRAW_MS)
        self.timer_slow = QTimer(self)
        self.timer_slow.timeout.connect(self._on_slow)
        self.timer_slow.start(SLOW_MS)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_ui(self, poll_interval: float, hz: float) -> None:
        app = QApplication.instance()
        if app is not None:
            # En la aplicación y no en la ventana: los diálogos (QMessageBox, QFileDialog)
            # son ventanas de primer nivel y no heredarían el estilo de un hijo.
            app.setStyleSheet(STYLESHEET)  # type: ignore[attr-defined]

        self.header = HeaderBar()
        self.plots = LivePlots(window_s=float(self.settings.get("window_s", 20.0)))
        self.phase = PhasePlot()
        self.control = ControlPanel()
        self.gains = GainsPanel(self.settings)
        self.session = SessionPanel(
            window_s=float(self.settings.get("window_s", 20.0)),
            # Lo pedido por línea de comandos gana sobre lo guardado; ambos se ignoraban.
            rate_hz=hz,
            poll_s=poll_interval,
        )
        self.health = HealthPanel()
        self.analysis = AnalysisPanel()

        self.control.command.connect(self._send)
        self.gains.command.connect(self._send)
        self.session.start_stream.connect(self._start_stream)
        self.session.stop_stream.connect(self._stop_stream)
        self.session.toggle_record.connect(self._toggle_record)
        self.session.window_changed.connect(self._on_window_changed)
        self.session.read_only_changed.connect(self._set_read_only)

        self.estop = QPushButton("PARO DE EMERGENCIA  ·  Esc")
        self.estop.setMinimumHeight(52)
        self.estop.setMinimumWidth(230)
        self.estop.setStyleSheet(ESTOP_STYLE)
        self.estop.clicked.connect(self._emergency_stop)
        # Ranura propia y pegajosa. En la línea de estado compartida, el resultado del
        # paro duraba menos que un ciclo: el propio paro cambia el modo a 0, y el aviso
        # de cambio de modo lo pisaba en la misma pasada de `_on_slow`. El mensaje más
        # importante de la app no puede depender de quién escribió último.
        self.estop_status = QLabel("paro: sin pedir")
        self.estop_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.estop_status.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")
        # Sólo `Esc`. `Space` también estaba conectado y se robaba la barra espaciadora de
        # toda la ventana: navegar con el tabulador y confirmar disparaba un paro.
        QShortcut(QKeySequence("Esc"), self).activated.connect(self._emergency_stop)

        self.status = QLabel("—")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")

        estop_box = QWidget()
        estop_layout = QVBoxLayout(estop_box)
        estop_layout.setContentsMargins(0, 0, 0, 0)
        estop_layout.setSpacing(2)
        estop_layout.addWidget(self.estop)
        estop_layout.addWidget(self.estop_status)

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(6, 6, 6, 0)
        top_layout.setSpacing(8)
        top_layout.addWidget(self.header, stretch=1)
        top_layout.addWidget(estop_box)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(5)
        layout.addWidget(top)
        layout.addWidget(self._banner_row())
        layout.addWidget(self._body(), stretch=1)
        self.setCentralWidget(central)

    def _banner_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)
        layout.addWidget(StatusBanner(), stretch=1)
        layout.addWidget(self.status, stretch=2)
        return row

    def _body(self) -> QSplitter:
        """Gráficas a la izquierda, controles a la derecha, ambos redimensionables.

        Las pestañas reemplazan a la columna de siete paneles apilados dentro de un
        ``QScrollArea`` con la barra horizontal desactivada: lo que no entraba en 470 px
        no se recortaba, directamente **no se podía alcanzar**, y el retrato de fase
        quedaba tan abajo que había que buscarlo.
        """
        tabs = QTabWidget()
        tabs.addTab(self.session, "Sesión")
        tabs.addTab(self.control, "Control")
        tabs.addTab(_scrollable(self.gains), "Ganancias")
        tabs.addTab(_scrollable(_stack(self.health, self.analysis)), "Salud y análisis")

        phase_box = QWidget()
        phase_layout = QVBoxLayout(phase_box)
        phase_layout.setContentsMargins(0, 0, 0, 0)
        phase_layout.setSpacing(2)
        caption = QLabel("Retrato de fase  α – α̇")
        caption.setStyleSheet(f"color:{COLOR_DIM}; font-size:11px;")
        phase_layout.addWidget(caption)
        phase_layout.addWidget(self.phase, stretch=1)
        phase_box.setMinimumHeight(180)

        side = QSplitter(Qt.Orientation.Vertical)
        side.addWidget(tabs)
        side.addWidget(phase_box)
        # Los controles primero: el retrato de fase se mira, los controles se usan. El
        # divisor queda a mano para invertir el reparto cuando lo que se está haciendo es
        # mirar el retrato.
        side.setSizes([640, 280])
        side.setMinimumWidth(430)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self.plots)
        body.addWidget(side)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        body.setSizes([1050, 470])
        return body

    # ── Comandos ──────────────────────────────────────────────────────────────

    def _send(self, params: dict) -> None:
        if self.link.read_only:
            self._say(f"no enviado (sólo lectura): {params}", COLOR_WARN)
            return
        self.poller.submit(**params)
        self._say(f"→ /cmd {params}")

    def _emergency_stop(self) -> None:
        self._estop_pending = True
        self.poller.request_stop()
        self._set_estop_status("paro: enviado, esperando…", COLOR_WARN)
        self._say("PARO DE EMERGENCIA enviado (x=1)", COLOR_WARN)

    def _set_estop_status(self, text: str, color: str) -> None:
        self.estop_status.setText(text)
        self.estop_status.setStyleSheet(MONO + f"color:{color}; font-size:11px; font-weight:600;")

    def _set_read_only(self, on: bool) -> None:
        self.link.read_only = on
        for panel in (self.control, self.gains):
            panel.setEnabled(not on)
        self.settings.update(read_only=on)

    def _on_window_changed(self, seconds: float) -> None:
        self.plots.set_window(seconds)
        self.settings.update(window_s=seconds)

    def _say(self, message: str, color: str = COLOR_DIM) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(MONO + f"color:{color}; font-size:11px;")

    # ── Adquisición ───────────────────────────────────────────────────────────

    def _start_stream(self) -> None:
        if self.stream is not None:
            return
        decim = max(1, round(CONTROL_HZ / float(self.session.hz.currentData())))
        poll = float(self.session.poll.value())
        if self.fake:
            from qube_app.fake import FakeDaqClient

            stream = DaqStream(decim=decim, poll_interval=poll, client=FakeDaqClient(board=self.board))
        else:
            stream = DaqStream(self.ip, decim=decim, poll_interval=poll)

        self._reset_capture(rate_hz=CONTROL_HZ / decim)
        self.stream = stream
        self.session.set_streaming(True)
        self._say(f"iniciando adquisición a {CONTROL_HZ / decim:.0f} Hz (sondeo {poll:.2f} s)…")
        self.settings.update(rate_hz=int(self.session.hz.currentData()), poll_s=poll)
        # Arrancar es I/O: `rj=1` con reintentos más `/daq?start`. Hacerlo acá congelaba
        # la ventana varios segundos cada vez que la radio le robaba tiempo al lazo.
        self._await(self.poller.submit_task(lambda: self._begin(stream), "iniciar DAQ"), self._on_started)

    def _begin(self, stream: DaqStream) -> None:
        """Corre en el hilo del sondeo."""
        try:
            # Sin esto, `loop_dt_max_us` queda dominado por el peor caso del arranque
            # —el escaneo WiFi bloqueante— y no se mide el lazo sino el boot.
            self.link.reset_loop_metrics()
        except Exception as exc:
            logger.warning("no se pudo resetear rj=1: %s", exc)
        stream.start()

    def _on_started(self, task: Task) -> None:
        if task.error is not None:
            self.stream = None
            self.session.set_streaming(False)
            self._say(f"no se pudo iniciar la adquisición: {task.error}", COLOR_BAD)
            return
        self._last_chunk_at = time.monotonic()
        self._say("adquiriendo", COLOR_GOOD)

    def _stop_stream(self) -> None:
        stream, self.stream = self.stream, None
        if stream is None:
            return
        self.session.set_streaming(False)
        self._say("deteniendo la adquisición…")
        self._await(self.poller.submit_task(lambda: self._end(stream), "detener DAQ"), self._on_stopped)

    @staticmethod
    def _end(stream: DaqStream) -> list:
        """Corre en el hilo del sondeo. Devuelve lo que quedaba en la cola."""
        stream.stop()
        return stream.drain()  # la cola del firmware es dato ya medido

    def _on_stopped(self, task: Task) -> None:
        for chunk in task.result or []:
            self._consume(chunk)
        self._redraw()
        if task.error is not None:
            self._say(f"adquisición detenida con error: {task.error}", COLOR_WARN)
            return
        self._say(f"adquisición detenida · {len(self.store)} muestras en memoria")

    def _reset_capture(self, rate_hz: float) -> None:
        """Deja la ventana lista para una captura nueva.

        El ``StepDetector`` también: el reloj del DAQ vuelve a cero en cada sesión, así
        que un escalón de la sesión anterior se volvía a medir sobre la traza nueva y el
        panel informaba un escalón fantasma con el setpoint viejo.
        """
        self.store = TraceStore(window_s=HISTORY_S, rate_hz=rate_hz)
        self.detector = StepDetector()
        self.power.clear()
        self.plots.clear()
        self.phase.clear()
        self._last_chunk_at = time.monotonic()

    def _toggle_record(self, on: bool) -> None:
        if not on:
            if self.recorder is not None:
                rows, path = self.recorder.rows, self.recorder.close()
                self.recorder = None
                self._say(f"grabado: {rows} filas en {path}", COLOR_GOOD)
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        folder = self.settings.get("record_dir") or str(Path.cwd())
        suggested = str(Path(folder) / f"capture_{stamp}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Grabar captura", suggested, "CSV (*.csv)")
        if not path:
            self.session.btn_record.setChecked(False)
            return
        self.recorder = Recorder(path)
        self.recorder.open()
        self.settings.update(record_dir=str(Path(path).parent))
        self._say(f"grabando en {path}", COLOR_GOOD)

    def _consume(self, chunk) -> None:
        self.store.extend(chunk)
        self._last_chunk_at = time.monotonic()
        if self.recorder is not None:
            self.recorder.write(chunk)

    # ── Tareas de I/O ─────────────────────────────────────────────────────────

    def _await(self, task: Task, callback: Callable[[Task], None]) -> None:
        """Registra una tarea para atenderla desde el temporizador, sin bloquear."""
        self._pending.append((task, callback))

    def _drain_pending(self) -> None:
        if not self._pending:
            return
        still: list[tuple[Task, Callable[[Task], None]]] = []
        for task, callback in self._pending:
            if task.done.is_set():
                callback(task)
            else:
                still.append((task, callback))
        self._pending = still

    # ── Dibujo y análisis ─────────────────────────────────────────────────────

    def _visible_slice(self) -> slice:
        t = self.store["t_s"]
        if not len(t):
            return slice(0, 0)
        start = float(t[-1]) - self.plots.window_s
        return slice(int(np.searchsorted(t, start)), len(t))

    def _on_draw(self) -> None:
        """Repinta **sólo si llegó algo**. Los bloques llegan a ~5 Hz, no a 20."""
        self._drain_pending()
        if self.stream is None:
            return
        chunks = self.stream.drain()
        if not chunks:
            return
        for chunk in chunks:
            self._consume(chunk)
        self._redraw()

    def _redraw(self) -> None:
        window = self._visible_slice()
        t = self.store["t_s"][window]
        if not len(t):
            return
        # α se envuelve sobre la ventana visible, no sobre toda la historia guardada.
        self.plots.update_traces(
            t,
            self.store["th_deg"][window],
            wrap_deg(self.store["al_deg"][window]),
            self.store["pwm"][window],
        )
        self.plots.update_modes(t, self.store["mode"][window])

    def _on_slow(self) -> None:
        stats = self.stream.stats if self.stream is not None else None
        if stats is not None:
            self.health.update_stream(stats)
        self.header.update_stream(stats)
        self._check_estop()
        # Antes que el `return` de abajo: si `/state` nunca respondió, el DAQ mudo era
        # justamente el caso en el que hacía falta reintentar.
        self._watch_stream(stats)

        state = self.poller.latest
        health = self.poller.health
        self.health.update_health(health)
        self.header.update_link(health.get("rtt_ms"), health.get("age_s", float("inf")))

        window = self._visible_slice()
        t = self.store["t_s"][window]

        # Retrato de fase: α̇ se deriva de la señal SIN envolver y el corte con NaN
        # impide que el salto de ±180° se dibuje como una trayectoria que no existe.
        if len(t) > 3:
            alpha_raw = self.store["al_deg"][window]
            alpha_dot = derive_velocity(t, alpha_raw)
            self.phase.update_portrait(*phase_portrait(alpha_raw, alpha_dot))
            self.analysis.update_upright(upright_stats(t, alpha_raw))

        if not state:
            return
        self.header.update_state(state)
        self._update_power(state, t)

        self.control.update_state(state)
        self.analysis.update_attempt(state)

        mode = state.get("mode")
        if mode != self._last_mode:
            self._last_mode = mode
            self._say(f"modo {MODE_NAMES.get(mode, str(mode)) if mode is not None else '—'}")
        # DESPUÉS del aviso de modo, no antes. Un `?m=` rechazado deja el modo donde
        # estaba, así que en la misma pasada salen los dos mensajes y el de modo es el
        # que sobra: es cierto y a la vez irrelevante. Escribir el rechazo primero lo
        # dejaba pisado — el mismo defecto que le costó al paro de emergencia tener que
        # mudarse a una ranura propia.
        self._check_mode_reject(state)
        if len(t):
            self.detector.update(state.get("setpoint_deg"), float(t[-1]))
        self.analysis.update_step(self.detector.measure(self.store["t_s"], self.store["th_deg"]))

        handoff = transition_summary(state)
        self.analysis.update_handoff(handoff)
        self.phase.mark_handoff(
            handoff.get("alpha_deg") if handoff else None,
            handoff.get("vel_dps") if handoff else None,
        )
        self.plots.mark_handoff(_handoff_time(handoff, t))

    def _check_mode_reject(self, state: dict) -> None:
        """Informa por qué el último ``?m=`` no tuvo efecto.

        Desde v1.60.0 el firmware **rechaza** los modos 2/4/5/6/7 sin homing (``hr=1``)
        o con el INA219 caído (``sf=1``): ``setMode()`` retorna sin hacer nada. El único
        aviso salía por Serial —que en este banco no se puede abrir sin reiniciar la
        placa— así que desde la app apretar «Aplicar modo» no hacía absolutamente nada y
        no había nada en pantalla que lo dijera. ``/state`` publica ``mode_reject`` desde
        esa misma versión, precisamente para esto.
        """
        reject = state.get("mode_reject")
        if reject is None:  # firmware anterior a v1.60.0: no hay nada que informar
            return
        reject = int(reject)
        if reject == self._last_reject:
            return
        self._last_reject = reject
        if reject:
            detail = MODE_REJECT_REASONS.get(reject, f"código {reject}")
            self._say(f"MODO RECHAZADO POR LA PLACA — {detail}", COLOR_BAD)

    def _update_power(self, state: dict, t: np.ndarray) -> None:
        p_mw = state.get("p_mw")
        if p_mw is not None and len(t):
            # Alineada al último t_s recibido: incertidumbre del orden del sondeo.
            self.power.append((float(t[-1]), float(p_mw)))
        # La potencia se dibuja acá y no en `_on_draw`: llega a 2 Hz desde `/state`, así
        # que redibujarla al ritmo de los bloques del DAQ sería trabajo sin dato nuevo.
        if self.power and len(t):
            pt = np.fromiter((p[0] for p in self.power), dtype=np.float64, count=len(self.power))
            pv = np.fromiter((p[1] for p in self.power), dtype=np.float64, count=len(self.power))
            visible = pt >= t[0]
            self.plots.update_power(pt[visible], pv[visible])

    def _check_estop(self) -> None:
        """El resultado del paro vuelve a la pantalla. Sin esto, «enviado» no significa nada."""
        if not self._estop_pending:
            return
        ok = self.poller.estop_ok
        if ok is None:
            return
        self._estop_pending = False
        stamp = datetime.now().strftime("%H:%M:%S")
        if ok:
            self._set_estop_status(f"paro: confirmado {stamp}", COLOR_GOOD)
        else:
            self._set_estop_status("PARO SIN CONFIRMAR — CORTAR ALIMENTACIÓN", COLOR_BAD)
            self._say("PARO SIN CONFIRMAR — CORTAR LA ALIMENTACIÓN", COLOR_BAD)

    def _watch_stream(self, stats) -> None:
        """Reintenta la adquisición si el DAQ enmudeció con errores. Nunca en silencio.

        Grabando **no** se reintenta: reconectar reinicia el reloj del DAQ en cero y la
        captura quedaría con una costura invisible en el medio del CSV. Ahí la decisión
        es del operador, no de la app.
        """
        if stats is None or self.stream is None or self._pending:
            return
        if time.monotonic() - self._last_chunk_at < RECONNECT_AFTER_S or not stats.errors:
            return
        if self.recorder is not None:
            self._say(
                f"DAQ mudo hace {time.monotonic() - self._last_chunk_at:.0f} s con {stats.errors} errores. "
                "No se reintenta durante una grabación: detener y volver a empezar.",
                COLOR_BAD,
            )
            return
        self._reconnects += 1
        self._say(
            f"reconexión #{self._reconnects}: el DAQ enmudeció ({stats.errors} errores). "
            "Se descarta la ventana anterior — la traza NO es continua.",
            COLOR_WARN,
        )
        self._stop_stream()
        QTimer.singleShot(600, self._start_stream)

    # ── Cierre ────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 — API de Qt
        """Salir no deja el motor energizado ni la adquisición corriendo.

        Todo el I/O va al hilo del sondeo y la espera tiene techo: con la placa muda,
        ``stop_motor`` son quince reintentos por dos segundos de timeout y la ventana
        quedaba congelada hasta medio minuto. Si vence el plazo se cierra igual y queda
        anotado en el log: dejar la ventana colgada no protege a nadie.
        """
        if self._closed:  # cerrar dos veces no vuelve a esperar el paro
            event.accept()
            return
        self._closed = True
        self.timer_draw.stop()
        self.timer_slow.stop()
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None

        stream, self.stream = self.stream, None
        tasks: list[Task] = []
        if stream is not None:
            tasks.append(self.poller.submit_task(stream.stop, "detener DAQ al cerrar"))
        self.poller.request_stop()
        self._estop_pending = True

        self.setEnabled(False)
        self._wait_for_shutdown(tasks)
        self.poller.stop(timeout=1.0)
        self.link.close()
        event.accept()

    def _wait_for_shutdown(self, tasks: list[Task]) -> None:
        # Con el hilo del sondeo ya muerto nadie va a atender el paro: esperar su
        # confirmación sería agotar el plazo entero para nada.
        expect_estop = self.poller.running
        deadline = time.monotonic() + CLOSE_TIMEOUT_S
        loop = QEventLoop()
        timer = QTimer(self)
        timer.setInterval(50)

        def check() -> None:
            settled = all(task.done.is_set() for task in tasks) and (
                not expect_estop or self.poller.estop_ok is not None
            )
            if settled or time.monotonic() >= deadline:
                if not settled:
                    logger.warning("cierre por tiempo: el paro o la detención del DAQ no confirmaron")
                timer.stop()
                loop.quit()

        timer.timeout.connect(check)
        timer.start()
        loop.exec()


# ── Utilidades de armado ──────────────────────────────────────────────────────


def _scrollable(widget: QWidget) -> QScrollArea:
    """Envuelve un panel alto. **Con** barra horizontal: desactivarla no encoge nada.

    La versión anterior la ponía en ``ScrollBarAlwaysOff``, así que los botones que no
    entraban en el ancho de la columna simplemente no existían para el usuario.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


def _stack(*widgets: QWidget) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return box


def _handoff_time(handoff: dict | None, t: np.ndarray) -> float | None:
    """Instante del traspaso en el reloj del DAQ, desde ``swing_trans_ms_ago``.

    Lleva la misma incertidumbre que la potencia y por la misma razón: el dato llega por
    el sondeo de ``/state``, no en la muestra binaria. Sirve para ubicar el traspaso en la
    traza; el valor exacto del ángulo y de la velocidad sale del latch del firmware.
    """
    if not handoff or not len(t):
        return None
    ms_ago = handoff.get("ms_ago")
    if not isinstance(ms_ago, (int, float)):
        return None
    t_mark = float(t[-1]) - float(ms_ago) / 1000.0
    return t_mark if t_mark >= float(t[0]) else None


def launch(ip: str, fake: bool = False, poll_interval: float = 0.2, hz: float = 500.0) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(ip=ip, fake=fake, poll_interval=poll_interval, hz=hz)
    window.show()
    return app.exec()


def demo_seconds(seconds: float) -> int:
    """Abre la ventana simulada, adquiere y se cierra sola. Verificación sin banco."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(ip="0.0.0.0", fake=True)
    window.show()
    window.session.btn_stream.setChecked(True)
    QTimer.singleShot(int(seconds * 1000), window.close)
    started = time.perf_counter()
    code = app.exec()
    print(f"ventana cerrada tras {time.perf_counter() - started:.1f} s · {len(window.store)} muestras dibujadas")
    return code
