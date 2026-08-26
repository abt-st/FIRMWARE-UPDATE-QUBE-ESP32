"""Barra superior: en qué modo está la planta y qué está haciendo, de un vistazo.

Se alimenta de ``/state`` a 2 Hz, **no del DAQ**, y por eso funciona con la adquisición
detenida: antes la ventana arrancaba completamente muerta hasta que alguien apretaba
«Adquirir», aunque la placa estuviera ahí contestando.

La distinción de relojes que el resto de la app cuida se mantiene: estos números son del
sondeo de ``/state``, con la latencia que eso implica, y sirven para **operar**. Para
**medir** están las trazas a 500 Hz, que son las que llevan la marca del tick que produjo
cada muestra.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qube_app.link import MODE_NAMES
from qube_app.stream import StreamStats
from qube_app.ui.theme import (
    BG_PANEL,
    BORDER,
    COLOR_ACCENT,
    COLOR_ALPHA,
    COLOR_BAD,
    COLOR_DIM,
    COLOR_GOOD,
    COLOR_PWM,
    COLOR_THETA,
    COLOR_WARN,
    MODE_COLORS,
    MONO,
)


class Readout(QWidget):
    """Un valor grande con su rótulo chico encima."""

    def __init__(self, caption: str, color: str, width: int = 96) -> None:
        super().__init__()
        self._caption = QLabel(caption)
        self._caption.setStyleSheet(f"color:{COLOR_DIM}; font-size:10px; letter-spacing:0.6px;")
        self._value = QLabel("—")
        self._value.setStyleSheet(MONO + f"color:{color}; font-size:21px; font-weight:600;")
        self._value.setMinimumWidth(width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._caption)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class HeaderBar(QFrame):
    """Modo, θ, α, PWM y salud del enlace, siempre visibles y fuera de cualquier scroll."""

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet(f"HeaderBar {{ background:{BG_PANEL}; border:1px solid {BORDER}; border-radius:6px; }}")

        self.mode = QLabel("—")
        self.mode.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:15px; font-weight:700;")
        self.mode.setMinimumWidth(190)

        self.theta = Readout("θ BRAZO", COLOR_THETA)
        self.alpha = Readout("α PÉNDULO", COLOR_ALPHA)
        self.pwm = Readout("PWM", COLOR_PWM, width=68)
        self.setpoint = Readout("SETPOINT θ", COLOR_DIM)

        self.link = QLabel("sin enlace")
        self.link.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")
        self.link.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.acquisition = QLabel("adquisición detenida")
        self.acquisition.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")
        self.acquisition.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        status = QWidget()
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(1)
        status_layout.addWidget(self.link)
        status_layout.addWidget(self.acquisition)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(18)
        layout.addWidget(self.mode)
        for readout in (self.theta, self.alpha, self.pwm, self.setpoint):
            layout.addWidget(readout)
        layout.addStretch(1)
        layout.addWidget(status)

    # ── Actualización ─────────────────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        """Refresca desde ``/state``. Un campo ausente se apaga, no se inventa."""
        mode = state.get("mode")
        color = MODE_COLORS.get(mode, COLOR_DIM) if mode is not None else COLOR_DIM
        self.mode.setText(f"● {MODE_NAMES.get(mode, str(mode))}" if mode is not None else "● —")
        self.mode.setStyleSheet(MONO + f"color:{color}; font-size:15px; font-weight:700;")

        self.theta.set_value(_deg(state.get("position_deg")))
        # `pend_position_deg` viene continuo del firmware: sin envolver, tras unas
        # vueltas muestra miles de grados y deja de decir nada. La traza de α se dibuja
        # envuelta por la misma razón.
        self.alpha.set_value(_deg(state.get("pend_position_deg"), wrap=True))
        pwm = state.get("pwm")
        self.pwm.set_value(f"{int(pwm):+d}" if pwm is not None else "—")
        self.setpoint.set_value(_deg(state.get("setpoint_deg")))

    def update_link(self, rtt_ms: float | None, age_s: float) -> None:
        if rtt_ms is None or age_s == float("inf"):
            self.link.setText("● sin enlace")
            self.link.setStyleSheet(MONO + f"color:{COLOR_BAD}; font-size:11px;")
            return
        color = COLOR_GOOD if age_s < 1.5 else (COLOR_WARN if age_s < 4.0 else COLOR_BAD)
        self.link.setText(f"● enlace {rtt_ms:.0f} ms · {age_s:.1f} s")
        self.link.setStyleSheet(MONO + f"color:{color}; font-size:11px;")

    def update_stream(self, stats: StreamStats | None) -> None:
        if stats is None or not stats.running:
            self.acquisition.setText("adquisición detenida")
            self.acquisition.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")
            return
        # Las pérdidas mandan sobre todo lo demás: una captura con pérdidas no sirve para
        # afirmar nada, y el número tiene que estar donde se mira sin buscarlo.
        color = COLOR_BAD if stats.dropped else (COLOR_WARN if stats.errors else COLOR_ACCENT)
        detail = f"{stats.dropped} perdidas" if stats.dropped else "0 perdidas"
        self.acquisition.setText(f"{stats.rate_hz:.1f} Hz · {detail}")
        self.acquisition.setStyleSheet(MONO + f"color:{color}; font-size:11px;")


def _deg(value: object, wrap: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    angle = float(value)
    if wrap:
        angle = (angle + 180.0) % 360.0 - 180.0
    return f"{angle:+.1f}°"
