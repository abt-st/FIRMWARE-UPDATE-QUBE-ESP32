# Experimento: Medición de CPR del Encoder — 2026-06-01

## Objetivo

Determinar experimentalmente el **CPR (Counts Per Revolution)** del encoder incremental del motor Premotec 990412016913, usado en el QUBE Servo.

## Método

El firmware del ESP32 usa decodificación **X4 (cuadratura completa)**: cada transición de línea (A↑, A↓, B↑, B↓) genera un conteo. El conteo crudo (`count` en `/state`) es independiente del `countsPerRev` configurado.

**Procedimiento (por vuelta):**
1. Parada segura del motor (comando `x`)
2. Reset del encoder a 0 (comando `r`)
3. Rotación manual exactamente 1 vuelta completa
4. Lectura del conteo crudo del encoder
5. Repetir N veces → **CPR = promedio(|count|)**

## Hardware

| Componente | Detalle |
|------------|---------|
| Motor | Premotec 990412016913 |
| Encoder | Incremental, push-pull 5V |
| Acondicionamiento | Divisor 4.7kΩ/8.2kΩ → Schmitt CD40106BE → GPIO34/GPIO35 |
| Microcontrolador | ESP32-WROOM-32 |

## Uso

```bash
# Conectar al ESP32 en modo AP (192.168.4.1)
uv run python experiments/2026-06-01_cpr_measurement/scripts/measure_cpr.py

# Con IP personalizada y 10 vueltas
uv run python experiments/2026-06-01_cpr_measurement/scripts/measure_cpr.py --ip 192.168.1.100 -n 10
```

El script guía al usuario paso a paso:
1. Verifica conexión con el ESP32
2. Para el motor (safeStop) por seguridad
3. Resetea el encoder a 0
4. Pide al usuario rotar 1 vuelta manualmente
5. Lee el conteo crudo después de cada vuelta
6. Calcula CPR promedio y desviación estándar
7. Compara con CPRs estándar de fábrica

## Notas

- El encoder es **push-pull 5V**, acondicionado con divisor resistivo y Schmitt trigger
- El conteo crudo incluye la multiplicación X4 de la cuadratura
- Se recomienda marcar el eje con cinta/marcador para alinear vueltas exactas
- Múltiples vueltas mejoran la precisión al promediar errores de alineación

## Cambios de Firmware Derivados

- El firmware actual ya soporta `count` crudo en `/state`
- No se requieren cambios de firmware para esta medición
