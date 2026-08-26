"""Paleta y hoja de estilos de la app. Un solo lugar donde está definido el color.

La paleta la fijan **las trazas**, no los controles: θ, α, PWM y potencia ya tenían un
color cada una y la interfaz se construye alrededor de eso, así que el azul de un botón
primario es el mismo azul de θ. Un panel que usa colores propios obliga a traducir
mentalmente entre la gráfica y el control que la mueve.

La hoja anterior era una línea (``QWidget{background:#0d1017;}``) y dejaba botones,
combos y spinboxes con el estilo nativo de Windows sobre fondo oscuro: sin borde, sin
hover, sin foco visible. Aquí se estilan explícitamente, incluido el ``:disabled``, que
es el estado que importa cuando el modo sólo lectura apaga medio panel.

Los tres colores de estado —verde, ámbar, rojo— se usan **sólo** para estado, nunca para
decorar: si algo está en rojo en esta app, hay que mirarlo.
"""

from __future__ import annotations

# ── Trazas ────────────────────────────────────────────────────────────────────
COLOR_THETA = "#4da3ff"
COLOR_ALPHA = "#ffb454"
COLOR_PWM = "#57d68a"
COLOR_POWER = "#c792ea"
COLOR_GRID = "#2a2f3a"
COLOR_MARK = "#ff5c7a"

# ── Superficies ───────────────────────────────────────────────────────────────
BG_APP = "#0d1017"
BG_PANEL = "#12151c"
BG_ELEVATED = "#171c26"
BG_INPUT = "#0a0d13"
BORDER = "#232833"
BORDER_STRONG = "#323a4b"

# ── Texto y estado ────────────────────────────────────────────────────────────
COLOR_TEXT = "#c8cfdb"
COLOR_DIM = "#7c869b"
COLOR_TITLE = "#8fa0bd"
COLOR_ACCENT = COLOR_THETA
COLOR_GOOD = "#57d68a"
COLOR_WARN = "#ffb454"
COLOR_BAD = "#ff5c7a"
COLOR_ESTOP = "#a01530"

#: Monoespaciada sólo para valores numéricos: es donde importa que las columnas alineen.
MONO = "font-family:Consolas,'Cascadia Mono',monospace;"

#: Color por modo del firmware. Vive acá y no en los paneles porque lo usan dos lugares
#: que tienen que coincidir: el chip de la barra superior y las bandas de fondo de las
#: trazas. Si divergen, el operador ve dos códigos de color para la misma cosa.
MODE_COLORS = {
    0: COLOR_DIM,  # libre / STOP
    1: COLOR_WARN,  # PWM manual
    2: COLOR_THETA,  # PID servo
    3: COLOR_WARN,  # homing
    4: COLOR_GOOD,  # LQR
    5: COLOR_ALPHA,  # swing-up
    6: COLOR_POWER,  # RL por HTTP
    7: COLOR_POWER,  # RL en el chip
}

STYLESHEET = f"""
QWidget {{
    background: {BG_APP};
    color: {COLOR_TEXT};
    font-size: 12px;
}}
QMainWindow, QScrollArea, QSplitter {{ background: {BG_APP}; }}

QGroupBox {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 9px;
    padding: 0 4px;
    color: {COLOR_TITLE};
}}

QLabel {{ background: transparent; }}
QLabel:disabled {{ color: {COLOR_DIM}; }}

/* ── Botones ─────────────────────────────────────────────────────────────── */
QPushButton {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 5px 12px;
    color: {COLOR_TEXT};
}}
QPushButton:hover {{ background: #1e2531; border-color: {COLOR_ACCENT}; }}
QPushButton:pressed {{ background: #0f131a; }}
QPushButton:disabled {{ background: {BG_PANEL}; border-color: {BORDER}; color: #4a5262; }}
QPushButton:checked {{
    background: rgba(77, 163, 255, 0.18);
    border-color: {COLOR_ACCENT};
    color: {COLOR_ACCENT};
    font-weight: 600;
}}
QPushButton:focus {{ outline: none; border-color: {COLOR_ACCENT}; }}

/* ── Campos numéricos y combos ───────────────────────────────────────────── */
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 18px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {BG_APP};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #43506a; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {BG_PANEL};
    color: #4a5262;
    border-color: {BORDER};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    /* Qt no dibuja la flecha nativa sobre un fondo oscuro con un contraste usable, así
       que se hace con un borde girado: sin recurso externo, que el .exe no empaqueta. */
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLOR_DIM};
    width: 0; height: 0;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {COLOR_ACCENT};
    selection-color: {BG_APP};
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {BG_ELEVATED};
    border: none;
    width: 15px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #263043; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {COLOR_DIM};
    width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {COLOR_DIM};
    width: 0; height: 0;
}}

/* ── Casillas ────────────────────────────────────────────────────────────── */
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:hover {{ border-color: {COLOR_ACCENT}; }}
QCheckBox::indicator:checked {{ background: {COLOR_ACCENT}; border-color: {COLOR_ACCENT}; }}

/* ── Pestañas ────────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {BG_PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {COLOR_DIM};
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 6px 12px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {COLOR_TEXT}; }}
QTabBar::tab:selected {{
    color: {COLOR_ACCENT};
    border-bottom: 2px solid {COLOR_ACCENT};
    font-weight: 600;
}}
QTabBar:focus {{ outline: none; }}

/* ── Barras de desplazamiento ────────────────────────────────────────────── */
/* Contraste alto a propósito: la barra es la única señal de que un panel sigue hacia
   abajo, y con el gris tenue anterior el contenido cortado parecía contenido ausente. */
QScrollBar:vertical {{ background: {BG_INPUT}; width: 11px; margin: 0; border-radius: 5px; }}
QScrollBar::handle:vertical {{ background: #46536b; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #5a6a88; }}
QScrollBar:horizontal {{ background: {BG_INPUT}; height: 11px; margin: 0; border-radius: 5px; }}
QScrollBar::handle:horizontal {{ background: #46536b; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #5a6a88; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Varios ──────────────────────────────────────────────────────────────── */
QToolTip {{
    background: {BG_ELEVATED};
    color: {COLOR_TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 5px 7px;
}}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover {{ background: {COLOR_ACCENT}; }}
QMessageBox {{ background: {BG_PANEL}; }}
"""

#: El paro no comparte estilo con ningún otro botón, a propósito: tiene que ser
#: inconfundible incluso de reojo y no debe parecerse a nada que se apriete por rutina.
ESTOP_STYLE = f"""
QPushButton {{
    background: {COLOR_ESTOP};
    color: white;
    font-weight: 800;
    font-size: 14px;
    letter-spacing: 1px;
    border: 1px solid #c81c3c;
    border-radius: 6px;
    padding: 8px 14px;
}}
QPushButton:hover {{ background: #c81c3c; }}
QPushButton:pressed {{ background: #7d0f24; }}
"""
