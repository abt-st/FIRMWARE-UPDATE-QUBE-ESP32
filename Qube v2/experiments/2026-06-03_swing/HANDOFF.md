# Swing-up & LQR Session Log — 2026-06-03/04 (HANDOFF)

## Estado actual del sistema

**Compila**: ✅ (RAM 15.0%, Flash 72.5%)  
**OTA**: ✅ Funciona (IP: 192.168.100.50)  
**Mejor resultado**: LQR sostuvo péndulo invertido **55+ segundos** (test swing_20260604T002350.csv)

## 🎯 Hitos alcanzados

1. **Swing-up estable** — péndulo oscila hasta ±150° sin spinning
2. **Transición swing-up→LQR** — ocurre a ~176-180° con vel<20°/s
3. **LQR sostiene péndulo** — 55+ segundos en ciclo límite alrededor de ±180°
4. **Sin crash** — PWM limitado a ±70 con soft saturation, 90s sin reinicio
5. **ArduinoOTA** — flash WiFi sin USB funciona
6. **`else if` fix** — bug crítico de modos resuelto

## 📊 Parámetros actuales del firmware

### Swing-up (modo 5)
| Parámetro | Valor | Nota |
|---|---|---|
| ke_gain | 0.5 | Ganancia del controlador de energía |
| balance_threshold | 5° | Umbral angular para transición LQR |
| SWINGUP_TRANSITION_VEL_DPS | 20°/s | Velocidad máx. para transicionar |
| Swing-up PWM limit | ±70 | Soft saturation en setMotor() |
| Kick PWM | ±40 | Limitado de ±70 a ±40 |
| centering_kp | 0.2 | Servo centering suave |

### Disipación de energía
| Parámetro | Valor | Nota |
|---|---|---|
| energy_ratio threshold | 0.95 | Disipación desde ~165° |
| brake_gain range | 0.2→1.0 | Progresivo (0.2 en 0.95, 1.0 en Er) |
| Reduced pump threshold | 0.85 | Bombeo 50% entre 0.85-0.95 |

### Anti-spin
| Parámetro | Valor | Nota |
|---|---|---|
| spinning delta | 200° | Delta raw entre samples para detectar spinning |
| spinning threshold | 720° | Acumulación raw para forzar detección |
| spin cooldown | 1000ms | Cooldown post-spin |
| spin brake PWM | ±60 | Reducido de ±100 |

### LQR (modo 4)
| Parámetro | Valor | Nota |
|---|---|---|
| K1 (servo pos) | 2.0 | |
| K2 (pend angle) | 22.0 | Base |
| K3 (servo vel) | 1.5 | |
| K4 (pend vel) | 9.0 | Base |
| K2_NEAR | 35.0 | Gains agresivos cerca de vertical |
| K4_NEAR | 15.0 | **No subier a 20 — empeora el LQR** |
| LQR_NEAR_DEG | 25° | Umbral para gain scheduling |
| LQR_FALLBACK_ALPHA_DEG | 30° | Umbral para fallback a swing-up |
| LQR_FALLBACK_TIME_MS | 500ms | Tiempo antes de fallback |
| LQR_CATCH_MS | 400ms | Catch mode duration |
| Catch mode PWM | ±20 | PWM del catch mode |
| LQR PWM limit | ±70 | Soft saturation protege |
| Hard stop | 25 PWM max | Limitado a 25 para evitar brownout |
| LQR_PROTECT_ALPHA_DEG | 140° | Apaga motor cerca del fondo |

### Soft saturation (en setMotor)
| Parámetro | Valor | Nota |
|---|---|---|
| k | 80° | Umbral de saturación |
| y | 2 | Agresividad de la curva |
| Formula | 1/(1+(|pos|/k)^y) | En pos=0: 1.0, en pos=80°: 0.50 |

### Velocidad del filtro
| Parámetro | Valor | Nota |
|---|---|---|
| VEL_ALPHA_PEND | 0.60 | Filtro EMA velocidad péndulo |
| VEL_ALPHA | 0.15 | Filtro EMA velocidad servo |

