# Swing-up Session Log — 2026-06-03/04

## 🎯 Hito: LQR sostiene péndulo invertido 55+ segundos

**Test**: swing_20260604T002350.csv
**Configuración**: K2_NEAR=30, K4_NEAR=15, ke=0.5, fallback=30°
**Resultado**: El LQR atrapa el péndulo a ~176° y lo mantiene en modo 4 durante
55+ segundos (de ~35s a 90s del test). El péndulo oscila en un ciclo límite
alrededor de ±180° pero nunca cae al fondo.

**COMPILA**: ✅ (RAM 15.0%, Flash 72.5%)
**OTA**: ✅ Subido por WiFi

### Tests realizados con soft saturation

| CSV | k_sat | centering_kp | catchMs | Resultado |
---|---|---|---|---|
swing_235743 | 30 | - | 0 | Oscila ±90° (PWM reducido demasiado) |
swing_235951 | 60 | - | 0 | Oscila ±120° |
swing_234620 | 80 | - | 0 | Oscila ±145° |
swing_000104 | 80 | 0.8 | 0 | Servo pegado, péndulo ±55° (centering agresivo) |
swing_000515 | 80 | 0.2 | 0 | **LQR catch a 181.2°, sostuvo 600ms** ✅ |
swing_000856 | 80 | 0.2 | 0 | LQR catch a 162.6°, spinning post-fallo |
swing_001325 | 80 | 0.2 | millis() | Oscila ±108°, sin transición LQR |

### Configuración actual del firmware

| Parámetro | Valor | Nota |
---|---|---|
ke_gain | 0.45 | Sweet spot para swing-up |
balance_threshold | 5° | Umbral angular para transición LQR |
SWINGUP_TRANSITION_VEL_DPS | 20°/s | Velocidad máx. para transicionar |
LQR_K1 | 2.0 | Posición servo |
LQR_K2 | 22 | Ángulo péndulo (base) |
LQR_K2_NEAR | 60 | Ángulo péndulo (<15° de vertical) |
LQR_K4 | 9 | Velocidad péndulo (base) |
LQR_K4_NEAR | 25 | Velocidad péndulo (<15° de vertical) |
LQR_CATCH_MS | 400ms | Duración del catch brake |
catch mode PWM | ±20 | PWM del catch mode |
LQR PWM limit | ±70 | Limitado por soft saturation |
swing-up PWM limit | ±70 | Limitado por soft saturation |
soft saturation k | 80° | Umbral de saturación suave |
soft saturation y | 2 | Agresividad de la curva |
centering_kp | 0.2 | Ganancia de recentrado del servo |
VEL_ALPHA_PEND | 0.60 | Filtro EMA velocidad péndulo |

### Hallazgo principal

El **servo centering** (kp=0.2) es la mejora más efectiva — reduce la oscilación del
servo y mejora la transferencia de energía al péndulo. Con centering, el péndulo llega
a 162-181° (vs 145° sin centering).

El **LQR atrapó el péndulo a 181.2°** y lo sostuvo ~600ms. El problema es que el
catch mode no estaba activo (lqr_catchMs=0). Con catch mode activo (millis()), el
swing-up no alcanza la amplitud necesaria para transicionar.

### Próximos pasos

1. **Reproducibilidad**: El test con catchMs=0 llegó a 181° pero con catchMs=millis()
   solo a 108°. Puede ser por condiciones iniciales o el offset del encoder.
   → Resetear offset antes de cada test y repetir.

2. **Aumentar ke_gain a 0.5**: Si el swing-up no llega a ±180°, subir ke para más
   autoridad. El spinning se controla con el anti-spin cooldown.

3. **Reducir LQR_FALLBACK_ALPHA_DEG a 30°**: Para que el LQR suelte el péndulo más
   rápido cuando lo pierda, evitando el spinning prolongado.


