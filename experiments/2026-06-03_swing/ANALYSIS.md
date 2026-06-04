# Swing-up Analysis — 2026-06-03

## Tests realizados (12 CSVs)

| CSV | ke | Duración | Resultado |
|---|---|---|---|
| swing_054527 | 0.4 | 20s | LQR catch a 172°, sostuvo 1.2s |
| swing_054736 | 0.5 | 20s | Péndulo giró -1080° (spinning) |
| swing_055038 | 0.5 | 20s | 3 vueltas, LQR sin autoridad |
| swing_055407 | 0.15 | 20s | Amplitud muy baja (±18°) |
| swing_055543 | 0.3 | 20s | Amplitud crece lento (±58°) |
| swing_055720 | 0.4 | 30s | Llega a 148°, no transiciona |
| swing_055813 | 0.4 | 60s | **LQR catch a 172°, sostuvo 1.3s** ✅ |
| swing_061936 | 0.45 | 90s | Spinning después de LQR catch |
| swing_062922 | 0.45 | 90s | Spinning, raw alcanzó 821° |

## Estado actual del sistema

### Lo que FUNCIONA ✅
- Swing-up desde reposo hasta ~170° (oscilación estable)
- Transición swing-up → LQR cuando el péndulo está cerca de vertical
- ArduinoOTA (flasheo WiFi sin USB)
- Wrap modular de ángulo [-180, 180]
- Logging CSV de experiments

### Lo que NO funciona ❌

#### 1. LQR pierde el péndulo después del catch
- **Causa**: El péndulo llega a vertical con demasiada inercia cinética
- **Datos**: LQR atrapa a ~170° pero el péndulo cruza vertical en ~200ms
- **Intentos**: Gain scheduling (K2_NEAR=60), catch mode (150ms brake), reducir velocity threshold a 80°/s
- **Resultado**: LQR sostiene ~1-1.3s máximo antes de perder el péndulo

#### 2. Spinning después de LQR failure
- **Causa**: Cuando el LQR falla, el swing-up retoma con el péndulo ya girando
- **Bug clave**: `pendPosRaw` acumula vueltas (llegó a 1608°). La energía calculada
  con ángulo raw usa `cos(alpha_raw)` que oscila ±1 cuando raw > 360°, causando
  que el `motion_sign` cambie de dirección cada vez que el péndulo cruza 0°/360°
- **Efecto**: El swing-up empuja en direcciones opuestas alternadamente, no logra
  ni bombear ni frenar — el péndulo queda girando indefinidamente
- **Anti-spin actual**: Detecta spinning (>720° raw) y aplica freno, pero el freno
  no es lo suficientemente fuerte contra el torque del motor

#### 3. Offset del encoder crece sin límite
- **Causa**: `pendulumOffsetDeg` se ajusta en el spin reset, pero el reset solo
  se activa cuando `alpha_dot < 1.0` Y `pendPosRaw > 360°` — condición que nunca
  se cumple mientras el péndulo gira
- **Efecto**: El offset acumulado hace que `pendPos` (wrapped) no represente la
  posición real del péndulo

## Root cause analysis

El problema fundamental es que **la energía calculada con ángulo raw no es válida
cuando el péndulo gira más de 360°**:

```
pendPosRaw = 720° → cos(720°) = cos(0°) = 1.0  (parece estar en fondo)
pendPosRaw = 540° → cos(540°) = cos(180°) = -1.0  (parece estar en vertical)
```

El péndulo puede estar en cualquier posición real, pero la energía calculada
oscila erráticamente. Esto hace que `energy_sign` y `motion_sign` se cacen
mutuamente, resultando en empuje aleatorio.

## Próximos pasos (orden de prioridad)

### P1: Fix energía con ángulo wrapped cuando raw > 360°
```cpp
// Cuando |pendPosRaw| > 360°, usar ángulo wrapped para energía
float alpha_for_energy = (abs(pendPosRaw) > 360.0f) ? pendPos : pendPosRaw;
const float E = 0.5f * PEND_INERTIA * alpha_dot * alpha_dot +
                mgl * (1.0f - cosf(alpha_for_energy * DEG_TO_RAD));
```
Esto mantiene el comportamiento correcto para oscilaciones normales (<360° raw)
y evita el bug de energía errática cuando el péndulo gira.

