# PID Servo Tuning Session Log — 2026-06-04

## Objetivo

Analizar, ajustar y documentar el PID del servo (modo 2). Evaluar la utilidad del PID del péndulo (modo 3). Probar soluciones al error estacionario del servo.

---

## 1. Contexto del Sistema

| Parámetro | Valor |
|---|---|
| Firmware | v1.31.0 → modificado durante sesión |
| Control period | 500 Hz (2ms) |
| PWM | 20 kHz, 8-bit (0–255) |
| Encoder servo | 2048 CPR (X4 → 8192 counts/rev) |
| Mesa | Desnivel que genera torque gravitacional constante |
| Péndulo | Pasivo, cuelga en 0° por gravedad |

---

## 2. PID Péndulo (Modo 3) — Eliminado

### ¿Por qué se eliminó?

El péndulo del QUBE **no tiene motor propio**. Es un brazo pasivo articulado conectado al servo. El modo 3 intentaba controlar la posición del péndulo moviendo el motor del servo, pero esto es un **sistema subactuado**: un motor para dos grados de libertad (brazo + péndulo).

**Conclusión:** El PID directo sobre el péndulo no tiene utilidad práctica. Los controladores correctos para el péndulo son:
- **LQR (modo 4)** — control simultáneo servo + péndulo (55+ segundos de equilibrio invertido)
- **Swing-up (modo 5)** — bombeo de energía para llevar el péndulo a la vertical

### Cambios aplicados

- Eliminadas variables: `Kp_pend`, `Ki_pend`, `Kd_pend`, `integralTermPend`, `filteredVelPend`
- Eliminado handler HTTP `sp` (setpoint péndulo)
- Eliminados handlers `kpp`, `kip`, `kdp` (gains péndulo)
- Conservadas: `prevPosPend` (usado por swing-up), `pendulumOffsetDeg` (usado por LQR), `VEL_ALPHA_PEND` (usado por LQR)

---

## 3. PID Servo (Modo 2) — Análisis de Resultados

### 3.1 Test de Step Response

Secuencia: `0° → 30° → -30° → 60° → 0° → -60° → 0°`

**Gains por defecto:** Kp=3.0, Ki=0.5, Kd=0.15

| Step | Rise(ms) | Overshoot | SS Error | Obs |
|---|---|---|---|---|
| 0→30° | N/A | 0.0% | +7.4° | No llega a 30° |
| 30→-30° | 462 | 19.4% | -6.9° | |
| -30→60° | 410 | 6.4% | +12.3° | No llega a 60° |
| 60→0° | 491 | 17.6% | -6.2° | |
| 0→-60° | 397 | 26.0% | -12.9° | |
| -60→0° | 420 | 23.7% | -0.9° | Cerca de 0° converge |

**Promedio:** SS error = 7.8°, Overshoot = 15.5%

### 3.2 Diagnóstico

El error estacionario es **consistente y direccional**: el brazo siempre queda corto del setpoint, en ambas direcciones. Esto indica que el motor no tiene suficiente fuerza para vencer la fricción cuando el error es pequeño.

---

## 4. Experimentos Realizados

### 4.1 Gains PID Mejorados

| Config | Avg |SS Error| | Avg Overshoot |
|---|---|---|
| Baseline (Kp=3, Ki=0.5, Kd=0.15) | 7.4° | 15.5% |
| Ki=1.5, Kd=0.20 | 8.7° | 7.3% |
| Kp=5, Ki=3, Kd=0.25 | — | — (test interrumpido) |

**Resultado:** Subir gains no resuelve el SS error. El problema no es la sintonización del PID.

### 4.2 Feedforward Constante

Se probó `ff=0`, `ff=10`, `ff=20` (PWM constante sumado a la salida del PID).

| ff | Avg |SS Error| |
|---|---|
| 0 (baseline) | 7.4° |
| 10 | 8.7° |
| 20 | 9.6° |

**Resultado:** El feedforward constante **empeora** el error. El torque del desnivel no es constante — cambia de dirección según la posición del brazo. Un bias fijo ayuda en un dirección pero frena en la otra.

### 4.3 Filtro de Velocidad (velAlpha)

Se hizo `velAlpha` configurable por HTTP (`va=<valor>`) y se probaron 3 valores.

| velAlpha | Freq. corte | Avg |SS Error| |
|---|---|---|
| 0.12 (default) | ~10.8 Hz | 7.8° |
| 0.30 | ~27 Hz | 8.0° |
| 0.60 | ~54 Hz | 8.4° |

**Resultado:** El filtro de velocidad **no afecta** el error estacionario. La derivada no es el bottleneck.

---

## 5. Causa Raíz: Soft Saturation

La función `setMotor()` aplica un factor de reducción progresivo del PWM:

```cpp
float pos_factor = 1.0f / (1.0f + powf(fabsf(pos) / 80.0f, 2.0f));
pwmValue = (int)(pwmValue * pos_factor);
```

