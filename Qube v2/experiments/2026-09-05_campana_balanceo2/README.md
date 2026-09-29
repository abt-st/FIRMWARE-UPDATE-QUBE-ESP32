# Campaña de balanceo 2: K4n + techo de PWM + integral + límite 100°

Campaña completa del 2026-09-05: 12 tandas de 5 min + 1 de 10 min + 3 corridas de
verificación del CARE solver. **El resultado principal no es una configuración ganadora,
sino un mecanismo entendido.**

## Resumen de todos los resultados

### CARE solver

Se ejecutó el CARE (`scipy.linalg.solve_continuous_are`) con los parámetros físicos
reales del QUBE (Dp=7.52e-6 medido, Dr=5e-6, Rm=8.4, km=0.042). Resultado:

| Ganancia | FW actual | CARE | Diferencia |
|---|---|---|---|
| K1 (θ) | 2,0 | 2,24 | +12% |
| **K2 (α)** | **22,0** | **51,0** | **×2,3** |
| K3 (θ̇) | 1,5 | 1,36 | −9% |
| K4 (α̇) | 9,0 | 3,86 | ×0,43 — **ignorado** |

El CARE subestima K4 porque el modelo lineal no captura fricción seca (P24: 13.4× la
viscosa), overruns HTTP (P28), ni la saturación de PWM. Se usó el valor empírico de C16.

### H3 (CARE K2=51 + K4n C16=25)

| Condición | traspasos | p50 | max | >3s | veredicto |
|---|---|---|---|---|---|
| `H3_base` (K2=51 solo) | 25 | **872** | 1792 | 0 | DENTRO DEL RUIDO |
| `H3_base` (K2=51 + Ki=0.02) | 15 | **1224** | 1574 | 0 | DENTRO DEL RUIDO |
| `H3_base` (K2=51 + Ki=0.05) | 12 | 298 | 1642 | 0 | **NO SIRVE** |
| `H3_near` (tanda 1) | 2 | — | **266772** | **1** | **LOGRADO** |
| `H3_near` (tanda 2) | 18 | 563 | 1501 | 0 | DENTRO DEL RUIDO |

**H3_near tanda 1 produjo un balanceo de 267 s** — el más largo del proyecto. Pero no
fue reproducible (tanda 2: p50 563, DENTRO DEL RUIDO).

### Integral de θ (P4/H8)

Se agregó Ki=0.05 al firmware (v1.69.0) con anti-windup condicional.

| Condición | p50 | max | >3s | fallas tope | Nota |
|---|---|---|---|---|---|
| C0_base con Ki=0 (7 tandas) | 624 | 1455 | 0 | 15.1 | línea base |
| C0_base con **Ki=0.05** | **506** | **3408** | **1** | 11 | primer >3s con defaults |
| C0_base con Ki=0.02 | 844 | 1738 | 0 | 19 | mediana +35% |

Single-event >3s logrado con FW defaults + integral. No es reproducible tanda a tanda.

### Límite del brazo 95° → 100°

Se probaron 95°, 100° y 105° para optimizar el balance falla-tope vs vueltas.

| Límite | fallas tope | vueltas | p50 | max |
|---|---|---|---|---|
| **95°** (n=2) | **18.5** | 8.5 | 624 | 3408 |
| **100°** (n=2) | **7** | 9.5 | **589** | 2050 |
| 105° (n=1) | 10 | 11 | 346 | 1648 |

**100° es el óptimo.** Las fallas por tope bajan 62% sin disparar las vueltas.

### C16 (K4n=25 sola) — repetida de ayer

| Tanda | traspasos | p50 | max | >3s | Observación |
|---|---|---|---|---|---|
| 1 | 3 | — | — | 0 | brazo atascado en +32° |
| **2** | **10** | **1150** | **6337** | **1** | brazo centrado |
| 3 | 2 | — | — | 0 | brazo atascado en +51° |

El patrón se repite: una de cada 3-4 tandas produce un evento >3s.

## Cronología completa del día