### P2: Anti-spin más agresivo
- Cuando se detecta spinning, resetear el offset INMEDIATAMENTE (no esperar a que
  la velocidad baje)
- Aplicar freno a PWM_MAX (no 60%) durante un período fijo (500ms)
- Después del freno, re-evaluar si el péndulo está oscilando o girando

### P3: LQR con braking phase más largo
- El catch mode actual (150ms) no es suficiente para disipar la energía cinética
- Probar 300-500ms de braking antes de LQR normal
- O: implementar "energy dissipation controller" que reduce la amplitud de
  oscilación antes de intentar equilibrar

### P4: Mejorar la transición swing-up → LQR
- Solo transicionar cuando el péndulo está EN VELOCIDAD CERO en el pico
  (no mientras se mueve hacia vertical)
- Agregar condición: `alpha_dot` debe haber cambiado de signo recientemente
  (el péndulo está en el pico de la oscilación)

## Configuración actual

| Parámetro | Valor | Nota |
|---|---|---|
| ke_gain | 0.45 | Sweet spot entre 0.3 (lento) y 0.5 (spinning) |
| balance_threshold | 5° | Umbral angular para transición LQR |
| SWINGUP_TRANSITION_VEL_DPS | 80°/s | Velocidad máx. para transicionar |
| LQR_K1 | 2.0 | Posición servo |
| LQR_K2 | 22 | Ángulo péndulo (base) |
| LQR_K2_NEAR | 60 | Ángulo péndulo (<15° de vertical) |
| LQR_K3 | 1.5 | Velocidad servo |
| LQR_K4 | 9 | Velocidad péndulo (base) |
| LQR_K4_NEAR | 25 | Velocidad péndulo (<15° de vertical) |
| LQR_CATCH_MS | 150ms | Duración del catch brake |
| LQR_FALLBACK_TIME_MS | 500ms | Tiempo antes de fallback a swing-up |
| VEL_ALPHA_PEND | 0.60 | Filtro EMA velocidad péndulo |
| CONTROL_PERIOD | 2000µs (500Hz) | Periodo del lazo de control |

---

## Plan de implementación para mañana

### Paso 1: Fix energía con ángulo wrapped (crítico)
**Archivo:** `esp32_qube_l298n.ino`, bloque swing-up (modo 5)
**Cambio:** Cuando `|pendPosRaw| > 360°`, usar `pendPos` (wrapped) para energía:
```cpp
// En modo 5, cálculo de energía:
float alpha_for_energy = (abs(pendPosRaw) > 360.0f) ? pendPos : pendPosRaw;
const float E = 0.5f * PEND_INERTIA * alpha_dot * alpha_dot +
                mgl * (1.0f - cosf(alpha_for_energy * DEG_TO_RAD));
```
**Por qué:** `cos(720°) = cos(0°) = 1.0` → energía calculada errática. Con wrapped, `cos(±160°)` es estable.

### Paso 2: Anti-spin más agresivo
**Archivo:** `esp32_qube_l298n.ino`, bloque swing-up (modo 5)
**Cambios:**
- Resetear offset INMEDIATAMENTE al detectar spinning (no esperar a `alpha_dot < 1.0`)
- Freno a PWM_MAX (no 60%) durante 500ms fijo
- Después del freno, re-evaluar estado
```cpp
if (spinning) {
  // Reset offset inmediato
  pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
  prevPosPend = 0.0f;
  // Freno máximo
  int brake_pwm = (alpha_dot > 0) ? -PWM_MAX : PWM_MAX;
  setMotor(brake_pwm);
  return;
}
```

### Paso 3: LQR catch mode más largo
**Archivo:** `esp32_qube_l298n.ino`
**Cambio:** `LQR_CATCH_MS` de 150ms → 400ms
**Por qué:** 150ms no disipa suficiente energía cinética. El péndulo a 200°/s recorre 30° en 150ms.

### Paso 4: Test
```bash
# Flash OTA
cd src/firmware && pio run -e esp32dev_ota --target upload --upload-port 192.168.100.50

# Test 60s
python experiments/2026-06-03_swing/test_swing.py --duration 60

# Verificar: no spinning, LQR sostiene >5s
```

