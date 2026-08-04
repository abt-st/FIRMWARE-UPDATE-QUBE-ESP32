"""Paneles de control, sesión, salud y análisis.

Ningún panel habla con la placa: todos emiten ``command`` con los parámetros de ``/cmd``
y la ventana principal los encola en el hilo del sondeo. Así un comando con reintentos
—que puede tardar segundos cuando la radio le roba tiempo al lazo— nunca congela la
interfaz.

Los modos 3 (homing) y 5 (swing-up) llevan al brazo contra los topes mecánicos, así que
piden confirmación explícita. No es formalismo: el homing golpea ambos extremos y el
swing-up bombea con el péndulo suelto.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from qube_app.analysis import StepMetrics, UprightStats
from qube_app.link import MODE_NAMES, MODES_THAT_MOVE_TO_STOPS
from qube_app.stream import StreamStats

MONO = "font-family:Consolas,monospace;"


def _spin(minimum: float, maximum: float, value: float, step: float = 0.1, decimals: int = 3) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class ControlPanel(QGroupBox):
    """Modo, setpoint, PWM manual, ceros y homing."""

    command = Signal(dict)

    def __init__(self) -> None:
        super().__init__("Control")
        self.mode = QComboBox()
        for code, name in MODE_NAMES.items():
            self.mode.addItem(name, code)
        apply_mode = QPushButton("Aplicar modo")
        apply_mode.clicked.connect(self._apply_mode)

        self.setpoint = _spin(-95.0, 95.0, 0.0, 1.0, 2)
        set_sp = QPushButton("Set θ (m2)")
        set_sp.clicked.connect(lambda: self.command.emit({"m": 2, "s": self.setpoint.value()}))

        self.pwm = QSpinBox()
        self.pwm.setRange(-255, 255)
        set_pwm = QPushButton("Set PWM (m1)")
        set_pwm.clicked.connect(lambda: self.command.emit({"m": 1, "p": self.pwm.value()}))

        zero_theta = QPushButton("Cero θ")
        zero_theta.clicked.connect(lambda: self.command.emit({"z": 1}))
        zero_alpha = QPushButton("Cero α")
        zero_alpha.clicked.connect(lambda: self.command.emit({"zp": 1}))
        homing = QPushButton("Homing (m3)")
        homing.clicked.connect(lambda: self._apply_mode(3))

        form = QFormLayout(self)
        form.addRow(self.mode, apply_mode)
        form.addRow(self.setpoint, set_sp)
        form.addRow(self.pwm, set_pwm)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        for button in (zero_theta, zero_alpha, homing):
            row_layout.addWidget(button)
        form.addRow(row)

    def _apply_mode(self, forced: int | None = None) -> None:
        mode = forced if isinstance(forced, int) else int(self.mode.currentData())
        if mode in MODES_THAT_MOVE_TO_STOPS and not self._confirm(mode):
            return
        self.command.emit({"m": mode})

    def _confirm(self, mode: int) -> bool:
        detail = (
            "El homing lleva el brazo contra AMBOS topes mecánicos y redefine θ=0."
            if mode == 3
            else "El swing-up bombea el brazo con el péndulo suelto y puede llegar al tope."
        )
        answer = QMessageBox.warning(
            self,
            f"Confirmar modo {mode}",
            f"{detail}\n\n¿El banco está despejado y el péndulo libre?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes


class GainsPanel(QGroupBox):
    """PID, LQR y swing-up. Los defaults son los del firmware, no inventados."""

    command = Signal(dict)

    def __init__(self) -> None:
        super().__init__("Ganancias")
        self.kp, self.ki, self.kd = _spin(0, 50, 3.0), _spin(0, 50, 0.5), _spin(0, 50, 0.15)
        self.k1, self.k2 = _spin(0, 200, 2.0), _spin(0, 200, 22.0)
        self.k3, self.k4 = _spin(0, 200, 1.5), _spin(0, 200, 9.0)
        self.ke, self.bt = _spin(0, 5, 0.75), _spin(0, 90, 20.0, 1.0, 1)
        self.sp_max, self.tn = _spin(0, 255, 200.0, 5.0, 0), _spin(0, 180, 175.0, 1.0, 1)

        grid = QGridLayout(self)
        self._add_group(grid, 0, "PID servo", [("kp", self.kp), ("ki", self.ki), ("kd", self.kd)])
        self._add_group(
            grid,
            1,
            "LQR",
            [("lqr1", self.k1), ("lqr2", self.k2), ("lqr3", self.k3), ("lqr4", self.k4)],
        )
        self._add_group(
            grid,
            2,
            "Swing-up",
            [("ke", self.ke), ("bt", self.bt), ("sp", self.sp_max), ("tn", self.tn)],
        )

    def _add_group(self, grid: QGridLayout, row: int, title: str, fields: list[tuple[str, QDoubleSpinBox]]) -> None:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for name, widget in fields:
            form.addRow(name, widget)
        send = QPushButton("Enviar")
        send.clicked.connect(lambda: self.command.emit({name: w.value() for name, w in fields}))
        form.addRow(send)
        grid.addWidget(box, row // 2, row % 2)


class SessionPanel(QGroupBox):
    """Adquisición, ventana de dibujo, grabación y modo sólo lectura."""

    start_stream = Signal()
    stop_stream = Signal()
    toggle_record = Signal(bool)
    window_changed = Signal(float)
    read_only_changed = Signal(bool)

    def __init__(self, window_s: float = 20.0) -> None:
        super().__init__("Sesión")
        self.hz = QComboBox()
        for hz in (500, 250, 100, 50):
            self.hz.addItem(f"{hz} Hz", hz)
        self.poll = _spin(0.05, 1.0, 0.2, 0.05, 2)

        self.btn_stream = QPushButton("Adquirir")
        self.btn_stream.setCheckable(True)
        self.btn_stream.toggled.connect(lambda on: (self.start_stream if on else self.stop_stream).emit())

        self.btn_record = QPushButton("Grabar CSV")
        self.btn_record.setCheckable(True)
        self.btn_record.toggled.connect(self.toggle_record.emit)

        # `window` a secas pisaría QWidget.window(): el atributo lleva sufijo a propósito.
        # El techo es el de `HISTORY_S`: pedir más ventana que historia guardada no
        # mostraría nada extra.
        self.window_box = _spin(5.0, 60.0, window_s, 5.0, 0)
        self.window_box.valueChanged.connect(self.window_changed.emit)

        self.read_only = QCheckBox("Sólo lectura (no enviar comandos)")
        self.read_only.setToolTip(
            "El contrato del proyecto es «último que escribe gana». Con un entrenamiento "
            "RL corriendo, la app debe quedarse callada."
        )
        self.read_only.toggled.connect(self.read_only_changed.emit)

        form = QFormLayout(self)
        form.addRow("Tasa", self.hz)
        form.addRow("Sondeo [s]", self.poll)
        form.addRow("Ventana [s]", self.window_box)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.btn_stream)
        row_layout.addWidget(self.btn_record)
        form.addRow(row)
        form.addRow(self.read_only)

    def set_streaming(self, on: bool) -> None:
        self.hz.setEnabled(not on)
        self.poll.setEnabled(not on)


class HealthPanel(QGroupBox):
    """Salud del enlace y del lazo. La app declara la calidad del canal por el que habla."""

    def __init__(self) -> None:
        super().__init__("Salud")
        self.fields: dict[str, QLabel] = {}
        form = QFormLayout(self)
        for key, label in (
            ("rate", "tasa efectiva"),
            ("dropped", "muestras perdidas"),
            ("gaps", "huecos / dt máx"),
            ("link", "RTT /state · edad"),
            ("loop", "loop_dt_max_us"),
            ("overruns", "loop_overruns"),
            ("ina", "INA219"),
        ):
            value = QLabel("—")
            value.setStyleSheet(MONO)
            self.fields[key] = value
            form.addRow(label, value)

    def update_stream(self, stats: StreamStats) -> None:
        self.fields["rate"].setText(f"{stats.rate_hz:7.1f} Hz  ({stats.samples} muestras)")
        dropped = self.fields["dropped"]
        dropped.setText(f"{stats.dropped}")
        # Rojo y sin eufemismos: una captura con pérdidas no es una captura completa.
        dropped.setStyleSheet(MONO + ("color:#ff5c7a; font-weight:700;" if stats.dropped else ""))
        self.fields["gaps"].setText(f"{stats.gaps}  ·  {stats.dt_max_ms:.1f} ms")

    def update_health(self, health: dict) -> None:
        rtt = health.get("rtt_ms")
        age = health.get("age_s", float("inf"))
        self.fields["link"].setText(f"{rtt:6.1f} ms · {age:4.1f} s" if rtt is not None else "— sin lectura")
        nominal = health.get("loop_dt_nom_us")
        self.fields["loop"].setText(f"{health.get('loop_dt_max_us')}  (nom {nominal})")
        overruns = health.get("loop_overruns")
        item = self.fields["overruns"]
        item.setText(str(overruns))
        item.setStyleSheet(MONO + ("color:#ff5c7a; font-weight:700;" if overruns else ""))
        ina = health.get("ina_ok")
        item = self.fields["ina"]
        item.setText("ok" if ina else "SIN INA219")
        # Sin INA219 no hay corte por calado: la protección está gateada por `inaOk`.
        item.setStyleSheet(MONO + ("" if ina else "color:#ff5c7a; font-weight:700;"))


class AnalysisPanel(QGroupBox):
    """Escalón, vertical invertida y traspaso latcheado por el firmware."""

    def __init__(self) -> None:
        super().__init__("Análisis")
        self.fields: dict[str, QLabel] = {}
        form = QFormLayout(self)
        for key, label in (
            ("step", "escalón θ → sp"),
            ("overshoot", "sobrepaso"),
            ("legacy", "sobrepaso (legacy)"),
            ("settling", "establecimiento"),
            ("sse", "error de régimen"),
            ("upright", "upright · hold"),
            ("handoff", "traspaso m5→m4"),
            ("energy", "E/E* en el traspaso"),
        ):
            value = QLabel("—")
            value.setStyleSheet(MONO)
            self.fields[key] = value
            form.addRow(label, value)
        note = QLabel("El sobrepaso se normaliza por el salto pedido; «legacy» divide por |sp|.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7c869b; font-size:11px;")
        form.addRow(note)

    def update_step(self, metrics: StepMetrics | None) -> None:
        if metrics is None:
            for key in ("step", "overshoot", "legacy", "settling", "sse"):
                self.fields[key].setText("—")
            return
        self.fields["step"].setText(f"{metrics.y0_deg:+.2f}° → {metrics.setpoint_deg:+.2f}°")
        self.fields["overshoot"].setText(f"{metrics.overshoot_pct:6.1f} %")
        self.fields["legacy"].setText(f"{metrics.overshoot_legacy_pct:6.1f} %")
        self.fields["settling"].setText(f"{metrics.settling_s:6.3f} s")
        self.fields["sse"].setText(f"{metrics.sse_deg:6.2f} °")

    def update_upright(self, stats: UprightStats) -> None:
        self.fields["upright"].setText(
            f"{100 * stats.fraction:5.1f} %  ·  {stats.hold_now_s:4.2f} s (máx {stats.hold_max_s:4.2f} s)"
        )

    def update_handoff(self, summary: dict | None) -> None:
        if summary is None:
            self.fields["handoff"].setText("sin traspaso")
            self.fields["energy"].setText("—")
            return
        reasons = "+".join(summary["reasons"]) or "?"
        alpha, vel = summary.get("alpha_deg"), summary.get("vel_dps")
        self.fields["handoff"].setText(f"{reasons}  α={alpha:+.2f}°  |α̇|={vel:.1f}°/s")
        self.fields["energy"].setText(f"{summary.get('energy_ratio'):.4f}")


class StatusBanner(QLabel):
    """Aviso permanente sobre el alcance del failsafe. No es decorativo."""

    def __init__(self) -> None:
        super().__init__(
            "El watchdog del firmware sólo cubre los modos 1 y 6. Los modos 2, 4 y 5 son "
            "autónomos y siguen corriendo aunque muera el enlace: el único respaldo es el "
            "límite duro de ±95° del brazo. Tener el corte de alimentación a mano."
        )
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setStyleSheet(
            "background:#2a1f14; color:#ffb454; border:1px solid #4a3a22;"
            "border-radius:4px; padding:6px; font-size:11px;"
        )
