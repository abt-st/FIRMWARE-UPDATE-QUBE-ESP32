"""
Genera el diagrama de la placa perforada de acondicionamiento de señal.
Placa: 28 columnas (A..AB) x 22 filas (1..22), paso 2.54 mm.
Contenido: 2x CD40106BE (doble inversion), 4 pull-ups, 4 RC, 2 bypass, 4 headers.

Uso:  uv run python docs/hardware/perfboard_layout.py
Salida: docs/hardware/perfboard_layout.png
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

N_COLS = 28
N_ROWS = 22

# Colores
C_HOLE = "#cfd8dc"
C_5V = "#e53935"
C_3V3 = "#fb8c00"
C_GND = "#37474f"
C_CHIP = "#263238"
C_PIN = "#ffd54f"
C_RES = "#8d6e63"
C_CAP = "#1e88e5"
C_CONN = "#43a047"
C_WIRE = "#90a4ae"
C_SIG = "#8e24aa"   # ruta de señal del encoder (A/B) hacia la entrada
C_JMP = "#00bcd4"   # jumper de doble inversión (pin2->3, pin6->9)
C_OUT = "#d81b60"   # salida acondicionada (nodo RC -> J4 -> GPIO ESP32)
C_MOD = "#455a64"   # cuerpo de módulo (LM2596 / INA219)
C_15V = "#00695c"   # red de potencia 15 V (fuente / VS del motor)
C_I2C = "#039be5"   # bus I2C (SDA/SCL al ESP32)


def col_label(i: int) -> str:
    """1->A ... 26->Z, 27->AA."""
    i0 = i - 1
    if i0 < 26:
        return chr(65 + i0)
    return "A" + chr(65 + (i0 - 26))


def xy(col: float, row: float) -> tuple[float, float]:
    """Coordenada de plot de un hueco (fila 1 arriba)."""
    return col, (N_ROWS + 1 - row)


fig, ax = plt.subplots(figsize=(15, 12))

# --- huecos de la placa ---
for c in range(1, N_COLS + 1):
    for r in range(1, N_ROWS + 1):
        x, y = xy(c, r)
        ax.add_patch(plt.Circle((x, y), 0.12, color=C_HOLE, zorder=1))

# --- etiquetas de columnas (arriba y abajo) ---
for c in range(1, N_COLS + 1):
    x, ytop = xy(c, 0.3)
    _, ybot = xy(c, N_ROWS + 0.7)
    ax.text(x, ytop, col_label(c), ha="center", va="center", fontsize=8, color="#546e7a")
    ax.text(x, ybot, col_label(c), ha="center", va="center", fontsize=8, color="#546e7a")

# --- etiquetas de filas (izq y der) ---
for r in range(1, N_ROWS + 1):
    xL, y = xy(0.2, r)
    xR, _ = xy(N_COLS + 0.8, r)
    ax.text(xL, y, str(r), ha="center", va="center", fontsize=8, color="#546e7a")
    ax.text(xR, y, str(r), ha="center", va="center", fontsize=8, color="#546e7a")


def bus(row: int, color: str, label: str, c0: int = 1, c1: int = N_COLS) -> None:
    x0, y = xy(c0, row)
    x1, _ = xy(c1, row)
    ax.plot([x0, x1], [y, y], color=color, lw=5, solid_capstyle="round", zorder=2)
    ax.text(x0 - 0.6, y + 0.45, label, ha="left", va="bottom", fontsize=9,
            color=color, fontweight="bold")


# --- buses (3 rails horizontales) ---
bus(1, C_5V, "5V  (a encoders)")
bus(4, C_3V3, "3V3  (Vcc chips + pull-ups)")
bus(20, C_GND, "GND")


def chip(left_col: int, top_row: int, name: str, sub: str,
         outs: dict[int, str]) -> None:
    """DIP-14 vertical. left_col = columna de pines 1..7; pines 14..8 a +3 col."""
    right_col = left_col + 3
    x0, ytop = xy(left_col - 0.45, top_row - 0.55)
    x1, ybot = xy(right_col + 0.45, top_row + 6 + 0.55)
    ax.add_patch(FancyBboxPatch((x0, ybot), x1 - x0, ytop - ybot,
                 boxstyle="round,pad=0.02,rounding_size=0.25",
                 fc=C_CHIP, ec="#000000", zorder=3))
    # muesca
    xm, ym = xy((left_col + right_col) / 2, top_row - 0.55)
    ax.add_patch(plt.Circle((xm, ym), 0.18, color="#90a4ae", zorder=4))
    # nombre
    xc, yc = xy((left_col + right_col) / 2, top_row + 3)
    ax.text(xc, yc + 0.25, name, ha="center", va="center", fontsize=11,
            color="white", fontweight="bold", zorder=5)
    ax.text(xc, yc - 0.35, sub, ha="center", va="center", fontsize=8,
            color="#b0bec5", zorder=5)
    # pines: izq 1..7 (arriba->abajo), der 14..8
    for k in range(7):
        pin_l = k + 1
        pin_r = 14 - k
        for col, pin in ((left_col, pin_l), (right_col, pin_r)):
            x, y = xy(col, top_row + k)
            ax.add_patch(Rectangle((x - 0.18, y - 0.18), 0.36, 0.36,
                         fc=C_PIN, ec="#000", lw=0.5, zorder=4))
            ax.text(x, y, str(pin), ha="center", va="center", fontsize=6.5,
                    color="#000", zorder=5)
    # etiquetas de salida/uso
    for pin, txt in outs.items():
        if pin <= 7:
            col, k = left_col, pin - 1
            dx = -0.55
            ha = "right"
        else:
            col, k = right_col, 14 - pin
            dx = 0.55
            ha = "left"
        x, y = xy(col, top_row + k)
        ax.text(x + dx, y, txt, ha=ha, va="center", fontsize=6.8,
                color="#37474f", zorder=5)


# U1 = servo (pines izq col F=6), U2 = pendulo (pines izq col Q=17)
chip(6, 8, "U1", "servo",
     {1: "A", 5: "B", 4: "OUT_B", 8: "OUT_D", 14: "Vcc", 7: "GND", 11: "E_IN", 13: "F_IN"})
chip(17, 8, "U2", "pendulo",
     {1: "A", 5: "B", 4: "OUT_B", 8: "OUT_D", 14: "Vcc", 7: "GND", 11: "E_IN", 13: "F_IN"})


def comp(col: float, row: float, w: float, h: float, color: str, label: str,
         fs: float = 7) -> None:
    x, y = xy(col, row)
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle="round,pad=0.02,rounding_size=0.1",
                 fc=color, ec="#000", lw=0.6, alpha=0.95, zorder=4))
    ax.text(x, y, label, ha="center", va="center", fontsize=fs,
            color="white", fontweight="bold", zorder=5)


def wire(c0: float, r0: float, c1: float, r1: float) -> None:
    x0, y0 = xy(c0, r0)
    x1, y1 = xy(c1, r1)
    ax.plot([x0, x1], [y0, y1], color=C_WIRE, lw=1.3, zorder=2)


def poly(pts: list[tuple[float, float]], color: str, lw: float = 1.6,
         ls: str = "-", z: int = 2) -> None:
    """Polilínea (col, row) -> coordenadas de plot."""
    xs = [xy(c, r)[0] for c, r in pts]
    ys = [xy(c, r)[1] for c, r in pts]
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z,
            solid_capstyle="round", dash_capstyle="round")


# --- pull-ups 2k2 (3V3 -> entrada del chip) ---
for col_pu, pin_row, base in ((4, 8, 6), (4.9, 12, 6), (15, 8, 17), (15.9, 12, 17)):
    comp(col_pu, 5.8, 0.7, 1.4, C_RES, "2k2", fs=6)
    wire(col_pu, 4, col_pu, 5.1)          # del bus 3V3
    if pin_row == 8:   # IN_A (pin1): diagonal corta directa al pin
        wire(col_pu, 6.5, base, pin_row)
    else:              # IN_C (pin5): baja recto y entra horizontal, por
        # debajo de los pines 2/3 (no toca el nodo interno IN_B)
        poly([(col_pu, 6.5), (col_pu, pin_row), (base, pin_row)], C_WIRE, lw=1.3)

# --- RC: 10k serie + 10n a GND, en la salida (pin4 OUT_B / pin8 OUT_D) ---
rc_data = [
    (4, 6, 4, "G34"),    # U1 OUT_B (pin4, col6)
    (10, 9, 8, "G35"),   # U1 OUT_D (pin8, col9)
    (15, 17, 4, "G32"),  # U2 OUT_B (pin4, col17)
    (21, 20, 8, "G33"),  # U2 OUT_D (pin8, col20)
]
# ruteo planar del nodo RC hasta su pin en J4 (salida a la ESP32)
#   tap = columna de bajada; lane = fila del carril horizontal; j4 = columna del pin
gpio_route = {
    4:  {"tap": 5,  "lane": 19.40, "j4": 16},  # G34 -> J4 pin "34"
    10: {"tap": 9,  "lane": 19.15, "j4": 17},  # G35 -> J4 pin "35"
    15: {"tap": 14, "lane": 18.90, "j4": 18},  # G32 -> J4 pin "32"
    21: {"tap": 20, "lane": 18.65, "j4": 19},  # G33 -> J4 pin "33"
}
for col_r, pin_col, pin_no, gpio in rc_data:
    pin_row = 8 + (pin_no - 1 if pin_no <= 7 else 14 - pin_no)
    comp(col_r, 16, 0.7, 1.6, C_RES, "10k", fs=6)
    comp(col_r, 18, 0.7, 0.9, C_CAP, "10n", fs=6)
    # salida del pin -> 10k: sale del chip en L para no quedar tapada
    poly([(pin_col, pin_row), (col_r, pin_row), (col_r, 15.2)], C_WIRE, lw=1.3)
    wire(col_r, 16.8, col_r, 17.5)         # 10k -> nodo
    wire(col_r, 18.5, col_r, 20)           # 10n -> GND
    # salida acondicionada: nodo -> J4 -> GPIO ESP32
    g = gpio_route[col_r]
    poly([(col_r, 17.5), (g["tap"], 17.5), (g["tap"], g["lane"]),
          (g["j4"], g["lane"]), (g["j4"], 21)], C_OUT, lw=1.5)
    ax.add_patch(plt.Circle(xy(col_r, 17.5), 0.12, color=C_OUT, zorder=5))  # nodo
    ax.text(*xy(col_r, 14.9), gpio, ha="center", va="center", fontsize=6.5,
            color=C_OUT, fontweight="bold", zorder=5)

# --- bypass 100n por chip: pin14 (Vcc, arriba) - GND (abajo, al bus) ---
for vcc_col, cap_col in ((9, 11), (20, 22)):
    comp(cap_col, 6.5, 0.7, 0.9, C_CAP, "100n", fs=6)
    wire(vcc_col, 8, cap_col, 6.15)                       # pin14 -> terminal Vcc
    poly([(cap_col, 6.95), (cap_col, 20)], C_WIRE, lw=1.3)  # terminal GND -> bus

# Vcc de cada chip al bus 3V3
wire(9, 8, 9, 4)
wire(20, 8, 20, 4)
# GND de cada chip (pin7) al bus GND
wire(6, 14, 6, 20)
wire(17, 14, 17, 20)

# E_IN (pin11) y F_IN (pin13) sin usar -> GND (entrada CMOS: no dejar flotando)
for rc in (9, 20):   # columna de pines 14..8 (lado derecho de cada chip)
    poly([(rc, 9), (rc + 4, 9), (rc + 4, 20)], C_WIRE, lw=1.1)    # F_IN pin13
    poly([(rc, 11), (rc + 3, 11), (rc + 3, 20)], C_WIRE, lw=1.1)  # E_IN pin11


def conn(c0: int, row: int, pins: list[str], label: str, label_above: bool = False) -> None:
    w = len(pins)
    x, y = xy(c0 + (w - 1) / 2, row)
    ax.add_patch(FancyBboxPatch((x - w / 2, y - 0.5), w, 1.0,
                 boxstyle="round,pad=0.02,rounding_size=0.12",
                 fc=C_CONN, ec="#000", lw=0.7, zorder=4))
    for i, p in enumerate(pins):
        xi, yi = xy(c0 + i, row)
        ax.text(xi, yi + 0.05, p, ha="center", va="center", fontsize=6,
                color="white", fontweight="bold", zorder=5)
    dy = 0.85 if label_above else -0.85
    ax.text(x, y + dy, label, ha="center", va="center", fontsize=7.5,
            color=C_CONN, fontweight="bold", zorder=5)


def module(c0: float, c1: float, r0: float, r1: float, title: str,
           pins: list[tuple[float, str]]) -> None:
    """Módulo (LM2596/INA219): caja con título y pines en el borde inferior."""
    y_top = xy(0, r0)[1]
    y_bot = xy(0, r1)[1]
    ax.add_patch(FancyBboxPatch((c0, y_bot), c1 - c0, y_top - y_bot,
                 boxstyle="round,pad=0.02,rounding_size=0.2",
                 fc=C_MOD, ec="#000", zorder=3))
    ax.text((c0 + c1) / 2, xy(0, r0 + 0.42)[1], title, ha="center",
            va="center", color="white", fontweight="bold", fontsize=9.5, zorder=5)
    for pc, plabel in pins:
        x, y = xy(pc, r1)
        ax.add_patch(Rectangle((x - 0.15, y - 0.15), 0.30, 0.30, fc=C_PIN,
                     ec="#000", lw=0.5, zorder=4))
        ax.text(pc, xy(0, r1 - 0.34)[1], plabel, ha="center", va="center",
                fontsize=4.5, color="white", fontweight="bold", zorder=5)


# --- conectores (headers de borde) ---
conn(1, 2, ["5V", "GND", "A", "B"], "J1 enc. servo", label_above=True)
conn(25, 2, ["5V", "GND", "A", "B"], "J2 enc. pendulo", label_above=True)
conn(1, 21, ["5V", "3V3", "GND", "SDA", "SCL"], "J3 → ESP32")
conn(16, 21, ["34", "35", "32", "33", "G"], "J4 → GPIO ESP32")
# GND de J4 (referencia de los GPIO) al bus GND
wire(20, 20, 20, 20.5)
# conectores de la sección de potencia (banda superior)
conn(21, 2, ["15V", "GND"], "J5 fuente", label_above=True)
conn(23, 2, ["VS", "GND"], "J6 →BTS7960", label_above=True)

# --- jumpers de doble inversión (pin2->pin3 y pin6->pin9, por chip) ---
for left_col in (6, 17):
    right_col = left_col + 3
    # pin2 (row 9) -> pin3 (row 10): arco corto al costado izquierdo
    poly([(left_col, 9), (left_col - 0.7, 9.5), (left_col, 10)],
         C_JMP, lw=2.0, z=6)
    # pin6 (izq, row 13) -> pin9 (der, row 13): puente sobre el chip
    poly([(left_col, 13), (right_col, 13)], C_JMP, lw=2.0, ls=(0, (4, 2)), z=6)
    # etiquetas de la ruta de inversión (2 dentro del chip, 2 en el borde)
    xi, yi = xy(left_col, 9)
    ax.text(xi + 0.45, yi, "OUT_A", ha="left", va="center", fontsize=5.5,
            color="#b0bec5", zorder=6)
    xi, yi = xy(left_col, 10)
    ax.text(xi + 0.45, yi, "IN_B", ha="left", va="center", fontsize=5.5,
            color="#b0bec5", zorder=6)
    xi, yi = xy(left_col, 13)
    ax.text(xi - 0.5, yi, "OUT_C", ha="right", va="center", fontsize=5.5,
            color="#37474f", zorder=6)
    xi, yi = xy(right_col, 13)
    ax.text(xi + 0.5, yi, "IN_D", ha="left", va="center", fontsize=5.5,
            color="#37474f", zorder=6)

# --- ruta de señal del encoder (A/B) desde el header hasta la entrada ---
# U1 (servo): J1 A=col3, B=col4 -> IN_A pin1 (6,8), IN_C pin5 (6,12)
poly([(3, 2.6), (3, 7.6), (5.8, 8)], C_SIG)
poly([(4, 2.6), (2.7, 3.3), (2.7, 11.7), (5.8, 12)], C_SIG)
# U2 (pendulo): J2 A=col27, B=col28 -> IN_A pin1 (17,8), IN_C pin5 (17,12)
poly([(27, 2.6), (27, 7.1), (16.35, 7.1), (16.35, 8), (17, 8)], C_SIG)
poly([(28, 2.6), (28, 7.25), (16.15, 7.25), (16.15, 12), (17, 12)], C_SIG)

# --- sección de potencia: LM2596 (buck 15V->5V) + INA219 (sensor de I) ---
module(5, 11, 1.85, 3.15, "LM2596",
       [(6, "IN+"), (7.5, "IN−"), (9, "OUT−"), (10.5, "OUT+")])
module(13, 20, 1.85, 3.15, "INA219",
       [(13.7, "VIN+"), (14.9, "VIN−"), (16, "VCC"),
        (17, "GND"), (18.2, "SDA"), (19.4, "SCL")])

# 5V: LM2596 OUT+ -> bus 5V (rodea el módulo por la derecha y sube)
poly([(10.5, 3.15), (10.5, 3.35), (11.6, 3.35), (11.6, 1)], C_5V, lw=2.5)
# 15V: LM2596 IN+ <-> INA219 VIN+ (misma red); el carril termina en VIN+,
# NO pasa bajo VIN- (así no parece cortocircuitar el shunt del INA219)
poly([(6, 3.15), (6, 3.45), (13.7, 3.45), (13.7, 3.15)], C_15V, lw=2.0)
# J5 alimenta esa red rodeando por debajo del bus 3V3 (sube en el hueco col 12)
poly([(21, 2.6), (21, 4.5), (12, 4.5), (12, 3.45)], C_15V, lw=2.0)
# VS (15V tras el shunt): INA219 VIN- -> J6 -> BTS7960
poly([(14.9, 3.15), (14.9, 3.65), (23, 3.65), (23, 2.6)], C_15V, lw=2.0)
# 3V3: INA219 VCC -> bus 3V3
poly([(16, 3.15), (16, 4)], C_3V3, lw=2.0)
# GND (izq): LM2596 IN-/OUT- -> baja por col 5 al bus GND
poly([(9, 3.15), (9, 3.85), (5, 3.85), (5, 20)], C_GND, lw=1.5)
poly([(7.5, 3.15), (7.5, 3.85)], C_GND, lw=1.5)              # tap IN-
# GND (der): INA219 GND + J5/J6 GND -> baja por col 26 al bus GND
poly([(17, 3.15), (17, 3.9), (26, 3.9), (26, 20)], C_GND, lw=1.5)
poly([(22, 2.6), (22, 3.9)], C_GND, lw=1.5)                  # J5 GND
poly([(24, 2.6), (24, 3.9)], C_GND, lw=1.5)                  # J6 GND
# I2C: INA219 SDA/SCL -> J3 (por la izquierda, columnas libres)
poly([(18.2, 3.15), (18.2, 3.55), (1.8, 3.55), (1.8, 20.8), (4, 20.8), (4, 20.5)],
     C_I2C, lw=1.4)
poly([(19.4, 3.15), (19.4, 3.75), (2.1, 3.75), (2.1, 21.0), (5, 21.0), (5, 20.5)],
     C_I2C, lw=1.4)

# --- leyenda ---
handles = [
    mpatches.Patch(color=C_CHIP, label="CD40106BE (DIP-14)"),
    mpatches.Patch(color=C_PIN, label="pin del chip"),
    mpatches.Patch(color=C_RES, label="resistor (2k2 pull-up / 10k serie)"),
    mpatches.Patch(color=C_CAP, label="condensador (10n RC / 100n bypass)"),
    mpatches.Patch(color=C_CONN, label="conector / header"),
    mpatches.Patch(color=C_SIG, label="señal encoder A/B (a IN_A/IN_C)"),
    mpatches.Patch(color=C_OUT, label="salida acondicionada → J4 (GPIO ESP32)"),
    mpatches.Patch(color=C_JMP, label="jumper doble inversión (2→3, 6→9)"),
    mpatches.Patch(color=C_MOD, label="módulo (LM2596 / INA219)"),
    mpatches.Patch(color=C_15V, label="potencia 15V (fuente / VS motor)"),
    mpatches.Patch(color=C_I2C, label="I2C (SDA/SCL → ESP32)"),
    mpatches.Patch(color=C_5V, label="bus 5V"),
    mpatches.Patch(color=C_3V3, label="bus 3V3"),
    mpatches.Patch(color=C_GND, label="bus GND"),
]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
          ncol=4, fontsize=8, frameon=False)

ax.set_title("Placa de acondicionamiento + potencia — 28 × 22  (A–AB)\n"
             "2× CD40106BE · doble inversión · 4 canales encoder · LM2596 (5V) · INA219 (I motor)",
             fontsize=13, fontweight="bold")
ax.set_xlim(-0.5, N_COLS + 1.5)
ax.set_ylim(-0.5, N_ROWS + 1.5)
ax.set_aspect("equal")
ax.axis("off")
fig.tight_layout()

out = Path(__file__).parent / "perfboard_layout.png"
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
print(f"OK -> {out}")