### Archivos a modificar
3. `experiments/2026-06-03_swing/ANALYSIS.md` — actualizar resultados

---

## Sesión 2026-06-04 — Iteración LQR (17 rounds)

### Tests realizados (17 flashes OTA)

| Round | Cambio principal | Resultado |
|---|---|---|
| 1-2 | Fix `else if` + K2_VERY_NEAR + damping LQR | Swing-up OK, spinning a los 20s |
| 3-4 | Catch mode PWM ±60, fallback 45°, vel threshold 15°/s | Transición con raw=-287°, offset acumulado |
| 5-6 | Fix energía: `pendPos_abs = fmod(pendPos+360,360)` | Pend a 0° — bug: cos(360°)=1.0 → energy_ratio=1 → PWM=0 |
| 7-8 | Fix referencia energía desde fondo | Otro bug: dist_from_vert=180° en fondo → energy_ratio=1 → PWM=0 |
| 9-10 | Revert a energía original + damping overlay | Swing-up OK pero solo ±8° — damping zones activas todo el tiempo |
| 11-12 | Revert completo a código original + dead zone 160° | Pend llega a 130° pero no crece — dead zone demasiado agresiva |
| 13-14 | Dead zone 172° + vel threshold 40°/s | Spinning después de transición |
| 15 | LQR gains probados (K2_NEAR=30, K4_NEAR=15) | LQR sostuvo 11.3s, oscilación ±25° — pero luego fallback y oscilaciones grandes |
| 16 | Servo protection direction-aware | Sin brownout pero oscilaciones persistentes |
| 17 | Fallback usa `pendPosRaw` (no `alpha` wrapped) | Crasheo a ~55s — brownout persiste |

### Hallazgos clave

1. **El swing-up funciona bien** — llega a ±170° consistentemente en ~10s
2. **El LQR puede sostener** — 11.3 segundos en round 15, pero no convergió
3. **El problema raíz es la transición**: el péndulo llega con demasiada energía cinética
4. **El catch mode (400ms, ±60 PWM) no frena suficiente**: el péndulo a 200°/s necesita ~2s para parar
5. **El fallback usa `alpha` (wrapped) que cruza discontinuamente** — fixed a `pendPosRaw`
6. **El brownout persiste** sin capacitor hardware — el motor stalled contra hard stop dispara corriente

### Cambios aplicados al firmware (vs sesión anterior)

| Archivo | Cambio |
|---|---|
| Línea ~196 | `LQR_K2_VERY_NEAR=55`, `LQR_K4_VERY_NEAR=20`, `LQR_DAMPING_GAIN=0.3` |
| Línea ~229 | `balance_threshold = 3.0f` (era 5) |
| Línea ~282 | `SWINGUP_TRANSITION_VEL_DPS = 15.0f` (era 80 hardcoded) |
| Modo 4 LQR | 3-tier gain scheduling + damping + centering (kp=0.15) |
| Modo 4 LQR | Catch mode: ±60 PWM (era ±20), 400ms |
| Modo 4 LQR | Servo protection direction-aware (corta PWM contra stop a 85°) |
| Modo 4 LQR | Fallback usa `pendPosRaw > 360°` (era `alpha > 45°`) |
| Modo 4 LQR | Protección usa `pendPosRaw > 250°` (era `alpha > 120°`) |
| Modo 5 Swing-up | Dead zone 172°: no bombear, solo damping cerca de vertical |
| Modo 5 Anti-spin | Threshold 360° (era 720°), brake ±PWM_MAX, cooldown 1s |
| Modo 5 Transición | `pendPosRaw < 200°` para evitar transición con offset |

### Hardware necesario

- **Capacitor electrolítico 470-1000µF** en rail 5V del ESP32 para prevenir brownout
- Ubicación: entre GND y VIN del ESP32, lo más cerca posible de la placa

### Próximos pasos recomendados

1. **Hardware**: Soldar capacitor en 5V
2. **Catch mode más largo**: 2-3 segundos con PWM proporcional a velocidad
3. **LQR con ángulo unwrap**: Usar ángulo continuo para evitar discontinuidades en ±180°
4. **Energy dissipation controller**: Reducir amplitud de oscilación ANTES de intentar equilibrar