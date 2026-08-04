"""
Tarjeta de pinout FISICO de la placa ESP32 DevKit V1 de 30 pines (QUBE v2).

A diferencia de system_wiring_l298n.py, que es un diagrama de redes (que se conecta
con que), esta figura dibuja la placa con sus dos headers en ORDEN FISICO, numerados
desde el extremo del USB, para poder cablear en el banco contando posiciones.

Marca en rojo las trampas de esta placa:
  1. Los 4 canales de encoder ocupan izq. #9-#12 en orden 33,32,35,34 -- INVERSO al
     del conector J4 de la perfboard (34,35,32,33): la cinta va cruzada.
  2. IN1/IN2 tambien van INVERTIDOS: el header baja D27(IN2), D26(IN1), mientras que
     el bloque del L298N va IN1, IN2. Una cinta recta los permuta, y permutarlos deja
     el lazo en realimentacion POSITIVA (MOTOR_DIR=-1 espera que un PWM crudo positivo
     BAJE la posicion). Medido en banco el 2026-08-03.
  3. SDA (der. #11) y SCL (der. #14) NO son contiguos: entre medio estan RX0 y TX0,
     que son la UART0 del USB.
  4. GPIO0 y GPIO6-11 no existen en esta placa (ninguno se usa).

Uso:  uv run python docs/hardware/pinout_esp32_30.py
Salida: docs/hardware/pinout_esp32_30.png
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

# --- colores por red (mismos que system_wiring_l298n.py) ---
C_5VE = "#e53935"   # 5 V dedicado ESP32 (LM2596 #2)
C_3V3 = "#fb8c00"   # rail 3V3 (regulador interno)
C_GND = "#37474f"   # tierra
C_I2C = "#039be5"   # I2C (SDA/SCL)
C_PWM = "#2e7d32"   # control PWM/dir (ESP32 -> L298N)
C_OUT = "#d81b60"   # senal de encoder acondicionada (RC -> GPIO)
C_ENA = "#7cb342"   # ENA: cableable pero sin conectar (opcion A)
C_WARN = "#c62828"  # trampa / no tocar
C_FREE = "#b0bec5"  # pin libre

C_BOARD = "#1565c0"
C_USB = "#455a64"

# (silkscreen, funcion, color, nota).  funcion None => pin libre.
LEFT = [
    ("VIN", "5 V  <- LM2596 #2", C_5VE, "riel dedicado, anti-brownout"),
    ("GND", "GND comun", C_GND, "topologia estrella"),
    ("D13", None, None, None),
    ("D12", None, None, None),
    ("D14", None, None, None),
    ("D27", "L298N IN2", C_WARN, "OJO: IN2 va ARRIBA de IN1"),
    ("D26", "L298N IN1", C_WARN, "el header va IN2,IN1 - cinta CRUZADA"),
    ("D25", "L298N ENA", C_ENA, "SIN CONECTAR (opcion A)"),
    ("D33", "Enc. pendulo B", C_OUT, "J4"),
    ("D32", "Enc. pendulo A", C_OUT, "J4"),
    ("D35", "Enc. servo B", C_OUT, "J4 - input only"),
    ("D34", "Enc. servo A", C_OUT, "J4 - input only"),
    ("VN", None, None, "GPIO39"),
    ("VP", None, None, "GPIO36"),
    ("EN", None, None, "reset"),
]

RIGHT = [
    ("3V3", "Vcc CD40106BE x2", C_3V3, "+ pull-ups 2k2 x4"),
    ("GND", "GND comun", C_GND, "una sola bajada"),
    ("D15", None, None, None),
    ("D2", None, None, None),
    ("D4", None, None, None),
    ("RX2", None, None, "GPIO16"),
    ("TX2", None, None, "GPIO17"),
    ("D5", None, None, None),
    ("D18", None, None, None),
    ("D19", None, None, None),
    ("D21", "INA219 SDA", C_I2C, ""),
    ("RX0", "UART0 del USB", C_WARN, "NO cablear aqui"),
    ("TX0", "UART0 del USB", C_WARN, "NO cablear aqui"),
    ("D22", "INA219 SCL", C_I2C, ""),
    ("D23", None, None, None),
]

fig, ax = plt.subplots(figsize=(17, 12))

# --- geometria ---
# La cabecera de la placa (BY1 .. Y_TOP) se deja libre a proposito: ahi van el
# titulo y el subtitulo, que si no pisan las filas #1 y #2.
BX0, BX1 = 40.0, 60.0          # bordes de la placa
BY0, BY1 = 12.0, 92.0          # abajo / arriba
Y_TOP = 82.0                   # centro del pin #1 (junto al USB)
Y_BOT = 18.0                   # centro del pin #15
DY = (Y_TOP - Y_BOT) / 14.0    # separacion entre pines

# cuerpo de la placa
ax.add_patch(FancyBboxPatch((BX0, BY0), BX1 - BX0, BY1 - BY0,
             boxstyle="round,pad=0.3,rounding_size=1.0",
             fc=C_BOARD, ec="#0d47a1", lw=1.6, zorder=2))
# conector USB
ax.add_patch(FancyBboxPatch((46.5, BY1 - 0.6), 7, 4.2,
             boxstyle="round,pad=0.2,rounding_size=0.5",
             fc=C_USB, ec="#000", lw=1.0, zorder=3))
ax.text(50, BY1 + 1.6, "USB", ha="center", va="center", fontsize=9,
        color="white", fontweight="bold", zorder=4)

ax.text(50, BY1 - 3.5, "ESP32 DevKit V1", ha="center", va="center",
        fontsize=14, color="white", fontweight="bold", zorder=4)
ax.text(50, BY1 - 7.2, "30 pines - modulo WROOM-32", ha="center", va="center",
        fontsize=9.5, color="#bbdefb", zorder=4)
ax.text(50, BY0 - 3.5, "vista desde arriba, USB hacia arriba",
        ha="center", va="center", fontsize=9, color="#546e7a",
        style="italic", zorder=4)


def draw_row(pins, side):
    """side: 'L' o 'R'. Dibuja los 15 pines de una fila con sus etiquetas."""
    x_pin = BX0 if side == "L" else BX1
    sign = -1 if side == "L" else 1
    ha_out = "right" if side == "L" else "left"

    for i, (silk, func, color, note) in enumerate(pins):
        y = Y_TOP - i * DY
        libre = func is None
        c = C_FREE if libre else color

        # circulo del pin
        ax.add_patch(Circle((x_pin, y), 0.95, fc=c, ec="#000", lw=0.7, zorder=6))
        # numero de posicion, dentro de la placa
        ax.text(x_pin - sign * 2.6, y, f"#{i + 1}", ha="center", va="center",
                fontsize=7, color="#e3f2fd", fontweight="bold", zorder=7)
        # serigrafia, dentro de la placa
        ax.text(x_pin - sign * 6.4, y, silk, ha="center", va="center",
                fontsize=9, color="white", fontweight="bold", zorder=7)

        # etiqueta de funcion, afuera
        x_lbl = x_pin + sign * 2.4
        if libre:
            txt = "libre" + (f"  ({note})" if note else "")
            ax.text(x_lbl, y, txt, ha=ha_out, va="center", fontsize=8,
                    color="#78909c", style="italic", zorder=7)
        else:
            # linea corta de salida, del color de la red
            ax.plot([x_pin + sign * 1.1, x_pin + sign * 2.1], [y, y],
                    color=c, lw=2.2, zorder=5, solid_capstyle="round")
            ax.text(x_lbl, y + 0.9, func, ha=ha_out, va="center", fontsize=9.5,
                    color=c, fontweight="bold", zorder=7)
            if note:
                ax.text(x_lbl, y - 1.4, note, ha=ha_out, va="center",
                        fontsize=7.5, color="#546e7a", zorder=7)


draw_row(LEFT, "L")
draw_row(RIGHT, "R")

ax.text(BX0 - 2.4, Y_TOP + 4.2, "FILA IZQUIERDA", ha="right", va="center",
        fontsize=10, color="#37474f", fontweight="bold")
ax.text(BX1 + 2.4, Y_TOP + 4.2, "FILA DERECHA", ha="left", va="center",
        fontsize=10, color="#37474f", fontweight="bold")


# =========================================================================
# Trampa 1: la cinta de encoders va CRUZADA
# =========================================================================
y_33 = Y_TOP - 8 * DY    # D33 -> izq #9
y_34 = Y_TOP - 11 * DY   # D34 -> izq #12
x_br = BX0 - 24.0

ax.plot([x_br + 1.2, x_br, x_br, x_br + 1.2],
        [y_33 + 1.0, y_33 + 1.0, y_34 - 1.0, y_34 - 1.0],
        color=C_WARN, lw=1.8, zorder=6)
ax.text(x_br - 1.0, (y_33 + y_34) / 2,
        "J4 de la perfboard: 34, 35, 32, 33\n"
        "header:            33, 32, 35, 34\n"
        "ORDEN INVERSO -> cinta cruzada\n"
        "(lo mismo pasa con IN1/IN2 arriba)",
        ha="right", va="center", fontsize=9, color=C_WARN, fontweight="bold",
        zorder=7,
        bbox=dict(boxstyle="round,pad=0.5", fc="#ffebee", ec=C_WARN, lw=1.2))

# =========================================================================
# Trampa 2: SDA y SCL no son contiguos
# =========================================================================
y_21 = Y_TOP - 10 * DY   # D21 -> der #11
y_22 = Y_TOP - 13 * DY   # D22 -> der #14
x_br2 = BX1 + 26.0

ax.plot([x_br2 - 1.2, x_br2, x_br2, x_br2 - 1.2],
        [y_21 + 1.0, y_21 + 1.0, y_22 - 1.0, y_22 - 1.0],
        color=C_WARN, lw=1.8, zorder=6)
ax.text(x_br2 + 1.0, (y_21 + y_22) / 2,
        "SDA y SCL NO son contiguos:\n"
        "entre medio estan RX0 y TX0.\n"
        "Correrse una posicion = UART0 del USB\n"
        "(se pierde el flasheo por serie)",
        ha="left", va="center", fontsize=9, color=C_WARN, fontweight="bold",
        zorder=7,
        bbox=dict(boxstyle="round,pad=0.5", fc="#ffebee", ec=C_WARN, lw=1.2))

# =========================================================================
# Nota: pines que esta placa no expone
# =========================================================================
ax.text(50, 2.5,
        "Esta placa NO expone GPIO0 ni GPIO6-11 (flash SPI): ninguno se usa, por eso la "
        "migracion desde la de 38 pines no requirio renumerar nada.\n"
        "Ninguno de los 9 GPIO en uso es pin de strapping (0, 2, 4, 5, 12, 15) -> el "
        "cableado no puede dejar la placa en un modo de arranque equivocado.",
        ha="center", va="center", fontsize=9, color="#37474f", zorder=7,
        bbox=dict(boxstyle="round,pad=0.55", fc="#eceff1", ec="#90a4ae", lw=1.0))

# =========================================================================
# Leyenda
# =========================================================================
handles = [
    mpatches.Patch(color=C_OUT, label="senal de encoder acondicionada (J4)"),
    mpatches.Patch(color=C_PWM, label="PWM / direccion -> L298N"),
    mpatches.Patch(color=C_I2C, label="I2C -> INA219"),
    mpatches.Patch(color=C_5VE, label="5 V dedicado (LM2596 #2)"),
    mpatches.Patch(color=C_3V3, label="3V3 (regulador interno)"),
    mpatches.Patch(color=C_GND, label="GND comun"),
    mpatches.Patch(color=C_ENA, label="ENA: cableable, sin conectar (opcion A)"),
    mpatches.Patch(color=C_WARN, label="NO cablear / trampa"),
    mpatches.Patch(color=C_FREE, label="pin libre"),
]
# Fuera del area de dibujo, abajo: con ncol=3 no tapa el recuadro de notas.
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
          fontsize=9, ncol=3, frameon=True, framealpha=0.95)

ax.set_title("QUBE v2 - Pinout fisico ESP32 DevKit V1 (30 pines)\n"
             "Posiciones contadas desde el extremo del USB - "
             "VERIFICAR contra el serigrafiado: hay clones con las filas espejadas",
             fontsize=14, fontweight="bold", pad=16)

ax.set_xlim(0, 100)
ax.set_ylim(-2, 98)
ax.set_aspect("equal")
ax.axis("off")

out = Path(__file__).with_suffix(".png")
fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
print(f"OK -> {out}")