### Crash loop durante swing-up (NUEVO PROBLEMA)
El ESP32 se reinicia a los ~10s de swing-up, cuando el péndulo alcanza ±130°.
El servo llega al hard stop (-45° a -47°) y el ESP32 crashea (posible brownout
por corriente del motor en el hard stop, o stack overflow).

**Patrón del crash**:
1. Swing-up arranca normalmente, péndulo oscila creciente
2. A los ~8-10s, péndulo alcanza ±130°, servo llega a -45° (hard stop)
3. ESP32 deja de responder HTTP
4. Después de ~10s, vuelve con mode=0 (reboot)

**Posibles causas**:
- Brownout: el hard stop a ±40 PWM causa pico de corriente que baja el voltaje
- Stack overflow: alguna función recursiva o buffer demasiado grande
- Watchdog timer: el control loop tarda demasiado en una iteración

**Próximos pasos para mañana**:
1. Reducir el hard stop PWM de 40 a 20
2. Agregar `yield()` o `delay(0)` en el control loop para alimentar el watchdog
3. Verificar el voltaje del ESP32 durante el swing-up con un multímetro
4. Si persiste, agregar `Serial.printf` de debug antes/después del hard stop

---

### Tests realizados hoy (CSVs en data/)

| CSV | Resultado |
---|---|
swing_224214 | Swing-up hasta ±130°, crash a 10.7s |
swing_224423 | Swing-up hasta ±141°, crash a 10.7s |

### Archivos modificados hoy
- `esp32_qube_l298n.ino`: `else if` fix, disipación energía, anti-spin cooldown
- `experiments/2026-06-03_swing/SESSION_LOG.md`: este log
- `experiments/2026-06-03_swing/ANALYSIS.md`: root cause + plan
- `CHANGELOG.md`: v1.30.1

## Hallazgo principal: `if` → `else if` en cadenas de modo

### Problema descubierto
Los bloques de modo 2, 3, 4, 5 usaban `if (mode == N)` independientes en vez de
`else if`. Esto causaba que cuando el modo cambiaba (ej: swing-up → LQR), el bloque
del modo anterior seguía ejecutándose en el mismo ciclo y sobreescribía `pwm`.

**Ejemplo concreto**: En la transición swing-up→LQR:
1. Swing-up (modo 5) calcula `pwm` y llama `setMode(4)` (cambia `mode` a 4)
2. El bloque `if (mode == 4)` se ejecuta (LQR calcula su pwm)
3. PERO el bloque `if (mode == 5)` TAMBIÉN se ejecuta (era independiente)
4. El anti-spin brake de modo 5 escribe `pwm = -100` sobre el LQR
5. El LQR pierde el péndulo inmediatamente

### Fix aplicado (incompleto)
- Cambiado `if (mode == 2)` → `if` (primero de la cadena)
- Cambiado `if (mode == 3)` → `} else if (mode == 3)`
- Cambiado `if (mode == 4)` → `} else if (mode == 4)`
- Cambiado `if (mode == 5)` → `} else if (mode == 5)`

### Problema restante
El `}` de cierre de modo 3 (antes de `else if (mode == 4)`) cierra el bloque
del timing loop en vez del bloque de modo 3. Necesita eliminarse para que el
`} else if` maneje el cierre.

---

## Progreso de la sesión

### 1. Disipación de energía en swing-up ✅
Implementada en 3 rangos de `energy_ratio = E / Er`:
- `energy_ratio >= 0.9`: freno progresivo (brake_gain 0.3→1.0 lineal)
- `energy_ratio >= 0.85`: bombeo reducido al 50%
- `energy_ratio < 0.85`: bombeo normal

**Resultado**: El péndulo oscila establemente hasta ±160-165° sin spinning.
Pero no llega a ±180° (vertical) porque la disipación frena demasiado pronto.

### 2. Umbrales de transición LQR ✅
- `|pendPos| > 150°`: péndulo en hemisferio superior
- `vel_raw < 15°/s`: velocidad angular casi cero (pico de oscilación)
- `dist_from_up < 5°`: muy cerca de la vertical