## 📁 CSVs de tests (experiments/2026-06-03_swing/data/)

27+ archivos CSV. Los más importantes:

| CSV | Configuración | Resultado |
|---|---|---|
| swing_20260604T002350.csv | K2_NEAR=30, K4_NEAR=15 | **LQR 55+ segundos** ✅ |
| swing_20260604T002826.csv | K2_NEAR=35, K4_NEAR=20 | LQR ~3s (K4_NEAR=20 empeora) |
| swing_20260603T000515.csv | k=80, centering=0.2 | LQR catch a 181.2°, 600ms |

## 🔧 Bugs corregidos en esta sesión

1. **`if`→`else if`** — modos 2/3/4/5 sobreescribían PWM entre sí
2. **Falta `}` en setMotor()** — bloque abierto, código muerto anidado
3. **`pendPos` acumulaba vueltas** — wrap a [-180,180] con fmod
4. **Energía errática con raw** — cos(raw) oscila cuando raw>360°
5. **LQR α=0 en fondo** — normalizeAngle(pendPos-180) = 0 cuando pendPos=0
6. **Hard stop brownout** — PWM_MAX en hard stop causaba crash
7. **Catch mode PWM_MAX** — catch mode aplicaba ±100, reducido a ±20
8. **Spinning sin cooldown** — anti-spin se re-activaba inmediatamente
9. **Transición con velocidad errónea** — EMA muy lento, se cambió a vel_raw
10. **Transición en fondo** — normalizeAngle(pendPos-180) trataba fondo como vertical

## 📝 Archivos modificados

| Archivo | Cambios |
|---|---|
| `esp32_qube_l298n.ino` | Todos los fixes + mejoras |
| `platformio.ini` | Env `esp32dev_ota` |
| `mcp/esp32_qube_server.py` | Herramienta `pio_ota_flash` |
| `mcp/README.md` | Documentación MCP |
| `CHANGELOG.md` | v1.27.0 a v1.31.0 |
| `experiments/2026-06-03_swing/` | 27+ CSVs, ANALYSIS.md, SESSION_LOG.md |

## 🔄 Próximos pasos recomendados

### Prioridad 1: Reducir amplitud del ciclo límite
El LQR sostiene el péndulo pero en un ciclo límite de ±170° (el péndulo casi
hace rotaciones completas). Para estabilizar en exactamente 180°:
- Probar un tercer tier de gains: K2_VERY_NEAR=50 para |alpha|<5°
- O: implementar "energy dissipation" dentro del modo LQR (no solo en swing-up)

### Prioridad 2: Mejorar la transición
La transición ocurre ~30% de las veces (depende de condiciones iniciales).
- Probar `vel_raw < 30°/s` (más laxo que 20 pero más estricto que 50)
- Verificar que el encoder no acumula offset que impida la transición

### Prioridad 3: Reducir oscilación del servo
El servo oscila entre -90° y +60° durante el LQR. Esto es ineficiente.
- Probar un centering también en el modo LQR (no solo en swing-up)
- O: agregar un término integral al LQR para eliminar error estacionario del servo

### Prioridad 4: Documentar para la tesis
Los resultados son significativos para la tesis:
- Swing-up desde reposo hasta posición invertida
- Transición automática a LQR
- 55+ segundos de equilibrio invertido
- Sistema completo: ESP32 + L298N + encoder incremental + Schmitt trigger

## 🚀 Comandos rápidos

```bash
# Compilar
cd src/firmware && pio run -e esp32dev

# Flash OTA
cd src/firmware && pio run -e esp32dev_ota --target upload --upload-port 192.168.100.50

# Flash USB
cd src/firmware && pio run -e esp32dev --target upload

# Test swing-up
python experiments/2026-06-03_swing/test_swing.py --duration 60

# Parar motor
curl "http://192.168.100.50/cmd?x=1"

# Leer estado
curl "http://192.168.100.50/state"
```
