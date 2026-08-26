"""
Diagrama de cableado COMPLETO del sistema QUBE (ayuda visual, no a escala).
Configuracion L298N + DOBLE LM2596, tal como esta montado hoy:
  Fuente 15 V -> INA219 -> L298N -> Motor.   (SIN fusible en linea)
  LM2596 #2 (buck 15->5 V) alimenta SOLO el ESP32 (rail 5V-E, aislado).
  LM2596 #1 (buck 15->5 V) alimenta la logica: L298N +5V, encoders y protoboard (rail 5V-L).
  2x CD40106BE para acondicionamiento (pull-ups 2k2 + doble inversion + RC 10k/10n).
  ESP32 DevKit V1 de 30 pines como concentrador (PWM IN1/IN2, I2C, encoders).

Diferencias respecto de versiones anteriores de esta figura:
  - Sin fusible de 1.5 A: la fuente entra directo al INA219.
  - Sin condensadores electroliticos (1000 uF del 5V-E, 470 uF del 15 V, 10 uF del 3V3)
    ni el ceramico de 100 nF del riel 3V3. Los unicos condensadores que quedan son los
    ceramicos de senal: 10 nF de cada filtro RC y 100 nF de bypass por CD40106BE.
  - El ESP32 se dibuja como el header FISICO de 30 pines (dos filas, #1 junto al USB),
    en el mismo orden y con los mismos colores que docs/hardware/pinout_esp32_30.py.

Uso:  uv run python docs/hardware/system_wiring_l298n.py
Salida: docs/hardware/system_wiring_l298n.png
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

# --- colores por red ---
C_15V = "#00695c"   # potencia 15 V (fuente / VS motor)
C_5VE = "#e53935"   # bus 5 V ESP32   (LM2596 #2, aislado)
C_5VL = "#3949ab"   # bus 5 V logica  (LM2596 #1: L298N +5V, encoders, protoboard)
C_3V3 = "#fb8c00"   # bus 3V3 (regulador ESP32)
C_GND = "#37474f"   # tierra
C_I2C = "#039be5"   # I2C (SDA/SCL)
C_PWM = "#2e7d32"   # control PWM/dir (ESP32 -> L298N)
C_SIG = "#8e24aa"   # senal encoder A/B (open-drain)
C_OUT = "#d81b60"   # senal acondicionada (RC -> GPIO)
C_MOT = "#000000"   # potencia del motor (M+/M-)

C_ENA = "#7cb342"   # ENA: cableable pero sin conectar (opcion A)
C_WARN = "#c62828"  # trampa / no cablear
C_FREE = "#b0bec5"  # pin libre

C_BLK = "#455a64"   # modulos de potencia
C_CHIP = "#263238"  # chips
C_MCU = "#1565c0"   # ESP32
C_ENC = "#6a1b9a"   # encoders
C_SRC = "#004d40"   # fuente
C_USB = "#455a64"
C_PIN = "#ffd54f"
C_RES = "#8d6e63"
C_CAP = "#1e88e5"

P: dict[str, tuple[float, float]] = {}

fig, ax = plt.subplots(figsize=(20, 12.2))


def block(x, y, w, h, title, fc, sub=None, tc="white", fs=11):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle="round,pad=0.1,rounding_size=1.2",
                 fc=fc, ec="#000", lw=1.3, zorder=3))
    ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="top",
            color=tc, fontweight="bold", fontsize=fs, zorder=6)
    if sub:
        ax.text(x + w / 2, y + h - 6.4, sub, ha="center", va="top",
                color="#cfd8dc", fontsize=7.5, zorder=6)
    return x, y, w, h


def pin(name, x, y, label, dx=0.0, dy=0.0, ha="center", va="center",
        color=C_PIN, fs=7):
    ax.add_patch(Circle((x, y), 0.75, fc=color, ec="#000", lw=0.5, zorder=6))
    ax.text(x + dx, y + dy, label, ha=ha, va=va, fontsize=fs,
            color="#111", fontweight="bold", zorder=7)
    P[name] = (x, y)


def net(pts, color, lw=2.0, ls="-", z=2):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z,
            solid_capstyle="round", dash_capstyle="round")


def link(a, b, color, lw=2.0, ls="-", via=None, z=2):
    pts = [P[a]] + (via or []) + [P[b]]
    net(pts, color, lw=lw, ls=ls, z=z)


def dot(x, y, color=C_GND):
    ax.add_patch(Circle((x, y), 0.8, fc=color, ec=color, zorder=7))


def rlabel(x, y, txt, color):
    ax.text(x, y, txt, ha="left", va="center", fontsize=8.5,
            color=color, fontweight="bold", zorder=8)


def comp(x, y, w, h, color, label, fs=6.5):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle="round,pad=0.02,rounding_size=0.4",
                 fc=color, ec="#000", lw=0.6, zorder=5))
    ax.text(x, y, label, ha="center", va="center", fontsize=fs,
            color="white", fontweight="bold", zorder=6)


# =========================================================================
# RAILS de alimentacion
# =========================================================================
GND_Y = 4
V5_Y = 96     # rail 5V-L (logica): encoders + L298N +5V
V3_Y = 154    # rail 3V3: sale del pin 3V3 del ESP32 (fila derecha #1)
net([(8, GND_Y), (262, GND_Y)], C_GND, lw=4)
net([(10, V5_Y), (150, V5_Y)], C_5VL, lw=3)   # 5V-L termina antes del ESP32
net([(36, V3_Y), (252, V3_Y)], C_3V3, lw=3)
rlabel(151, V5_Y, "5V-L", C_5VL)
rlabel(263, GND_Y, "GND", C_GND)
rlabel(253.5, V3_Y, "3V3", C_3V3)

# espinas 3V3 hacia la zona de senal (pull-ups + Vcc de los chips)
net([(36, V3_Y), (36, 30)], C_3V3, lw=2)
net([(36, 60), (82, 60)], C_3V3, lw=2)
net([(36, 30), (82, 30)], C_3V3, lw=2)

# =========================================================================
# CADENA DE POTENCIA:  Fuente -> INA219 -> L298N -> Motor   (sin fusible)
# =========================================================================
block(6, 104, 20, 16, "FUENTE", C_SRC, sub="15 V DC")
pin("SRC_P", 26, 116, "+15V", dx=-1.2, ha="right", fs=7)
pin("SRC_G", 26, 108, "GND", dx=-1.2, ha="right", fs=7)

block(70, 104, 30, 18, "INA219", C_BLK, sub="sensor de corriente")
pin("INA_VINp", 70, 116, "VIN+", dx=1.4, ha="left", fs=6.5)
pin("INA_VINm", 100, 116, "VIN-", dx=-1.4, ha="right", fs=6.5)
pin("INA_VCC", 76, 104, "VCC", dy=1.6, fs=6)
pin("INA_GND", 82, 104, "GND", dy=1.6, fs=6)
pin("INA_SDA", 90, 104, "SDA", dy=1.6, fs=6)
pin("INA_SCL", 96, 104, "SCL", dy=1.6, fs=6)

block(118, 100, 34, 26, "L298N", C_BLK, sub="puente H dual")
pin("L_VS", 118, 122, "VS +15V", dx=1.4, ha="left", fs=6)
pin("L_5V", 118, 113, "+5V", dx=1.4, ha="left", fs=6.5)
pin("L_GND", 118, 104, "GND", dx=1.4, ha="left", fs=6.5)
pin("L_IN1", 126, 100, "IN1", dy=1.6, fs=6)
pin("L_IN2", 134, 100, "IN2", dy=1.6, fs=6)
pin("L_ENA", 142, 100, "ENA", dy=1.6, fs=6)
pin("L_O1", 152, 120, "OUT1", dx=-1.4, ha="right", fs=6)
pin("L_O2", 152, 106, "OUT2", dx=-1.4, ha="right", fs=6)

block(158, 105, 24, 18, "MOTOR", "#5d4037", sub="DC")
pin("MOT_p", 158, 118, "M+", dx=1.4, ha="left", fs=6.5)
pin("MOT_m", 158, 110, "M-", dx=1.4, ha="left", fs=6.5)

# --- LM2596 #1 (logica): 15->5 V, alimenta L298N +5V, encoders y protoboard ---
block(70, 76, 30, 16, "LM2596 #1", C_BLK, sub="buck 15->5 V - logica")
pin("L2_INp", 76, 92, "IN+", dy=-1.6, fs=6)
pin("L2_OUTp", 94, 92, "OUT+", dy=-1.6, fs=5.5)
pin("L2_INm", 82, 76, "IN-", dy=-1.6, fs=6)
pin("L2_OUTm", 88, 76, "OUT-", dy=-1.6, fs=5.5)

# --- LM2596 #2 (ESP32): 15->5 V, alimenta SOLO el ESP32 (rail aislado) ---
block(36, 72, 28, 14, "LM2596 #2", C_BLK, sub="buck 15->5 V - ESP32", fs=10)
pin("L1_INp", 42, 86, "IN+", dy=-1.6, fs=6)
pin("L1_OUTp", 58, 86, "OUT+", dy=-1.6, fs=5.5)
pin("L1_INm", 48, 72, "IN-", dy=-1.6, fs=6)
pin("L1_OUTm", 54, 72, "OUT-", dy=-1.6, fs=5.5)

# =========================================================================
# ESP32 DevKit V1 - header FISICO de 30 pines (#1 = extremo del USB)
# Mismo orden y colores que docs/hardware/pinout_esp32_30.py
# =========================================================================
ESP_X0, ESP_X1 = 200.0, 240.0
ESP_TOP = 126.0     # centro del pin #1 de cada fila
ESP_DY = 8.0        # separacion entre pines

# (serigrafia, clave en P, etiqueta de funcion, color).  etiqueta None => pin libre.
ESP_LEFT = [
    ("VIN", "ESP_VIN", "5 V <- LM2596 #2", C_5VE),
    ("GND", "ESP_GNDL", "GND (alternativa)", C_FREE),
    ("D13", None, None, None),
    ("D12", None, None, None),
    ("D14", None, None, None),
    ("D27", "ESP_D27", "L298N IN2", C_PWM),
    ("D26", "ESP_D26", "L298N IN1", C_PWM),
    ("D25", "ESP_D25", "ENA - sin conectar", C_ENA),
    ("D33", "ESP_D33", "pend. B", C_OUT),
    ("D32", "ESP_D32", "pend. A", C_OUT),
    ("D35", "ESP_D35", "servo B", C_OUT),
    ("D34", "ESP_D34", "servo A", C_OUT),
    ("VN", None, None, None),
    ("VP", None, None, None),
    ("EN", "ESP_EN", "reset", C_FREE),
]

ESP_RIGHT = [
    ("3V3", "ESP_3V3", "Vcc U1/U2 + pull-ups", C_3V3),
    ("GND", "ESP_GNDR", "GND comun (estrella)", C_GND),
    ("D15", None, None, None),
    ("D2", None, None, None),
    ("D4", None, None, None),
    ("RX2", None, None, None),
    ("TX2", None, None, None),
    ("D5", None, None, None),
    ("D18", None, None, None),
    ("D19", None, None, None),
    ("D21", "ESP_D21", "INA219 SDA", C_I2C),
    ("RX0", None, "UART0 del USB", C_WARN),
    ("TX0", None, "UART0 del USB", C_WARN),
    ("D22", "ESP_D22", "INA219 SCL", C_I2C),
    ("D23", None, None, None),
]

ax.add_patch(FancyBboxPatch((ESP_X0, 8), ESP_X1 - ESP_X0, 132,
             boxstyle="round,pad=0.3,rounding_size=1.2",
             fc=C_MCU, ec="#0d47a1", lw=1.5, zorder=3))
# conector USB, arriba (define el pin #1 de cada fila)
ax.add_patch(FancyBboxPatch((212, 138.4), 16, 4.4,
             boxstyle="round,pad=0.2,rounding_size=0.5",
             fc=C_USB, ec="#000", lw=0.9, zorder=4))
ax.text(220, 140.6, "USB", ha="center", va="center", fontsize=7,
        color="white", fontweight="bold", zorder=5)
ax.text(220, 135.4, "ESP32 DevKit V1", ha="center", va="center",
        fontsize=11, color="white", fontweight="bold", zorder=6)
ax.text(220, 131.4, "30 pines - vista superior, USB arriba",
        ha="center", va="center", fontsize=6.5, color="#bbdefb", zorder=6)


def esp_row(pins, side):
    """side: 'L' o 'R'. Dibuja los 15 pines de una fila del header."""
    x = ESP_X0 if side == "L" else ESP_X1
    sign = 1 if side == "L" else -1          # hacia adentro de la placa
    for i, (silk, key, func, color) in enumerate(pins):
        y = ESP_TOP - i * ESP_DY
        libre = func is None
        c = C_FREE if libre else color
        ax.add_patch(Circle((x, y), 0.75, fc=c, ec="#000", lw=0.5, zorder=6))
        if key:
            P[key] = (x, y)
        ax.text(x + sign * 2.7, y, f"#{i + 1}", ha="center", va="center",
                fontsize=5.5, color="#e3f2fd", fontweight="bold", zorder=7)
        ax.text(x + sign * 6.2, y, silk, ha="center", va="center",
                fontsize=7, color="white", fontweight="bold", zorder=7)
        if libre:
            ax.text(x + sign * 8.6, y, "libre",
                    ha="left" if side == "L" else "right", va="center",
                    fontsize=5.5, color="#cfd8dc", style="italic", zorder=7)
        elif side == "R":
            # etiqueta adentro: a la derecha no llega ningun cable por el borde
            ax.text(ESP_X1 - 15.5, y, func, ha="right", va="center",
                    fontsize=6, color=c, fontweight="bold", zorder=7)
        else:
            # etiqueta afuera y por debajo del cable que entra a ese pin
            ax.text(ESP_X0 - 3.0, y - 2.5, func, ha="right", va="center",
                    fontsize=6.3, color=c, fontweight="bold", zorder=7)


esp_row(ESP_LEFT, "L")
esp_row(ESP_RIGHT, "R")

# =========================================================================
# ACONDICIONAMIENTO: encoders -> CD40106 (x2 inv) -> RC -> GPIO
# =========================================================================
block(6, 40, 16, 14, "ENC", C_ENC, sub="servo")
pin("ES_A", 22, 50, "A", dx=-1.4, ha="right", fs=6.5)
pin("ES_B", 22, 44, "B", dx=-1.4, ha="right", fs=6.5)
pin("ES_5V", 10, 40, "5V", dy=1.6, fs=6)
pin("ES_G", 16, 40, "GND", dy=1.6, fs=6)

block(6, 10, 16, 14, "ENC", C_ENC, sub="pendulo")
pin("EP_A", 22, 20, "A", dx=-1.4, ha="right", fs=6.5)
pin("EP_B", 22, 14, "B", dx=-1.4, ha="right", fs=6.5)
pin("EP_5V", 10, 10, "5V", dy=1.6, fs=6)
pin("EP_G", 16, 10, "GND", dy=1.6, fs=6)

block(46, 38, 28, 18, "U1 CD40106BE", C_CHIP, sub="servo - doble inversion")
pin("U1_Ai", 46, 50, "A", dx=1.4, ha="left", fs=6)
pin("U1_Bi", 46, 42, "B", dx=1.4, ha="left", fs=6)
pin("U1_Ao", 74, 50, "", color=C_OUT)
pin("U1_Bo", 74, 42, "", color=C_OUT)
pin("U1_Vcc", 60, 56, "14", dy=-1.4, fs=6)
pin("U1_G", 60, 38, "7", dy=1.4, fs=6)

block(46, 8, 28, 18, "U2 CD40106BE", C_CHIP, sub="pendulo - doble inversion")
pin("U2_Ai", 46, 20, "A", dx=1.4, ha="left", fs=6)
pin("U2_Bi", 46, 12, "B", dx=1.4, ha="left", fs=6)
pin("U2_Ao", 74, 20, "", color=C_OUT)
pin("U2_Bo", 74, 12, "", color=C_OUT)
pin("U2_Vcc", 60, 26, "14", dy=-1.4, fs=6)
pin("U2_G", 60, 8, "7", dy=1.4, fs=6)

# =========================================================================
# NETS
# =========================================================================
# ---- 15 V: Fuente -> nodo -> {INA219 VIN+, LM2596 #1 IN+, LM2596 #2 IN+} ----
# Sin fusible: la fuente entra directo al shunt del INA219.
net([(26, 116), (70, 116)], C_15V, lw=2.5)
dot(52, 116, C_15V)                                 # nodo 15 V
net([(52, 116), (52, 90)], C_15V, lw=2.2)           # bajante 15 V
dot(52, 100, C_15V)
dot(52, 90, C_15V)
net([(52, 100), (76, 100), (76, 92)], C_15V, lw=2.2)  # -> LM2596 #1 IN+
net([(52, 90), (42, 90), (42, 86)], C_15V, lw=2.2)    # -> LM2596 #2 IN+
# VS (15 V tras el shunt): INA219 VIN- -> L298N VS
net([(100, 116), (110, 116), (110, 122), (118, 122)], C_15V, lw=2.5)

# ---- 5V-L (logica): LM2596 #1 OUT+ -> rail -> {L298N +5V, encoders, protoboard} ----
net([(94, 92), (94, V5_Y)], C_5VL, lw=2.5)
dot(94, V5_Y, C_5VL)
net([(114, V5_Y), (114, 113), (118, 113)], C_5VL, lw=2.0)  # rail -> L298N +5V
dot(114, V5_Y, C_5VL)
net([(10, V5_Y), (10, 40)], C_5VL, lw=2.0)                 # rail -> enc servo 5V
dot(10, V5_Y, C_5VL)
net([(10, 40), (10, 10)], C_5VL, lw=2.0)                   # -> enc pendulo 5V
dot(10, 40, C_5VL)

# ---- 5V-E (ESP32): LM2596 #2 OUT+ -> ESP32 VIN (rail dedicado, aislado) ----
net([(58, 86), (58, 142), (192, 142), (192, 126), (200, 126)], C_5VE, lw=2.5)

# ---- 3V3: ESP32 3V3 (der. #1) -> rail -> {INA VCC, pull-ups, U1/U2 Vcc} ----
net([(240, 126), (252, 126), (252, V3_Y)], C_3V3, lw=2.0)
net([(76, 104), (76, V3_Y)], C_3V3, lw=2.0)   # INA VCC -> rail
dot(76, V3_Y, C_3V3)
net([(60, 56), (60, 60)], C_3V3, lw=2.0)      # U1 Vcc -> stub
net([(60, 26), (60, 30)], C_3V3, lw=2.0)      # U2 Vcc -> stub

# ---- pull-ups 2k2: uno por canal, rama a 3V3 ----
pullups = [
    (38, 50, 60),   # servo A
    (44, 42, 60),   # servo B
    (38, 20, 30),   # pendulo A
    (44, 12, 30),   # pendulo B
]
for xr, wy, stub_y in pullups:
    cy = (wy + stub_y) / 2
    comp(xr, cy, 2.6, 3.2, C_RES, "2k2", fs=5.5)
    net([(xr, wy), (xr, cy - 1.6)], C_3V3, lw=1.6)
    net([(xr, cy + 1.6), (xr, stub_y)], C_3V3, lw=1.6)
    dot(xr, wy, C_SIG)

# ---- GND: todo a la barra GND ----
for node in ("SRC_G", "L_GND", "U2_G", "EP_G"):
    x0, y0 = P[node]
    net([(x0, y0), (x0, GND_Y)], C_GND, lw=1.6)
    dot(x0, GND_Y, C_GND)
# ESP32 GND: basta una bajada, se toma la de la fila derecha (#2)
net([(240, 118), (258, 118), (258, GND_Y)], C_GND, lw=1.8)
dot(258, GND_Y, C_GND)
# grounds "de arriba" a carriles libres
net([(16, 40), (28, 40), (28, GND_Y)], C_GND, lw=1.6)   # ENC servo GND
dot(28, GND_Y, C_GND)
net([(60, 38), (66, 38), (66, GND_Y)], C_GND, lw=1.6)   # U1 pin 7 GND
dot(66, GND_Y, C_GND)
# GND de LM2596 #2 (ESP32): sale por la izquierda esquivando U1
net([(48, 72), (54, 72)], C_GND, lw=1.6)                # une IN-/OUT- del buck
net([(48, 72), (32, 72), (32, GND_Y)], C_GND, lw=1.6)
dot(32, GND_Y, C_GND)
# GND de la seccion INA219 + LM2596 #1 a colector unico a la derecha (x=104)
net([(82, 104), (82, 100), (104, 100), (104, GND_Y)], C_GND, lw=1.6)  # INA219 GND
net([(82, 76), (104, 76)], C_GND, lw=1.6)                             # LM2596 #1 IN-/OUT-
dot(88, 76, C_GND)
dot(104, 76, C_GND)
dot(104, 100, C_GND)
dot(104, GND_Y, C_GND)

# ---- Motor: L298N OUT1/OUT2 -> motor ----
net([(152, 120), (155, 120), (155, 118), (158, 118)], C_MOT, lw=2.5)
net([(152, 106), (155, 106), (155, 110), (158, 110)], C_MOT, lw=2.5)

# ---- Control PWM/dir: ESP32 -> L298N ----
# OJO: en el header D27 (=IN2) queda ARRIBA de D26 (=IN1); en el L298N el orden es
# IN1, IN2. Una cinta recta los permuta (ver pinout.md, "trampas de cableado").
net([(200, 86), (134, 86), (134, 100)], C_PWM, lw=1.8)   # D27 -> IN2
net([(200, 78), (126, 78), (126, 100)], C_PWM, lw=1.8)   # D26 -> IN1
net([(200, 70), (142, 70), (142, 100)], C_ENA, lw=1.4,
    ls=(0, (4, 2)))                                      # D25 -> ENA (jumper puesto: n/c)

# ---- I2C: ESP32 (fila derecha) <-> INA219, rodeando la placa por arriba ----
net([(90, 104), (90, 101), (66, 101), (66, 150), (244, 150), (244, 46),
     (240, 46)], C_I2C, lw=1.8)                          # SDA -> D21 (der. #11)
net([(96, 104), (96, 99), (62, 99), (62, 146), (248, 146), (248, 22),
     (240, 22)], C_I2C, lw=1.8)                          # SCL -> D22 (der. #14)

# ---- senal encoder A/B -> entradas del chip ----
net([(22, 50), (34, 50), (46, 50)], C_SIG, lw=1.8)            # servo A
net([(22, 44), (30, 44), (30, 42), (46, 42)], C_SIG, lw=1.8)  # servo B
net([(22, 20), (46, 20)], C_SIG, lw=1.8)                      # pend A
net([(22, 14), (30, 14), (30, 12), (46, 12)], C_SIG, lw=1.8)  # pend B

# ---- salida acondicionada: U out -> RC(10k + 10n) -> GPIO ----
# El orden en el header (D33, D32, D35, D34) es el INVERSO del de la perfboard:
# por eso los cuatro canales se cruzan antes de entrar al ESP32.
rc_map = [
    # (salida chip, pin ESP32, y salida, y del GPIO, canal vertical, x del 10 nF)
    ("U1_Ao", "ESP_D34", 50, 38, 162, 98),
    ("U1_Bo", "ESP_D35", 42, 46, 158, 108),
    ("U2_Ao", "ESP_D32", 20, 54, 154, 100),
    ("U2_Bo", "ESP_D33", 12, 62, 150, 114),
]
for out, gpio, oy, gy, cx, capx in rc_map:
    x0, y0 = P[out]
    gx, _ = P[gpio]
    comp(90, oy, 5.0, 2.6, C_RES, "10k", fs=5.5)
    net([(x0, y0), (87.5, oy)], C_OUT, lw=1.6)
    net([(92.5, oy), (cx, oy), (cx, gy), (gx, gy)], C_OUT, lw=1.6)
    dot(capx, oy, C_OUT)
    comp(capx, oy - 5.0, 4.4, 2.4, C_CAP, "10nF", fs=5.0)
    net([(capx, oy), (capx, oy - 3.8)], C_OUT, lw=1.3)
    net([(capx, oy - 6.2), (capx, GND_Y)], C_GND, lw=1.2)
    dot(capx, GND_Y, C_GND)

# ---- bypass 100 nF por chip (pin 14 -> pin 7, pegado al CD40106) ----
for bx, stub_y, cy in ((81, 60, 47), (79, 30, 17)):
    comp(bx, cy, 5.0, 2.4, C_CAP, "100nF", fs=5.0)
    net([(bx, stub_y), (bx, cy + 1.2)], C_3V3, lw=1.3)
    net([(bx, cy - 1.2), (bx, GND_Y)], C_GND, lw=1.2)
    dot(bx, GND_Y, C_GND)

# =========================================================================
# leyenda + titulo
# =========================================================================
handles = [
    mpatches.Patch(color=C_15V, label="15 V (fuente / VS motor)"),
    mpatches.Patch(color=C_5VE, label="5 V ESP32 (LM2596 #2)"),
    mpatches.Patch(color=C_5VL, label="5 V logica (LM2596 #1)"),
    mpatches.Patch(color=C_3V3, label="3V3 (ESP32)"),
    mpatches.Patch(color=C_GND, label="GND (estrella)"),
    mpatches.Patch(color=C_MOT, label="potencia motor (M+/M-)"),
    mpatches.Patch(color=C_PWM, label="PWM/dir (ESP32->L298N)"),
    mpatches.Patch(color=C_ENA, label="ENA: cableable, sin conectar (opcion A)"),
    mpatches.Patch(color=C_I2C, label="I2C (SDA/SCL)"),
    mpatches.Patch(color=C_SIG, label="senal encoder A/B"),
    mpatches.Patch(color=C_OUT, label="senal acondicionada (RC->GPIO)"),
    mpatches.Patch(color=C_RES, label="R (2k2 pull-up / 10k RC)"),
    mpatches.Patch(color=C_CAP, label="C ceramica (10nF RC, 100nF bypass)"),
    mpatches.Patch(color=C_WARN, label="no cablear (UART0 del USB)"),
    mpatches.Patch(color=C_FREE, label="pin libre"),
]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
          ncol=5, fontsize=8.5, frameon=False)

ax.set_title("QUBE — Diagrama de cableado completo (ayuda visual, no a escala)\n"
             "Fuente 15 V (sin fusible) · INA219 · L298N · Motor · "
             "2× LM2596 (5 V: ESP32 + logica) · 2× CD40106BE · "
             "ESP32 DevKit V1 de 30 pines",
             fontsize=14, fontweight="bold")
ax.set_xlim(0, 276)
ax.set_ylim(-2, 164)
ax.set_aspect("equal")
ax.axis("off")
fig.tight_layout()

out = Path(__file__).parent / "system_wiring_l298n.png"
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
print(f"OK -> {out}")
