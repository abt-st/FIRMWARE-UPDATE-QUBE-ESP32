"""Ventana principal: ata la adquisición, el sondeo, el dibujo y el análisis.

Reparto de hilos, que es la decisión estructural de todo esto:

- ``DaqStream`` pide bloques y los deja en una cola;
- ``StatePoller`` sondea ``/state`` y ejecuta los comandos con sus reintentos;
- la ventana **sólo dibuja**, en un temporizador propio a ~30 Hz que se lleva lo
  acumulado. Nunca un repintado por bloque: eso ataría la interfaz al ritmo de la radio.

El paro de emergencia no pasa por la cola de comandos: tiene su propia bandera, que el
hilo del sondeo atiende antes que nada.
"""

from __future__ import annotations

import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
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
from qube_app.link import MODE_NAMES, QubeLink
from qube_app.poller import StatePoller
from qube_app.recorder import Recorder
from qube_app.stream import CONTROL_HZ, DaqStream
from qube_app.ui.panels import (
    AnalysisPanel,
    ControlPanel,
    GainsPanel,
    HealthPanel,
    SessionPanel,
    StatusBanner,
)
from qube_app.ui.plots import LivePlots, PhasePlot

#: Capacidad de las trazas, independiente de la ventana visible: cambiar el zoom no
#: debe tirar historia que ya se pagó por radio. 60 s a 500 Hz son 30.000 muestras.
HISTORY_S = 60.0
#: Cada cuánto se mira la cola del DAQ. Es un techo, no un ritmo: si no llegó nada, el
#: ciclo devuelve de inmediato y no se repinta. Los bloques llegan a ~5 Hz.
DRAW_MS = 50
#: Análisis y salud. Más rápido que el sondeo de `/state` sería recalcular sobre el
#: mismo dato.
SLOW_MS = 300


