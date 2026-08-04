"""Trazas en vivo con pyqtgraph: las cuatro señales y el retrato de fase.

Cada gráfica se dibuja llamando ``setData`` sobre un único item persistente. Crear items
nuevos por cuadro es lo que hace que una GUI de telemetría se degrade con el tiempo —el
problema que ya tenía la GUI web con Chart.js al acumular miles de puntos.

**Los relojes no se mezclan sin decirlo.** θ, α y PWM llevan la marca del tick del ESP32
que produjo la muestra. La potencia viene de ``/state`` a 2 Hz, porque la muestra binaria
de 16 B no lleva INA219: se la alinea con el último ``t_s`` recibido en el momento de
llegar, lo que la deja con una incertidumbre del orden del período de sondeo. El eje lo
declara.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

# Paleta sobria y de alto contraste: son trazas para leer, no para decorar.
COLOR_THETA = "#4da3ff"
COLOR_ALPHA = "#ffb454"
COLOR_PWM = "#57d68a"
COLOR_POWER = "#c792ea"
COLOR_GRID = "#2a2f3a"
COLOR_MARK = "#ff5c7a"


def _style_plot(plot: pg.PlotWidget, y_label: str, y_range: tuple[float, float] | None = None) -> None:
    plot.setBackground("#12151c")
    plot.showGrid(x=True, y=True, alpha=0.25)
    plot.setLabel("left", y_label)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=y_range is None)
    if y_range is not None:
        # PlotWidget reenvía esto al PlotItem, cuya firma sí es (min, max, padding); la
        # que ve el analizador estático es la heredada de GraphicsView, de un argumento.
        plot.setYRange(y_range[0], y_range[1], padding=0.02)  # pyright: ignore[reportCallIssue]


class TracePlot(QWidget):
    """Una gráfica con su encabezado y el valor instantáneo a la derecha."""

    def __init__(
        self,
        title: str,
        color: str,
        units: str,
        y_range: tuple[float, float] | None = None,
        height: int = 150,
    ) -> None:
        super().__init__()
        self.units = units
        self._header = QLabel(title)
        self._header.setStyleSheet(f"color:{color}; font-weight:600;")
        self._value = QLabel("—")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._value.setStyleSheet("color:#c8cfdb; font-family:Consolas,monospace;")

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(height)
        _style_plot(self.plot, units, y_range)
        # Ancho 1 a propósito: un lápiz más grueso deja de ser cosmético y Qt lo dibuja
        # por el doble (16,4 ms contra 8,2 ms por cuadro, medido con 10.000 puntos).
        self.curve = self.plot.plot(pen=pg.mkPen(color, width=1))

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.addWidget(self._header)
        head_layout.addStretch(1)
        head_layout.addWidget(self._value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        layout.addWidget(head)
        layout.addWidget(self.plot)

    def set_data(self, t: np.ndarray, y: np.ndarray) -> None:
        self.curve.setData(t, y)
        self._value.setText(f"{y[-1]:+.2f} {self.units}" if len(y) else "—")

    def clear(self) -> None:
        self.curve.setData([], [])
        self._value.setText("—")


class LivePlots(QWidget):
    """Las cuatro trazas apiladas, con eje X compartido en segundos."""

    def __init__(self, window_s: float = 20.0) -> None:
        super().__init__()
        self.window_s = window_s
        self._x_right: float | None = None
        # Rango fijo, no automático: el auto-rango recalcula límites y repinta en cada
        # `setData`, y costaba 15 puntos de CPU. ±140° cubre todo el recorrido mecánico
        # (270° de tope a tope), así que no puede recortar la traza.
        self.theta = TracePlot("θ brazo", COLOR_THETA, "°", y_range=(-140, 140))
        self.alpha = TracePlot("α péndulo (envuelto)", COLOR_ALPHA, "°", y_range=(-190, 190))
        self.pwm = TracePlot("PWM aplicado", COLOR_PWM, "", y_range=(-260, 260))
        self.power = TracePlot("Potencia · INA219 @ 2 Hz", COLOR_POWER, "mW")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for panel in (self.theta, self.alpha, self.pwm, self.power):
            layout.addWidget(panel)
        # Las cuatro comparten eje de tiempo —comparar α con el PWM que lo causó es para
        # lo que sirve mirarlas juntas— pero el rango se fija en cada una por separado en
        # vez de con `setXLink`. Enlazadas, cada `setData` propaga un cambio de rango a
        # las otras tres y se repintan las cuatro por cada traza que se actualiza: 16
        # repintados por ciclo en vez de 4.
        self.power.plot.setLabel("bottom", "t [s] · reloj del ESP32")

    def set_window(self, seconds: float) -> None:
        self.window_s = seconds
        self.reset_time_range()  # el encuadre viejo ya no corresponde

    def update_traces(self, t: np.ndarray, theta: np.ndarray, alpha_wrapped: np.ndarray, pwm: np.ndarray) -> None:
        self.theta.set_data(t, theta)
        self.alpha.set_data(t, alpha_wrapped)
        self.pwm.set_data(t, pwm)
        if len(t):
            self.set_time_range(float(t[-1]))

    def set_time_range(self, t_last: float) -> None:
        """Avanza la ventana **a saltos**, no deslizándola.

        Cada cambio de rango obliga a pyqtgraph a regenerar las marcas y los rótulos de
        los cuatro ejes, y eso resultó ser el costo dominante de toda la interfaz: con la
        ventana deslizándose en cada actualización, el pintado se llevaba el 74 % de un
        núcleo; saltando, el 19 %. El salto es de un cuarto de ventana, así que a 20 s de
        ventana el eje se redibuja cada 5 s en vez de cinco veces por segundo.

        La contrapartida es visible y deliberada: la traza avanza por páginas en vez de
        desplazarse con suavidad, que es como se comporta un registrador de banda.
        """
        if self._x_right is not None and self._x_right - self.window_s <= t_last <= self._x_right:
            return
        # El borde izquierdo nunca baja de cero: al arrancar, la ventana es [0, window] y
        # la traza la va llenando. Sin este tope, los primeros segundos se dibujan contra
        # un eje que empieza en tiempo negativo y sobra media gráfica.
        self._x_right = max(t_last + self.window_s * 0.25, self.window_s)
        x0 = self._x_right - self.window_s
        for panel in (self.theta, self.alpha, self.pwm, self.power):
            # El mismo reenvío al PlotItem que en `_style_plot`.
            panel.plot.setXRange(x0, self._x_right, padding=0.0)  # pyright: ignore[reportCallIssue]

    def reset_time_range(self) -> None:
        """Olvida la ventana actual: la próxima muestra vuelve a encuadrar."""
        self._x_right = None

    def update_power(self, t: np.ndarray, p_mw: np.ndarray) -> None:
        self.power.set_data(t, p_mw)

    def clear(self) -> None:
        for panel in (self.theta, self.alpha, self.pwm, self.power):
            panel.clear()
        self.reset_time_range()


class PhasePlot(QWidget):
    """Retrato de fase α–α̇, con la marca del traspaso que latcheó el firmware."""

    def __init__(self) -> None:
        super().__init__()
        self.plot = pg.PlotWidget()
        _style_plot(self.plot, "α̇ [°/s]")
        self.plot.setLabel("bottom", "α [°]")
        self.plot.setMouseEnabled(x=True, y=True)
        self.curve = self.plot.plot(pen=pg.mkPen(COLOR_ALPHA, width=1.0))
        # Las verticales de ±180° son la vertical invertida: la referencia del swing-up.
        for x in (-180.0, 180.0):
            self.plot.addItem(pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(COLOR_GRID, width=1)))
        self.handoff = pg.ScatterPlotItem(size=11, brush=pg.mkBrush(COLOR_MARK), pen=None)
        self.plot.addItem(self.handoff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

    def update_portrait(self, alpha: np.ndarray, alpha_dot: np.ndarray) -> None:
        # `connect="finite"` es lo que hace efectivo el corte con NaN del análisis: sin
        # esto, pyqtgraph uniría los dos extremos del envolvimiento con una recta.
        self.curve.setData(alpha, alpha_dot, connect="finite")

    def mark_handoff(self, alpha_deg: float | None, vel_dps: float | None) -> None:
        if alpha_deg is None or vel_dps is None:
            self.handoff.setData([], [])
            return
        self.handoff.setData([float(alpha_deg)], [float(vel_dps)])

    def clear(self) -> None:
        self.curve.setData([], [])
        self.handoff.setData([], [])