| # | Condición | Duración | p50 | max | >3s | falla3 | falla2 | Estado firmware |
|---|---|---|---|---|---|---|---|---|
| 1 | C0_base | 5 min | 552 | 1227 | 0 | 11 | 4 | v1.68.0 (límite 95, Ki=0) |
| 2 | C0_base | 5 min | 537 | 1493 | 0 | 14 | 3 | v1.68.0 |
| 3 | C16_k4n_25_solo | 5 min | — | — | 0 | 2 | 0 | v1.68.0 — SIN POTENCIA |
| 4 | C16_k4n_25_solo | 5 min | 1150 | **6337** | **1** | 8 | 1 | v1.68.0 |
| 5 | C16_k4n_25_solo | 5 min | 571 | 579 | 0 | 2 | 0 | v1.68.0 — SIN POTENCIA |
| 6 | C17_lpm110_k4n_25 | 5 min | 549 | 766 | 0 | 22 | 3 | v1.68.0 |
| 7 | C18_lpm110_k4n_25_k4_18 | 5 min | 429 | 624 | 0 | 11 | 1 | v1.68.0 |
| 8 | C5_lpm110 | 5 min | 676 | 799 | 0 | 12 | 0 | v1.68.0 |
| 9 | C0_base | 5 min | 647 | 1468 | 0 | 15 | 3 | v1.68.0 |
| 10 | C19_k4n_30 | 5 min | 578 | 1735 | 0 | 15 | 4 | v1.68.0 |
| 11 | C0_base | 5 min | **726** | 2418 | 0 | 9 | 7 | v1.68.0 |
| — | — | — | — | — | — | — | — | — **CARE aquí** — |
| 12 | H3_base (K2=51) | 5 min | **872** | 1792 | 0 | 19 | 3 | v1.68.0 (Ki=0) |
| **13** | **H3_near (K2=51+K4=18)** | **5 min** | **133543** | **266772** | **1** | **2** | **0** | **v1.68.0 — 267 s** |
| 14 | H3_near (repeat) | 5 min | 563 | 1501 | 0 | 13 | 4 | v1.68.0 — no réplica |
| — | — | — | — | — | — | — | — | **Integral + límite aquí** |
| 15 | H3_base + Ki=0.02 | 5 min | **1224** | 1574 | 0 | 14 | 2 | v1.68.0 + HTTP Ki |
| 16 | C0_base + Ki=0 | 5 min | 683 | 2352 | 0 | 16 | 7 | v1.69.0 (Ki=0 por HTTP) |
| 17 | C0_base + Ki=0.02 | 5 min | 844 | 1738 | 0 | 19 | 3 | v1.69.0 (Ki=0.02 HTTP) |
| 18 | C0_base + **Ki=0.05** | 5 min | 506 | **3408** | **1** | **11** | **9** | v1.69.0 (Ki=0.05 HTTP, lim 95) |
| 19 | C0_base + Ki=0.05 | 10 min | 742 | 1434 | 0 | 26 | 8 | v1.69.0 (lim 95) |
| 20 | C0_base **lim=100°** | 5 min | 718 | 1269 | 0 | **8** | 8 | v1.69.0 (Ki=0.05, lim 100) |
| 21 | C0_base lim=105° | 5 min | 346 | 1648 | 0 | 10 | **11** | v1.69.0 (lim 105) |
| **22** | **C0_base v1.69.0 final** | **5 min** | 460 | 2050 | 0 | **7** | 11 | **v1.69.0 firmware** |

## Firmware v1.69.0

Hardcodeado:
- `lqr_Ki = 0.05` — integral de θ con anti-windup condicional
- `SERVO_HARD_LIMIT_DEG = 100°` — 5° extra de recorrido
- HTTP: `?lqri=<val>` — ajuste en vivo
- Serial: `L13 <val>` — idem
- `/state` → `lqr_ki`

## Mecanismo de la deriva del brazo (P4/H8)

1. El péndulo converge con α_offset ≠ 0 (1–8°, causas: P24, tilt, P22)
2. La ley LQR u = -(K1·θ + K2·α + ...) no puede cancelar el offset sin integral
3. En equilibrio: θ = -K2/K1 · α_offset
4. Con K2=22 (FW), α_offset max ≈ 8.6° (dentro de ±95°)
5. Con K2=51 (CARE), α_offset max ≈ 3.7° (la mayoría de tandas fuera)
6. El integrador (Ki=0.05) acumula lentamente y cancela el offset
7. Pero converge en ~0.5-1 s, tiempo durante el cual el brazo deriva al tope
8. El límite 95→100° da ~40 ms extra → el integrador tiene oportunidad de invertir

## Archivos

- `campana.py` — script de campaña (adaptado de ayer, incluye H3 + Ki)
- `analiza.py` — análisis por traza
- `data/` — trazas *.{jsonl,json}, resúmenes, bases_sesion.json
- `PLAN_CARE.md` — CARE solver y candidatos
- `README.md` — este archivo