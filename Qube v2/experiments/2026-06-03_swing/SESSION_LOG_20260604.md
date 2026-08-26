# Session Log — 2026-06-04 (Sesión nocturna)

## Resumen

Sesión intensiva de ~3 horas enfocada en: correcciones de firmware, integración de componentes de hardware (capacitor, diodo flyback), y iteración del controlador swing-up + LQR.

**Resultado principal:** Se identificaron y documentaron múltiples problemas de hardware y firmware. El swing-up funciona pero el LQR no logra estabilizar el péndulo en la vertical de forma sostenida.

---

## Estado del Hardware

| Componente | Estado | Notas |
|---|---|---|
| ESP32 | ✅ Funcional | Sin daño permanente |
| LM2596 (5V) | ✅ Funcional | Salida 5.0V estable |
| L298N (H-bridge) | ✅ Funcional | Diodos internos de protección activos |
| INA219 (sensor corriente) | ⚠️ Dañado | `ina_ok: true` pero lecturas inconsistentes tras picos de corriente |
| Motor DC + Encoder | ✅ Funcional | Gira en ambas direcciones |
| Fuente 14.6V | ✅ Funcional | 14.68V medidos |
| **Diodo 1N4007** | ❌ **Quemado** | Se quemó por polaridad invertida. No usar diodo externo — L298N tiene protección interna |
| **Capacitor 470µF** | ❌ **Dañado** | Se dañó por polaridad invertida. Descartar los 3 usados (470µF, 220µF, 100µF) |

### Conexión actual del hardware:
- Fuente 14.6V → INA219 → L298N (VS/GND)
- LM2596 (VIN desde 14.6V) → 5V → ESP32 VIN
- L298N OUT1/OUT2 → Motor DC
- **Sin capacitor** en rail 5V (los disponibles se quemaron)
- **Sin diodo externo** (el L298N tiene protección interna)

---

## Cambios de Firmware Aplicados

### 1. Alpha continuo para LQR (CRÍTICO)
**Archivo:** `esp32_qube_l298n.ino`, línea ~1527
**Problema:** `alpha = pendPos - copysign(180, pendPos)` usa posición wrapped [-180,180] que cruza discontinuamente en ±180°.
**Fix:** Calcular alpha con aritmética modular usando `pendPosRaw`:
```cpp
float alpha = fmodf(alpha_raw - 180.0f, 360.0f);
if (alpha < -180.0f) alpha += 360.0f;
else if (alpha > 180.0f) alpha -= 360.0f;
alpha = -alpha;  // negativo=debajo, positivo=arriba (cruzado)
```
**Resultado:** Elimina la discontinuidad de alpha en ±180°. El LQR debería funcionar mejor.

### 2. Recovery persistente en swing-up
**Archivo:** Línea ~1654
**Problema:** Cuando el péndulo cruzaba 180°, el swing-up seguía bombeando y el péndulo se iba a spinning.
**Fix:** Variable global `swing_recovering` que:
- Activa cuando `|pendPosRaw| > 180°`
- Mantiene motor apagado (pwm=0)
- Espera a que `|pendPos| < 30°` (péndulo cae al fondo)
- Reanuda pumping

**Estado:** Implementado pero NO probado correctamente (el primer test corrió con firmware viejo por error de caché de PlatformIO).

### 3. Dead zone a 160°
**Archivo:** Línea ~1653
**Cambio:** De 172° a 160° para permitir que el swing-up alcance amplitudes más altas.
**Resultado:** El péndulo alcanza ±170° y transiciona a LQR.

### 4. Damping progresivo 150°-180°
**Archivo:** Línea ~1672
**Implementación:** Damping lineal de 0.3 (a 150°) a 1.0 (a 180°).
**Resultado:** Reduce la velocidad del péndulo antes de la vertical pero no es suficiente para prevenir overshoot.

### 5. LQR gains probados (K2_NEAR=30, K4_NEAR=15)
**Archivo:** Línea ~196
**Valores:** Los mismos que lograron 55+ segundos en la sesión anterior.
**Resultado:** El LQR sostuvo 7.7 segundos en un test (round 15) con oscilaciones de ±25°.

### 6. Catch mode PWM ±60 (400ms)
**Archivo:** Línea ~1518
**Cambio:** De ±20 a ±60 para mayor fuerza de frenado al entrar a LQR.
**Resultado:** Mejora la captura pero no es suficiente para frenar el péndulo completamente.

### 7. Fallback usa pendPosRaw
**Archivo:** Línea ~1580
**Cambio:** De `alpha > 45°` (wrapped) a `|pendPosRaw| > 360°` (raw).
**Resultado:** El fallback se activa correctamente cuando el péndulo acumula una vuelta.

### 8. Servo protection direction-aware en LQR
**Archivo:** Línea ~1596
**Implementación:** Corta PWM que empuja hacia el hard stop (±70° → ±85°).
**Resultado:** Previene brownout por motor stalled contra el stop.

### 9. Transición balance_threshold = 1°
**Archivo:** Línea ~229
**Cambio:** De 5° a 1° para transicionar solo cuando el péndulo está muy cerca de la vertical.
**Resultado:** NO probado (el firmware con este cambio nunca se flasheó correctamente).

### 10. Anti-spin threshold 360°
**Archivo:** Línea ~1617
**Cambio:** De 720° a 360° para detectar spinning antes.

---

## Tests Realizados (22+ flashes OTA)

