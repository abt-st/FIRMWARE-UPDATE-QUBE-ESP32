"""Paneles de control, sesión, salud y análisis.

Ningún panel habla con la placa: todos emiten ``command`` con los parámetros de ``/cmd``
y la ventana principal los encola en el hilo del sondeo. Así un comando con reintentos
—que puede tardar segundos cuando la radio le roba tiempo al lazo— nunca congela la
interfaz.

Los modos 3 (homing) y 5 (swing-up) llevan al brazo contra los topes mecánicos, así que
piden confirmación explícita. No es formalismo: el homing golpea ambos extremos y el
swing-up bombea con el péndulo suelto.

**Dos reglas que vienen de defectos ya pagados en este archivo:**

1. *Nunca conectar una señal de Qt directamente a un método con argumentos opcionales.*
   ``clicked`` emite ``checked=False`` y ``isinstance(False, int)`` es ``True`` en Python,
   así que el ``forced`` de :meth:`ControlPanel._apply_mode` le ganaba al combo y todos
   los modos se enviaban como ``m=0``. El selector de modos no funcionó nunca.
2. *Los defaults de las ganancias son los del firmware y se verifican contra el ``.ino``*
   (``tests/test_app_ui.py``). Un default equivocado no se ve en pantalla: se ve cuando
   alguien aprieta «Enviar» y la placa queda reconfigurada en silencio.
3. *Un mando que la placa rechaza tiene que decirlo acá.* Desde v1.60.0 el firmware
   **rechaza** los modos 2/4/5/6/7 si no se hizo homing (``hr=1``) o si el INA219 está
   caído (``sf=1``): ``setMode()`` retorna sin hacer nada y el único aviso sale por
   Serial, que en este banco no se puede abrir sin reiniciar la placa. Apretar «Aplicar
   modo» no hacía absolutamente nada y la app no tenía nada que decir al respecto,
   aunque ``/state`` publica ``mode_reject`` desde esa misma versión justamente para
   esto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    QVBoxLayout,
    QWidget,
)

from qube_app.analysis import StepMetrics, UprightStats
from qube_app.link import (
    MODE_NAMES,
    MODE_REJECT_REASONS,
    MODES_REQUIRING_HOMING,
    MODES_REQUIRING_INA,
    MODES_THAT_MOVE_TO_STOPS,
    SAFETY_ACTIONS,
    SWING_FAIL_REASONS,
)
from qube_app.settings import AppSettings
from qube_app.stream import StreamStats
from qube_app.ui.theme import COLOR_BAD, COLOR_DIM, COLOR_GOOD, COLOR_WARN, MONO

#: Antigüedad de ``/state`` a partir de la cual el enlace deja de estar sano [s].
LINK_WARN_S = 1.5
LINK_BAD_S = 4.0


def _fmt(value: object, spec: str = "", default: str = "—") -> str:
    """Formatea tolerando ``None`` y tipos inesperados.

    Un ``/state`` incompleto no puede tumbar el ciclo de análisis: el formateo directo
    (``f"{valor:+.2f}"``) lanzaba **dentro de un slot de QTimer**, donde la excepción se
    lleva la actualización entera y no aparece en ningún lado.
    """
    if value is None:
        return default
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def _paint(label: QLabel, color: str | None = None, bold: bool = False) -> None:
    """Recolorea un valor sin perder la tipografía monoespaciada."""
    style = MONO
    if color:
        style += f"color:{color};"
    if bold:
        style += "font-weight:700;"
    label.setStyleSheet(style)


def _value_label(text: str = "—") -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(MONO)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _spin(minimum: float, maximum: float, value: float, step: float = 0.1, decimals: int = 3) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


# ── Control ───────────────────────────────────────────────────────────────────


class ControlPanel(QWidget):
    """Modo, setpoint, PWM manual, ceros y homing.

    Widget pelado y no ``QGroupBox``: vive dentro de una pestaña que ya se llama
    «Control», y el marco con título repetido sumaba un borde y un rótulo de más.

    **Conoce las compuertas de entrada a modo del firmware.** No para duplicar la
    decisión —la toma la placa— sino para no ofrecer un botón que no va a hacer nada:
    con ``hr=1`` y sin homing, «Aplicar modo» sobre un 4 es un ``GET`` que la placa
    descarta, y hasta esta versión la app se quedaba tan callada como la placa.
    """

    command = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        #: Último ``/state`` conocido. Vacío hasta el primer sondeo: mientras esté
        #: vacío **no se bloquea nada**, porque no saber no es lo mismo que saber que no.
        self._state: dict = {}
        self.mode = QComboBox()
        for code, name in MODE_NAMES.items():
            self.mode.addItem(name, code)
        apply_mode = QPushButton("Aplicar modo")
        # La lambda no es cosmética: conectar el método directamente le pasa el `checked`
        # del click como `forced`, y `isinstance(False, int)` lo convierte en el modo 0.
        apply_mode.clicked.connect(lambda: self._apply_mode())

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

        # Estado de la compuerta, siempre visible. El homing dejó de ser una utilidad
        # de calibración y pasó a ser un requisito de arranque: sin él la app no puede
        # entrar a ningún modo de control, y eso tiene que leerse sin ir a buscarlo.
        self.gate = QLabel("compuerta de homing: sin lectura de /state")
        self.gate.setWordWrap(True)
        self.gate.setStyleSheet(MONO + f"color:{COLOR_DIM}; font-size:11px;")

        self.homing_info = _value_label("homing: —")
        self.homing_info.setWordWrap(True)

        form = QFormLayout()
        # «Modo a aplicar» y no «Modo»: el combo es una petición, no un indicador. Con el
        # rótulo a secas se leía como el estado de la planta y contradecía al encabezado,
        # que sí muestra el modo real que informa `/state`.
        form.addRow("Modo a aplicar", self._row(self.mode, apply_mode))
        form.addRow("Setpoint θ [°]", self._row(self.setpoint, set_sp))
        form.addRow("PWM", self._row(self.pwm, set_pwm))
        form.addRow(self._row(zero_theta, zero_alpha, homing))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 4)
        layout.addLayout(form)
        layout.addWidget(self.gate)
        layout.addWidget(self.homing_info)
        layout.addStretch(1)  # los campos arriba, no repartidos por todo el alto

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for widget in widgets:
            layout.addWidget(widget)
        return row

    # ── Compuertas del firmware ───────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        """Refresca lo que la app sabe de las compuertas y del homing.

        Se alimenta del sondeo de ``/state``, igual que el encabezado. Un campo ausente
        —una placa con firmware anterior a v1.60.0— deja la compuerta en «desconocida»
        y no bloquea nada: la app no puede saber más que la placa.
        """
        self._state = state
        blocked = self.blocked_reason(int(self.mode.currentData()))
        if not state:
            self.gate.setText("compuerta de homing: sin lectura de /state")
            _paint(self.gate, COLOR_DIM)
        elif state.get("homing_ok"):
            self.gate.setText("compuerta de homing: ABIERTA (homing válido)")
            _paint(self.gate, COLOR_GOOD)
        elif not state.get("homing_required", True):
            # `hr=0` es una decisión legítima de trabajo de banco, pero cambia con qué
            # garantía se está midiendo: los límites del servo quedan contra un cero
            # arbitrario. Se dice, no se esconde.
            self.gate.setText("compuerta de homing: SUELTA (hr=0) — θ=0 es donde se encendió la placa")
            _paint(self.gate, COLOR_WARN)
        else:
            self.gate.setText(f"compuerta de homing: CERRADA — {MODE_REJECT_REASONS[2]}")
            _paint(self.gate, COLOR_BAD)

        self.homing_info.setText(self._homing_line(state))
        # El botón no se deshabilita: quien quiera mandar el comando igual debe poder
        # hacerlo (la placa es la que decide). Lo que cambia es que ahora avisa antes.
        self.gate.setToolTip(blocked or "")

    @staticmethod
    def _homing_line(state: dict) -> str:
        if not state:
            return "homing: —"
        phase = state.get("homing_phase", "—")
        rango = _fmt(state.get("homing_range"), ".1f")
        centro = _fmt(state.get("homing_center"), ".1f")
        # `homing_pwm_sign` es el sentido MEDIDO motor↔encoder, no `MOTOR_DIR`. Es el
        # test de un minuto de P26 y hasta ahora había que ir a leerlo con `curl`.
        signo = state.get("homing_pwm_sign")
        signo_txt = "sin homing" if not signo else f"{int(signo):+d}"
        fail = state.get("homing_fail")
        cola = f"  ·  FALLA {fail}" if fail else ""
        return f"homing: {phase}  ·  recorrido {rango}°  ·  centro {centro}°  ·  pwm_sign {signo_txt}{cola}"

    def blocked_reason(self, mode: int) -> str:
        """Por qué el firmware va a rechazar este modo, o ``""`` si va a pasar.

        Replica las dos compuertas de ``setMode()`` **sin adivinar**: si ``/state`` no
        trajo el campo, devuelve ``""``. Preferir un aviso de menos a inventar uno: un
        bloqueo falso sería peor que el silencio que se está corrigiendo.
        """
        state = self._state
        if not state:
            return ""
        if mode in MODES_REQUIRING_HOMING and state.get("homing_required", True) and not state.get("homing_ok", True):
            return MODE_REJECT_REASONS[2]
        if mode in MODES_REQUIRING_INA and state.get("ina_required", True) and state.get("ina_ok", True) is False:
            return MODE_REJECT_REASONS[3]
        return ""

    def _apply_mode(self, forced: int | None = None) -> None:
        # `isinstance(True, int)` es True: el bool se descarta explícitamente por si
        # alguien vuelve a conectar esto a una señal que emite `checked`.
        mode = forced if isinstance(forced, int) and not isinstance(forced, bool) else int(self.mode.currentData())
        blocked = self.blocked_reason(mode)
        if blocked and not self._confirm_blocked(mode, blocked):
            return
        if mode in MODES_THAT_MOVE_TO_STOPS and not self._confirm(mode):
            return
        self.command.emit({"m": mode})

    def _confirm_blocked(self, mode: int, reason: str) -> bool:
        """Avisa que la placa va a descartar el comando. Devuelve True si igual se manda.

        Se ofrece mandarlo igual a propósito: la app **no** es la autoridad sobre la
        compuerta —lo es el firmware— y una lectura de ``/state`` con un segundo de
        antigüedad podría estar desactualizada respecto de un homing recién terminado.
        Lo que no puede volver a pasar es que el comando salga sin que nadie lo diga.
        """
        answer = QMessageBox.warning(
            self,
            f"El firmware va a rechazar el modo {mode}",
            f"{reason}\n\n"
            "El comando se envía igual, pero `setMode()` retorna sin hacer nada: el modo "
            "no cambia y el único aviso sale por Serial.\n\n¿Enviarlo de todos modos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

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


# ── Ganancias ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GainSpec:
    """Un campo de ganancia, atado al firmware por los dos extremos.

    ``firmware_symbol`` es la variable del ``.ino`` de la que sale ``default``, y
    ``param`` el nombre que acepta ``/cmd``. El test los verifica leyendo el firmware:
    es lo único que impide que vuelvan a divergir en silencio.
    """

    param: str
    label: str
    firmware_symbol: str
    default: float
    minimum: float
    maximum: float
    step: float = 0.1
    decimals: int = 3
    inert: str = ""
    """Ficha del registro de problemas si el firmware acepta el parámetro y **lo pisa**.

    Un mando que no hace nada y no lo dice es peor que no tenerlo, que es exactamente lo
    que pasó con `bt` durante toda la vida de las dos interfaces.

    Hoy no hay ningún campo marcado. `?ke=` lo estuvo: el lazo de bombeo lo sobrescribía
    con `KE_GAIN_BASE` en el primer tick con |α| > 5°, así que lo que se escribía
    sobrevivía milisegundos ([P23]). **Cerrado en firmware v1.59.0**: `ke ≥ 0` fija un
    override que la rama adaptativa respeta y `/state` publica `ke_gain` y `ke_override`
    para verificar contra qué valor se está midiendo. La marca se quedó puesta tres
    versiones de firmware de más, desalentando el uso de un mando que ya funcionaba — el
    error simétrico del que la marca existe para evitar.
    """


@dataclass(frozen=True)
class GainGroup:
    title: str
    specs: tuple[GainSpec, ...] = field(default_factory=tuple)
    columns: int = 1
    """Grupos de cuatro campos en dos columnas: la columna lateral es angosta y una
    pila de siete filas obligaba a scrollear para llegar al botón «Enviar»."""


#: Los rangos respetan el ``constrain`` del firmware donde exista: aceptar un valor que
#: la placa va a recortar es mentirle a quien lo escribe. ``sp`` llegaba a admitir 255 y
#: el firmware lo clampeaba a 100.
GAIN_GROUPS: tuple[GainGroup, ...] = (
    GainGroup(
        "PID servo (m2)",
        (
            GainSpec("kp", "kp", "Kp", 3.0, 0.0, 50.0),
            GainSpec("ki", "ki", "Ki", 0.5, 0.0, 50.0),
            GainSpec("kd", "kd", "Kd", 0.45, 0.0, 50.0),
        ),
    ),
    GainGroup(
        "LQR (m4)",
        (
            GainSpec("lqr1", "K₁ · θ", "lqr_K1", 2.0, 0.0, 200.0),
            GainSpec("lqr2", "K₂ · α", "lqr_K2", 22.0, 0.0, 200.0),
            GainSpec("lqr3", "K₃ · θ̇", "lqr_K3", 1.5, 0.0, 200.0),
            GainSpec("lqr4", "K₄ · α̇", "lqr_K4", 9.0, 0.0, 200.0),
        ),
        columns=2,
    ),
    GainGroup(
        "Swing-up (m5)",
        (
            # Rango desde -1: el firmware distingue `ke ≥ 0` (override manual) de
            # `ke < 0` (suelta el override y manda la rama adaptativa). Con el mínimo en
            # 0 no había forma de volver a lo adaptativo desde la app sin un `curl`.
            GainSpec("ke", "ke · energía", "ke_gain", 0.65, -1.0, 5.0, 0.05),
            GainSpec("sp", "PWM máx", "swingupPwmMax", 60.0, 10.0, 100.0, 5.0, 0),
            GainSpec("tn", "α captura [°]", "swingupCatchDeg", 155.0, 120.0, 178.0, 1.0, 1),
        ),
    ),
)


class GainsPanel(QWidget):
    """PID, LQR y swing-up. Los defaults salen del firmware, no de la memoria de nadie.

    Cada grupo envía **sólo los campos que cambiaron**. Mandar los tres de una vez hacía
    que tocar ``kp`` reescribiera ``ki`` y ``kd`` con lo que la app creyera que valían, y
    lo que la app cree no es lo que la placa tiene: ``/state`` no publica las ganancias,
    así que no hay forma de leerlas de vuelta.
    """

    command = Signal(dict)

    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.fields: dict[str, QDoubleSpinBox] = {}
        self._sent: dict[str, float] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_presets())
        for group in GAIN_GROUPS:
            layout.addWidget(self._build_group(group))

        note = QLabel(
            "Valores locales: el firmware no publica las ganancias en /state, "
            "así que esto es lo que la app envió, no lo que la placa tiene."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{COLOR_DIM}; font-size:11px;")
        layout.addWidget(note)
        layout.addStretch(1)
        self._refresh_presets()

    # ── Presets ───────────────────────────────────────────────────────────────

    def _build_presets(self) -> QGroupBox:
        box = QGroupBox("Presets")
        self.preset_names = QComboBox()
        self.preset_names.setEditable(True)
        self.preset_names.setToolTip("Escribir un nombre nuevo para guardar; elegir uno para cargarlo.")
        load = QPushButton("Cargar")
        load.clicked.connect(self._load_preset)
        save = QPushButton("Guardar")
        save.clicked.connect(self._save_preset)
        delete = QPushButton("Borrar")
        delete.clicked.connect(self._delete_preset)

        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.preset_names, stretch=1)
        for button in (load, save, delete):
            row_layout.addWidget(button)
        layout.addWidget(row)
        # Cargar rellena los campos y no envía nada: escribir en la placa es siempre un
        # acto explícito, incluso cuando el juego de ganancias ya se usó antes.
        hint = QLabel("Cargar sólo rellena los campos: hay que apretar «Enviar» en cada grupo.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{COLOR_DIM}; font-size:11px;")
        layout.addWidget(hint)
        return box

    def _refresh_presets(self) -> None:
        if self.settings is None:
            return
        current = self.preset_names.currentText()
        self.preset_names.blockSignals(True)
        self.preset_names.clear()
        self.preset_names.addItems(self.settings.names())
        # Sólo si había algo escrito: al construir el panel, `current` está vacío y
        # restaurarlo dejaba la casilla en blanco con los presets escondidos adentro.
        if current:
            self.preset_names.setCurrentText(current)
        self.preset_names.blockSignals(False)

    def _load_preset(self) -> None:
        if self.settings is None:
            return
        values = self.settings.presets.get(self.preset_names.currentText())
        if values:
            self.apply_values(values)

    def _save_preset(self) -> None:
        if self.settings is None:
            return
        name = self.preset_names.currentText().strip()
        if not name:
            return
        self.settings.save_preset(name, self.values())
        self._refresh_presets()
        self.preset_names.setCurrentText(name)

    def _delete_preset(self) -> None:
        if self.settings is None:
            return
        self.settings.delete_preset(self.preset_names.currentText())
        self._refresh_presets()

    def _build_group(self, group: GainGroup) -> QGroupBox:
        box = QGroupBox(group.title)
        grid = QGridLayout(box)
        grid.setVerticalSpacing(5)
        grid.setHorizontalSpacing(7)
        for index, spec in enumerate(group.specs):
            widget = _spin(spec.minimum, spec.maximum, spec.default, spec.step, spec.decimals)
            tip = f"/cmd?{spec.param}=…  ·  firmware: {spec.firmware_symbol} = {spec.default:g}"
            if spec.param == "ke":
                tip += (
                    "\n\n≥ 0 fija un override manual que la rama adaptativa respeta; "
                    "< 0 lo suelta y devuelve el control a KE_GAIN_BASE/BOOST.\n"
                    "El override SOBREVIVE a un `m=5` a propósito.\n\n"
                    "0,65 es el valor inicial de la variable, no el que usa el lazo: al "
                    "arrancar, `ke_override` vale −1 y el primer tick de bombeo escribe "
                    "KE_GAIN_BASE = 0,75. `ke_gain` en /state dice cuál rige.\n\n"
                    "⚠ Sin caracterizar en banco: los barridos anteriores a v1.59.0 "
                    "midieron KE_GAIN_BASE contra sí mismo (P23)."
                )
            if spec.inert:
                tip += (
                    f"\n\n⚠ {spec.inert}: el firmware acepta el parámetro y después LO PISA "
                    "en el propio lazo. Lo que se escriba acá sobrevive milisegundos. "
                    "Ver docs/REGISTRO_PROBLEMAS.md."
                )
            widget.setToolTip(tip)
            self.fields[spec.param] = widget
            self._sent[spec.param] = spec.default
            row, column = divmod(index, group.columns)
            grid.addWidget(QLabel(spec.label), row, 2 * column)
            grid.addWidget(widget, row, 2 * column + 1)
            # El estirón va al campo, no al rótulo: sin esto el botón «Enviar», que
            # abarca todas las columnas, repartía el ancho en partes iguales y dejaba
            # «kp» separado de su casilla por media columna vacía.
            grid.setColumnStretch(2 * column, 0)
            grid.setColumnStretch(2 * column + 1, 1)
        send = QPushButton("Enviar")
        send.clicked.connect(lambda _=False, g=group: self._send_group(g))
        rows = (len(group.specs) + group.columns - 1) // group.columns
        grid.addWidget(send, rows, 0, 1, 2 * group.columns)
        return box

    def _send_group(self, group: GainGroup) -> None:
        changed = {
            spec.param: self.fields[spec.param].value()
            for spec in group.specs
            if self.fields[spec.param].value() != self._sent[spec.param]
        }
        if not changed:
            return
        self._sent.update(changed)
        self.command.emit(changed)

    # ── Presets ───────────────────────────────────────────────────────────────

    def values(self) -> dict[str, float]:
        return {param: widget.value() for param, widget in self.fields.items()}

    def apply_values(self, values: dict[str, float]) -> None:
        """Carga un preset en los campos. **No** lo envía: enviar es un acto explícito."""
        for param, value in values.items():
            widget = self.fields.get(param)
            if widget is not None:
                widget.setValue(float(value))


# ── Sesión ────────────────────────────────────────────────────────────────────


class SessionPanel(QWidget):
    """Adquisición, ventana de dibujo, grabación y modo sólo lectura."""

    start_stream = Signal()
    stop_stream = Signal()
    toggle_record = Signal(bool)
    window_changed = Signal(float)
    read_only_changed = Signal(bool)

    def __init__(self, window_s: float = 20.0, rate_hz: float = 500.0, poll_s: float = 0.2) -> None:
        super().__init__()
        self.hz = QComboBox()
        for hz in (500, 250, 100, 50):
            self.hz.addItem(f"{hz} Hz", hz)
        self.set_rate_hz(rate_hz)
        self.poll = _spin(0.05, 1.0, poll_s, 0.05, 2)
        self.poll.setToolTip(
            "El firmware sirve como mucho 512 muestras por respuesta: a 500 Hz, 1,02 s. "
            "Sondear más lento pierde muestras aunque el anillo no se llene."
        )

        self.btn_stream = QPushButton("Adquirir")
        self.btn_stream.setCheckable(True)
        self.btn_stream.toggled.connect(self._on_stream_toggled)

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

        form = QFormLayout()
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 4)
        layout.addLayout(form)
        layout.addStretch(1)

    def set_rate_hz(self, hz: float) -> None:
        """Preselecciona la tasa pedida por línea de comandos, si es una de las ofrecidas."""
        index = self.hz.findData(int(hz))
        if index >= 0:
            self.hz.setCurrentIndex(index)

    def _on_stream_toggled(self, on: bool) -> None:
        (self.start_stream if on else self.stop_stream).emit()

    def set_streaming(self, on: bool) -> None:
        self.hz.setEnabled(not on)
        self.poll.setEnabled(not on)
        # El botón queda diciendo qué está pasando, no qué se puede hacer: con la
        # adquisición corriendo, "Adquirir" apretado se lee como si no hubiera arrancado.
        self.btn_stream.setText("Adquiriendo…" if on else "Adquirir")
        if self.btn_stream.isChecked() != on:
            self.btn_stream.blockSignals(True)
            self.btn_stream.setChecked(on)
            self.btn_stream.blockSignals(False)


# ── Salud ─────────────────────────────────────────────────────────────────────


class HealthPanel(QGroupBox):
    """Salud del enlace y del lazo. La app declara la calidad del canal por el que habla.

    Los contadores de error del transporte se calculaban desde el primer día y **no se
    mostraban en ningún lado**: cuando ``/daq/read`` empezaba a fallar la traza se
    congelaba sin explicación. Ahora tienen su fila, en rojo cuando no son cero.
    """

    def __init__(self) -> None:
        super().__init__("Salud")
        self.fields: dict[str, QLabel] = {}
        form = QFormLayout(self)
        for key, label in (
            ("rate", "tasa efectiva"),
            ("dropped", "muestras perdidas"),
            ("gaps", "huecos / dt máx"),
            ("daq_err", "DAQ: errores · 503"),
            ("link", "RTT /state · edad"),
            ("state_err", "/state: errores"),
            ("loop", "loop_dt_max_us"),
            ("overruns", "loop_overruns"),
            ("ina", "INA219"),
            ("safety", "seguridad: cortes · derates"),
        ):
            value = _value_label()
            self.fields[key] = value
            form.addRow(label, value)

        self.last_error = QLabel("")
        self.last_error.setWordWrap(True)
        self.last_error.setStyleSheet(f"color:{COLOR_BAD}; font-size:11px;")
        self.last_error.setVisible(False)
        form.addRow(self.last_error)

    def update_stream(self, stats: StreamStats) -> None:
        self.fields["rate"].setText(f"{stats.rate_hz:7.1f} Hz  ({stats.samples} muestras)")
        dropped = self.fields["dropped"]
        dropped.setText(f"{stats.dropped}")
        # Rojo y sin eufemismos: una captura con pérdidas no es una captura completa.
        _paint(dropped, COLOR_BAD if stats.dropped else None, bold=bool(stats.dropped))
        self.fields["gaps"].setText(f"{stats.gaps}  ·  {stats.dt_max_ms:.1f} ms")

        errors = self.fields["daq_err"]
        errors.setText(f"{stats.errors}  ·  {stats.busy_503}")
        _paint(errors, COLOR_BAD if stats.errors else (COLOR_WARN if stats.busy_503 else None))
        self._show_error(stats.last_error)

    def update_health(self, health: dict) -> None:
        rtt = health.get("rtt_ms")
        age = health.get("age_s", float("inf"))
        link = self.fields["link"]
        link.setText(
            f"{_fmt(rtt, '6.1f', '     —')} ms · {_fmt(age, '4.1f')} s" if rtt is not None else "— sin lectura"
        )
        # Un enlace muerto se veía igual que uno sano: la edad crecía en gris.
        _paint(link, COLOR_BAD if age >= LINK_BAD_S else (COLOR_WARN if age >= LINK_WARN_S else COLOR_GOOD))

        state_errors = health.get("errors") or 0
        item = self.fields["state_err"]
        item.setText(str(state_errors))
        _paint(item, COLOR_BAD if state_errors else None)

        self.fields["loop"].setText(f"{_fmt(health.get('loop_dt_max_us'))}  (nom {_fmt(health.get('loop_dt_nom_us'))})")
        overruns = health.get("loop_overruns")
        item = self.fields["overruns"]
        item.setText(_fmt(overruns))
        _paint(item, COLOR_BAD if overruns else None, bold=bool(overruns))

        ina = health.get("ina_ok")
        item = self.fields["ina"]
        item.setText("ok" if ina else "SIN INA219")
        # Sin INA219 no hay corte por calado: la protección está gateada por `inaOk`.
        _paint(item, None if ina else COLOR_BAD, bold=not ina)

        # Un corte de la capa de seguridad se veía como «el modo dejó de andar»: el
        # firmware publica el motivo desde v1.60.0 y la app no lo miraba. Los derates
        # van aparte porque `safety_action` se limpia al tick siguiente y un escalado por
        # tensión, sin contador, es literalmente invisible — fue lo que escondió el fallo
        # de homing del 2026-08-06.
        cuts = health.get("safety_cuts") or 0
        derates = health.get("safety_derates") or 0
        action = SAFETY_ACTIONS.get(health.get("safety_action") or 0, "")
        item = self.fields["safety"]
        item.setText(f"{cuts} · {derates}" + (f"   ← {action}" if action else ""))
        _paint(item, COLOR_BAD if (cuts or action) else (COLOR_WARN if derates else None), bold=bool(cuts or action))

        self._show_error(health.get("last_error", ""))

    def _show_error(self, message: str | None) -> None:
        if not message:
            return
        self.last_error.setText(f"último error: {message}")
        self.last_error.setVisible(True)


# ── Análisis ──────────────────────────────────────────────────────────────────


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
            ("attempt", "intento · reintentos"),
            ("failure", "fin del último intento"),
        ):
            value = _value_label()
            self.fields[key] = value
            form.addRow(label, value)
        note = QLabel(
            "El sobrepaso se normaliza por el salto pedido; «legacy» divide por |sp|.\n"
            "«reintentos» no es adorno: sin ese número, «enganchó al primer intento» y "
            "«enganchó al tercero» se leen igual y el reintento automático (rt=1, por "
            "omisión activo desde v1.63.0) infla las tasas de éxito en silencio."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{COLOR_DIM}; font-size:11px;")
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

    def update_attempt(self, state: dict) -> None:
        """Estado del intento de balanceo en curso, tal como lo lleva el firmware.

        Nada de esto se reconstruye desde las trazas: el reintento, el recentrado y el
        motivo de la caída son máquinas de estado del ``.ino`` y sólo el ``.ino`` sabe
        en cuál está. Muestrear el modo desde el cliente llega tarde y da otra cosa.
        """
        if not state:
            self.fields["attempt"].setText("—")
            self.fields["failure"].setText("—")
            return

        count = state.get("swing_retry_count")
        limit = state.get("swing_retry_max")
        if count is None:
            # Firmware anterior a v1.63.0: no hay reintento y no hay nada que declarar.
            self.fields["attempt"].setText("sin reintento (firmware < v1.63.0)")
        else:
            fase = []
            if state.get("swing_recenter_phase"):
                fase.append("recentrando el brazo")
            if state.get("swing_zero_phase"):
                fase.append("esperando quietud (re-cero de α)")
            if not state.get("swing_retry_enabled", True):
                fase.append("reintento DESACTIVADO (rt=0)")
            detalle = "  ·  " + ", ".join(fase) if fase else ""
            self.fields["attempt"].setText(f"{_fmt(count)} de {_fmt(limit)} reintentos{detalle}")
        item = self.fields["attempt"]
        _paint(item, COLOR_WARN if count else None, bold=bool(count))

        reason = state.get("swing_fail_reason") or 0
        item = self.fields["failure"]
        # `swing_zero_ok = 0` DESPUÉS de un intento significa que no se aquietó y el modo
        # abortó a 0: el firmware no arranca a ciegas y la app tampoco debe callarlo.
        aborto_por_quietud = (
            not reason
            and state.get("swing_zero_enabled")
            and state.get("swing_zero_ok") is not None
            and not state.get("swing_zero_ok")
            and not state.get("swing_zero_phase")
        )
        if aborto_por_quietud:
            item.setText("el péndulo no se aquietó: no se pudo re-establecer el cero")
            _paint(item, COLOR_WARN, bold=True)
            return
        item.setText(SWING_FAIL_REASONS.get(int(reason), f"código {reason}") if reason else "sin fallas")
        _paint(item, COLOR_BAD if reason else None, bold=bool(reason))

    def update_handoff(self, summary: dict | None) -> None:
        if summary is None:
            self.fields["handoff"].setText("sin traspaso")
            self.fields["energy"].setText("—")
            return
        reasons = "+".join(summary.get("reasons") or []) or "?"
        # Todo con `_fmt`: un `/state` parcial lanzaba dentro del slot del QTimer.
        alpha = _fmt(summary.get("alpha_deg"), "+.2f")
        vel = _fmt(summary.get("vel_dps"), ".1f")
        self.fields["handoff"].setText(f"{reasons}  α={alpha}°  |α̇|={vel}°/s")
        self.fields["energy"].setText(_fmt(summary.get("energy_ratio"), ".4f"))


class StatusBanner(QLabel):
    """Aviso sobre el alcance del failsafe. No es decorativo.

    Una línea con el detalle en el tooltip: el texto completo ocupaba un tercio de la
    columna y lo que se lee todos los días termina siendo invisible igual.
    """

    DETAIL = (
        "El watchdog del firmware sólo cubre los modos 1 (PWM manual) y 6 (RL por HTTP).\n\n"
        "Los modos 2 (PID), 4 (LQR) y 5 (swing-up) son autónomos por diseño y siguen "
        "corriendo aunque muera el enlace: el único respaldo es el límite duro de ±95° "
        "del brazo, que dispara setMode(0).\n\n"
        "Tener el corte de alimentación a mano."
    )

    def __init__(self) -> None:
        super().__init__("⚠  El watchdog sólo cubre m1 y m6 — m2/m4/m5 siguen sin enlace")
        self.setToolTip(self.DETAIL)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setStyleSheet(
            f"background:#2a1f14; color:{COLOR_WARN}; border:1px solid #4a3a22;"
            "border-radius:4px; padding:5px 8px; font-size:11px;"
        )
