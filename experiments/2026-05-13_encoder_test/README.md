# Experimento: Prueba de Encoder y Diagnóstico INA219 — 2026-05-13

## Objetivo

1. Diagnosticar la señal del encoder del servo y determinar la topología de acondicionamiento adecuada.
2. Recuperar la telemetría del INA219 tras reconexión de hardware.
3. Validar la detección I2C del sensor de corriente.

## Configuración del Hardware

| Componente | Modelo / Valor |
|------------|----------------|
| Microcontrolador | ESP32-WROOM-32 |
| Driver de motor | L298N (H-bridge) |
| Sensor de corriente | INA219 (I2C, dirección 0x40) |
| Motor | DC con encoder incremental (Premotec 990412016913) |
| Encoder servo | Push-pull 5V (medido: ~4.7V en reposo) |
| Alimentación | 12V LiPo 3S |

## Pruebas Realizadas

### 1. Diagnóstico de señal de encoder

**Topología probada (divisor resistivo):**
- Divisor 10kΩ / 10kΩ desde línea encoder a GPIO34/GPIO35
- Nivel alto medido en GPIO: **35–40 mV** ❌
- Resultado: **INSUFICIENTE** — nivel muy por debajo del umbral lógico del ESP32

**Topología adoptada (confirmada):**
- Encoder servo: push-pull 5V, ~4.7V en reposo
- Divisor 4.7kΩ / 8.2kΩ → Vout = 3.17V (seguro para ESP32)
- Nivel alto en GPIO: **~2.5V** ✅

### 2. Reconexión INA219

- Se reconectó la ruta de potencia/sensado completa.
- Se recuperó lectura estable de `v_bus`, `i_ma` y `p_mw`.
- Se implementó `scanI2CBus()` e `initIna219()` para autodetección.

### 3. Diagnóstico I2C

- Escaneo automático de direcciones `0x01..0x7E` en `setup()`.
- Prueba de direcciones candidatas: `0x40`, `0x41`, `0x44`, `0x45`.
- Comando serial `n` para reintentar detección sin reiniciar.

## Datos Capturados

| Archivo | Hora | Descripción |
|---------|------|-------------|
| `qube_2026-05-13T23_32_49.csv` | 23:32 | Sesión de diagnóstico INA219 + encoder |

## Parámetros PID Utilizados

| Parámetro | Valor |
|-----------|-------|
| Kp | 0.75 |
| Ki | 0.15 |
| Kd | 0.06 |
| Frecuencia de muestreo | 200 Hz |

## Resultados y Hallazgos

### Hallazgos clave del encoder

1. El encoder del servo es **push-pull a 5V**, no open-drain.
2. El divisor resistivo a GND produce niveles insuficientes (~35 mV).
3. La topología correcta es **divisor a 3.3V** con resistores de pull-up.

### Hallazgos del INA219

1. El sensor puede no ser detectado si la dirección I2C no coincide.
2. La autodetección con múltiples direcciones resuelve el problema.
3. El escaneo I2C periódico ayuda a diagnosticar problemas de hardware.

## Cambios de Firmware Derivados

- **v1.17.1**: Reconexión de hardware, documentación de incidente de encoder.
- **v1.17.2**: Confirmación de comportamiento push-pull, topología de acondicionamiento.
- **v1.17.3**: Escaneo I2C, autodetección INA219, comando serial `n`.

## Conclusiones

1. El acondicionamiento de señal del encoder es **crítico** para la medición de posición.
2. La autodetección de hardware mejora la robustez del sistema.
3. Se recomienda validar eléctricamente cada señal antes de conectar al ESP32.