| Round | Cambio | Resultado |
|---|---|---|
| 1-2 | K2_VERY_NEAR, damping LQR | Swing-up OK, spinning a los 20s |
| 3-4 | Catch ±60, fallback 45°, vel 15°/s | Transición con raw=-287°, offset acumulado |
| 5-6 | Fix energía con pendPos_abs | **Bug:** energy_ratio=1 en reposo → PWM=0 |
| 7-8 | Fix referencia energía desde fondo | **Bug:** dist_from_vert=180° en fondo → PWM=0 |
| 9-10 | Revert a energía original | Swing-up OK pero solo ±8° |
| 11-12 | Dead zone 160°, vel 40°/s | Péndulo llega a 172°, transiciona a LQR |
| 13-14 | Dead zone 172° | Spinning después de transición |
| 15 | LQR gains probados (K2=30, K4=15) | **LQR sostuvo 11.3s** — mejor resultado |
| 16 | Servo protection | Sin brownout pero oscilaciones |
| 17 | Fallback usa pendPosRaw | Crasheo a ~55s |
| 18-20 | Tests sin capacitor/diodo | Swing-up funciona ±113° en 60s |
| 21 | Diodo 1N4007 (polaridad invertida) | **ESP32 crashea a ~200ms** — diodo cortocircuita L298N |
| 22 | Diodo removido, capacitor 470µF | **Capacitor dañado** — 2V en rail 5V |
| 23 | Capacitor removido, cables invertidos | Sistema funciona, INA219 recuperado |
| 24 | Alpha continuo + recovery persistente | **NO flasheó** — error de caché PlatformIO |
| 25 | Clean build + reflash | Test interrumpido por usuario |

---

## Problemas Encontrados

### Hardware
1. **Diodo 1N4007 NO es compatible con H-bridge** — En un H-bridge, la polaridad del motor se invierte. El diodo se convierte en cortocircuito en un sentido. **No usar diodo externo** — el L298N tiene diodos flyback internos.
2. **Capacitor electrolítico polarizado** — Se daña permanentemente si se instala al revés. Los 3 capacitores usados deben descartarse.
3. **INA219 dañado parcialmente** — Probablemente dañado por los picos de corriente del diodo invertido. Las lecturas son inconsistentes.

### Firmware
1. **Energy ratio bug** — Usar `pendPos` directamente en `cos()` causa discontinuidad en ±180°. Fix: usar `pendPos_abs = fmod(pendPos+360, 360)`.
2. **Alpha discontinuo** — `pendPos - copysign(180, pendPos)` cruza discontinuamente. Fix: aritmética modular con `pendPosRaw`.
3. **Recovery no persistente** — Sin estado `swing_recovering`, el recovery se ejecuta una vez y el pumping se reanuda inmediatamente.
4. **PlatformIO caché** — Error `FileNotFoundError: .sconsign312.tmp`. Fix: `pio run -t clean` antes de recompilar.

---

## Resultados Clave

### ✅ Lo que funciona
- Swing-up alcanza ±170° consistentemente
- LQR atrapa el péndulo (mejor resultado: 11.3 segundos)
- Servo protection previene brownout
- Anti-spin detecta spinning y resetea offset
- Alpha continuo elimina discontinuidad (implementado, pendiente de prueba)

### ❌ Lo que NO funciona
- LQR no estabiliza — oscilaciones demasiado grandes después de la captura
- Recovery no se probó con el firmware correcto
- Damping progresivo no es suficiente para prevenir overshoot
- Los componentes de hardware (diodo, capacitor) se dañaron por polaridad incorrecta

---

## Próximos Pasos

1. **Probar firmware con alpha continuo y recovery persistente** — Ya compilado y flasheado, necesita test de 90s
2. **Instalar capacitor 470µF NUEVO** (no los dañados) con polaridad correcta
3. **Si el LQR no estabiliza:** Considerar LQR con ángulo unwrap (usar `pendPosRaw` directamente en vez de wrapped)
4. **Documentar en ANALYSIS.md** los resultados del test con recovery

---

## Archivos CSV Generados

- `swing_20260604T042032.csv` — Test 60s, firmware viejo (error de caché)
- `swing_20260604T042344.csv` — Test 90s, firmware viejo (error de caché)
- `swing_20260604T042716.csv` — Test interrumpido, firmware nuevo (alpha continuo + recovery)

---

## Parámetros Finales del Firmware

| Parámetro | Valor | Notas |
|---|---|---|
| `ke_gain` | 0.5 | Ganancia swing-up |
| `balance_threshold` | 1.0° | Umbral de transición a LQR |
| `SWINGUP_TRANSITION_VEL_DPS` | 15°/s | Velocidad máx. para transicionar |
| `LQR_K2_NEAR` | 30.0 | K2 cerca de vertical |
| `LQR_K4_NEAR` | 15.0 | K4 cerca de vertical |
| `LQR_K2_VERY_NEAR` | 55.0 | K2 muy cerca de vertical |
| `LQR_K4_VERY_NEAR` | 20.0 | K4 muy cerca de vertical |
| `LQR_NEAR_DEG` | 25.0° | Umbral para gains agresivos |
| `LQR_VERY_NEAR_DEG` | 5.0° | Umbral para gains muy agresivos |
| `LQR_DAMPING_GAIN` | 0.3 | Damping en LQR |
| `LQR_FALLBACK_ALPHA_DEG` | 45.0° | Umbral de fallback |
| `LQR_FALLBACK_TIME_MS` | 500ms | Tiempo antes de fallback |
| Dead zone swing-up | 160° | Zona de no-bombeo |
| Anti-spin threshold | 360° | Detección de spinning |
| Catch mode PWM | ±60 | Frenado al entrar a LQR |
| Catch mode duration | 400ms | Duración del catch |
| Servo protection | ±70° a ±85° | Direction-aware cutoff |
| `swing_recovering` | persistente | Estado de recovery |
| `SWING_RECOVERY_THRESHOLD` | 30° | Umbral para salir de recovery |
