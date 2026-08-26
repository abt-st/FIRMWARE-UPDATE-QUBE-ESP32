"""Trazas en vivo con pyqtgraph: las cuatro señales y el retrato de fase.

Cada gráfica se dibuja llamando ``setData`` sobre un único item persistente. Crear items
nuevos por cuadro es lo que hace que una GUI de telemetría se degrade con el tiempo —el
problema que ya tenía la GUI web con Chart.js al acumular miles de puntos. Las bandas de
modo siguen la misma regla: se reserva un **pool** de regiones y se reposicionan, y sólo
cuando la segmentación cambió de verdad.

**Los relojes no se mezclan sin decirlo.** θ, α y PWM llevan la marca del tick del ESP32
que produjo la muestra. La potencia viene de ``/state`` a 2 Hz, porque la muestra binaria
de 16 B no lleva INA219: se la alinea con el último ``t_s`` recibido en el momento de
llegar, lo que la deja con una incertidumbre del orden del período de sondeo. El eje lo
declara. La marca del traspaso tiene la misma incertidumbre y por la misma razón: sale de
``swing_trans_ms_ago``, que también llega por el sondeo.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qube_app.ui.theme import (
    BG_PANEL,
    COLOR_ALPHA,
    COLOR_DIM,
    COLOR_GRID,
    COLOR_MARK,
    COLOR_POWER,
    COLOR_PWM,
    COLOR_THETA,
    MODE_COLORS,
    MONO,
)

#: Ancho fijo del eje vertical: con anchos automáticos ("−190" contra "−260") las cuatro
#: áreas de dibujo quedaban desalineadas y el eje de tiempo compartido dejaba de leerse
#: como compartido.
AXIS_WIDTH = 54

#: Cuántas franjas de modo puede haber a la vista. Con más cambios que esto en una
#: ventana, las viejas se descartan: son las que ya salieron por la izquierda.
MODE_BAND_POOL = 14


def _style_plot(plot: pg.PlotWidget, y_label: str = "", y_range: tuple[float, float] | None = None) -> None:
    plot.setBackground(BG_PANEL)
    plot.showGrid(x=True, y=True, alpha=0.22)
    # Sin rótulo vertical en las trazas: el encabezado ya dice qué señal es y el valor
    # instantáneo de la derecha lleva la unidad. El "°" girado en el margen izquierdo no
    # agregaba nada y se comía ancho de dibujo en las cuatro gráficas.
    if y_label:
        plot.setLabel("left", y_label)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=y_range is None)
    plot.getAxis("left").setWidth(AXIS_WIDTH)
    if y_range is not None:
        # PlotWidget reenvía esto al PlotItem, cuya firma sí es (min, max, padding); la
        # que ve el analizador estático es la heredada de GraphicsView, de un argumento.
        plot.setYRange(y_range[0], y_range[1], padding=0.02)  # pyright: ignore[reportCallIssue]


class ModeRibbon(QWidget):
    """Cinta con el modo activo, sobre el mismo eje de tiempo que las trazas.

    ``mode`` viaja en cada muestra del DAQ desde el primer día y no se dibujaba en ningún
    lado. Verlo alineado con las trazas es lo que permite decir *dónde* entró el LQR, en
    vez de deducirlo del momento en que el PWM cambió de forma.

    **Por qué una cinta y no el fondo de las cuatro gráficas.** Se probaron las dos. Pintar
    franjas translúcidas detrás de cada traza cuesta **18 puntos de CPU** con la ventana
    llena —medido: 34 % contra 52 % de un núcleo—, porque son cuatro rectángulos con alfa
    del tamaño del área de dibujo y se recomponen en cada repintado. La cinta lleva la
    misma información en 1/40 del área, no tiñe las trazas y se lee mejor. Después de todo
    lo que costó bajar el pintado en este proyecto (ver §4.b de `APP_ESCRITORIO.md`), no
    se le regalan 18 puntos a un sombreado.
    """

    HEIGHT = 26

    def __init__(self, pool: int = MODE_BAND_POOL) -> None:
        super().__init__()
        self.plot = pg.PlotWidget()
        self.plot.setBackground(BG_PANEL)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setYRange(0, 1, padding=0)  # pyright: ignore[reportCallIssue]
        self.plot.setFixedHeight(self.HEIGHT)
        for edge in ("left", "bottom"):
            axis = self.plot.getAxis(edge)
            axis.setStyle(showValues=False, tickLength=0)
            axis.setPen(pg.mkPen(None))
        # El margen izquierdo lo ocupa el rótulo, con exactamente el ancho del eje de las
        # trazas: la cinta se lee **en vertical** contra ellas, así que si no queda a
        # plomo no sirve para nada.
        self.plot.getAxis("left").setWidth(0)
        self.plot.getAxis("bottom").setHeight(2)

        self._regions: list[pg.LinearRegionItem] = []
        self._labels: list[pg.TextItem] = []
        for _ in range(pool):
            region = pg.LinearRegionItem(movable=False)
            # Sin líneas de borde: `LinearRegionItem` las dibuja brillantes por omisión y
            # se leen como si marcaran un evento. Lo único que marca un instante acá es la
            # línea del traspaso.
            for line in region.lines:
                line.setPen(pg.mkPen(None))
            region.hide()
            self.plot.addItem(region, ignoreBounds=True)
            self._regions.append(region)

            label = pg.TextItem("", color=BG_PANEL, anchor=(0, 0.5))
            label.hide()
            self.plot.addItem(label, ignoreBounds=True)
            self._labels.append(label)

        self.caption = QLabel("modo ")
        self.caption.setStyleSheet(f"color:{COLOR_DIM}; font-size:10px;")
        self.caption.setFixedWidth(AXIS_WIDTH)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        layout.addWidget(self.caption)
        layout.addWidget(self.plot, stretch=1)
        self._signature: tuple = ()
        self._segments: list[tuple[float, float, int]] = []
        self._x0 = 0.0

    def set_x_range(self, x0: float, x1: float) -> None:
        self._x0 = x0
        self.plot.setXRange(x0, x1, padding=0.0)  # pyright: ignore[reportCallIssue]
        self._place_labels()

    def update_modes(self, t_s: np.ndarray, mode: np.ndarray) -> None:
        """Reposiciona los tramos. Sólo reestiliza cuando cambió la **estructura**.

        Los bordes exteriores del primer y del último tramo son los de la ventana visible,
        así que se mueven en cada cuadro: comparar los tramos enteros no coincidía nunca y
        reaplicaba pincel, texto y visibilidad sobre todo el pool cinco veces por segundo.
        La estructura —los modos y los instantes en que cambian— sí es estable, y
        ``setRegion`` de pyqtgraph corta solo cuando el tramo no se movió.
        """
        segments = _mode_segments(t_s, mode)[-len(self._regions) :] if len(t_s) else []
        structure = tuple(code for _, _, code in segments) + tuple(t0 for t0, _, _ in segments[1:])
        restyle = structure != self._signature
        self._signature = structure

        # `strict=False` a propósito: el pool es más largo que los tramos visibles, y los
        # sobrantes se ocultan en el bucle de abajo.
        self._segments = segments
        self._place_labels()
        for region, label, (t0, t1, code) in zip(self._regions, self._labels, segments, strict=False):
            region.setRegion((t0, t1))
            if restyle:
                region.setBrush(QColor(MODE_COLORS.get(int(code), COLOR_DIM)))
                region.show()
                label.setText(f" m{int(code)}")
                label.show()
        if restyle:
            for region in self._regions[len(segments) :]:
                region.hide()
            for label in self._labels[len(segments) :]:
                label.hide()

    def _place_labels(self) -> None:
        """Ancla cada rótulo al inicio del tramo, **o al borde visible si empezó antes**.

        El tramo más viejo casi siempre empieza fuera de la ventana —es el modo en el que
        se venía— y con el rótulo anclado a su inicio real quedaba fuera de la vista. Es
        justo el tramo que uno mira para saber en qué modo está corriendo esto.
        """
        for label, (t0, t1, _) in zip(self._labels, self._segments, strict=False):
            x = max(t0, self._x0)
            if x < t1:  # tramo enteramente a la izquierda: no hay dónde ponerlo
                label.setPos(x, 0.5)

    def clear(self) -> None:
        self._signature = ()
        self._segments = []
        for region in self._regions:
            region.hide()
        for label in self._labels:
            label.hide()


def _mode_segments(t_s: np.ndarray, mode: np.ndarray) -> list[tuple[float, float, int]]:
    """Tramos contiguos de modo constante, como ``(t_inicio, t_fin, modo)``."""
    if len(t_s) < 2 or len(mode) != len(t_s):
        return []
    edges = np.flatnonzero(np.diff(mode)) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(t_s)]))
    return [(float(t_s[i]), float(t_s[j - 1]), int(mode[i])) for i, j in zip(starts, ends, strict=True)]


class TracePlot(QWidget):
    """Una gráfica con su encabezado y el valor instantáneo a la derecha."""

    def __init__(
        self,
        title: str,
        color: str,
        units: str,
        y_range: tuple[float, float] | None = None,
        height: int = 130,
        show_time_axis: bool = False,
    ) -> None:
        super().__init__()
        self.units = units
        self._header = QLabel(title)
        self._header.setStyleSheet(f"color:{color}; font-weight:600; font-size:11px;")
        self._value = QLabel("—")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._value.setStyleSheet(MONO + f"color:{color};")

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(height)
        _style_plot(self.plot, y_range=y_range)
        # Sólo la última gráfica lleva rótulos de tiempo: las cuatro repetían las mismas
        # marcas, y cada eje que sobra es alto perdido y una regeneración más por salto
        # de ventana (ver el §4.b de APP_ESCRITORIO.md).
        if not show_time_axis:
            self.plot.getAxis("bottom").setStyle(showValues=False)
            self.plot.getAxis("bottom").setHeight(10)
        # Ancho 1 a propósito: un lápiz más grueso deja de ser cosmético y Qt lo dibuja
        # por el doble (16,4 ms contra 8,2 ms por cuadro, medido con 10.000 puntos).
        self.curve = self.plot.plot(pen=pg.mkPen(color, width=1))
        # Marca del traspaso: item persistente, sólo se mueve y se muestra.
        self.handoff = pg.InfiniteLine(angle=90, pen=pg.mkPen(COLOR_MARK, width=1, style=Qt.PenStyle.DashLine))
        self.handoff.hide()
        self.plot.addItem(self.handoff, ignoreBounds=True)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(AXIS_WIDTH, 0, 2, 0)
        head_layout.addWidget(self._header)
        head_layout.addStretch(1)
        head_layout.addWidget(self._value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 0)
        layout.setSpacing(1)
        layout.addWidget(head)
        layout.addWidget(self.plot)

    def set_data(self, t: np.ndarray, y: np.ndarray) -> None:
        self.curve.setData(t, y)
        self._value.setText(f"{y[-1]:+.2f} {self.units}" if len(y) else "—")

    def set_handoff(self, t_s: float | None) -> None:
        if t_s is None:
            self.handoff.hide()
            return
        self.handoff.setPos(float(t_s))
        self.handoff.show()

    def clear(self) -> None:
        self.curve.setData([], [])
        self._value.setText("—")
        self.handoff.hide()


class LivePlots(QWidget):
    """Las cuatro trazas apiladas, con eje X compartido en segundos."""

    def __init__(self, window_s: float = 20.0) -> None:
        super().__init__()
        self.window_s = window_s
        self._x_range: tuple[float, float] | None = None
        # Rango fijo, no automático: el auto-rango recalcula límites y repinta en cada
        # `setData`, y costaba 15 puntos de CPU. ±140° cubre todo el recorrido mecánico
        # (270° de tope a tope), así que no puede recortar la traza.
        self.theta = TracePlot("θ  brazo", COLOR_THETA, "°", y_range=(-140, 140))
        self.alpha = TracePlot("α  péndulo (envuelto)", COLOR_ALPHA, "°", y_range=(-190, 190))
        self.pwm = TracePlot("PWM aplicado", COLOR_PWM, "", y_range=(-260, 260))
        self.power = TracePlot("Potencia · INA219 @ 2 Hz", COLOR_POWER, "mW", height=110, show_time_axis=True)
        self.panels = (self.theta, self.alpha, self.pwm, self.power)

        self.ribbon = ModeRibbon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.ribbon)
        for panel in self.panels:
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

    def update_modes(self, t: np.ndarray, mode: np.ndarray) -> None:
        self.ribbon.update_modes(t, mode)

    def mark_handoff(self, t_s: float | None) -> None:
        for panel in self.panels:
            panel.set_handoff(t_s)

    def set_time_range(self, t_last: float) -> None:
        """Avanza la ventana **a saltos**, no deslizándola.

        Cada cambio de rango obliga a pyqtgraph a regenerar las marcas y los rótulos de
        los ejes, y eso resultó ser el costo dominante de toda la interfaz: con la
        ventana deslizándose en cada actualización, el pintado se llevaba el 74 % de un
        núcleo; saltando, el 19 %. El salto es de un cuarto de ventana, así que a 20 s de
        ventana el eje se redibuja cada 5 s en vez de cinco veces por segundo.

        La contrapartida es visible y deliberada: la traza avanza por páginas en vez de
        desplazarse con suavidad, que es como se comporta un registrador de banda.
        """
        span = self._span_for(t_last)
        if span == self._x_range:
            return  # el mismo encuadre: repintar el eje sería trabajo sin dato nuevo
        self._x_range = span
        for panel in self.panels:
            # El mismo reenvío al PlotItem que en `_style_plot`.
            panel.plot.setXRange(span[0], span[1], padding=0.0)  # pyright: ignore[reportCallIssue]
        self.ribbon.set_x_range(*span)  # la cinta se lee en vertical: tiene que ir a plomo

    def _span_for(self, t_last: float) -> tuple[float, float]:
        """El encuadre que corresponde a ``t_last``, cuantizado a cuartos de ventana.

        Mientras la captura es más corta que la ventana, el eje **crece** desde cero en
        vez de reservar el ancho completo: con 20 s de ventana y 9 s capturados, la mitad
        derecha quedaba en blanco y la app parecía trabada. Sigue cuantizado al mismo
        cuarto de ventana, así que el eje se regenera con la misma frecuencia de antes y
        la optimización que costó 60 puntos de CPU queda intacta.
        """
        step = self.window_s * 0.25
        quantized = (int(t_last / step) + 1) * step
        if quantized <= self.window_s:
            return (0.0, quantized)  # ventana creciente: el borde izquierdo es el origen
        return (quantized - self.window_s, quantized)

    def reset_time_range(self) -> None:
        """Olvida la ventana actual: la próxima muestra vuelve a encuadrar."""
        self._x_range = None

    def update_power(self, t: np.ndarray, p_mw: np.ndarray) -> None:
        self.power.set_data(t, p_mw)

    def clear(self) -> None:
        for panel in self.panels:
            panel.clear()
        self.ribbon.clear()
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
