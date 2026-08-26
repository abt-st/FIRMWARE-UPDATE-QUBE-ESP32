# HANDOFF — Sesión 2026-06-15: Sweep v2 Completo

## Estado del hardware
- ESP32 IP: `192.168.100.50` (STA mode)
- Driver: BTS7960
- **ESP32 ONLINE** al final de la sesión
- INA219: OK, Vbus ~15.1V

## Estado del firmware

Firmware desplegado (sin cambios desde sesión anterior):
- **Catch mode:** gain=0.25, limit ±50 PWM
- **Centering gain:** 0.5
- **Transiciones LQR:** >155°, vel <30°/s
- **ke_gain:** (no verificado, pero funciona con sp≥55)

## Resultados del Sweep v2

### Tabla resumen

| SP | Catch | Trans | Miss | Rate | AvgMax | AvgCatch | Spins |
|----|-------|-------|------|------|--------|----------|-------|
| 45 | 0 | 0 | 5 | **0%** | 108° | --- | 0 |
| 50 | 2 | 0 | 3 | **40%** | 140° | 10.2s | 0 |
| 55 | 5 | 0 | 0 | **100%** | 154° | 6.2s | 0 |
| 60 | 5 | 0 | 0 | **100%** | 296° | 9.2s | 1 |
| 65 | 5 | 0 | 0 | **100%** | 301° | 2.1s | 2 |

**Sweet spot: sp=55** (100% catch, 0 spins, más controlado)

### Comparación con sesión anterior

| Métrica | 2026-06-10 | 2026-06-15 |
|---------|-----------|-----------|
| Best SP | 45 (80% catch) | 55 (100% catch) |
| sp=45 catch rate | 80% | **0%** |
| sp=55 catch rate | N/A | **100%** |
| Firmware | Igual | Igual |

**Cambios observados:**
1. sp=45 ya no funciona (0% vs 80% antes)
2. sp=55 funciona perfecto (100%)
3. El sweet spot se movió de 45 a 55

**Posible causa:** Los parámetros de energy pumping (ke_gain) pueden haber cambiado, o el hardware tiene diferente fricción/inercia.

## Análisis detallado

### sp=55: El sweet spot
- 100% catch rate, 0 spins
- Péndulo alcanza 154° (justo en el umbral de 155°)
- Catch time: 6.2s promedio
- **Comportamiento controlado:** el péndulo no hace giros completos
- **Seguro:** mínimo estrés mecánico

### sp=65: El rápido
- 100% catch rate, 2 spins
- Catch time: 2.1s promedio (el más rápido)
- Péndulo frecuentemente sobrepasa (avg max 301°)
- **Riesgo:** más estrés mecánico, giros no deseados

### sp=45: Roto
- 0% catch rate
- Péndulo solo alcanza 108° (necesita 155°)
- **Causa probable:** energy pumping insuficiente a este nivel de PWM

## Próximos pasos

### Opción A: Usar sp=55 (recomendado para la tesis)
- Implementar sp=55 como default para swing-up
- Probar estabilidad a largo plazo (10+ minutos)
- Documentar que sp=55 es el mínimo para 100% catch

### Opción B: Investigar por qué sp=45 dejó de funcionar
- Verificar ke_gain actual
- Comparar con firmware anterior
- Puede ser un problema de hardware (frección, etc.)

### Opción C: Usar sp=65 para velocidad
- Solo si se necesita catch rápido
- Aceptar el riesgo de spins

## Archivos generados

| Archivo | Descripción |
|---------|-------------|
| `sweep_swingup.py` | Script de sweep con retry logic y mejor manejo de errores |
| `autoresearch.sh` | Benchmark harness con análisis correcto del directorio |
| `data/sweep_20260615T123517/sweep_data.csv` | Datos crudos del sweep (3,886 líneas) |
| `data/sweep_20260615T123517/summary.txt` | Resumen legible |
| `HANDOFF.md` | Este archivo |

## Comandos para la próxima sesión

```bash
# Verificar ESP32
curl "http://192.168.100.50/state"

# Test rápido sp=55
curl "http://192.168.100.50/cmd?r=1" && sleep 0.5 && curl "http://192.168.100.50/cmd?sp=55" && sleep 0.1 && curl "http://192.168.100.50/cmd?m=5"

# Ejecutar sweep completo
uv run python experiments/2026-06-15_sweep_v2/sweep_swingup.py

# Analizar resultados
bash experiments/2026-06-15_sweep_v2/autoresearch.sh
```
