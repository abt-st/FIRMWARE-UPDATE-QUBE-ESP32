"""
Diagrama de cableado COMPLETO del sistema QUBE (ayuda visual, no a escala).
Configuracion L298N + DOBLE LM2596:
  Fuente 12 V -> Fusible 1.5 A -> INA219 -> L298N -> Motor.
  LM2596 #1 (buck 12->5 V) alimenta SOLO el ESP32 (rail 5V-E, aislado).
  LM2596 #2 (buck 12->5 V) alimenta la logica: L298N +5V, encoders y protoboard (rail 5V-L).
  2x CD40106BE para acondicionamiento (pull-ups 2k2 + doble inversion + RC 10k/10n).
  ESP32 como concentrador (PWM IN1/IN2/ENA, I2C, encoders).

Uso:  uv run python docs/hardware/system_wiring_l298n.py
Salida: docs/hardware/system_wiring_l298n.png
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

# --- colores por red ---
C_12V = "#00695c"   # potencia 12 V (fuente / VS motor)
C_5VE = "#e53935"   # bus 5 V ESP32   (LM2596 #1, aislado)
C_5VL = "#3949ab"   # bus 5 V logica  (LM2596 #2: L298N +5V, encoders, protoboard)
C_3V3 = "#fb8c00"   # bus 3V3 (regulador ESP32)
C_GND = "#37474f"   # tierra
C_I2C = "#039be5"   # I2C (SDA/SCL)
C_PWM = "#2e7d32"   # control PWM/dir (ESP32 -> L298N)
C_SIG = "#8e24aa"   # senal encoder A/B (open-drain)
C_OUT = "#d81b60"   # senal acondicionada (RC -> GPIO)
C_MOT = "#000000"   # potencia del motor (M+/M-)
C_FUSE = "#c62828"  # fusible (resaltado)

C_BLK = "#455a64"   # modulos de potencia
C_CHIP = "#263238"  # chips
C_MCU = "#1565c0"   # ESP32
C_ENC = "#6a1b9a"   # encoders
C_SRC = "#004d40"   # fuente
C_PIN = "#ffd54f"
C_RES = "#8d6e63"
C_CAP = "#1e88e5"

P: dict[str, tuple[float, float]] = {}

fig, ax = plt.subplots(figsize=(20, 13))


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
V3_Y = 128
net([(8, GND_Y), (206, GND_Y)], C_GND, lw=4)
net([(10, V5_Y), (150, V5_Y)], C_5VL, lw=3)   # 5V-L termina antes del ESP32
net([(36, V3_Y), (206, V3_Y)], C_3V3, lw=3)
rlabel(151, V5_Y, "5V-L", C_5VL)
rlabel(207, GND_Y, "GND", C_GND)
rlabel(207, V3_Y, "3V3", C_3V3)

# espinas 3V3 hacia la zona de senal (pull-ups + Vcc de los chips)
net([(36, V3_Y), (36, 30)], C_3V3, lw=2)
net([(36, 60), (82, 60)], C_3V3, lw=2)
net([(36, 30), (82, 30)], C_3V3, lw=2)

# =========================================================================
# CADENA DE POTENCIA:  Fuente -> Fusible -> INA219 -> L298N -> Motor
# =========================================================================
block(6, 104, 20, 16, "FUENTE", C_SRC, sub="12 V DC")
pin("SRC_P", 26, 116, "+12V", dx=-1.2, ha="right", fs=7)
pin("SRC_G", 26, 108, "GND", dx=-1.2, ha="right", fs=7)

block(34, 112, 18, 8, "FUSIBLE", C_FUSE, sub="1.5 A", fs=10)
pin("F_L", 34, 116, "", color=C_FUSE)
pin("F_R", 52, 116, "", color=C_FUSE)

block(70, 104, 30, 18, "INA219", C_BLK, sub="sensor de corriente")
pin("INA_VINp", 70, 116, "VIN+", dx=1.4, ha="left", fs=6.5)
pin("INA_VINm", 100, 116, "VIN-", dx=-1.4, ha="right", fs=6.5)
pin("INA_VCC", 76, 104, "VCC", dy=1.6, fs=6)
pin("INA_GND", 82, 104, "GND", dy=1.6, fs=6)
pin("INA_SDA", 90, 104, "SDA", dy=1.6, fs=6)
pin("INA_SCL", 96, 104, "SCL", dy=1.6, fs=6)

block(118, 100, 34, 26, "L298N", C_BLK, sub="puente H dual")
pin("L_VS", 118, 122, "VS +12V", dx=1.4, ha="left", fs=6)
pin("L_5V", 118, 113, "+5V", dx=1.4, ha="left", fs=6.5)
pin("L_GND", 118, 104, "GND", dx=1.4, ha="left", fs=6.5)
pin("L_IN1", 126, 100, "IN1", dy=1.6, fs=6)
pin("L_IN2", 134, 100, "IN2", dy=1.6, fs=6)
pin("L_ENA", 142, 100, "ENA", dy=1.6, fs=6)
pin("L_O1", 152, 120, "OUT1", dx=-1.4, ha="right", fs=6)
pin("L_O2", 152, 106, "OUT2", dx=-1.4, ha="right", fs=6)

block(166, 105, 24, 18, "MOTOR", "#5d4037", sub="DC")
pin("MOT_p", 166, 118, "M+", dx=1.4, ha="left", fs=6.5)
pin("MOT_m", 166, 110, "M-", dx=1.4, ha="left", fs=6.5)

# --- LM2596 #2 (logica): 12->5 V, alimenta L298N +5V, encoders y protoboard ---
block(70, 76, 30, 16, "LM2596 #2", C_BLK, sub="buck 12->5 V - logica")
pin("L2_INp", 76, 92, "IN+", dy=-1.6, fs=6)
pin("L2_OUTp", 94, 92, "OUT+", dy=-1.6, fs=5.5)
pin("L2_INm", 82, 76, "IN-", dy=-1.6, fs=6)
pin("L2_OUTm", 88, 76, "OUT-", dy=-1.6, fs=5.5)

# --- LM2596 #1 (ESP32): 12->5 V, alimenta SOLO el ESP32 (rail aislado) ---
block(36, 72, 28, 14, "LM2596 #1", C_BLK, sub="buck 12->5 V - ESP32", fs=10)
pin("L1_INp", 42, 86, "IN+", dy=-1.6, fs=6)
pin("L1_OUTp", 58, 86, "OUT+", dy=-1.6, fs=5.5)
pin("L1_INm", 48, 72, "IN-", dy=-1.6, fs=6)
pin("L1_OUTm", 54, 72, "OUT-", dy=-1.6, fs=5.5)

# =========================================================================
# ESP32 (concentrador)
# =========================================================================
block(172, 14, 34, 90, "ESP32", C_MCU, sub="WROOM-32")
esp_pins = [
    ("ESP_5V", 96, "5V / VIN", C_5VE),
    ("ESP_3V3", 88, "3V3", C_3V3),
    ("ESP_GND", 80, "GND", C_GND),
    ("ESP_26", 72, "GPIO26 IN1", C_PWM),
    ("ESP_27", 66, "GPIO27 IN2", C_PWM),
    ("ESP_25", 60, "GPIO25 ENA (n/c)", C_PWM),
    ("ESP_21", 52, "GPIO21 SDA", C_I2C),
    ("ESP_22", 46, "GPIO22 SCL", C_I2C),
    ("ESP_34", 38, "GPIO34 servo A", C_OUT),
    ("ESP_35", 32, "GPIO35 servo B", C_OUT),
    ("ESP_32", 26, "GPIO32 pend. A", C_OUT),
    ("ESP_33", 20, "GPIO33 pend. B", C_OUT),
]
for name, yy, lbl, col in esp_pins:
    pin(name, 172, yy, lbl, dx=2.0, ha="left", fs=6.5, color=col)

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
# ---- 12 V: Fuente -> Fusible -> nodo -> {INA219 VIN+, LM2596 #1 IN+, #2 IN+} ----
link("SRC_P", "F_L", C_12V, lw=2.5)
net([(52, 116), (70, 116)], C_12V, lw=2.5)          # fusible -> VIN+
dot(60, 116, C_12V)                                 # nodo 12 V
net([(60, 116), (60, 90)], C_12V, lw=2.2)           # bajante 12 V
dot(60, 100, C_12V)
dot(60, 90, C_12V)
net([(60, 100), (76, 100), (76, 92)], C_12V, lw=2.2)  # -> LM2596 #2 IN+
net([(60, 90), (42, 90), (42, 86)], C_12V, lw=2.2)    # -> LM2596 #1 IN+
# VS (12 V tras el shunt): INA219 VIN- -> L298N VS
net([(100, 116), (109, 116), (109, 122), (118, 122)], C_12V, lw=2.5)

# ---- 5V-L (logica): LM2596 #2 OUT+ -> rail -> {L298N +5V, encoders, protoboard} ----
net([(94, 92), (94, V5_Y)], C_5VL, lw=2.5)
dot(94, V5_Y, C_5VL)
net([(114, V5_Y), (114, 113), (118, 113)], C_5VL, lw=2.0)  # rail -> L298N +5V
dot(114, V5_Y, C_5VL)
net([(10, V5_Y), (10, 40)], C_5VL, lw=2.0)                 # rail -> enc servo 5V
dot(10, V5_Y, C_5VL)
net([(10, 40), (10, 10)], C_5VL, lw=2.0)                   # -> enc pendulo 5V
dot(10, 40, C_5VL)

# ---- 5V-E (ESP32): LM2596 #1 OUT+ -> ESP32 VIN (rail dedicado, aislado) ----
net([(58, 86), (58, 68), (170, 68), (170, 96), (172, 96)], C_5VE, lw=2.5)
dot(172, 96, C_5VE)

# ---- 3V3: ESP32 3V3 -> rail -> {INA VCC, pull-ups, U1/U2 Vcc} ----
net([(172, 88), (163, 88), (163, V3_Y)], C_3V3, lw=2.0)
dot(172, 88, C_3V3)
dot(163, V3_Y, C_3V3)
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
# ESP32 GND -> ramal comun con el 10 uF
net([(172, 80), (158, 80)], C_GND, lw=1.6)
dot(158, 80, C_GND)
# grounds "de arriba" a carriles libres
net([(16, 40), (28, 40), (28, GND_Y)], C_GND, lw=1.6)   # ENC servo GND
dot(28, GND_Y, C_GND)
net([(60, 38), (66, 38), (66, GND_Y)], C_GND, lw=1.6)   # U1 pin 7 GND
dot(66, GND_Y, C_GND)
# GND de LM2596 #1 (ESP32): sale por la izquierda esquivando U1
net([(48, 72), (54, 72)], C_GND, lw=1.6)                # une IN-/OUT- del buck #1
net([(48, 72), (32, 72), (32, GND_Y)], C_GND, lw=1.6)
dot(32, GND_Y, C_GND)
# GND de la seccion INA219 + LM2596 #2 a colector unico a la derecha (x=104)
net([(82, 104), (82, 100), (104, 100), (104, GND_Y)], C_GND, lw=1.6)  # INA219 GND
net([(82, 76), (104, 76)], C_GND, lw=1.6)                             # LM2596 #2 IN-/OUT-
dot(88, 76, C_GND)
dot(104, 76, C_GND)
dot(104, 100, C_GND)
dot(104, GND_Y, C_GND)

# ---- Motor: L298N OUT1/OUT2 -> motor ----
net([(152, 120), (159, 120), (159, 118), (166, 118)], C_MOT, lw=2.5)
net([(152, 106), (159, 106), (159, 110), (166, 110)], C_MOT, lw=2.5)

# ---- Control PWM/dir: ESP32 -> L298N (IN1, IN2, ENA n/c) ----
net([(172, 72), (126, 72), (126, 100)], C_PWM, lw=1.8)      # GPIO26 -> IN1
net([(172, 66), (134, 66), (134, 100)], C_PWM, lw=1.8)      # GPIO27 -> IN2
net([(172, 60), (142, 60), (142, 100)], C_PWM, lw=1.5, ls=(0, (4, 2)))  # GPIO25 -> ENA (jumper puesto: n/c)

# ---- I2C: ESP32 <-> INA219 ----
net([(90, 104), (90, 101), (103, 101), (103, 52), (172, 52)], C_I2C, lw=1.8)  # SDA
net([(96, 104), (96, 99), (107, 99), (107, 46), (172, 46)], C_I2C, lw=1.8)    # SCL

# ---- senal encoder A/B -> entradas del chip ----
net([(22, 50), (34, 50), (46, 50)], C_SIG, lw=1.8)            # servo A
net([(22, 44), (30, 44), (30, 42), (46, 42)], C_SIG, lw=1.8)  # servo B
net([(22, 20), (46, 20)], C_SIG, lw=1.8)                      # pend A
net([(22, 14), (30, 14), (30, 12), (46, 12)], C_SIG, lw=1.8)  # pend B

# ---- salida acondicionada: U out -> RC(10k + 10n) -> GPIO ----
rc_map = [
    ("U1_Ao", "ESP_34", 50, 38, 98),
    ("U1_Bo", "ESP_35", 42, 32, 116),
    ("U2_Ao", "ESP_32", 20, 26, 100),
    ("U2_Bo", "ESP_33", 12, 20, 122),
]
for out, gpio, oy, gy, dx in rc_map:
    x0, y0 = P[out]
    gx, _ = P[gpio]
    comp(90, oy, 5.0, 2.6, C_RES, "10k", fs=5.5)
    net([(x0, y0), (87.5, oy)], C_OUT, lw=1.6)
    net([(92.5, oy), (160, oy), (160, gy), (gx, gy)], C_OUT, lw=1.6)
    dot(dx, oy, C_OUT)
    comp(dx, oy - 5.0, 4.4, 2.4, C_CAP, "10nF", fs=5.0)
    net([(dx, oy), (dx, oy - 3.8)], C_OUT, lw=1.3)
    net([(dx, oy - 6.2), (dx, GND_Y)], C_GND, lw=1.2)
    dot(dx, GND_Y, C_GND)

# ---- bypass 100 nF por chip (pin 14 -> pin 7, pegado al CD40106) ----
for bx, stub_y, cy in ((81, 60, 47), (79, 30, 17)):
    comp(bx, cy, 5.0, 2.4, C_CAP, "100nF", fs=5.0)
    net([(bx, stub_y), (bx, cy + 1.2)], C_3V3, lw=1.3)
    net([(bx, cy - 1.2), (bx, GND_Y)], C_GND, lw=1.2)
    dot(bx, GND_Y, C_GND)

# ---- condensadores bulk ----
# 1000 uF en 5V-E (anti-brownout, junto a ESP32 VIN)
comp(150, 84, 6.6, 4.0, C_CAP, "1000µF", fs=5.5)
net([(150, 68), (150, 86)], C_5VE, lw=1.4)
dot(150, 68, C_5VE)
net([(150, 82), (150, GND_Y)], C_GND, lw=1.2)
dot(150, GND_Y, C_GND)
# 470 uF en 12 V (VS del L298N)
comp(110, 84, 6.0, 4.0, C_CAP, "470µF", fs=5.5)
net([(109, 116), (110, 116), (110, 86)], C_12V, lw=1.4)
net([(110, 82), (110, GND_Y)], C_GND, lw=1.2)
dot(110, GND_Y, C_GND)
# 10 uF en 3V3 (junto a los pines 3V3/GND del ESP32)
comp(166, 84, 5.4, 3.6, C_CAP, "10µF", fs=6)
net([(172, 88), (166, 88), (166, 86)], C_3V3, lw=1.4)
net([(166, 82), (166, 80), (172, 80)], C_GND, lw=1.2)

# =========================================================================
# leyenda + titulo
# =========================================================================
handles = [
    mpatches.Patch(color=C_12V, label="12 V (fuente / VS motor)"),
    mpatches.Patch(color=C_FUSE, label="fusible 1.5 A"),
    mpatches.Patch(color=C_5VE, label="5 V ESP32 (LM2596 #1)"),
    mpatches.Patch(color=C_5VL, label="5 V logica (LM2596 #2)"),
    mpatches.Patch(color=C_3V3, label="3V3 (ESP32)"),
    mpatches.Patch(color=C_GND, label="GND (estrella)"),
    mpatches.Patch(color=C_MOT, label="potencia motor (M+/M-)"),
    mpatches.Patch(color=C_PWM, label="PWM/dir (ESP32->L298N)"),
    mpatches.Patch(color=C_I2C, label="I2C (SDA/SCL)"),
    mpatches.Patch(color=C_SIG, label="senal encoder A/B"),
    mpatches.Patch(color=C_OUT, label="senal acondicionada (RC->GPIO)"),
    mpatches.Patch(color=C_RES, label="R (2k2 pull-up / 10k RC)"),
    mpatches.Patch(color=C_CAP, label="C ceramica (10nF RC, 100nF bypass) / bulk µF"),
]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
          ncol=5, fontsize=8.5, frameon=False)

ax.set_title("QUBE — Diagrama de cableado completo (ayuda visual, no a escala)\n"
             "Fuente 12 V · Fusible 1.5 A · INA219 · L298N · Motor · "
             "2× LM2596 (5 V: ESP32 + logica) · 2× CD40106BE · ESP32",
             fontsize=14, fontweight="bold")
ax.set_xlim(0, 216)
ax.set_ylim(-2, 134)
ax.set_aspect("equal")
ax.axis("off")
fig.tight_layout()

out = Path(__file__).parent / "system_wiring_l298n.png"
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
print(f"OK -> {out}")