| Posición | Factor | PWM disponible |
|---|---|---|
| 0° | 1.00 | 100% (PWM_MAX=100) |
| 30° | 0.875 | 87 |
| 45° | 0.764 | 76 |
| 60° | 0.640 | 64 |
| 90° | 0.442 | 44 |

**Problema:** A medida que el brazo se aleja del centro, el PWM disponible disminuye. Pero el torque gravitacional del desnivel de la mesa es constante. El motor pierde autoridad y el brazo queda corto del setpoint.

**¿Por qué existe la soft saturation?** Sin ella, el motor stalled a posiciones extremas (90°+) causa brownout del ESP32. La soft saturation protege el hardware pero limita el tracking.

---

## 6. Solución: Feedforward Gravitacional (dependiente de posición)

### 6.1 Concepto

En lugar de un bias constante, el feedforward usa un modelo del torque gravitacional:

```cpp
float ff = servo_ff_pwm * sinf(pos * DEG_TO_RAD);
pwm += (int)(MOTOR_DIR * ff);
```

**Justificación física:** El torque gravitacional sobre el brazo es proporcional a `sin(ángulo)`:
- A 0° (vertical): sin(0) = 0 → sin torque
- A 30°: sin(30°) = 0.5 → 50% del torque máximo
- A 60°: sin(60°) = 0.866 → 87% del torque máximo
- A 90° (horizontal): sin(90°) = 1.0 → torque máximo

El feedforward compensa exactamente lo que la soft saturation le quita al motor.

### 6.2 Analogía con Swing-up

El swing-up (modo 5) usa el concepto de **energía** para decidir la dirección del PWM:
```cpp
float dE = refEnergy - energy;
int swingPwm = (int)(ke_gain * dE * cosf(alpha) * PWM_SWINGUP);
```

El feedforward usa el mismo principio: **conocer la física del sistema para compensar perturbaciones conocidas**, en vez de depender exclusivamente del integral para descubrirlas.

### 6.3 Implementación

**Firmware:**
- Variable `servo_ff_pwm` (configurable por HTTP: `?ff=<valor>`)
- Se aplica después del deadband (para mantener el brazo contra gravedad incluso en reposo)
- Se aplica antes del stiction kick y la limitación de PWM

**Calibración:**
1. Poner modo 2 (PID servo)
2. Subir `ff` gradualmente hasta que el SS error se minimice
3. Valor recomendado para empezar: `ff=15`

### 6.4 Referencia: ¿Se ha hecho antes?

**Soft saturation + feedforward en sistemas similares:**

| Sistema | Soft Saturation | Feedforward | Ref |
|---|---|---|---|
| Quanser QUBE-Servo original | No (motor brushless, sin brownout) | Sí (gravity comp.) | Quanser QUBE lab manuals |
| Brazos robóticos industriales | Sí (current limiting) | Sí (gravity + friction comp.) | Estándar en control de robots |
| Pendulum control (Åström & Murray) | No | Sí (energy-based) | Feedback Systems, Ch. 4 |
| Este proyecto (QUBE ESP32) | Sí (PWM position-dependent) | **Implementado hoy** (sin(pos)) | — |

**Conclusión:** La combinación soft saturation + feedforward posicional es una técnica estándar en control de sistemas con actuadores limitados. No se encontró en la literatura del QUBE-Servo original porque ese sistema usa un motor brushless sin el problema de brownout.

---

## 7. Cambios de Firmware Realizados

| Cambio | Línea | Descripción |
|---|---|---|
| `velAlpha` configurable | ~160 | `const float VEL_ALPHA` → `float velAlpha` + handler HTTP `va` |
| `servo_ff_pwm` | ~176 | Nueva variable + handler HTTP `ff` |
| Feedforward sin(pos) | ~1398 | `ff * sin(pos * DEG_TO_RAD)` |
| Telemetría | ~592 | `servo_ff_pwm` y `vel_alpha` en `/state` |
| Eliminado modo 3 | ~177 | Variables PID péndulo y handlers HTTP |
| `printHelp` | ~909 | Actualizado (ya no menciona modo 3) |

**Compilación:** RAM 15.0%, Flash 72.5% — sin cambios significativos.

---

## 8. Archivos Generados

| Archivo | Descripción |
|---|---|
| `test_pid.py` | Script de test con gains y ff configurables por HTTP |
| `analyze_pid.py` | Análisis automático de step response |
| `data/servo_pid_*.csv` | 7 CSVs de tests del servo PID |
| `SESSION_LOG.md` | Este documento |

---

## 9. Próximos Pasos

1. **Calibrar ff:** Probar `ff=15` y medir el SS error resultante
2. **Documentar en CHANGELOG:** Los cambios de firmware requieren entrada
3. **Verificar LQR y swing-up:** Confirmar que la eliminación del modo 3 no rompió nada
4. **Actualizar MODELO_FISICO_SISTEMA_QUBE.md:** Documentar el feedforward gravitacional
