# 📊 Datos Experimentales — QUBE Servo

Esta carpeta contiene los archivos CSV generados durante las sesiones experimentales de validación del control PID en la plataforma QUBE Servo Modernizada.

## Formato CSV

Cada archivo contiene las siguientes columnas:

| Columna | Unidad | Descripción |
|---------|--------|-------------|
| `t_s` | segundos | Timestamp relativo al inicio de la sesión |
| `position_deg` | grados | Posición angular medida del servo |
| `setpoint_deg` | grados | Setpoint de referencia |
| `error_deg` | grados | Error de seguimiento (setpoint - posición) |
| `pwm` | duty | Señal PWM aplicada al motor (-255 a +255) |
| `current_ma` | mA | Corriente consumida por el motor (INA219) |
| `voltage_v` | V | Voltaje de bus (INA219) |
| `power_mw` | mW | Potencia instantánea (INA219) |

## Sesiones

| Archivo | Fecha | Modo | Notas |
|---------|-------|------|-------|
| `qube_2026-05-07T00_32_35.csv` | 2026-05-07 | m2 (PID) | Convergencia inicial, Ki=0.0 |
| `qube_2026-05-07T00_38_29.csv` | 2026-05-07 | m2 (PID) | Sintonización Ki |
| `qube_2026-05-07T00_41_58.csv` | 2026-05-07 | m2 (PID) | Validación estabilidad |
| `qube_2026-05-07T00_58_12.csv` | 2026-05-07 | m2 (PID) | Test cambio setpoint |
| `qube_2026-05-13T23_32_49.csv` | 2026-05-13 | m2 (PID) | Post HW-FIX-1 |

## Generación de datos

Los datos son capturados por la GUI Python (`gui/app.py`) que se comunica con el ESP32 vía HTTP (`/state`). La frecuencia de muestreo es de 10 Hz (100 ms entre muestras).

## Uso

- Puedes analizar los datos con Python, MATLAB o cualquier herramienta compatible con CSV
- Script de análisis de ejemplo: `experiments/analyze_pid.py` (próximamente)
- Notebooks Jupyter: `experiments/notebooks/` (próximamente)

---

*Última actualización: Mayo 26, 2026*