class MainWindow(QMainWindow):
    def __init__(self, ip: str, fake: bool = False, poll_interval: float = 0.2, hz: float = 500.0) -> None:
        super().__init__()
        self.setWindowTitle(f"QUBE · telemetría y análisis en vivo — {'SIMULADO' if fake else ip}")
        self.resize(1500, 940)
        self.fake = fake
        self.ip = ip
        self.default_poll = poll_interval
        self.default_hz = hz

        self.link = QubeLink(ip)
        self.poller = StatePoller(self.link, period_s=0.5)
        self.stream: DaqStream | None = None
        self.recorder: Recorder | None = None
        self.store = TraceStore(window_s=HISTORY_S, rate_hz=CONTROL_HZ)
        self.power: deque[tuple[float, float]] = deque(maxlen=2000)
        self.detector = StepDetector()
        self._last_mode: int | None = None

        self._build_ui()
        if not fake:
            self.poller.start()

        self.timer_draw = QTimer(self)
        self.timer_draw.timeout.connect(self._on_draw)
        self.timer_draw.start(DRAW_MS)
        self.timer_slow = QTimer(self)
        self.timer_slow.timeout.connect(self._on_slow)
        self.timer_slow.start(SLOW_MS)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.plots = LivePlots(window_s=20.0)
        self.phase = PhasePlot()
        self.control = ControlPanel()
        self.gains = GainsPanel()
        self.session = SessionPanel(window_s=20.0)
        self.health = HealthPanel()
        self.analysis = AnalysisPanel()

        self.control.command.connect(self._send)
        self.gains.command.connect(self._send)
        self.session.start_stream.connect(self._start_stream)
        self.session.stop_stream.connect(self._stop_stream)
        self.session.toggle_record.connect(self._toggle_record)
        self.session.window_changed.connect(self.plots.set_window)
        self.session.read_only_changed.connect(self._set_read_only)

        estop = QPushButton("PARO DE EMERGENCIA  (Esc)")
        estop.setMinimumHeight(52)
        estop.setStyleSheet(
            "background:#a01530; color:white; font-weight:800; font-size:15px;border:none; border-radius:6px;"
        )
        estop.clicked.connect(self._emergency_stop)
        # Dos atajos: el que uno busca por instinto y el que ya tiene el dedo encima.
        for key in ("Esc", "Space"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(self._emergency_stop)

        self.status = QLabel("—")
        self.status.setStyleSheet("color:#c8cfdb; font-family:Consolas,monospace;")

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(6, 6, 6, 6)
        side_layout.addWidget(estop)
        side_layout.addWidget(self.status)
        side_layout.addWidget(StatusBanner())
        for panel in (self.session, self.control, self.health, self.analysis, self.gains):
            side_layout.addWidget(panel)
        side_layout.addWidget(QLabel("Retrato de fase α–α̇"))
        side_layout.addWidget(self.phase, stretch=1)

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(470)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plots, stretch=3)
        layout.addWidget(scroll, stretch=1)
        self.setCentralWidget(central)
        self.setStyleSheet(
            "QWidget{background:#0d1017; color:#c8cfdb;} QGroupBox{border:1px solid #232833;"
            "border-radius:5px; margin-top:9px; padding:8px;}"
            "QGroupBox::title{subcontrol-origin:margin; left:8px; color:#8fa0bd;}"
        )

    # ── Comandos ──────────────────────────────────────────────────────────────

    def _send(self, params: dict) -> None:
        if self.fake:
            self.status.setText(f"(simulado) {params}")
            return
        if self.link.read_only:
            self.status.setText(f"no enviado (sólo lectura): {params}")
            return
        self.poller.submit(**params)
        self.status.setText(f"→ /cmd {params}")

    def _emergency_stop(self) -> None:
        if self.fake:
            self.status.setText("(simulado) PARO")
            return
        self.poller.request_stop()
        self.status.setText("PARO DE EMERGENCIA enviado (x=1)")

    def _set_read_only(self, on: bool) -> None:
        self.link.read_only = on
        for panel in (self.control, self.gains):
            panel.setEnabled(not on)

    # ── Adquisición ───────────────────────────────────────────────────────────

    def _start_stream(self) -> None:
        if self.stream is not None:
            return
        decim = max(1, round(CONTROL_HZ / float(self.session.hz.currentData())))
        poll = float(self.session.poll.value())
        if self.fake:
            from qube_app.fake import FakeDaqClient

            self.stream = DaqStream(decim=decim, poll_interval=poll, client=FakeDaqClient())
        else:
            # Sin esto, `loop_dt_max_us` queda dominado por el peor caso del arranque
            # —el escaneo WiFi bloqueante— y no se mide el lazo sino el boot.
            try:
                self.link.reset_loop_metrics()
            except Exception as exc:
                self.status.setText(f"aviso: no se pudo resetear rj=1 ({exc})")
            self.stream = DaqStream(self.ip, decim=decim, poll_interval=poll)

        self.store = TraceStore(window_s=HISTORY_S, rate_hz=CONTROL_HZ / decim)
        self.power.clear()
        self.plots.clear()
        self.phase.clear()
        try:
            self.stream.start()
        except Exception as exc:
            self.stream = None
            self.session.btn_stream.setChecked(False)
            self.status.setText(f"no se pudo iniciar la adquisición: {exc}")
            return
        self.session.set_streaming(True)
        self.status.setText(f"adquiriendo a {CONTROL_HZ / decim:.0f} Hz (sondeo {poll:.2f} s)")

    def _stop_stream(self) -> None:
        if self.stream is None:
            return
        self.stream.stop()
        for chunk in self.stream.drain():  # la cola del firmware es dato ya medido
            self._consume(chunk)
        self.stream = None
        self.session.set_streaming(False)
        self.status.setText("adquisición detenida")

    def _toggle_record(self, on: bool) -> None:
        if not on:
            if self.recorder is not None:
                path, rows = self.recorder.close(), self.recorder.rows
                self.recorder = None
                self.status.setText(f"grabado {rows} filas en {path}")
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        suggested = str(Path.cwd() / f"capture_{stamp}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Grabar captura", suggested, "CSV (*.csv)")
        if not path:
            self.session.btn_record.setChecked(False)
            return
        self.recorder = Recorder(path)
        self.recorder.open()
        self.status.setText(f"grabando en {path}")

    def _consume(self, chunk) -> None:
        self.store.extend(chunk)
        if self.recorder is not None:
            self.recorder.write(chunk)

    # ── Dibujo y análisis ─────────────────────────────────────────────────────

    def _visible_slice(self) -> slice:
        t = self.store["t_s"]
        if not len(t):
            return slice(0, 0)
        start = float(t[-1]) - self.plots.window_s
        return slice(int(np.searchsorted(t, start)), len(t))

    def _on_draw(self) -> None:
        """Repinta **sólo si llegó algo**. Los bloques llegan a ~5 Hz, no a 30."""
        if self.stream is None:
            return
        chunks = self.stream.drain()
        if not chunks:
            return
        for chunk in chunks:
            self._consume(chunk)
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

    def _on_slow(self) -> None:
        if self.stream is not None:
            self.health.update_stream(self.stream.stats)
        state = self.poller.latest
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
        self.health.update_health(self.poller.health)

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

        mode = state.get("mode")
        if mode != self._last_mode:
            self._last_mode = mode
            self.status.setText(f"modo {MODE_NAMES.get(mode, str(mode)) if mode is not None else '—'}")
        if len(t):
            self.detector.update(state.get("setpoint_deg"), float(t[-1]))
        self.analysis.update_step(self.detector.measure(self.store["t_s"], self.store["th_deg"]))

        handoff = transition_summary(state)
        self.analysis.update_handoff(handoff)
        self.phase.mark_handoff(
            handoff.get("alpha_deg") if handoff else None,
            handoff.get("vel_dps") if handoff else None,
        )

    # ── Cierre ────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 — API de Qt
        """Salir no deja el motor energizado ni la adquisición corriendo."""
        self.timer_draw.stop()
        self.timer_slow.stop()
        if self.stream is not None:
            self.stream.stop()
        if self.recorder is not None:
            self.recorder.close()
        if not self.fake:
            self.link.stop_motor()
            self.poller.stop()
            self.link.close()
        event.accept()


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
    stats = window.store
    print(f"ventana cerrada tras {time.perf_counter() - started:.1f} s · {len(stats)} muestras dibujadas")
    return code
