# HANDOFF — Sesión 2026-06-11: Swing-up PWM Tuning + Transiciones LQR

## Estado del hardware
- ESP32 IP: `192.168.100.50` (STA mode)
- Driver: BTS7960
- **ESP32 OFFLINE al final de la sesión** — necesita power cycle o wait para reconnect
- INA219: OK, Vbus ~14.8V

## Estado del firmware (EN FLASH, pero sin verificar)

### Último firmware subido vía HTTP `/update` con 3 cambios:

**1. Catch mode reducido** (L1514-1516)
```cpp
// ANTES: gain=0.5f, limit ±100
// AHORA:
float brake_pwm = lockedBrakeDir * fabsf(rawVelForCatch) * 0.25f;
pwm = constrain((int)brake_pwm, -50, 50);
```

**2. LQR centering gain reducido** (L1577-1579)
```cpp
// ANTES: centering_gain = 1.0
// AHORA:
float centering_gain = 0.5f;
float centering = -centering_gain * theta;
pwm += (int)centering;  // ← IMPORTANTE: este línea se perdió en un edit y se restauró
```

**3. Transiciones LQR restringidas** (L1715-1750)
```cpp
// ANTES: canTransition a 130° con vel < 120°/s
// AHORA:
bool nearVertical = fabsf(pendPos) > 155.0f;  // >155° para transicionar
bool verySlow = vel_raw_dps < 30.0f;
bool atPeakTransition = atPeak && (180.0f - fabsf(pendPos) < 25.0f);
bool forcedTransition = fabsf(pendPos) > 165.0f;  // era 150°
bool energyReady = ... && fabsf(pendPos) > 145.0f;  // era 100°
```

### ⚠️ VERIFICAR que el ESP32 suba correctamente tras power cycle
El último upload fue exitoso (`{"ok":true}`) pero el ESP32 se quedó offline. Puede haber un crash loop en el firmware nuevo. Si no responde tras 30s, power cycle manual.

## Cambios anteriores (ya en firmware)

| Parámetro | Valor | HTTP | Descripción |
|---|---|---|---|
| `swingupPwmMax` | 50 | `?sp=` | PWM limit para swing-up (10-100) |
| `ke_gain` | 0.65 | `?ke=` | Ganancia energy pumping |
| `balance_threshold` | 1.0 | `?bt=` | Umbral transición LQR |
| `pendulumOffsetDeg` | 0 | `?zp=` | Offset péndulo |
| Servo limit (modo 5) | 60° | N/A | Brakes antes del tope |

## Datos parciales del sweep

El sweep `sweep_20260611T022855` completó:
- **sp=45**: 4 catch / 1 transient / 0 miss (80% catch rate) — avg_max=153°
- **sp=50**: 2 catch / 1 transient / 2 miss — incompleto (interrumpido)
- **sp=55, 60, 65**: NO ejecutados

**Hallazgo parcial:** sp=45 con transiciones restringidas da 80% catch rate. El péndulo SÍ alcanza la vertical (155°+) antes de que LQR lo atrape.

CSV: `experiments/2026-06-10_autoresearch_swing/data/sweep_20260611T022855/sweep_data.csv`

## Problemas detectados en sesión

### 1. Servo se va al tope durante catch (RESUELTO PARCIALMENTE)
- Catch mode daba ±100 PWM → reducido a ±50
- Centering gain 1.0 → 0.5
- **Pendiente de verificar** con firmware nuevo

### 2. Péndulo no llega a 170° (RESUELTO)
- Causa: `canTransition` se activaba a 130°
- Fix: subido umbral a 155°, vel < 30°/s
- **Sweep parcial confirma que funciona** (80% catch a sp=45)

### 3. Flash falla por OneDrive lock (RESUELTO)
- Script `src/firmware/flash.py` usa HTTP POST a `/update`
- Si `firmware.bin` está bloqueado, convierte `.elf` → `.bin` en `/tmp`

### 4. ESP32 queda offline tras último flash
- **Último cambio:** catch mode gain reducido + centering reducido
- **Causa probable:** puede ser crash loop si algún parámetro causó comportamiento inestable
- **Fix:** power cycle + revertir centering a 0.15 si persiste

## Para la próxima sesión

### Pasos de inicio
1. Power cycle el ESP32 (desconectar/reconectar 12V)
2. Verificar: `curl "http://192.168.100.50/state"` → mode=0
3. Si no responde: flash anterior via serial o revisar si el firmware nuevo tiene bug

### Tareas pendientes
1. **Completar el sweep** — ejecutar `sweep_swingup.py` con sp=[45,50,55,60,65]
2. **Verificar catch mode** — con el firmware nuevo, el catch no debe enviar el servo al tope
3. **Verificar transiciones** — el péndulo debe llegar a 155°+ antes de la transición
4. **Sweet spot** — sp=45 parece prometedor (80% catch), pero falta sp=55-65
5. **Update CHANGELOG** — hay entrada [1.37.0] pero le faltan los cambios de catch mode y transiciones

### Comandos útiles
```bash
# Verificar ESP32
curl "http://192.168.100.50/state"

# Cambiar sp en vivo
curl "http://192.168.100.50/cmd?sp=55"

# Test rápido swing-up
curl "http://192.168.100.50/cmd?r=1" && sleep 0.5 && curl "http://192.168.100.50/cmd?m=5"

# Detener
curl "http://192.168.100.50/cmd?x=1"

# Build + flash
uv run python src/firmware/flash.py --ip 192.168.100.50

# Sweep completo
uv run python experiments/2026-06-10_autoresearch_swing/sweep_swingup.py
```

### Archivos clave
| Archivo | Estado |
|---|---|
| `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino` | Modificado (catch+transitions+centering) |
| `src/firmware/flash.py` | Nuevo — build+upload vía HTTP |
| `experiments/2026-06-10_autoresearch_swing/sweep_swingup.py` | Nuevo — sweep de sp values |
| `CHANGELOG.md` | Entrada [1.37.0] agregada (parcial) |

### Si el firmware nuevo causa crash
Revertir estos 3 cambios:
1. Catch mode: `gain 0.25f → 0.5f`, limit `-50,50 → -100,100`
2. Centering: `gain 0.5f → 1.0f`
3. Transiciones: `155° → 130°`, `30°/s → 120°/s`, `165° → 150°`, `145° → 100°`
