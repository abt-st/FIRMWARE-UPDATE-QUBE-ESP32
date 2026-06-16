# HANDOFF — Sesión 2026-06-15: Sweep v3 (Auditoría + Correcciones)

## Estado del hardware
- ESP32 IP: `192.168.100.50` (STA mode)
- Driver: BTS7960
- **ESP32 ONLINE** al final de la sesión
- INA219: OK, Vbus ~15.0V

## Estado del firmware

Firmware desplegado (sin cambios desde sesión anterior):
- **Catch mode:** gain=0.25, limit ±50 PWM
- **Centering gain:** 0.5
- **Transiciones LQR:** >155°, vel <30°/s

## Resultados del Sweep v3 (VERIFICADOS)

### Tabla resumen — clasificación corregida

| SP | Catch | Chatter | Miss | Clean% | Total% | AvgMax | AvgCatch |
|----|-------|---------|------|--------|--------|--------|----------|
| 45 | 0 | 0 | 5 | **0%** | 0% | 99° | --- |
| 50 | 3 | 1 | 1 | **60%** | 80% | 165° | 16.1s |
| 55 | 2 | 2 | 1 | **40%** | 80% | 183° | 7.7s |
| **60** | **4** | **0** | **1** | **80%** | 80% | 144° | 3.0s |
| 65 | 3 | 2 | 0 | **60%** | 100% | 254° | 2.6s |

### Sweet spot verificado: sp=60

- **80% clean catch rate** (4/5 intentos, 0 chatter)
- Catch time promedio: 3.0s (el más rápido con catches limpios)
- Max angle promedio: 144° (controlado, sin giros excesivos)
- 0 eventos de chatter — LQR se mantiene estable una vez que atrapa

### Corrección de la auditoría v2

La sesión anterior (v2) reportó sp=55 como sweet spot con 100% catch rate.
**Esto era incorrecto** — el script v2 no distinguía CATCH de CHATTER.

| Conclusión v2 | Realidad (v3) |
|---|---|
| sp=55 = 100% catch | sp=55 = 40% clean, 40% chatter, 20% miss |
| sp=60 = 100% catch | sp=60 = 80% clean, 0% chatter, 20% miss |
| sp=65 = 100% catch | sp=65 = 60% clean, 40% chatter, 0% miss |
| Sweet spot: sp=55 | **Sweet spot: sp=60** |

### Detalle de catches por intento

**sp=60 (sweet spot):**
- att=1: CATCH max=158° lqr=3.7s ✓
- att=2: CATCH max=145° lqr=2.5s ✓
- att=3: CATCH max=148° lqr=2.9s ✓
- att=4: CATCH max=151° lqr=2.8s ✓
- att=5: MISS max=116° — péndulo no alcanzó 155°

**sp=55 (no recomendado):**
- att=1: CHATTER max=232° lqr=3.5s losses=1 ✗
- att=2: CATCH max=143° lqr=4.8s ✓
- att=3: CATCH max=157° lqr=19.9s ✓
- att=4: CHATTER max=242° lqr=2.7s losses=1 ✗
- att=5: MISS max=138° ✗

### Hallazgo: patrón de chatter

Los intentos con chatter muestran un patrón claro:
- Max angle > 200° → el péndulo acumula demasiada energía
- LQR atrapa pero pierde el control rápidamente
- sp=60 evita esto: max angle promedio 144° (controlado)

## Calidad de datos

### Poll rate
- Configurado: 10Hz
- Real promedio: **6.6Hz** (66% throughput)
- Causa: retry backoff `time.sleep(0.1 * (attempt + 1))` demasiado agresivo
- **Recomendación:** Usar backoff fijo de 50ms o implementar polling asíncrono

### Samples
- Esperado: 300 samples/attempt
- Real promedio: ~200 samples/attempt
- Sin truncamientos detectados

## Próximos pasos

### 1. Implementar sp=60 como default
```cpp
int swingupPwmMax = 60; // sweet spot verificado por auditoría
```

### 2. Reducir retry backoff
```python
time.sleep(0.05)  # fijo 50ms, no progresivo
```

### 3. Repetir con POLL_HZ realista
POLL_HZ=5 para reflejar la latencia real de ~150ms/request.

### 4. Probar estabilidad a largo plazo
10+ minutos de operación continua con sp=60.

## Archivos generados

| Archivo | Descripción |
|---------|-------------|
| `sweep_swingup.py` | Script corregido con CHATTER classification |
| `analyze_sweep.py` | Analizador Python (reemplaza autoresearch.sh) |
| `data/sweep_20260615T131134/sweep_data.csv` | Datos crudos verificados |
| `data/sweep_20260615T131134/summary.txt` | Resumen |
| `HANDOFF.md` | Este archivo |

## Comandos para la próxima sesión

```bash
# Verificar ESP32
curl "http://192.168.100.50/state"

# Test rápido sp=60
curl "http://192.168.100.50/cmd?r=1" && sleep 0.5 && curl "http://192.168.100.50/cmd?sp=60" && sleep 0.1 && curl "http://192.168.100.50/cmd?m=5"

# Ejecutar sweep corregido
uv run python experiments/2026-06-15_sweep_v3/sweep_swingup.py

# Auditar resultados
uv run python experiments/2026-06-15_sweep_v3/analyze_sweep.py experiments/2026-06-15_sweep_v3/data
```