**Problema**: `vel_raw < 15°/s` es casi inalcanzable. En el pico de la
oscilación (170°), la velocidad sigue siendo ~142°/s. El umbral debería
ser más laxo (~50-80°/s) o la disipación debe ser más efectiva.

### 3. LQR gains y catch mode ✅
- Gains base: K1=2.0, K2=22, K3=1.5, K4=9
- Gains agresivos (<15° de vertical): K2_NEAR=60, K4_NEAR=25
- Catch mode: 400ms de freno a ±40 PWM al entrar a LQR
- Fallback: 500ms antes de volver a swing-up
- Hard stop proporcional (2 PWM/grado, limitado a 40)

### 4. Anti-spin con cooldown ✅
- Detección por delta de posición raw >200° o acumulación >720°
- Reset inmediato de offset + freno PWM_MAX
- Cooldown de 1000ms para no re-activar inmediatamente
- Reset de cooldown al entrar a LQR

---

## Datos de tests (CSVs guardados)

| CSV | brake_gain | Resultado |
|---|---|---|
| swing_173358 | 0.3 | Oscila ±170°, LQR catch fallido |
| swing_173808 | 0.3 | Oscila ±170°, LQR catch a -171.9° |
| swing_182109 | 0.3 | Oscila ±170°, LQR catch, ESP32 crash |
| swing_182535 | 2.0 | Oscila ±165°, disipación excesiva |
| swing_182810 | 1.0 | Oscila ±165°, disipación excesiva |
| swing_183106 | 0.5 | Oscila ±160°, estable 60s sin spinning |
| swing_183343 | 0.5 | Oscila ±160°, estable 60s |
| swing_183622 | progresivo 0.3→1.0 | Oscila ±160°, spinning a los 16s |
| swing_183909 | progresivo 0.3→1.0 | Oscila ±160°, spinning a los 16s (mismo bug `if`→`else if`) |

---

## Plan para mañana

### Prioridad 1: Arreglar compilación
1. Eliminar el `}` extra en línea ~1505 del `.ino`
2. Verificar que la cadena `if/else if` de modos 2→3→4→5 compila
3. Verificar que `pendPos`, `pendPosRaw`, `dt` son visibles en todos los bloques

### Prioridad 2: Probar con `else if` fix
El bug de `if` independiente explica por qué el LQR perdía el péndulo — el
anti-spin brake de modo 5 sobreescribía el pwm del LQR. Con `else if`, el
LQR debería funcionar correctamente.

**Test esperado**: Swing-up hasta ~170° → transición a LQR → LQR sostiene
el péndulo porque el anti-spin no interfiere.

### Prioridad 3: Ajustar disipación si es necesario
Si el LQR funciona con `else if` pero el péndulo no llega a ±180°:
- Subir `brake_gain` progresivo de 0.3→1.0 a 0.2→0.8
- O reducir el umbral de disipación de 0.9 a 0.95

### Prioridad 4: Reducir LQR gains si el catch es muy violento
Si el LQR atrapa el péndulo pero lo pierde por exceso de ganancia:
- Reducir K2_NEAR de 60 a 40
- Reducir K4_NEAR de 25 a 15

---

## Archivos modificados

| Archivo | Cambios |
|---|---|
| `esp32_qube_l298n.ino` | Disipación energía, anti-spin cooldown, `else if` (incompleto), LQR gains |
| `experiments/2026-06-03_swing/ANALYSIS.md` | Análisis de root cause + plan |
| `experiments/2026-06-03_swing/test_swing.py` | Script de test con logging CSV |
| `experiments/2026-06-03_swing/data/` | 19 CSVs de tests |
| `CHANGELOG.md` | v1.29.0 con cambios de hoy |
| `mcp/README.md` | Documentación MCP |
| `mcp/esp32_qube_server.py` | Herramienta `pio_ota_flash` |
