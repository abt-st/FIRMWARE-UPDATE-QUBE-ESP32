# Plan: Re-sintonía LQR desde el CARE + K4n empírico

## Hallazgo del CARE solver

Se ejecutó `scipy.linalg.solve_continuous_are` (CARE) con el modelo físico real del
QUBE (Dp=7.52e-6, Dr=5e-6, Rm=8.4, km=0.042, V=12.0). La linealización alrededor de
α=π (péndulo invertido) da un polo inestable en **s = 16,11 rad/s** (ω_n ≈ 14,3 rad/s
— coincide con lo medido en banco).

### Lo que dice el CARE vs valores actuales del firmware

| Ganancia | CARE (Q=[5,10,1,5]) | FW actual | Diferencia |
|---|---|---|---|
| **K1 (θ)** — posición del brazo | **2,24** | 2,00 | +12% — cerca |
| **K2 (α)** — ángulo del péndulo | **51,0** | 22,0 | **×2,3 — el cambio principal** |
| **K3 (θ̇)** — velocidad del brazo | **1,36** | 1,50 | −9% — cerca |
| **K4 (α̇)** — velocidad del péndulo | **3,86** | 9,0 | **×0,43 — CARE quiere la mitad** |

### Tensión K4: CARE vs C16 (empírico)

CARE dice K4=3-5 para cualquier Q que se pruebe. **C16 (k4n=25, ayer) demostró que
K4_near=25 funciona mejor que 15** — en la dirección opuesta al CARE.

**Causa probable:** el modelo lineal asume actuación perfecta sin retardo. La planta
real tiene fricción seca 13,4× la viscosa (P24), overruns HTTP en ~1/tick (P28), y
saturación de PWM al 28,6% del tiempo — todas ausentes del modelo. El CARE lo que
encuentra es que "en un mundo ideal no hace falta tanto damping", pero el mundo real
sí lo necesita.

**Decisión:** ignorar el K4 del CARE y quedarse con los valores que C16 validó.

## Propuesta H3 (first candidate para A/B)

| Banda | K1(θ) | K2(α) | K3(θ̇) | K4(α̇) | Fuente |
|---|---|---|---|---|---|
| **BASE** (|α|≥25°) | 2,00 | **51,0** | 1,50 | **9,0** | CARE K2, FW resto |
| **NEAR** (5°<|α|<25°) | 2,00 | **58,7** | 1,50 | **25,0** | CARE K2, C16 K4 |
| **V.NEAR** (|α|<5°) | 2,00 | **61,3** | 1,50 | **30,0** | CARE K2, C16 K4+ |

Sólo cambian **dos números** respecto al firmware:
- K2 base: 22 → 51 (×2,3)
- K2 near: 30 → 59 (×2,0)
- K2 vnear: 55 → 61 (×1,1 — apenas)
- K4 near: 15 → 25 (C16)
- K4 vnear: 20 → 30 (C16+)

### Riesgos

1. **K2=51 puede saturar más rápido.** Con K2 al doble, `u = -(2·θ + 51·α + ...)` dará
   valores mayores y el limitador a `lqrPwmMax=70` cortará más seguido. Pero en defaults
   el PWM está saturado el 14,2% del tiempo (contra el techo literal) — hay margen.
2. **K4 near=25 elimina el escalón del gain scheduling.** Con base K4=9 y near=25, el
   salto al cruzar |α|=25° es abrupto. Se puede suavizar con `lqr_damping_gain` o
   simplemente medir si molesta.

## Protocolo de prueba

```
# 1. Línea base fresca (verificar banco sano)
python campana.py C0_base 5

# 2. Cargar H3_base
python -c "
import requests, time
URL = 'http://192.168.4.1'
# Base
for p in [('lqr2','51.0'), ('lqr2n','58.68'), ('lqr2vn','61.31'), ('lqr4n','25.0'), ('lqr4vn','30.0')]:
    r = requests.get(f'{URL}/cmd?{p[0]}={p[1]}')
    print(p[0], p[1], r.status_code)
    time.sleep(0.05)
"

# 3. Correr tanda H3
python campana.py H3_base 5
```

Los comandos HTTP se pueden aplicar sin reflashear — el firmware acepta `lqr2=`, `lqr2n=`,
`lqr2vn=`, `lqr4n=` por `/cmd`. Si funciona, se hardcodean en `esp32_qube.ino:471-482`
y se sube el firmware.

## Si H3 no funciona

| Síntoma | Qué hacer |
|---|---|
| K2=51 satura demasiado | Probar K2=35, 40, 45 en A/B |
| K4 near=25 agresivo | Bajar a 20 (firmware lo usa en vnear) |
| No hay mejora visible | El CARE subestima el efecto de P24. Modelar fricción seca y re-computar |