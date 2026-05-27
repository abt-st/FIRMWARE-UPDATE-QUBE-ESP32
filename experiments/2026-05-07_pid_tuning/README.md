# Experimento: Ajuste PID — 2026-05-07

## Objetivo

Capturar datos de respuesta del sistema de control PID en lazo cerrado para evaluar el desempeño del seguidor de posición angular del QUBE Servo.

## Configuración del Hardware

| Componente | Modelo / Valor |
|------------|----------------|
| Microcontrolador | ESP32-WROOM-32 |
| Driver de motor | L298N (H-bridge) |
| Sensor de corriente | INA219 (I2C) |
| Motor | DC con encoder incremental (Premotec 990412016913) |
| Alimentación | 12V LiPo 3S |

## Parámetros PID Utilizados

| Parámetro | Valor | Nota |
|-----------|-------|------|
| Kp | 0.75 | — |
| Ki | **0.0** | ⚠️ Integral DESHABILITADA |
| Kd | 0.06 | — |
| PWM_MIN | 12 | — |
| PWM_MAX | 210 | — |
| Frecuencia de muestreo | 200 Hz | `CONTROL_PERIOD_US = 5000` |

### ⚠️ Limitación conocida

Durante estas sesiones **Ki = 0.0** (integral desactivada). Esto causó que el motor nunca alcanzara el setpoint con error < 10°, deteniéndose 10–30° antes por fricción estática.

**Corrección aplicada posteriormente** (v1.17.0):
- Ki: 0.0 → 0.15
- Zona de activación integral: `|err| < 8°` → `|err| < 45°`
- Velocidad máxima para integrar: 25°/s → 60°/s

## Sesiones de Captura

| Archivo | Hora | Descripción |
|---------|------|-------------|
| `qube_2026-05-07T00_32_35.csv` | 00:32 | Sesión 1 |
| `qube_2026-05-07T00_38_29.csv` | 00:38 | Sesión 2 |
| `qube_2026-05-07T00_41_58.csv` | 00:41 | Sesión 3 |
| `qube_2026-05-07T00_58_12.csv` | 00:58 | Sesión 4 |

## Resultados Observados

- El motor arrancaba correctamente y respondía al setpoint.
- **Error en régimen permanente de 10–30°** — el motor se detenía antes de llegar al ángulo objetivo.
- Causa: fricción estática del motor + Ki = 0.0 (sin acción integral para compensar).

## Conclusiones

1. El control proporcional (Kp) y derivativo (Kd) funcionan correctamente.
2. La acción integral es **necesaria** para eliminar el error en estado estable causado por fricción.
3. La corrección en v1.17.0 (Ki = 0.15, zona ampliada) resolvió el problema.
4. Se recomienda usar los archivos de esta sesión como **baseline** para comparar con la respuesta mejorada post-Ki.
