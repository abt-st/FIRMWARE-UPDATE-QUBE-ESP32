## [1.39.0] — 2026-06-16
### Entrenamiento RLtools-compatible: reward swingup_balance, red [64,64], exportación C++

#### Problema identificado
- Red [128,128] en `fast_train.py` era demasiado grande para inferencia ESP32 (~51 KB flash vs 17 KB con RLtools).
- No existía reward que adaptara penalidades entre fases de swing-up y balance.
- Sin forma de exportar pesos SB3 al formato C++ de RLtools (`persist_code`).

#### Cambios aplicados

**1. Nueva reward `swingup_balance` (`src/qube_rl/rewards.py`)**
- Penalidades leves durante swing-up (brazo libre), pesadas durante balance (brazo centrado).
- `balance_weight`: 0.1 (down) → 0.5 (inverted). `vel_weight`: 0.0005 → 0.0025.
- Verificado: DOWN=0.0, 45°=0.15, 135°=0.85, UP=1.0.

**2. Red [64,64] por defecto en `train.py`**
- Nuevo flag `--net-arch` (default 64). Guarda como `qube_sac_{net}x2.zip`.
- ~17 KB flash, ~1-2 KB RAM en ESP32 — compatible RLtools.

**3. Refactor de `fast_train.py`**
- Usa `swingup_balance` y [64,64] por defecto. Nuevos flags: `--reward`, `--net-arch`, `--exp-name`.

**4. Nuevo módulo `export_rltools.py`**
- Extrae pesos actor SB3 → genera header C++ `constexpr float[]` (RLtools `persist_code`).
- Uso: `uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip`

#### Notas
- Flujo completo: `train.py` → `export_rltools.py` → firmware ESP32 con RLtools.
- Compatible con modelos existentes: `--net-arch 256` reproduce config anterior.
- Sin cambios al firmware ni interfaz HTTP — solo pipeline de entrenamiento.

## [1.38.0] — 2026-06-16
### Filtro de Kalman (LQG) para estimación de estados del LQR

#### Problema identificado
El LQR (modo 4) estimaba velocidades angulares mediante diferencias finitas + filtro EMA,
que es ruidoso y introduce fase. El docs del proyecto priorizaba LQG (LQR + Kalman) como
mejora #1 por su factibilidad en ESP32 y alto impacto en desempeño.

#### Cambios aplicados

**1. Implementación del Filtro de Kalman discreto (4 estados)**
- Estado: `x = [theta, alpha, dtheta, dalpha]` (posiciones y velocidades)
- Mediciones: `z = [theta, alpha]` (solo posiciones de encoder)
- Modelo: péndulo rotatorio invertido linearizado, discretizado con Euler a 500 Hz
- Predict: propagación con modelo físico (motor + péndulo)
- Update: corrección con mediciones de encoder (posiciones)
- Matrices Q, R, P ajustables en runtime

**2. Integración con LQR (modo 4)**
- Cuando `kf_enabled=true`: LQR usa velocidades estimadas por el KF
- Cuando `kf_enabled=false`: LQR usa EMA (comportamiento original, sin cambios)
- EMA siempre se calcula como fallback (no se pierde información)

**3. HTTP command `kf<0|1>`**
- `GET /cmd?kf=1` activa el filtro de Kalman (resetea estado)
- `GET /cmd?kf=0` vuelve al filtro EMA
- Toggle en tiempo real para comparar desempeño

**4. Telemetría expandida en `/state`**
- `kf_enabled`: estado del filtro
- `kf_theta`, `kf_alpha`: posiciones estimadas por KF
- `kf_dtheta`, `kf_dalpha`: velocidades estimadas por KF (la mejora principal)

#### Arquitectura del KF
```
Modelo discreto (Euler, Ts=2ms):
  Ad = [1  0  Ts   0    ]    Bd = [0, 0, Km*Ts, 0]^T
       [0  1   0  Ts   ]
       [0  0 1-b1*Ts  0     ]
       [0  w2*Ts  0  1-b2*Ts]

H = [1 0 0 0]  (mide posiciones)
    [0 1 0 0]

Predict: x = Ad*x + Bd*u,  P = Ad*P*Ad^T + Q
Update:  K = P*H^T*(H*P*H^T + R)^-1,  x = x + K*(z - H*x)
```

#### Parámetros del modelo
| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `KF_MOTOR_GAIN` | 50.0 | PWM -> deg/s^2 |
| `KF_SERVO_FRIC` | 2.0 | Amortiguamiento servo (1/s) |
| `KF_PEND_FREQ` | 12.3 | sqrt(g/l) pendulo [rad/s] |
| `KF_PEND_FRIC` | 0.5 | Amortiguamiento pendulo (1/s) |
| `kf_Q_pos` | 0.1 | Ruido proceso: posicion (deg^2) |
| `kf_Q_vel` | 10.0 | Ruido proceso: velocidad (deg/s^2) |
| `kf_R_pos` | 0.5 | Ruido medicion: encoder (deg^2) |

#### Cambios de firmware
```cpp
// Filtro de Kalman: predict + update en cada ciclo LQR
if (kf_enabled) {
  kalmanPredict((float)lastPwmCmd / (float)PWM_MAX);
  kalmanUpdate(theta, alpha_raw);
}
// LQR usa KF cuando habilitado
float velTheta_ctrl = kf_enabled ? kf_x[2] : lqr_filteredVelTheta;
float velAlpha_ctrl = kf_enabled ? kf_x[3] : lqr_filteredVelAlpha;
```

#### Notas
- RAM: ~200 bytes adicionales (P 4x4 + K 4x2 + x 4)
- CPU: <50 us por ciclo (predict + update) — insignificante a 500 Hz
- No afecta otros modos (PID, swing-up) — solo LQR (modo 4)
- Parámetros del modelo (`KF_MOTOR_GAIN`, etc.) requieren calibración experimental
- Toggle: `curl "http://192.168.4.1/cmd?kf=1"`


## [1.37.0] — 2026-06-11
### Swing-up: PWM acotado + param HTTP ajustable en vivo

#### Problema identificado
El servo golpeaba el tope mecánico izquierdo durante el swing-up porque PWM_MAX=100
era excesivo para resonant pumping. El servo se saturaba en el borde y no podía
oscilar en fase con el péndulo. Además, no había forma de ajustar el PWM sin
recompilar el firmware.

#### Cambios aplicados

**1. `SWINGUP_PWM_MAX` → `swingupPwmMax` (mutable)**
- Antes: `const int SWINGUP_PWM_MAX = 100` (const, inmutable)
- Ahora: `int swingupPwmMax = 50` (configurable vía HTTP en runtime)
- Rango aceptado: 10–100

**2. HTTP param `sp<val>`**
- Nuevo handler en `handleCmd`: `?sp=55` ajusta `swingupPwmMax` en tiempo real
- Permite encontrar el sweet spot sin recompilar
- Formato: `GET /cmd?sp=55`

**3. Todos los paths de modo 5 usan `swingupPwmMax`**
- Kick sinusoidal (péndulo quieto): `constrain(pwm, -swingupPwmMax, swingupPwmMax)`
- Resonant pump (péndulo oscilando): `constrain(pwm, -swingupPwmMax, swingupPwmMax)`
- Damping (próximo a vertical): `constrain(..., -swingupPwmMax, swingupPwmMax)`
- Recovery brake: `constrain(..., -swingupPwmMax, swingupPwmMax)`
- Servo limit brake: `constrain(center_pwm, -swingupPwmMax, swingupPwmMax)`
- Anti-spin brake se mantiene en `PWM_MAX` (frenado máximo para parar spinning)

**4. Servo limit reducido: 80° → 60°**
- Brakes antes de llegar al tope mecánico
- Previene que el servo se acumule en el borde durante pumping

**5. Fix bug pre-existente: `sv` → `pos`**
- Variable `sv` no existía en el scope del modo 5
- Corregida a `pos` (la variable real de posición del servo, línea 1407)

**6. Script `flash.py` — build+upload vía HTTP**
- Usa `POST /update` en vez de espota.py/esptool
- Soluciona el lock de OneDrive sobre `firmware.bin`
- Si `.bin` está bloqueado, convierte `.elf`→`.bin` en `/tmp`
- Args: `--ip`, `--build-only`, `--upload-only`

#### Cambios de firmware
```cpp
// Constante mutable (antes era const)
int swingupPwmMax = 50;  // configurable por HTTP: sp<val>

// Handler HTTP nuevo
if (request->hasParam("sp")) {
  swingupPwmMax = constrain(request->getParam("sp")->value().toInt(), 10, 100);
}

// Todos los constrain del modo 5 ahora usan swingupPwmMax
pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
```

#### Notas
- Default: `swingupPwmMax=50` (punto medio entre 35=insuficiente y 65=excesivo)
- Para ajustar en vivo: `curl "http://IP/cmd?sp=55"`
- Compilación: RAM 15.0%, Flash 73.1%
- Sweep parcial: sp=45 → 80% catch rate

## [1.36.0] — 2026-06-08
### Swing-up funcionando con driver BTS7960

#### Problema identificado
El swing-up con el nuevo driver BTS7960 no funcionaba: el servo se atascaba en los límites mecánicos, la bomba de energía no consideraba la posición del servo, y el frenado de emergencia era inefectivo por la soft saturation.

#### Cambios aplicados

**1. Filtro EMA para velocidad del péndulo en swing-up**
- Antes: `alpha_dot` sin filtrar a 500Hz causaba ruido que impedía el kick alternante
- Ahora: `swing_filteredVelAlpha` con misma constante que LQR (0.60)

**2. `setMotorDirect()` — bypass de soft saturation**
- Función nueva para frenado de emergencia sin la reducción de PWM por soft saturation
- Hard stop a 150° motor-shaft usa `setMotorDirect` para frenado efectivo

**3. Modulación por posición del servo en bomba de energía**
- Amplitud del bombeo se reduce linealmente: 100% en centro, 0% a 200°
- Previene que el servo se acumule en un lado del rango
- Cutoff 200° (actúa solo cerca del hard stop 150°)

**4. Centering suave del servo durante swing-up**
- kp=0.15 proporcional a posición raw del servo
- Guía el servo de vuelta al centro sin frenar la bomba de energía

**5. Parámetros ajustados para BTS7960**
- Soft saturation k: 80° → 120°
- Damping threshold: 120° → 165°
- LQR transition: hemisferio 165°→140°, velocidad 10→50°/s, distancia 1°→20°
- Hard stop: 150° motor-shaft (≈80° output)

**6. Bug Python 3.14 en scripts de sweep**
- `urlopen(url, 5)` interpretaba 5 como data, no timeout → fix: `urlopen(url, timeout=5)`

#### Resultados del entrenamiento (Fase 1-4)
- **ke=0.65 optimo** (25-36% catch rate, hold promedio 82s)
- **bt=1 optimo** (mejor catch rate, servo controlado)
- **LQR hold: 59-88s** (de 90s posibles)
- Transiciones: hemisferio >130°, vel <80°/s, dist <25°
- **Peak detection**: detecta pico de posicion (alpha_dot zero crossing) — sin mejora significativa
- **Forced transition a 165°+**: sin mejora significativa
- **Angle-dependent PWM limit**: PEOR — mata transferencia de energia
- **Ramp-down desde 60°**: PEOR — servo sin autoridad
- **Hard stop final: 120° motor-shaft** con setMotorDirect

#### Problema pendiente: brownout
- Crash rate 20%: motor golpea limite mecanico, voltaje baja
- Angle-dependent limit reduce energia — no es solucion firmware
- **Solucion requerida: capacitor 470-1000uF en rail 5V**

#### Analisis de 173 CSVs
- Catch SOLO ocurre a 150°+ (28% catch rate en 150-180°, 100% en 200°+)
- 85% de intentos no llegan a 150° — bottleneck es energia de bombeo

#### Notas
- Scripts: `test_lqr.py [ke] [attempts] [duration]`, `analyze_all.py`
- Parámetros tuneables vía HTTP: `?ke=`, `?bt=`
- Archivos: `COMPARISON.md` (historico), `SESSION_LOG.md` (detallado)

## [1.35.1] — 2026-06-08
### Fix: selector de modo + reparación SPIFFS + Chart.js CDN

#### Problema 1: Selector de modo se revertía a STOP
El selector de modo en la GUI HTML (`data/index.html`) se revertía inmediatamente a STOP al hacer clic en "Aplicar".

**Causa raíz:** `cmd()` limpiaba `modeUserOverride=false` antes de que el `fetch()` completara. El WebSocket (100ms) enviaba `mode=0` y revertía el selector.

**Fix:** Eliminadas `modeUserOverride=false` y `clearTimeout(modeOverrideTimer)` de `cmd()`. Ahora se gestiona exclusivamente por el `onchange` del `<select>` (8s de gracia).

#### Problema 2: SPIFFS corrupto
Los uploads OTA de SPIFFS (`pio run --target uploadfs`) reportaban SUCCESS pero el contenido no cambiaba. El ESP32 servía archivos viejos o devolvía 500.

**Fix:** Agregado endpoint `GET /format` al firmware que ejecuta `SPIFFS.format()` + `ESP.restart()`. Después se suben los archivos vía `POST /fs`.

#### Problema 3: Chart.js no disponible offline
`chart.min.js` (208KB) no se podía subir a SPIFFS corrupto.

**Fix:** Cambiado `<script src="/chart.min.js">` a CDN de jsDelivr (`cdn.jsdelivr.net/npm/chart.js@4.4.7`). Requiere internet (modo STA).

#### Cambios de firmware
```cpp
// Nuevo endpoint /format
server.on("/format", HTTP_GET, [](AsyncWebServerRequest *request) {
  bool ok = SPIFFS.format();
  request->send(200, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false}");
  delay(500);
  ESP.restart();
});

#### Notas
- Para reparar SPIFFS en el futuro: `GET /format` → subir archivos vía `POST /fs`
- El parámetro `reboot` temporal en `/cmd` fue removido (ya existe `/restart`)
- OneDrive bloquea archivos `.pio/build` durante sync — usar directorio temporal para builds OTA

## [1.35.0] — 2026-06-08
### Migración de driver de motor: L298N → BTS7960

#### Problema identificado
El L298N (H-Bridge BJT) tiene limitaciones significativas: caída de voltaje de ~2V por los transistores bipolares, corriente máxima de 2A continua (3A pico), y ruido de conmutación PWM de ~100 mV pico que afecta las señales de encoder. Además, se requiere disipador para operación sostenida.

#### Decisión
Migrar a **BTS7960** (Infineon, Dual Half-Bridge MOSFET) — módulo IBT-2. Mejoras sustanciales:

| Parámetro | L298N (antes) | BTS7960 (ahora) |
|-----------|--------------|-----------------|
| Tecnología | BJT | MOSFET |
| RDS(on) total | ~530 mΩ | ~32 mΩ (16 mΩ × 2) |
| Caída de voltaje @ 2A | ~2.0 V | ~0.5 V |
| Corriente máxima | 2A cont. / 3A pico | 10A cont. / 43A pico |
| Disipación @ 2A | ~4 W (requiere disipador) | ~0.1 W (sin disipador) |
| Ruido PWM switching | ~100 mV pico | ~20 mV pico |
| Protecciones | Ninguna integrada | Overcurrent, OTP, UVLO, SCP |
| Costo | $1.50–3 USD | $2–5 USD |

#### Conexiones (GPIOs sin cambio)

| Función | GPIO ESP32 | Conexión L298N (antes) | Conexión BTS7960 (ahora) |
|---------|-----------|----------------------|------------------------|
| PWM adelante | GPIO26 | IN1 | RPWM |
| PWM reversa | GPIO27 | IN2 | LPWM |
| Enable | GPIO25 | ENA (jumper) | R_EN/L_EN (pull-up interno) |
| Motor + | — | OUT1 | M+ |
| Motor − | — | OUT2 | M− |

#### Cambios de documentación
1. **README.md**: Diagrama de arquitectura, topología de potencia, pinout completo, BOM, Cableado de EN, tabla de comparativa de rendimiento, referencias/datasheets actualizados
2. **MODELO_FISICO_SISTEMA_QUBE.md**: Modelo del puente H (§4), topología de MOSFETs, tabla PWM RPWM/LPWM, modelo de pérdidas con RDS(on), ecuación del bloque motor, fuentes de ruido reducidas
3. **Investigación Modernización**: Diagrama de bloques, flujo de datos, asignación de pines, tabla comparativa, BOM
4. **estabilizacion_senales.md**: Tablas de ruido RF/budget, diagramas de tierra (star ground)
5. **integracion_encoder_pendulo.md**: Estado del driver
6. **Validation docs** (5 archivos): Marco científico, resumen ejecutivo, checklist, matriz de referencias
7. **AI research docs** (4 archivos): Modelado LQR, CD40106BE, condicionamiento encoder, RL
8. **src/qube_ui/app.py**: Título de ventana y header
9. **AGENTS.md**: Tabla de arquitectura base
10. **Backup L298N**: Documentación anterior preservada en `backup_l298n/` (gitignored)

#### Archivos no modificados (intencionalmente)
- **Firmware** (`esp32_qube_l298n.ino`): No requiere cambios — el control PWM diferencial IN1/IN2 es idéntico a RPWM/LPWM. Los GPIOs (26, 27) permanecen igual. `MOTOR_DIR` puede necesitar ajuste al instalar el nuevo driver.
- **CHANGELOG entradas anteriores**: Registros históricos preservados con referencias L298N originales
- **Session logs de experimentos**: Datos de sesiones con L298N preservados intactos

#### Notas
- No se requiere recompilar firmware — el esquema de control PWM es compatible (IN1/IN2 = RPWM/LPWM)
- Al instalar el BTS7960, verificar que `MOTOR_DIR` sea correcto (puede requerir invertir cables M+/M−)
- El módulo IBT-2 tiene R_EN y L_EN con pull-up interno — no es necesario conectar el pin EN
- La reducción de ruido de ~5× mejora la relación señal/ruido del encoder (verificado experimentalmente en sesión 2026-06-04: ~20 mV vs ~100 mV)


## [1.34.0] — 2026-06-04
### Eliminación completa del PID Péndulo (modo 3)

#### Problema identificado
El péndulo del QUBE es un brazo articulado pasivo sin motor propio. El modo 3 (PID Péndulo) intentaba controlar algo que no existe físicamente. Se eliminó completamente del firmware, interfaz web, GUI Python y servidor MCP.

#### Cambios de firmware
1. **Variables eliminadas**: `Kp_pend`, `Ki_pend`, `Kd_pend`, `integralTermPend`, `filteredVelPend`, `pendulum_setpoint_deg`
2. **Constantes eliminadas**: `PEND_ANTIWIND_*`, `PEND_STICTION_*`, `PEND_DEADBAND_*`, `PEND_LIMIT_*` (11 constantes)
3. **Función eliminada**: `resetPendulumPid()`
4. **Bloque modo 3 eliminado**: todo el control PID del péndulo en el loop principal
5. **Handlers HTTP eliminados**: `sp` (setpoint péndulo), `kpp`/`kip`/`kdp` (gains péndulo)
6. **Serial**: sub-comando `sp` eliminado, referencias removidas de handlers `zp`, `op`, `edp`, `cprp`, `r`
7. **Telemetría JSON**: removidos `pend_setpoint_deg` y `pend_error_deg` de `/state`
8. **Conservado**: `prevPosPend` (swing-up), `VEL_ALPHA_PEND` (LQR), encoder péndulo, modos 4 y 5

#### Cambios de interfaz web (SPIFFS)
1. **index.html** (ambos data/): opción `PID Péndulo` removida del selector de modos
2. **Panel PID Péndulo eliminado**: entradas Kp/Ki/Kd y botón OK
3. **Fila SP P eliminada**: input setpoint péndulo y botón Set
4. **Script restaurado**: funciones `toggleRec()`, `clearRec()`, `exportCSV()`, chart flush optimization, mode override

#### Cambios de GUI Python
1. **client.py**: métodos `set_pendulum_setpoint()` y `set_pendulum_pid()` eliminados
2. **app.py**: `3: "PID Péndulo"` removido de MODE_NAMES, secciones UI SETPOINT PÉNDULO y PID PÉNDULO eliminadas, métodos `_send_pendulum_setpoint()` y `_send_pendulum_pid()` eliminados
3. **Conservado**: gráfico péndulo, status labels, LQR, Swing-up, calibración (CPR/dir/offset péndulo)

#### Cambios MCP
1. **Herramienta `qube_set_swing_up()` eliminada**
2. **`qube_set_mode()`**: modo 3 removido de descripción y diccionario

#### Archivos modificados
- `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino`
- `src/firmware/data/index.html`
- `src/firmware/esp32_qube_l298n/data/index.html`
- `src/qube_ui/app.py`
- `src/qube_ui/client.py`
- `mcp/esp32_qube_server.py`


## [1.33.0] — 2026-06-04
### Firmware: alpha continuo, recovery persistente, dead zone + hardware fixes

#### Sesión nocturna — 22+ iteraciones de firmware, 3+ horas

#### Cambios de firmware (críticos)
1. **Alpha continuo para LQR**: `alpha` calculado con aritmética modular usando `pendPosRaw` en vez de `pendPos - copysign(180, pendPos)`. Elimina la discontinuidad en ±180° que rompía el LQR y el fallback.
2. **Recovery persistente en swing-up**: Variable global `swing_recovering` que mantiene el motor apagado cuando el péndulo cruza la vertical (`|pendPosRaw| > 180°`), espera a que caiga al fondo (`|pendPos| < 30°`), y reanuda el pumping.
3. **Dead zone a 160°**: El swing-up no bombea cuando `|pendPosRaw| > 160°`. Permite que el péndulo alcance ±170° sin overshoot a spinning.
4. **Damping progresivo 150°-180°**: Damping lineal de 0.3 a 1.0 del PWM máximo según proximidad a la vertical.
5. **LQR K2_NEAR=30, K4_NEAR=15**: Gains probados que lograron 55+ segundos de estabilización (revertido de experimentos con K2=35, K4=20 que empeoraban el LQR).
6. **Catch mode ±60 PWM**: Frenado al entrar a LQR (era ±20).
7. **Fallback usa `pendPosRaw > 360°`**: En vez de `alpha > 45°` (wrapped) que no se activaba.
8. **Servo protection direction-aware**: Corta PWM que empuja hacia el hard stop del servo (±70° → ±85°).
9. **Anti-spin threshold 360°**: Reducido de 720° para detectar spinning antes.
10. **`balance_threshold = 1.0°`**: Transicionar a LQR solo cuando el péndulo está a <1° de la vertical.

#### Resultados
- Swing-up alcanza ±170° consistentemente ✅
- LQR atrapa el péndulo (mejor resultado: 11.3 segundos) ✅
- Servo protection previene brownout ✅
- Alpha continuo implementado (pendiente de prueba completa) ✅
- **LQR no estabiliza sostenidamente** — oscilaciones demasiado grandes después de la captura ❌

#### Hardware
- **INA219 dañado parcialmente**: Lecturas inconsistentes tras picos de corriente del diodo invertido. `ina_ok: true` pero voltaje inestable.
- **Diodo 1N4007 quemado**: Se quemó por polaridad invertida. **No usar diodo externo con H-bridge** — el L298N tiene diodos flyback internos.
- **3 capacitores dañados** (470µF, 220µF, 100µF): Se dañaron por polaridad invertida. Descartar.
- **LM2596 descalibrado temporalmente**: Se ajustó a 5V con potenciómetro.

#### Archivos
- `experiments/2026-06-03_swing/SESSION_LOG_20260604.md` — log completo de la sesión
- `experiments/2026-06-03_swing/data/` — 5+ CSVs de tests

#### Notas
- RAM: 15.0%, Flash: 72.5%
- Error de caché PlatformIO: `pio run -t clean` antes de recompilar si aparece `FileNotFoundError: .sconsign312.tmp`
- Próximo paso: probar firmware con alpha continuo + recovery en test de 90s

---

# CHANGELOG — QUBE ESP32 (Firmware + Documentación)

Registro de cambios del firmware `esp32_qube_l298n.ino` y documentación del proyecto para la modernización de la plataforma QUBE Servo en el marco de la tesis.

---
## [1.32.0] — 2026-06-04
### GUI HTML: selector de modos, recolección de datos, fix freeze

#### Problema identificado
Selector de modos desincronizado, freeze de la página, y botón Set no movía el motor.

#### Cambios aplicados
1. **Selector de modos**: `selected` movido a STOP (modo 0), WebSocket sincroniza el modo
   al dropdown con flag `modeUserOverride` (8s) para no sobreescribir selección manual.
2. **Panel "Recolección de datos"**: botones Grabar/Exportar CSV/Borrar. Datos solo se
   acumulan cuando el usuario presiona Grabar. Estado visible con conteo de muestras y tiempo.
3. **Fix freeze**: chart updates throttleados a 200ms, `splice(0,n)` batch en vez de `shift()`,
   CSV export usa `Array.push + join` en vez de concatenación de strings.
4. **Botones Set Servo / Set Pén**: ahora envían `m=2&s=VALUE` y `m=3&sp=VALUE` respectivamente,
   activando el modo automáticamente. Setpoints separados en vez de enviarse juntos.
5. **SPIFFS upload**: se usó endpoint `/fs` POST del firmware (SPIFFS OTA no escribe).

#### Archivos modificados
`src/firmware/esp32_qube_l298n/data/index.html` (reescritura completa)

---

## [1.31.1] — 2026-06-04
### Firmware: tuning LQR gains + handoff document

#### Cambios aplicados
1. **K2_NEAR**: 30→35 (subido ligeramente para más autoridad cerca de vertical)
2. **K4_NEAR**: 20→15 (revertido — K4_NEAR=20 empeora el LQR: 3s vs 55s con 15)
3. **Handoff document**: `experiments/2026-06-03_swing/HANDOFF.md` con todos los
   parámetros, bugs corregidos, CSVs, y próximos pasos

#### Hallazgo importante
K4_NEAR=20 es peor que K4_NEAR=15. Con K4=20 el LQR pierde el péndulo en ~3s
vs 55+ s con K4=15. El damping excesivo cerca de la vertical parece desestabilizar
el ciclo límite.

#### Notas
Compilación: ✅ RAM 15.0%, Flash 72.5%
27+ CSVs de tests en `experiments/2026-06-03_swing/data/`

---

## [1.31.0] — 2026-06-04
### Firmware: LQR sostiene péndulo invertido 55+ segundos

#### Resultado
El LQR mantiene el péndulo en modo 4 (control invertido) durante **55+ segundos**
en un ciclo límite estable alrededor de ±180°. El péndulo oscila entre -130° y
+210° (wrapped) pero nunca cae al fondo.

#### Cambios aplicados
1. **LQR gains moderados**: K2_NEAR 60→30, K4_NEAR 25→15 (reduce overshoot)
2. **LQR_NEAR_DEG**: 15→25° (gain scheduling en rango más amplio)
3. **ke_gain**: 0.45→0.5 (más autoridad en swing-up)
4. **LQR_FALLBACK_ALPHA_DEG**: 45→30° (evita soltar el péndulo innecesariamente)
5. **Servo centering**: kp=0.2 en swing-up (reduce oscilación del servo)
6. **Soft saturation**: k=80°, y=2 (protección suave contra hard stop)
7. **Anti-spin con cooldown**: 1s, reset inmediato de offset
8. **Disipación de energía**: threshold 0.95, brake progresivo

#### Parámetros finales del sistema
| Parámetro | Valor |
|---|---|
| ke_gain | 0.5 |
| balance_threshold | 5° |
| vel threshold | 20°/s |
| K1, K2 (base) | 2.0, 22 |
| K2_NEAR, K4_NEAR | 30, 15 |
| LQR_NEAR_DEG | 25° |
| LQR_FALLBACK_ALPHA_DEG | 30° |
| LQR_FALLBACK_TIME_MS | 500ms |
| soft saturation k | 80° |
| centering_kp | 0.2 |

#### Notas
El sistema entra en un ciclo límite — el péndulo no se estabiliza en exactamente
180° pero se mantiene en el hemisferio superior indefinidamente. Para lograr
estabilización completa se requiere reducir la amplitud del ciclo límite, posiblemente
con gains LQR más altos cuando el péndulo está muy cerca de ±180°.

---

## [1.30.1] — 2026-06-03
### Firmware: bug crítico `if`→`else if` en cadenas de modo + disipación swing-up

#### Bug crítico descubierto
Los bloques de modo 2/3/4/5 usaban `if (mode == N)` independientes en vez de
`else if`. Cuando el modo cambiaba (swing-up→LQR), el bloque del modo anterior
seguía ejecutándose y sobreescribía `pwm`.

**Efecto**: En transición swing-up→LQR, el anti-spin brake de modo 5 escribía
`pwm = -100` sobre el LQR, causando que perdiera el péndulo inmediatamente.

**Fix**: Cambiado a cadena `if/else if` (INCOMPLETO — falta eliminar `}` extra
en cierre de modo 3, línea ~1505).

#### Disipación de energía en swing-up
- `energy_ratio >= 0.9`: freno progresivo (brake_gain 0.3→1.0 lineal)
- `energy_ratio >= 0.85`: bombeo reducido al 50%
- `energy_ratio < 0.85`: bombeo normal
- Resultado: péndulo oscila estable ±160° sin spinning

#### Anti-spin con cooldown
- Reset inmediato de offset + freno PWM_MAX + cooldown 1000ms
- Reset de cooldown al entrar a LQR

#### Notas
- Compilación pendiente (error de scope por `}` extra)
- Tests CSV en `experiments/2026-06-03_swing/data/` (19 archivos)
- Log completo en `experiments/2026-06-03_swing/SESSION_LOG.md`

---

## [1.30.0] — 2026-06-03
### Firmware: OTA web + SPIFFS file upload + GUI flasheo

#### Cambios aplicados

**1. Endpoint `/update` (flasheo firmware vía HTTP)**
- `POST /update` acepta multipart con binario `.bin`, escribe con `Update` library, reinicia al completar.
- Detiene modo y motor antes de flashear.

**2. Endpoint `/fs` (upload de archivos a SPIFFS)**
- `POST /fs` acepta multipart con archivo, escribe directamente a SPIFFS (`/filename`).
- Permite actualizar `index.html` desde el navegador sin reflashear toda la partición SPIFFS.

**3. Endpoint `/restart` (reinicio remoto)**
- `GET /restart` responde `{"ok":true}` y reinicia el ESP32.

**4. GUI HTML: panel Firmware OTA**
- Nuevo panel "Firmware OTA" en el sidebar derecho de la GUI web (`index.html`).
- Selector de archivo `.bin`, botón "Flashear", barra de progreso con porcentaje.
- Upload directo a `/update` con `XMLHttpRequest` para feedback en tiempo real.
- CSS: `.ota-bar`, `.ota-fill`, `.ota-status` integrado al tema dark existente.

**5. GUI Python/Tkinter: panel de flasheo**
- Nueva sección "⚡ FIRMWARE" en el panel lateral de `src/qube_ui/app.py`.
- Selector de entorno (`esp32dev`, `esp32dev_debug`, `esp32dev_ota`).
- Selector de puerto serie con detección automática vía `pyserial` + botón ⟳.
- Botón "⚡ Flashear" ejecuta `pio run` + `pio run --target upload` en thread background.
- Botón "✕ Cancelar" aborta el proceso.
- Log de output con scroll, limpieza de ANSI y `\r`.

**6. Fix: auto-scaling de ejes Y en gráficos**
- Péndulo y servo: margen cambiado de `std * 0.5, min 5°` a `ptp * 0.1, min 5°`.
- Péndulo: Y clampeado a ±200° (rango físico real del encoder).
- Fix: datos concentrados cerca de borde ya no se cortan.

#### Notas
- RAM: 15.0% (49092/327680), Flash: 72.5% (949961/1310720).
- Para actualizar solo el HTML sin reflashear firmware: `curl -X POST http://192.168.100.50/fs -F "file=@index.html;filename=index.html"`.
- Upload SPIFFS vía `pio run --target uploadfs` con `ArduinoOTA` puede no reiniciar automáticamente; el endpoint `/fs` es más confiable para updates incrementales.

---


## [1.29.0] — 2026-06-03
### Firmware: anti-spin, LQR catch mode, gain scheduling, MCP docs

#### Cambios aplicados

**1. Anti-spin en swing-up (modo 5)**
- Detección de spinning: delta de posición raw >200° entre samples o acumulación >720°.
- Cuando detecta spinning: frena según dirección de velocidad (60% PWM_MAX).
- Cuando se frena: recalibra offset del encoder.
- Energía calculada con ángulo raw (evita error por wrap en oscilaciones normales).

**2. LQR catch mode**
- Al transicionar de swing-up a LQR, aplica freno máximo por 150ms.
- Objetivo: disipar energía cinética antes de intentar equilibrar.
- Freno basado en dirección de velocidad angular raw.

**3. Gain scheduling LQR**
- Gains base: K1=2.0, K2=22, K3=1.5, K4=9.
- Gains agresivos cerca de vertical (<15°): K2_NEAR=60, K4_NEAR=25.
- Hard stop proporcional (2 PWM/grado de overshoot).

**4. Transición más estricta**
- `balance_threshold`: 12°→5°.
- `SWINGUP_TRANSITION_VEL_DPS`: 500→80°/s.
- `VEL_ALPHA_PEND`: 0.15→0.60 (respuesta más rápida).

**5. MCP server**
- Nueva herramienta `pio_ota_flash(ip)` para flasheo OTA desde MCP.
- Documentación completa en `mcp/README.md`.

**6. Tests y logging**
- Script `experiments/2026-06-03_swing/test_swing.py` con logging CSV.
- 12 tests realizados, análisis en `experiments/2026-06-03_swing/ANALYSIS.md`.

#### Resultados de pruebas
- Swing-up estable hasta ~170° (ke=0.4-0.45) ✅
- LQR atrapa péndulo cerca de vertical, sostiene ~1.3s ✅
- Spinning después de LQR failure ❌ (root cause identificado, fix pendiente)

#### Root cause del spinning (PENDIENTE)
- La energía se calcula con `pendPosRaw` (ángulo crudo acumulado).
- Cuando raw >360°, `cos(raw)` oscila erráticamente → `motion_sign` inestable.
- Fix: usar ángulo wrapped para energía cuando `|pendPosRaw| > 360°`.
- Ver `ANALYSIS.md` para detalles completos.

#### Notas
- RAM: 15.0% (49084/327680), Flash: 72.3% (947569/1310720).
- ArduinoOTA funciona: flash WiFi sin USB desde environment `esp32dev_ota`.

---

## [1.28.1] — 2026-06-03
### Firmware: fix wrap ángulo péndulo + pruebas swing-up

#### Problema identificado
- `pendPos` acumulaba vueltas sin wrap (1554° en pruebas). `normalizeAngle(pendPos - 180)` fallaba para la transición LQR.
- Transición swing-up→LQR demasiado permisiva: `balance_threshold=12°`, `SWINGUP_TRANSITION_VEL_DPS=500°`.
- Hard stop del LQR aplicaba PWM_MAX sin proporcionalidad, causando rebote violento.

#### Cambios aplicados

**1. Wrap modular de `pendPos` (crítico)**
- `pendPosRaw` = ángulo crudo (para cálculo de velocidad, sin discontinuidades).
- `pendPos` = wrap a [-180, 180] con `fmod(pendPos + 180, 360) - 180`.
- Velocidad del péndulo calculada con `pendPosRaw` en modos 3, 4 y 5.

**2. LQR: gains + transición más estricta**
- `balance_threshold`: 12°→8° (solo transiciona más cerca de vertical).
- `SWINGUP_TRANSITION_VEL_DPS`: 500→200°/s (solo transiciona con baja velocidad).
- Gains: K1=2.0, K2=22, K3=1.5, K4=9 (incrementados para más autoridad).
- Hard stop proporcional (2 PWM/grado de overshoot).

**3. Swing-up: bombeo excesivo de energía**
- El péndulo gira indefinidamente en vez de oscilar (motor sobrepotenciado).
- `ke_gain=0.5` es demasiado alto para el hardware actual.
- **Pendiente**: reducir `ke_gain` o implementar swing-up con control de amplitud.

#### Datos de pruebas
- Test 1: LQR atrapó péndulo a ~0.4° de vertical, sostuvo ~1.2s, luego perdió.
- Test 2: Péndulo acumuló 3 vueltas (-1080°), swing-up no logró oscilación.
- Logs guardados en `experiments/2026-06-03_swing/data/`.

---

## [1.28.0] — 2026-06-03
### Firmware: ArduinoOTA + LQR hard stop proporcional + MCP docs

#### Cambios aplicados

**1. ArduinoOTA (flasheo por WiFi)**
- `#include <ArduinoOTA.h>`, `ArduinoOTA.begin()` en setup, `ArduinoOTA.handle()` en loop.
- Hostname: `qube-esp32`. Detiene motor al iniciar OTA.
- Nuevo environment `[env:esp32dev_ota]` en `platformio.ini`.

**2. LQR hard stop proporcional**
- Hard stop a ±120° ahora aplica fuerza proporcional al overshoot (2 PWM/grado).
- Orden corregido: hard stop ANTES del `constrain` final.
- Gains reducidos: K2 25→18, K4 10→8 para captura menos agresiva.
- Fallback time reducido: 2000ms→1000ms para detectar fallos más rápido.

**3. MCP server**
- Nueva herramienta `pio_ota_flash(ip)` para flasheo OTA desde MCP.
- Documentación completa en `mcp/README.md`.

#### Notas
- Primer flash con OTA requiere USB; subsecuentes son por WiFi.
- RAM: 15.0% (49076/327680 bytes), Flash: 72.3% (947181/1310720 bytes).

---

## [1.27.0] — 2026-06-03
### Firmware: calidad de código — correcciones, constantes nombradas, watchdog INA219

#### Problema identificado
Revisión de calidad del firmware reveló:
- **C1**: Cambio de modo duplicado entre HTTP y Serial sin histéresis en transiciones LQR↔swing-up.
- **C2**: `Serial.readStringUntil()` con timeout de 1s bloqueaba el lazo de control a 500 Hz.
- **D1**: Variables muertas (`swingPhase`, `exciteStartMs`, `prevError`, `prevErrorPend`) asignadas pero nunca leídas.
- **D2**: `pwmAttachCompat` ignoraba el bool de retorno sin documentar por qué.
- **D3**: INA219 sin watchdog — si el sensor I2C se desconectaba, los valores quedaban stale.
- **M1**: ~20 magic numbers en los bloques PID/LQR/swing-up sin nombre ni documentación.

#### Cambios aplicados

**1. `setMode()` unificado (C1)**
- Punto único de cambio de modo usado por HTTP (`handleCmd`) y Serial (`case 'm'`).
- Histéresis LQR→swing-up con `lqr_inFallback` flag para evitar rebote rápido.

**2. `processSerialCommand()` con buffer acotado (C2)**
- `readStringUntil('\n')` → lectura caracter por caracter con `Serial.read()` y timeout de 50ms.
- Buffer estático de 64 bytes con protección contra overflow.

**3. Código muerto eliminado (D1)**
- `swingPhase`, `exciteStartMs` y `resetSwingUp()` eliminados (asignados, nunca leídos).
- `prevError` y `prevErrorPend` eliminados (PID usa velocidad filtrada, no error previo).

**4. INA219 watchdog (D3)**
- Verificación I2C cada 1000 ms con `Wire.beginTransmission()` + `endTransmission()`.
- Reintento automático de `initIna219()` cada 5000 ms si el sensor falla.

**5. Constantes nombradas (M1)**
- LQR: `LQR_FALLBACK_TIME_MS`, `LQR_FALLBACK_ALPHA_DEG`, `LQR_REARM_ALPHA_DEG`, `LQR_SERVO_LIMIT_DEG`, `LQR_HARDSTOP_DEG`, `LQR_PROTECT_ALPHA_DEG`.
- PID Servo: `PID_ANTIWIND_ERR_DEG`, `PID_ANTIWIND_VEL_DPS`, `DEADBAND_*_DEG`, `STICTION_*`.
- PID Péndulo: `PEND_ANTIWIND_ERR_DEG`, `PEND_ANTIWIND_VEL_DPS`, `PEND_DEADBAND_DEG`.
- Swing-up: `SWINGUP_TRANSITION_VEL_DPS`, `SWINGUP_KICK_DUTY_FRAC`, `SWINGUP_KICK_PERIOD_MS`, `SWINGUP_QUIET_THRESHOLD_RADPS`, `SWINGUP_PROD_DEADZONE`.
- INA219: `INA_WATCHDOG_PERIOD_MS`, `INA_INIT_RETRY_MS`.

#### Notas
- `USE_ENA_PWM = false` confirmado: PWM en IN1/IN2 (ENA no conectado en hardware).
- RAM: 13.7% (44948/327680 bytes), Flash: 67.7% (887429/1310720 bytes).
- Upload exitoso en COM5 (ESP32-D0WD-V3, rev v3.1).

---

## [1.26.1] — 2026-06-03
### GUI: layout de gráficas — subplots más altos, sin overflow

#### Problema identificado
Los 4 subplots del panel de gráficas se veían comprimidos verticalmente con gaps excesivos entre ellos, causando:
- Subplots de 1.31" de alto (en figura 9×8") demasiado estrechos para series temporales legibles.
- `hspace=0.5` (50% de la altura de subplot como gap) — 27% del alto de figura desperdiciado en gaps vacíos.
- Márgenes superior/inferior (0.96/0.06) demasiado estrechos, riesgo de clipping de títulos de subplot.

#### Cambios aplicados

**1. `App._build_charts` (gridspec)**
- `hspace`: 0.5 → 0.28 (reduce gaps entre subplots, +14% altura por subplot).
- `top`: 0.96 → 0.97 (más espacio para títulos del primer subplot).
- `bottom`: 0.06 → 0.07 (más espacio para xlabel del último subplot).
- `left`: 0.08 → 0.09 (alinea ylabel izquierdo con el borde del panel).
- `right`: 0.97 → 0.95 (libra espacio para los ticks derechos de la subplot `twinx()` de Potencia).

#### Cambios de firmware
```cpp
// Sin cambios — solo ajuste de layout del GUI.
```

#### Notas
- Altura efectiva por subplot: 1.31" → 1.49" (+14%).
- `twinx()` de la subplot de Potencia sigue creando su propio eje Y a la derecha (`V bus`) — el ajuste `right=0.95` previene que se salga del área visible.
- Lint: `ruff check`/`ruff format`/`pyright` pasan en `src/qube_ui/`.

---

## [1.26.0] — 2026-06-03
### GUI: paridad completa con endpoints HTTP del firmware

#### Problema identificado
Auditoría cruzada GUI ↔ firmware reveló opciones del firmware sin exponer en `qube_ui.app`:
- Parámetros HTTP sin widget: `cprp` (CPR péndulo), `edp` (dir encoder péndulo), `op` (offset péndulo), `gs`/`kpf`/`kif`/`kdf`/`kpc`/`kic`/`kdc` (gain scheduling), `wifi_ssid`/`wifi_pass`/`wifi_reconnect` (config STA).
- Campos `/state` no parseados: `gain_scheduling`, `gain_mode`.
- Métodos del cliente sin caller en UI: `set_cpr`, `set_encoder_dir` (código muerto).

#### Cambios aplicados

**1. `QubeState` (cliente)**
- Nuevos campos: `gain_scheduling: bool`, `gain_mode: int`.
- `from_json` los reconoce y los asigna a la dataclass.

**2. `ESP32Client` (cliente)**
- Nuevos métodos: `set_pendulum_cpr`, `set_pendulum_encoder_dir`, `set_pendulum_offset`, `set_gain_scheduling`, `set_servo_pid_fine`, `set_servo_pid_coarse`, `set_wifi_ssid`, `set_wifi_password`, `wifi_reconnect`.
- Validación local de SSID (1-32 chars) y password (>= 8 chars) para evitar round-trips inútiles.

**3. `App._build_control_panel` (GUI)**
- Nueva sección **CALIBRACIÓN (CPR / DIR)**: campos CPR servo/péndulo + radiobuttons `+-1` para dirección encoder servo/péndulo + botón "Aplicar Calibración".
- Nueva sección **GAIN SCHEDULING (PID SERVO)**: checkbox "Activar dual-mode" + sub-bloques para ganancias fino (`kpf`/`kif`/`kdf`) y grueso (`kpc`/`kic`/`kdc`) + botón "Aplicar Gains Fino/Grue.".
- Nueva sección **WIFI STA**: campos SSID (texto) y password (enmascarado) + botones "Aplicar WiFi" y "Reconectar".
- Sección **OFFSET** ampliada con fila independiente para offset del péndulo (`op`) junto a la fila del servo.
- Sección **ESTADO ACTUAL** ampliada con etiquetas de telemetría `GainSch: {on|off} ({fino|grueso})` y `CPR servo: N`.

**4. Handlers de envío**
- Nuevos: `_send_pendulum_offset`, `_send_encoder_dir`, `_send_pendulum_encoder_dir`, `_send_calibration`, `_send_gain_scheduling`, `_send_gain_gains`, `_send_wifi`, `_send_wifi_reconnect`.
- Validación de entrada + `messagebox.showerror` en valores no numéricos o credenciales inválidas.

#### Cambios de firmware
```cpp
// Sin cambios — este commit solo agrega soporte GUI para endpoints existentes.
// Endpoints cubiertos ahora en GUI:
//   /cmd?cprp, edp, op, gs, kpf, kif, kdf, kpc, kic, kdc, wifi_ssid, wifi_pass, wifi_reconnect
```

#### Notas
- Los radiobuttons de dirección de encoder aplican cambios inmediatamente al seleccionar (no requieren "Aplicar"); consistente con el patrón de cambio de modo.
- "Aplicar Calibración" envía CPR y dirección en una sola acción (4 comandos consecutivos al firmware).
- "Aplicar WiFi" no reconecta automáticamente — usuario debe pulsar "Reconectar" para activar STA, evitando desconexiones accidentales.
- Lint: `ruff check`/`ruff format`/`pyright` pasan en `src/qube_ui/`.


---

## [1.25.0] — 2026-06-01
### Swing-up funcional + LQR con fallback automático + 500Hz

#### Problema identificado
- El péndulo no lograba estabilizarse con swing-up (modo 5) + LQR (modo 4).
- **Bug 1:** Signo invertido en la ley de energía del swing-up — el motor peleaba contra el péndulo.
- **Bug 2:** Kick unidireccional — el péndulo se atascaba colgado hacia abajo.
- **Bug 3:** LQR usaba ángulo sin normalizar — la protección siempre mataba el PWM.
- **Bug 4:** Sin fallback — cuando el LQR fallaba, el sistema se quedaba en modo 4 muerto.
- **Bug 5:** Servo desbordaba a ±175°+ durante LQR causando crash mecánico.

#### Cambios aplicados

**1. Ley de energía corregida (modo 5)**
- Antes: `E_err = E - Er` → signo invertido, torque contra el péndulo.
- Ahora: `energy_sign = (Er > E) ? 1.0f : -1.0f` → ley Quanser/Åström-Furuta correcta.

**2. Kick alternante para iniciar oscilación (modo 5)**
- Antes: PWM constante `MOTOR_DIR * PWM_MAX * 0.8` siempre en una dirección.
- Ahora: Alterna dirección cada 250ms (~periodo natural/2) para construir resonancia.
- Threshold ampliado: `abs(alpha_dot) < 0.15f` (era 0.1).

**3. Función `normalizeAngle()` + LQR normalizado (modo 4)**
- Nueva función que normaliza ángulos a [-180, 180].
- `alpha = normalizeAngle(pendPos - 180.0f)` → 0=arriba, ±180=abajo.
- Velocidades calculadas con ángulo crudo (evita errores en wrap-around).

**4. Fallback automático LQR → Swing-up**
- Si `|alpha| > 90°` por >2 segundos → vuelve a modo 5 (swing-up).
- Permite ciclar swing-up → LQR → fallback → swing-up hasta estabilizar.

**5. Protección LQR ampliada y hard stop de servo**
- Protección: `|alpha| > 140°` → PWM=0 (era 150°).
- Hard stop: `|pos| > 120°` → fuerza motor de vuelta al centro.

**6. Filtro de velocidad más rápido**
- `VEL_ALPHA_PEND = 0.30f` (era 0.15) → reduce retardo de 33ms a 17ms.

**7. Frecuencia de control: 200 Hz → 500 Hz**
- `CONTROL_PERIOD_US = 2000` (era 5000) → latencia 2ms vs 5ms.

**8. Balance threshold reducido**
- `balance_threshold = 12°` (era 20°) → transición más cercana a vertical.

**9. Velocidad gate en transición**
- Solo permite transición si `|alpha_dot| < 500°/s` (evita transiciones prematuras).

#### Cambios de firmware
```cpp
// NUEVA: normalización de ángulo
float normalizeAngle(float deg) {
  deg = fmodf(deg, 360.0f);
  if (deg > 180.0f) deg -= 360.0f;
  else if (deg < -180.0f) deg += 360.0f;
  return deg;
}

// Swing-up: energía corregida + kick alternante
const float energy_sign = (Er > E) ? 1.0f : -1.0f;
if (abs(alpha_dot) < 0.15f) {
    if (((millis() / 250) % 2) == 0)
        pwm = MOTOR_DIR * (int)(PWM_MAX * 0.7f);
    else
        pwm = -MOTOR_DIR * (int)(PWM_MAX * 0.7f);
} else {
    float u = ke_gain * energy_sign * motion_sign;
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}

// LQR: ángulo normalizado + fallback + hard stop
const float alpha = normalizeAngle(pendPos - 180.0f);
// ... (fallback si |alpha|>90 por >2s)
// ... (hard stop si |pos|>120)

// Control: 500 Hz
const unsigned long CONTROL_PERIOD_US = 2000;
```

#### Parámetros LQR actuales
- K1=1.5 (posición servo), K2=25 (ángulo péndulo), K3=1.0 (vel servo), K4=10 (vel péndulo)
- VEL_ALPHA_PEND=0.30, balance_threshold=12°, velocity gate=500°/s

#### Notas
- Resultado: LQR atrapa péndulo a 0.2° de la vertical pero no sostiene >0.5s.
- Limitación física identificada: motor L298N demasiado lento. BTS7960 recomendado como upgrade.
- Datos de test en `experiments/2026-06-01_swing/`
- Log completo de tuning en `experiments/2026-06-01_swing/TUNING_LOG.md`


## [1.24.1] — 2026-06-01

### Fix LQR: ángulo péndulo sin normalizar + protección mata motor

#### Problema identificado
- El swing-up (modo 5) funcionaba y el péndulo llegaba a ~0° (vertical), pero el LQR (modo 4) nunca lograba estabilizarlo.
- **100% de los 6 ciclos de swing-up fallaron**: el péndulo llegaba a 160-178° y el LQR apagaba el motor inmediatamente.
- **Causa raíz:** El LQR usaba `pendPos` crudo (que puede ser -521°, 512°, etc. por acumulación del encoder) directamente como `alpha`.
- La protección `abs(alpha) > 150` se activaba siempre porque 161° > 150°, aunque 161° es casi la vertical (180°).
- Segunda causa: la condición de transición swing-up→LQR usaba `fmodf(abs(pendPos), 360) - 180` que no normalizaba correctamente.

#### Cambios aplicados

**1. Función `normalizeAngle()`**
- Normaliza cualquier ángulo a [-180, 180].
- Usada en LQR y en la condición de transición del swing-up.

**2. LQR con ángulo normalizado (modo 4)**
- `alpha = normalizeAngle(pendPos - 180.0)` → 0=arriba, ±180=abajo.
- Velocidades calculadas con ángulo crudo (evita errores en wrap-around ±180°).
- Protección `abs(alpha) > 150` ahora funciona correctamente: solo apaga motor cuando el péndulo está cerca del fondo.

**3. Transición swing-up→LQR simplificada**
- Antes: `fmodf(abs(pendPos), 360) - 180` (incorrecto para ángulos negativos grandes).
- Ahora: `dist_from_up = abs(normalizeAngle(pendPos - 180.0))`.

#### Cambios de firmware
```cpp
// NUEVA: normalización de ángulo
float normalizeAngle(float deg) {
  deg = fmodf(deg, 360.0f);
  if (deg > 180.0f) deg -= 360.0f;
  else if (deg < -180.0f) deg += 360.0f;
  return deg;
}

// LQR: ANTES (sin normalizar, protección siempre activa)
const float alpha = pendPos;  // -521° → abs > 150 → PWM=0

// LQR: DESPUÉS (normalizado, 0=arriba)
const float alpha_raw = pendPos;
const float alpha = normalizeAngle(pendPos - 180.0f);  // 0=arriba
// Velocidades calculadas de alpha_raw (sin wrap-around)
```

#### Notas
- Los gains LQR (K1=1, K2=25, K3=0.5, K4=3) pueden necesitar ajuste fino ahora que el LQR efectivamente controla.
- Si el péndulo oscila alrededor de la vertical sin estabilizar, subir K2 y K4.
- Subir firmware: `pio run --target upload`


## [1.24.0] — 2026-06-01

### PCNT hardware encoder + CPR medido experimentalmente

#### Problema identificado
- El encoder del servo usaba polling en `loop()` (`USE_ENCODER_POLLING`), que perdia transiciones porque el loop tambien maneja WiFi, web server, INA219 y serial.
- Las ISRs por software (`isrEncoderA/B`) usaban `digitalRead()` dentro de la interrupcion (~5us cada llamada), demasiado lento para seguir el ritmo de un encoder incremental a velocidad real.
- El encoder del pendulo no tenia ISRs configuradas, solo polling.
- El CPR de ambos encoders estaba configurado en 2048 por defecto sin verificacion experimental.
- Medir el CPR manualmente era impreciso: el usuario debia rotar el eje y contar vueltas, introduciendo error humano significativo.

#### Cambios aplicados

**1. PCNT (Pulse Counter) hardware para ambos encoders**
- Reemplaza ISRs y polling con el periferico PCNT del ESP32, que decodifica cuadratura X4 en hardware sin intervencion de CPU.
- PCNT_UNIT_0: encoder servo (GPIO34/GPIO35)
- PCNT_UNIT_1: encoder pendulo (GPIO32/GPIO33)
- Cada canal configura: pulse en un pin, control en el otro, con modos REVERSE/KEEP para direccion.
- Eliminadas: `isrEncoderA`, `isrEncoderB`, `isrPendulumA`, `isrPendulumB`, `updateEncoderPolling`, `updatePendulumPolling`, `resetEncoderStateTracker`, `resetPendulumStateTracker`.
- Eliminadas variables: `encoderCount`, `pendulumCount`, `encoderLastState`, `pendulumLastState`, `USE_ENCODER_INTERRUPTS`, `USE_ENCODER_POLLING`.

**2. ISRs para encoder pendulo (agregadas, ahora obsoletas)**
- Se agregaron `isrPendulumA`/`isrPendulumB` antes de migrar a PCNT. Quedan como referencia pero no se usan.

**3. Reset PCNT via HTTP y serial**
- Comando `r` ahora llama `resetPcnt()` en vez de `encoderCount = 0`.
- Comando `zp` (HTTP) solo resetea offset, no el contador PCNT.

**4. CPR verificado experimentalmente**
- Encoder pendulo: CPR = 2048 confirmado (1024 counts = 180.000 exacto).
- Encoder servo: CPR = 2048 verificado via PID (setPosition a 45/-45/0 grados funciona correctamente).
- Ambos encoders son el mismo modelo Premotec 990412016913.

**5. Scripts de medicion de CPR** (`experiments/2026-06-01_cpr_measurement/`)
- `diagnose_encoder.py`: lee estados enc_a/enc_b en tiempo real para diagnosticar hardware.
- `sweep_cpr.py`: barrido no-interactivo con soporte para encoder servo o pendulum.
- `motor_sweep_cpr.py`: mueve el motor con PWM y graba counts.
- `servo_sweep_cpr.py`: barrido servo considerando rango mecanico +/-90 grados.
- `dual_encoder_sweep.py`: compara servo vs pendulum simultaneamente.

#### Cambios de firmware
```cpp
// ANTES: polling en loop (perdia transiciones)
void loop() {
  updateEncoderPolling();    // ~5us por digitalRead x2
  updatePendulumPolling();   // same
  ...
}

// DESPUES: PCNT en hardware (cero perdida)
void loop() {
  ws.cleanupClients();      // PCNT cuenta en background
  ...
}

// Init PCNT (X4 cuadratura)
pcnt_config_t ch0 = {
    .pulse_gpio_num = pinA,
    .ctrl_gpio_num = pinB,
    .lctrl_mode = PCNT_MODE_KEEP,
    .hctrl_mode = PCNT_MODE_REVERSE,
    .pos_mode = PCNT_COUNT_INC,
    .neg_mode = PCNT_COUNT_DEC,
    .counter_h_lim = 32767,
    .counter_l_lim = -32768,
    .unit = PCNT_UNIT_0,
    .channel = PCNT_CHANNEL_0,
};
```

#### Notas
- El PCNT de 16 bits permite ~4 vueltas completas antes de overflow (con CPR=2048). El loop a 200Hz lee el counter periodicamente.
- El ratio de la caja de engranajes es ~10:1 (medido via comparacion dual encoder).
- Los scripts de medicion corrigen el bug de emojis Unicode en Windows (cp1252).

## [1.23.1] — 2026-06-01

### Fix swing-up (modo 5): signo invertido de energía y kick unidireccional

#### Problema identificado
- El péndulo no subía al activar swing-up (modo 5): se quedaba estático colgado hacia abajo.
- El motor generaba mucha fricción porque empujaba en una sola dirección sin alternar.
- **Causa raíz 1:** La ley de bombeo de energía usaba `E - Er` en vez de `Er - E`, invirtiendo el signo del torque. El motor peleaba contra el péndulo en vez de bombearle energía.
- **Causa raíz 2:** El kick inicial (`abs(alpha_dot) < 0.1`) siempre aplicaba `MOTOR_DIR * PWM_MAX * 0.8` (= -80), dirección constante. Esto atascaba el péndulo en vez de iniciar oscilación.

#### Cambios aplicados

**1. Signo correcto de la ley de energía (Quanser/Åström-Furuta)**
- Antes: `u = ke_gain * (E - Er) * sign_val * 80.0` → signo invertido.
- Ahora: `u = ke_gain * sign(Er - E) * sign(α̇ · cos α)` → bombea cuando E < Er, reduce cuando E > Er.
- Eliminada la constrain a [-1, 1] y la multiplicación por 80.0 innecesaria.

**2. Kick alternante para iniciar oscilación**
- Antes: PWM constante en una dirección → péndulo se atasca.
- Ahora: alterna dirección cada 250ms (~periodo natural del péndulo / 2) para construir amplitud por resonancia.
- Se activa cuando `abs(alpha_dot) < 0.15` (threshold ampliado de 0.1 a 0.15).

#### Cambios de firmware
```cpp
// ANTES (buggeado):
const float E_err = E - Er;  // signo invertido
if (abs(alpha_dot) < 0.1f) {
    pwm = MOTOR_DIR * PWM_MAX * 0.8f;  // siempre -80
} else {
    float u = ke_gain * E_err * sign_val * 80.0f;
    u = constrain(u, -1.0f, 1.0f);
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}

// DESPUÉS (corregido):
const float energy_sign = (Er > E) ? 1.0f : -1.0f;
if (abs(alpha_dot) < 0.15f) {
    // Kick alternante cada 250ms
    if (((millis() / 250) % 2) == 0)
        pwm = MOTOR_DIR * (int)(PWM_MAX * 0.7f);
    else
        pwm = -MOTOR_DIR * (int)(PWM_MAX * 0.7f);
} else {
    float u = ke_gain * energy_sign * motion_sign;
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}
```

#### Notas
- Parámetro ajustable `ke_gain` (default 0.5) controla la intensidad del bombeo. Subir si el motor no tiene fuerza para construir oscilación.
- `balance_threshold` (default 20°) controla la transición automática a LQR (modo 4).
- Subir firmware: `pio run --target upload`

## [1.23.0] — 2026-06-01

### Gain Scheduling dual-mode para PID servo (Modo 2)

#### Problema identificado
- El PID del modo 2 usaba gains fijos (Kp=3.0, Ki=0.5, Kd=0.15) para cualquier magnitud de error.
- Errores pequeños (<10°) generaban movimientos demasiado agresivos que causaban overshoot y pérdida de posición por backlash mecánico.
- Errores grandes (>10°) no tenían suficiente ganancia para responder rápidamente.
- El escalonamiento de PWM existente limitaba la potencia pero no la dinámica del controlador.

#### Cambios aplicados

**1. Gain Scheduling dual-mode (modo 2)**
- Dos juegos de gains independientes: **modo fino** (|error| ≤ 10°) y **modo grueso** (|error| > 10°).
- Modo fino: Kp=2.0, Ki=0.8, Kd=0.2 — movimientos suaves, más amortiguación, PWM acotado (max 50).
- Modo grueso: Kp=4.0, Ki=0.2, Kd=0.1 — respuesta rápida, PWM libre (max 100).
- Histérisis de ±2° sobre el umbral (10°) para evitar chattering entre modos.
- Dead band adaptiva: 0.5° en modo fino, 1.0° en modo grueso.
- Toggle `useGainScheduling` para activar/desactivar el dual-mode (default: off, usa PID clásico).

**2. Nuevos parámetros HTTP**
- `gs=0|1` — activar/desactivar gain scheduling.
- `kpf`, `kif`, `kdf` — gains del modo fino (Kp, Ki, Kd).
- `kpc`, `kic`, `kdc` — gains del modo grueso (Kp, Ki, Kd).

**3. Nuevos comandos seriales**
- `g0` / `g1` — desactivar/activar gain scheduling.
- `gf<val>`, `gi<val>`, `gd<val>` — ajustar gains del modo fino.
- `GC<val>`, `GI<val>`, `Gd<val>` — ajustar gains del modo grueso.

**4. Telemetría extendida**
- Campo `gain_scheduling` (true/false) en JSON de `/state`.
- Campo `gain_mode` (0=fino, 1=grueso) en JSON de `/state`.

**5. Ayuda actualizada**
- Línea de ayuda serial incluye comandos de gain scheduling.
- Página HTML de `/` incluye endpoints de gain scheduling.

#### Notas
- **Backward compatible**: `useGainScheduling` default es `false`, mantiene el PID clásico existente.
- Activar con `GET /cmd?gs=1` o `g1` por serial.
- Los gains clásicos (Kp/Ki/Kd) siguen funcionando cuando el gain scheduling está desactivado.
- Los parámetros de gain scheduling se resetean al cambiar de esquema (fine ↔ coarse).

---
## [1.22.0] — 2026-06-01

### README completo: diagrama eléctrico actualizado con Schmitt Trigger + filtro RC

#### Problema identificado
- El README no reflejaba el circuito de acondicionamiento de señal real implementado en la protoboard.
- El diagrama eléctrico mostraba solo Schmitt Trigger sin filtro RC, aunque el hardware ya tenía resistencias 10 kΩ y capacitores 10 nF a GND en cada canal.
- Referencia interna a `gui/esp32_client.py` apuntaba a un archivo inexistente (migrado a `src/qube_ui/client.py`).

#### Cambios aplicados

**1. Diagrama eléctrico actualizado**
- Circuito de acondicionamiento: Schmitt Trigger CD40106BE → filtro RC (10 kΩ serie + 10 nF a GND) → GPIO ESP32.
- Diagrama de bloques general incluye Schmitt + RC en cada canal encoder.
- Topología de potencia incluye GND del CD40106BE.

**2. Sección de acondicionamiento de señal reescrita**
- Circuito completo con doble inversión + filtro RC documentado con diagrama ASCII.
- Cálculo de filtro RC: τ = 100 µs, f_c ≈ 1.59 kHz.
- Tabla comparativa de 3 topologías: pull-up solamente, pull-up + Schmitt, pull-up + Schmitt + RC.
- BOM actualizado: resistores 10 kΩ (×4) + capacitores 10 nF (×4).

**3. Modos de operación actualizados**
- Modo m5 (swing-up) incluido en todas las tablas de modos.
- Tabla de parámetros PID actualizada con columna LQR.
- Endpoints HTTP completos con todos los parámetros nuevos (swing-up, WiFi, LQR).

**4. Estructura del proyecto reflejada**
- Rutas actualizadas: `src/firmware/`, `src/qube_ui/`, `src/qube_analysis/`.
- Referencia a `gui/esp32_client.py` corregida a `src/qube_ui/client.py`.
- Sección "Documentación Adicional" con tabla de navegación a docs/.

**5. Roadmap actualizado**
- Ítems completados: swing-up, WiFi STA no-bloqueante, GUI con LQR/swing-up, filtro RC.
- Nuevo ítem: PCB Rev2.0 con acondicionamiento integrado.

#### Notas
- Solo cambios en documentación (README.md). No se modifica firmware ni código Python.
- Todos los enlaces internos verificados contra archivos existentes en el repositorio.

## [1.21.0] — 2026-05-29

### Swing-up (Modo 5), WiFi STA no-bloqueante y credenciales gitignored

#### Problema identificado
- No existía modo de swing-up para levantar el péndulo desde la posición colgante hasta la vertical invertida.
- La conexión WiFi STA bloqueaba el arranque del ESP32 durante 15 segundos si la red no estaba disponible.
- Las credenciales WiFi estaban hardcodeadas o requerían NVS, sin opción de configuración desde GUI.
- El AP solo era accesible en 192.168.4.1,requiriendo desconectarse de la red local.

#### Cambios aplicados

**1. Modo 5: Swing-up por energía (Quanser)**
- Control basado en energía: `E = 0.5*J*α'² + mgl*(1-cos(α))`, `Er = 2*mgl`.
- Dirección de torque: `sign(α' * cos(α))` para agregar energía al péndulo.
- Kick constante cuando el péndulo está quieto (`|α'| < 0.1`) para iniciarlo.
- Transición automática a LQR (modo 4) cuando `|α|` está cerca de 180° (vertical arriba).
- Corregido bug: la transición a LQR solo se activa cerca de la vertical ARRIBA (180°), no abajo (0°).
- Ganancia ajustable vía HTTP: `/cmd?ke=0.5&bt=20` (ke = ganancia energía, bt = umbral transición LQR).

**2. WiFi STA no-bloqueante**
- `connectStaIfConfigured()` ya no usa `while()` con timeout — `WiFi.begin()` conecta en background.
- El AP `QUBE-ESP32` está disponible inmediatamente al arrancar, sin esperar al STA.

**3. Credenciales WiFi gitignored (`credentials.h`)**
- Nuevo archivo `credentials.h` con `DEFAULT_STA_SSID` y `DEFAULT_STA_PASS`.
- Agregado a `.gitignore` — nunca se sube al repositorio.
- `loadWifiCredentials()` usa credenciales de `credentials.h` cuando NVS está vacío.
- El usuario edita `credentials.h` con sus datos reales y compila.

**4. HTTP endpoints para WiFi**
- `/cmd?wifi_ssid=Red&wifi_pass=Clave` — guardar credenciales en NVS.
- `/cmd?wifi_reconnect=1` — reconectar WiFi sin reiniciar.

**5. GUI actualizada (`src/qube_ui/app.py`)**
- Nuevo radio button "Swing-up" en modos de operación.
- Sección "SWING-UP" con parámetros `ke` (gain) y `threshold` (umbral LQR).
- Método `_send_swing_up()` para enviar parámetros.

**6. Cliente actualizado (`src/qube_ui/client.py`)**
- Nuevo método `set_swing_up_params(ke, balance_threshold)`.

**7. MCP server actualizado (`mcp/esp32_qube_server.py`)**
- `qube_set_mode()` actualizado: modos 0-5 documentados.
- Nueva herramienta `qube_set_swing_up(ke, balance_threshold)`.
- Nuevas herramientas `qube_set_wifi(ssid, password)` y `qube_wifi_reconnect()`.

#### Cambios de firmware
```cpp
// Swing-up (modo 5)
float ke_gain = 0.5f;           // Ganancia energía
float balance_threshold = 20.0f; // Umbral transición LQR
int swingPhase = 0;             // 0=excitacion, 1=bombeo
unsigned long exciteStartMs = 0;

// WiFi credentials (gitignored)
#include "credentials.h"
#define DEFAULT_STA_SSID "TuRed"
#define DEFAULT_STA_PASS "TuClave"
```

#### Notas
- Para probar swing-up: conectar péndulo abajo, ejecutar `zp=1` (zero péndulo), luego activar modo 5.
- El péndulo debe estar colgado hacia abajo (0°) antes de activar swing-up.
- RAM: 13.6% (44,684 / 327,680 bytes), Flash: 62.5% (818,545 / 1,310,720 bytes).

## [1.20.0] — 2026-05-29

### Encoder de Péndulo, Modo PID Péndulo y LQR Péndulo Invertido

#### Problema identificado
- El firmware solo soportaba el encoder del servo (GPIO34/35), sin lectura del encoder del péndulo (GPIO32/33).
- No existía modo de control para posicionar el péndulo ni para estabilizarlo en posición vertical (invertido).
- La GUI no mostraba datos del péndulo ni permitía controlar los nuevos modos.

#### Cambios aplicados

**1. Encoder del péndulo (GPIO32/33)**
- Agregadas variables `pendulumCount`, `pendCountsPerRev`, `pendulumDir` para el segundo encoder.
- Implementada decodificación cuadratura X4 por polling (`updatePendulumPolling()`) idéntica al encoder servo.
- Funciones: `getPendulumPositionDeg()`, `zeroPendulumHere()`, `resetPendulumPid()`.

**2. Modo 3: PID Posición Péndulo**
- Control PID del motor basado en el ángulo del péndulo (no del servo).
- Ganancias por defecto: `Kp_pend=15.0`, `Ki_pend=0.5`, `Kd_pend=2.0`.
- Setpoint vía HTTP: `/cmd?m=3&sp=0` (sp = setpoint péndulo).
- Anti-windup y deadband independientes del PID servo.

**3. Modo 4: LQR Péndulo Invertido**
- Control en espacio de estados: `u = -(K1*θ + K2*α + K3*θ' + K4*α')`.
- Estado: `[theta_servo, alpha_pendulo, vel_servo, vel_pendulo]`.
- Ganancias por defecto: `K1=1.0`, `K2=25.0`, `K3=0.5`, `K4=3.0`.
- Protección: si `|α| > 150°` (péndulo caído), PWM = 0 para evitar daño.
- Ganancias ajustables vía HTTP: `/cmd?lqr1=1&lqr2=25&lqr3=0.5&lqr4=3`.

**4. Estado JSON expandido (`/state`)**
- Nuevos campos: `pend_count`, `pend_raw_position_deg`, `pend_position_deg`, `pend_offset_deg`, `pend_setpoint_deg`, `pend_error_deg`.

**5. Nuevos comandos HTTP**
- `sp` — setpoint péndulo (modo 3).
- `zp` — zero encoder péndulo.
- `op` — offset péndulo.
- `edp` — dirección encoder péndulo (+1/-1).
- `cprp` — counts per revolution encoder péndulo.
- `kpp`, `kip`, `kdp` — ganancias PID péndulo.
- `lqr1`, `lqr2`, `lqr3`, `lqr4` — ganancias LQR.

**6. Serial: comandos actualizados**
- `m0..m4` — modos extendidos (antes `m0..m2`).
- `sp<deg>`, `zp`, `op<deg>`, `edp<1|-1>`, `cprp<val>` — péndulo.
- `kpp<val>`, `kip<val>`, `kdp<val>` — PID péndulo.

**7. GUI (`src/qube_ui/app.py`) actualizada**
- 4 subplots: Servo, Péndulo, PWM, Potencia.
- Panel de control: setpoint péndulo, PID péndulo, LQR ganancias.
- Botón "Zero Péndulo" en acciones.
- Estado muestra servo y péndulo simultáneamente.
- Modos de operación: STOP, PWM Manual, PID Servo, PID Péndulo, LQR Invertido.

**8. Cliente (`src/qube_ui/client.py`, `gui/esp32_client.py`) actualizado**
- `QubeState` incluye campos de péndulo.
- Nuevos métodos: `set_pendulum_setpoint()`, `set_pendulum_pid()`, `zero_pendulum()`, `set_lqr_gains()`.

**9. MCP server (`mcp/esp32_qube_server.py`) corregido**
- `DATA_DIR` corregido: apuntaba a `./data/` (no existe) → `./experiments/`.
- Herramientas CSV (`qube_list_experiments`, `qube_read_csv`, `qube_analyze_csv`) ahora buscan recursivamente en `experiments/*/data/`.

#### Cambios de firmware
```cpp
// Encoder péndulo (GPIO32/33)
static const int PIN_PEND_A = 32;
static const int PIN_PEND_B = 33;
volatile long pendulumCount = 0;

// PID Péndulo (modo 3)
float Kp_pend = 15.0f;
float Ki_pend = 0.5f;
float Kd_pend = 2.0f;

// LQR (modo 4)
float lqr_K1 = 1.0f;   // θ servo
float lqr_K2 = 25.0f;  // α péndulo
float lqr_K3 = 0.5f;   // θ' velocidad servo
float lqr_K4 = 3.0f;   // α' velocidad péndulo
```

#### Notas
- RAM: 13.6% (44,672 / 327,680 bytes), Flash: 62.0% (812,193 / 1,310,720 bytes).
- Para modo LQR, el péndulo debe estar cerca de la vertical antes de activar (swing-up manual o desde modo 3).
- Los 36 tests del proyecto pasan correctamente.

## [1.19.0] — 2026-05-28

### Migración de Adafruit_INA219 a INA219_WE + fix de compilación PlatformIO

#### Problema identificado
- `Adafruit_INA219` (v1.2.3) no compila con ESP32 Arduino Core 3.x: `'Serial' was not declared in this scope` en Adafruit BusIO.
- La librería lleva 3 años sin actualización y causa core panic + boot loop en ESP32 Core 3.x ([adafruit/Adafruit_INA219#58](https://github.com/adafruit/Adafruit_INA219/issues/58)).
- Flags `ARDUINO_USB_MODE=1` + `ARDUINO_USB_CDC_ON_BOOT=1` causan que `Serial` no se declare correctamente con PlatformIO + `src_dir`.

#### Cambios aplicados

**1. Librería INA219 reemplazada**
- `adafruit/Adafruit INA219 @ ^1.2.0` → `wollewald/INA219_WE @ ^1.4.1`
- INA219_WE está activamente mantenido (v1.4.1, dic 2025) y compatible con ESP32 Core 2.x y 3.x.

**2. Plataforma fijada a ESP32 Core 2.x**
- `platform = espressif32` (v7.0.1, Core 3.x) → `platform = espressif32@5.4.0` (Core 2.x, framework 3.20006).
- Core 2.x declara `Serial` correctamente sin necesidad de `USB.h`.

**3. Flags USB eliminados**
- Eliminados `-DARDUINO_USB_MODE=1` y `-DARDUINO_USB_CDC_ON_BOOT=1` de `build_flags`.
- Con Core 2.x + sin flags USB, `Serial` = UART0 (GPIO1/3) — funciona para flashing y monitor serial.

**4. API INA219_WE actualizada en firmware**
- `Adafruit_INA219 ina219(addr)` → `INA219_WE ina219(&Wire, addr)`
- `ina219.begin()` → `ina219.init()`
- `ina219.setCalibration_32V_2A()` → eliminado (INA219_WE calibra automáticamente en `init()`)
- `ina219.getPower_mW()` → `ina219.getBusPower()`
- Agregado `ina219.setMeasureMode(INA219_CONTINUOUS)` después de `init()`

**5. Fallback class actualizada**
- Clase stub `Adafruit_INA219` reemplazada por `INA219_WE` con API compatible.

**6. `#include <Arduino.h>` agregado**
- Necesario para que `Serial` se declare en el scope global con PlatformIO + `src_dir`.

**7. platformio.ini corregido**
- Agregado `[platformio] src_dir = esp32_qube_l298n`
- Corregido `check_tool = clang-tidy` → `clangtidy`

#### Cambios de firmware
```cpp
// platformio.ini
platform = espressif32@5.4.0          // antes: espressif32 (sin versión)
lib_deps = wollewald/INA219_WE @ ^1.4.1  // antes: adafruit/Adafruit INA219
build_flags = -DCORE_DEBUG_LEVEL=3    // eliminados ARDUINO_USB_MODE y CDC_ON_BOOT

// esp32_qube_l298n.ino
#include <Arduino.h>                   // agregado al inicio
INA219_WE ina219(&Wire, 0x40);        // antes: Adafruit_INA219 ina219(0x40)
ina219.init();                        // antes: ina219.begin()
ina219.setMeasureMode(INA219_CONTINUOUS); // nuevo
powermW = ina219.getBusPower();       // antes: ina219.getPower_mW()
```

#### Notas
- **UART0** (GPIO1/3) se usa para Serial (USB CDC deshabilitado). Para monitoreo, usar `pio device monitor`.
- RAM: 13.6% (44,584 / 327,680 bytes), Flash: 61.6% (807,609 / 1,310,720 bytes).
- Referencia: [INA219_WE GitHub](https://github.com/wollewald/INA219_WE), [Adafruit_INA219 Issue #58](https://github.com/adafruit/Adafruit_INA219/issues/58)

---

## [1.18.0] — 2026-05-27

### Reescritura y ampliación del README.md

#### Cambios aplicados

**1. Instructivo de Uso completo (nuevo)**
- Guía paso a paso de 11 secciones: prerrequisitos, clonar, LM2596, firmware, WiFi, modos, GUI, HTTP, flujo de trabajo, tests, troubleshooting.
- Incluye diagrama de flujo visual del proceso completo (preparar → ajustar → flashear → verificar → calibrar → monitorear).
- Tabla de troubleshooting con 7 síntomas, causas y soluciones.

**2. Diagramas de arquitectura reescritos**
- Diagrama de conexión general con INA219 en serie (bloques separados: fuente → INA219 → L298N → motor).
- Diagrama detallado de conexión del INA219 (VIN+/VIN− en serie, I2C, alimentación 3.3V).
- Diagrama de flujo de datos con FreeRTOS tasks (control 200 Hz, INA219 100 Hz, telemetry 20 Hz, WiFi event-driven).

**3. Sección Schmitt Trigger CD40106BE documentada**
- Investigación completa: CD40106BE hex inversor Schmitt Trigger, pinout DIP-14, umbrales VT+/VT−, histéresis.
- Circuito de acondicionamiento con doble inversión (INV1+INV2 → GPIO34, INV3+INV4 → GPIO35).
- Protección de entrada: R_series 2.2kΩ + R_pd 10kΩ + C 100nF.
- Alimentación a 3.3V con bypass 100nF (explicación de por qué se necesita).
- Uso de los 6 inversores: 4 para encoders + 2 reservados.
- Nota sobre voltaje de salida: pin 3V3 del ESP32 entrega ~3.5V, seguro para GPIO (máx 3.6V).
- Comparativa: divisor 10kΩ/10kΩ (1.75V, marginal) vs Schmitt trigger (3.5V, limpio).
- Costo total: ~$0.73 USD.
- Estado: implementado en protoboard para encoders servo (GPIO34/35).

**4. Circuito de encoders actualizado**
- Se documentó el circuito actual real: divisor resistivo 10kΩ/10kΩ (3.5V → 1.75V) + Schmitt trigger CD40106BE.
- Se aclaró que 1.75V es marginal para el ESP32 y el Schmitt regenera a 3.5V.

**5. Estructura del README reorganizada**
- 14 secciones numeradas en tabla de contenidos.
- Hardware requerido con tabla de componentes incluyendo CD40106BE.
- Pinout completo con tabla pin por pin, cableado ENA, configuración ESP32.
- Control PID, firmware (FreeRTOS tasks, comandos), calibración, resultados.
- Roadmap actualizado con Schmitt trigger como completado.

#### Notas
- No se modificó el firmware (`esp32_qube_l298n.ino`) en esta entrada.
- Todos los cambios son de documentación.
- Referencia: `docs/research/ai_research/CD40106BE_INVESTIGATION.md`

---

## [1.17.3] — 2026-05-13

### Diagnóstico y autodetección de INA219 por I2C

#### Problema identificado
- En arranque aparecía `INA219: NO DETECTADO` aun con hardware aparentemente conectado.
- Causa probable: dirección I2C distinta a la esperada o problema de bus no visible en logs.

#### Cambios aplicados

**1. Escaneo I2C en arranque y bajo demanda**
- Se agrega `scanI2CBus()` para listar dispositivos detectados en direcciones `0x01..0x7E`.
- Se ejecuta automáticamente en `setup()` y también por comando serial `n`.

**2. Inicialización INA219 con direcciones candidatas**
- Se agrega `initIna219()` que prueba `0x40`, `0x41`, `0x44`, `0x45` y aplica calibración al detectar el sensor.
- Se registra dirección activa en `inaAddr` y se imprime en serial (`INA219: OK @ 0x..`).

**3. Mejoras de diagnóstico por serial**
- `printHelp()` ahora incluye `n(ina scan)` para relanzar detección sin reiniciar.
- El mensaje final de arranque muestra estado y dirección detectada cuando corresponde.

#### Cambios de firmware
```cpp
void scanI2CBus() { ... }                // Escaneo I2C para diagnóstico
bool initIna219() { ... }                // Detección INA219 en varias direcciones
case 'n': { scanI2CBus(); ... }          // Comando serial para reintentar detección
```

#### Notas
- Si el scan no lista ningún dispositivo, el problema es eléctrico (SDA/SCL, GND común, alimentación o pull-ups).
- Si aparece una dirección diferente a las candidatas, se puede extender la lista en `initIna219()`.

---

## [1.17.2] — 2026-05-13

### Confirmación experimental del encoder servo y ajuste de acondicionamiento

#### Problema identificado
- Persistía incertidumbre sobre el tipo de salida del encoder del servo durante pruebas de banco.
- Medición validada por el usuario: en estado abierto el canal alcanza hasta **4.7 V**, y con adaptación resistiva se observa nivel alto de **~2.5 V** en GPIO.

#### Cambios aplicados

**1. Confirmación de comportamiento eléctrico (servo)**
- Se registra el encoder servo como salida compatible con **push-pull a 5 V** en el punto de prueba actual.
- Nivel alto en reposo: ~4.7 V (línea original del encoder).

**2. Adaptación segura a ESP32**
- Topología adoptada para canales A/B del servo: **divisor 10 kΩ / 10 kΩ** hacia GPIO34/GPIO35.
- Nivel alto esperado en ESP32: ~2.5 V (dentro de umbral lógico y seguro para 3.3 V).

#### Notas
- Se mantiene GND común entre fuente, encoder, L298N, INA219 y ESP32.
- Esta entrada documenta validación de hardware y actualización de criterio de cableado; no implica cambios de código en `esp32_qube_l298n.ino`.

---

## [1.17.1] — 2026-05-13

### Reconexión de hardware para recuperar INA219 y diagnóstico de señal de encoder

#### Problema identificado
- Se requirió reconectar el sistema completo para restablecer telemetría del INA219 (bus, corriente y potencia).
- Durante el diagnóstico del encoder, la etapa con divisor resistivo entregó solo **35–40 mV** al GPIO del ESP32 en estado alto.
- Ese nivel queda muy por debajo del umbral lógico de entrada digital, por lo que la ESP32 no detecta flancos y no mide `CNT/POS`.

#### Cambios aplicados

**1. Reconexión integral del cableado de medición (INA219)**
- Se volvió a cablear la ruta de potencia/sensado para recuperar lectura estable del INA219 en telemetría.
- Se validó retorno de variables `v_bus`, `i_ma` y `p_mw` en `GET /state` y salida serial.

**2. Registro del incidente de encoder por nivel lógico insuficiente**
- Se documenta que la topología con divisor resistivo usada en esta prueba no permitió nivel alto válido para ESP32.
- Hallazgo de banco: alto en A/B de 35–40 mV (indetectable), consistente con comportamiento de salida tipo open-drain cuando falta pull-up efectivo.

#### Notas
- Este registro corresponde a reconexión/diagnóstico de hardware; no requiere cambios adicionales de firmware en esta entrada.
- Acción recomendada para encoder: pull-up externo por canal a 3.3 V y evitar divisor a GND cuando la salida sea open-drain.

---

## [1.17.0] — 2026-05-07

### Corrección de Error en Régimen Permanente — Habilitación de Acción Integral

#### Problema identificado
- Tras 4 sesiones experimentales de captura de datos, se identificó que el motor **nunca alcanzaba el ángulo asignado** con error < 10°.
- El setpoint se enviaba correctamente, el motor arrancaba, pero se detenía 10–30° antes por fricción estática.
- Causa raíz: `Ki = 0.0` (integral desactivada) y zona de activación de integral restringida a `|err| < 8°`, que nunca se alcanzaba porque el motor se frenaba antes de entrar en esa zona.

#### Cambios aplicados

**1. Ki: 0.0 → 0.15**
- Habilita la acción integral para acumular corrección cuando el motor se frena por fricción.
- El anti-windup `INTEGRAL_LIMIT = 250` limita la acumulación máxima.

**2. Zona de activación integral: `|err| < 8°` → `|err| < 45°`**
- Permite que el integrador actúe durante el transitorio completo, no solo en zona de estado estable.
- Con el esquema anterior, si el motor se detenía a 20° del setpoint, la integral nunca acumulaba.

**3. Velocidad máxima para activación integral: 25°/s → 60°/s**
- Permite integrar durante el transitorio de aproximación, no solo en estado cuasi-estático.

#### Cambios de firmware
```cpp
// Ganancia integral habilitada
float Ki = 0.15f;  // Antes: 0.0f

// Zona de activación del integrador (lazo de control)
if (abs(err) < 45.0f && abs(filteredVel) < 60.0f) {  // Antes: 8° / 25°/s
  integralTerm += err * dt;
  ...
}
```

#### Ajuste fino recomendado
- Si converge pero oscila alrededor del setpoint: reducir `Ki` a `0.10`
- Si sigue sin alcanzar el setpoint: subir `Ki` a `0.20`
- Comandos HTTP: `/cmd?ki=0.10` o `/cmd?ki=0.20`

---

## [1.16.0] — 2026-05-06

### WiFi AP+STA, CORS, GUI Web y Diagnósticos de Red

#### Cambios aplicados

**1. Modo WiFi AP+STA simultáneo**
- El ESP32 ahora puede crear su propio AP (`QUBE-ESP32` / `qube1234`) **y** conectarse a una red LAN al mismo tiempo.
- Variables configurables: `ENABLE_STA`, `STA_SSID`, `STA_PASS`, `WIFI_CONNECT_TIMEOUT_MS` (15 s).
- Función `connectStaIfConfigured()` con timeout y feedback por Serial.

**2. AP explícitamente visible**
- `WiFi.softAP(AP_SSID, AP_PASS, 6, false, 4)` — canal 6, `hidden=false`, máx 4 clientes.
- Antes el AP podía aparecer como "red oculta" en Windows.

**3. Headers CORS en todas las rutas HTTP**
- `addCorsHeaders()` añade `Access-Control-Allow-Origin: *` a todas las respuestas.
- Handlers OPTIONS registrados para `/state` y `/cmd` (preflight del navegador).
- Permite usar la GUI web desde cualquier origen sin error de CORS.

**4. Diagnóstico de red en runtime**
- Función `printNetworkInfo()`: imprime AP SSID, AP IP, LAN SSID, LAN IP por Serial.
- Comando Serial `'i'` → ejecuta `printNetworkInfo()`.
- `printHelp()` actualizado con mención al comando `i(IP)`.

#### Variables de configuración añadidas
```cpp
const bool ENABLE_STA = true;
const char* STA_SSID = "";  // Rellenar con SSID del router
const char* STA_PASS = "";  // Rellenar con contraseña
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
```

---

## [1.15.0] — 2026-04-29

### Endurecimiento del Lazo de Control y Preparación para Estabilización de Señales

#### Problema identificado
- El motor oscila ±8–15° alrededor del setpoint debido a PWM_MIN=28, que fuerza al motor a moverse incluso para errores muy pequeños (< 1°).
- La autoridad de Kp=0.42 es insuficiente para setpoints grandes o transitorios rápidos.
- El deadband de 0.3° es demasiado pequeño, permitiendo que el ruido del encoder cause chatter.

#### Cambios de firmware aplicados

**1. Reducción de PWM_MIN: 28 → 12**
- Permite resolución de control más fina (motor puede moverse en pasos más pequeños).
- Reduce la banda muerta donde el controlador no puede ajustar PWM sin jump abrupto.
- Nota: El motor debe probarse en modo manual (`m1, p15`) para verificar que funciona a PWM ≥ 12.

**2. Aumento de Ganancia Proporcional: Kp 0.42 → 0.75**
- Mejora la respuesta en transitorios y setpoints lejanos (>30°).
- Compensa la reducción de PWM_MIN_SIZE al permitir mayor autoridad de corrección.
- No se cambia Ki/Kd en esta versión (Ki permanece desactivada).

**3. Ampliación de Deadband: 0.3° → 0.8°**
- Suprime oscilaciones residuales causadas por ruido discreto del encoder (±1 LSB ≈ 0.176°/cnt).
- Mejora estabilidad en estado estable sin sacrificar capacidad transiente.

#### Beneficios esperados
- ✅ Control más suave sin oscilación tipo bang-bang
- ✅ Mejor tracking en transitorios rápidos (>30°)
- ✅ Reducción de chattering en setpoint constante
- ✅ Mejor resolución de control en zona lineal

#### Cambios de firmware mínimos
```cpp
// Línea 121: PWM_MIN
const int PWM_MIN = 12;    // Antes: 28

// Línea 121: Kp  
float Kp = 0.75f;         // Antes: 0.42f

// Línea 641: Deadband
if (abs(err) <= 0.8f) {   // Antes: 0.3f
  pwm = 0;
}
```

#### Comandos de calibración aún activos
- `kp<val>`: sobrescribe Kp en runtime
- `ki<val>`: idem
- `kd<val>`: idem
- `/cmd?kp=0.75`: equivalente HTTP

#### Validación recomendada
1. Compilar y cargar firmware
2. Probar modo manual: `m1` → `p15` → motor debe girar suavemente
3. Probar PID en setpoint 0°: `m2, s0` → debe converger sin oscilar
4. Probar transiente: `s45` → debe alcanzar setpoint en ~2–3 segundos sin overshoot excesivo

---

## [HW-FIX-1] — 2026-04-29

### Diagnóstico de hardware — Encoder sin lectura confiable

#### Causa raíz identificada
- El encoder del servo (Premotec 990412016913) tiene salida **open-drain**: en estado neutro flota alrededor de **2.5 V**, y llega a 5 V solo en el pico de conmutación.
- El level shifter en la ruta A/B medía **~7 MΩ** de impedancia de señal, insuficiente para sostener un nivel lógico limpio.
- Resultado: señal indeterminada que el ESP32 (GPIO34/GPIO35) no puede discriminar como 0 o 1. `CNT` y `POS` no cambian aunque el eje gire.

#### Solución de hardware aplicada
- Se **eliminó el level shifter** del camino de señal A/B.
- Se instalaron **pull-up de 4.7 kΩ a 3.3 V** directamente en las líneas A y B.

```
Encoder A ──┬── 4.7kΩ ── 3.3V
            └── GPIO34 (ESP32)

Encoder B ──┬── 4.7kΩ ── 3.3V
            └── GPIO35 (ESP32)

Encoder GND ─── GND común
```

#### Por qué es seguro sin el level shifter
- Con salida open-drain y pull-up a 3.3 V, la línea oscila entre 0 V (transistor interno conduce) y 3.3 V (pull-up sostiene). Nunca supera 3.3 V en el GPIO.
- El ESP32 GPIO34/GPIO35 no es 5 V tolerante, pero con este esquema nunca ve más de 3.3 V.

#### Cambios de firmware
- **Ninguno requerido.** El firmware ya usaba `INPUT` (sin pull-up interno) en GPIO34/GPIO35, que es correcto para esta topología.

---

## [1.14.0] — 2026-04-28

### Problema detectado
- La posición seguía reportándose incorrecta tras estabilizar el modo de control. En esta etapa, la causa probable pasa a ser **calibración de escala y/o signo del encoder** (no solo captura de pulsos).

### Añadido
- **Calibración en runtime de lectura de encoder** (sin recompilar):
  - `ed<1|-1>`: define dirección de encoder (`encoderDir`).
  - `cpr<val>`: define cuentas por vuelta (`countsPerRev`).
- Equivalentes HTTP:
  - `/cmd?ed=-1`
  - `/cmd?cpr=2048`
- Telemetría JSON extendida:
  - `encoder_dir`
  - `counts_per_rev`

### Objetivo
- Corregir lecturas mal orientadas o mal escaladas de forma inmediata durante la puesta a punto del banco.

---

## [1.13.0] — 2026-04-28

### Problema detectado
- En algunas pruebas, `M:2` permanecía activo pero `POS/CNT` casi no variaban, afectando directamente al PID por falta de retroalimentación confiable.

### Añadido
- **Decodificación de encoder por polling (cuadratura X4)** en `loop()` con tabla de transición (`QUAD_LUT`).
- **Selector de modo de captura**:
  - `USE_ENCODER_INTERRUPTS` (ISR A/B)
  - `USE_ENCODER_POLLING` (sondeo)
- En esta versión se deja **polling activo por defecto** y **interrupciones desactivadas** para robustez en banco.
- **Telemetría de diagnóstico** añadida en JSON:
  - `enc_a`
  - `enc_b`

### Resultado esperado
- Si las señales A/B están presentes en hardware, `CNT/POS` deben actualizarse aunque las ISR no disparen correctamente.
- Si `enc_a/enc_b` quedan fijos, el problema es físico (cableado, nivel lógico o encoder incorrecto), no del PID.

---

## [1.12.0] — 2026-04-28

### Problema detectado
- Durante pruebas de setpoint en PID (`M:2`), el sistema regresaba a `M:0` con `PWM:0` aunque el eje no había llegado al objetivo. Causa: activación del timeout de comandos en banco de pruebas.

### Cambiado
- **Failsafe por timeout configurable**:
  - Nueva bandera `ENABLE_COMMAND_TIMEOUT`.
  - Valor por defecto: `false` para ajuste y calibración en banco.
  - Al ponerla en `true`, se mantiene el comportamiento previo (`safeStop()` cuando expira `COMMAND_TIMEOUT_MS`).

### Nota de uso
- Para operación final con mayor seguridad, reactivar `ENABLE_COMMAND_TIMEOUT = true`.

---

## [1.11.0] — 2026-04-28

### Problema detectado
- Desfase angular sistemático entre setpoint y posición medida (ejemplo reportado: `s-90` alcanzaba alrededor de `45°`). Esto indica referencia cero mecánica desalineada respecto al cero del encoder.

### Añadido
- **Calibración de offset angular en runtime**:
  - Variable `positionOffsetDeg` aplicada a la posición usada por PID y telemetría.
  - Función `zeroPositionHere()` para fijar el cero en la posición mecánica actual.
- **Nuevos comandos serie**:
  - `z` : toma la posición actual como cero (`positionOffsetDeg = rawPos`), pone `setpoint=0` y resetea PID.
  - `o<deg>` : fija manualmente el offset (en grados).
- **Nuevos comandos HTTP**:
  - `/cmd?z=1`
  - `/cmd?o=<deg>`
- **Telemetría extendida**:
  - `raw_position_deg`
  - `offset_deg`

### Resultado esperado
- Corrección directa de desfases constantes (ej. ±45°) sin recablear ni recompilar por cada prueba.

---

## [1.10.0] — 2026-04-28

### Problema detectado
- Aunque el eje alcanzaba `45°`, seguía acumulando demasiada energía al cruzar el setpoint y luego se disparaba de nuevo hacia ángulos grandes. La causa ya no era la dirección del control, sino una combinación de mando excesivo cerca del objetivo e integración activa fuera de la zona útil.

### Cambiado
- **Ganancias**:
  - `Kp`: 0.50 → **0.42**
  - `Ki`: 0.002 → **0.0**
  - `Kd`: se mantiene en **0.06**
- **Integración condicionada**:
  - El término integral solo se acumula si `|err| < 8°` y `|vel| < 25°/s`.
  - Fuera de esa ventana, el integrador se reinicia a `0` para evitar windup durante aproximaciones rápidas.
- **Compensación de fricción más conservadora**:
  - `PWM_MIN` solo se fuerza si `|err| > 8°` y `|vel| < 15°/s`.
- **Límite de PWM dependiente del error**:
  - `|err| < 20°` → `PWM <= 80`
  - `|err| < 10°` → `PWM <= 55`
  - `|err| < 5°` → `PWM <= 35`

### Objetivo
- Reducir la energía con la que el eje cruza el setpoint.
- Evitar que un sobreimpulso pequeño se convierta en una fuga de gran amplitud.

---

## [1.9.0] — 2026-04-28

### Ajuste fino
- A partir de una respuesta ya estable en `45°` (sobreimpulso aproximado de `1.9°` y correcciones finales entre `PWM=0` y `PWM=1`), se realizó un refinamiento para mejorar el asentamiento final y reducir error residual.

### Cambiado
- **Ganancias PID**:
  - `Kp`: 0.55 → **0.50**
  - `Ki`: 0.00 → **0.002**
  - `Kd`: se mantiene en **0.06**
- **Banda muerta de posición**:
  - `|err| <= 0.5°` → **`|err| <= 0.3°`**

### Objetivo
- Reducir ligeramente el sobreimpulso sin perder rapidez.
- Permitir corrección lenta del error estático residual sin reintroducir oscilación apreciable.

---

## [1.8.0] — 2026-04-28

### Problema detectado
- La telemetría mostró inversión prematura del control antes de alcanzar el setpoint (`PWM:+28` alrededor de 32° con `SP=45°`). Esto indicó que la derivada seguía dominando la ley de control aun con el filtro previo, provocando **chattering** y frenado anticipado.

### Cambiado
- **Ganancias PD reajustadas** para dar mayor peso al error de posición y menor peso al término derivativo:
  - `Kp`: 0.35 → **0.55**
  - `Kd`: 0.18 → **0.06**
- **Filtro de velocidad más suave**:
  - `VEL_ALPHA`: 0.25 → **0.12**
  - Esto incrementa el suavizado de la velocidad estimada y reduce inversión espuria de signo por ruido o cuantización del encoder.
- **Compensación de fricción (`PWM_MIN`) menos agresiva**:
  - Antes: se forzaba cuando `|err| > 2°` y `|vel| < 50°/s`
  - Ahora: solo se fuerza cuando `|err| > 6°` y `|vel| < 20°/s`
  - Objetivo: evitar comportamiento tipo bang-bang durante la aproximación al setpoint.

---

## [1.7.0] — 2026-04-28

### Problema detectado
Con `Kd=0.45` a 200 Hz, el ruido de ±1-2 counts del encoder cuadratura generaba velocidades aparentes de ~70°/s. El término derivativo (0.45×70=31 PWM) superaba al proporcional (0.25×45=11 PWM) desde el primer ciclo, enviando el motor en dirección contraria al setpoint.

### Cambiado
- **Filtro paso-bajo en la velocidad** (`filteredVel`): la derivada ya no se calcula directamente de muestra a muestra sino como EMA (*Exponential Moving Average*) con `VEL_ALPHA=0.25`. Esto reduce el impacto del ruido cuántico del encoder sin eliminar la información de velocidad real.
  - Fórmula: `filteredVel = 0.25 × rawVel + 0.75 × filteredVel`
- **`filteredVel` se inicializa a 0** en `resetPid()` para evitar transitorio al arrancar.
- **Ganancias reajustadas** a valores seguros con derivada filtrada:
  - `Kp`: 0.25 → **0.35**
  - `Kd`: 0.45 → **0.18** (Kd efectivo equivalente mayor gracias al filtro)

---

## [1.6.0] — 2026-04-28

### Cambiado
- **Ganancias PID** ajustadas para reducir oscilación creciente (sistema subamortiguado):
  - `Kp`: 0.4 → **0.25** (menos agresividad proporcional)
  - `Kd`: 0.20 → **0.45** (mayor amortiguación al cruzar el setpoint)
- **Lógica de zona muerta (`PWM_MIN`)**: antes se forzaba `PWM_MIN` siempre que `|err| > 0.8°`, lo que inyectaba energía extra mientras el motor ya tenía velocidad alta, amplificando las oscilaciones. Ahora solo se fuerza si se cumplen **ambas** condiciones:
  - `|err| > 2.0°` (lejos del setpoint)
  - `|velocidad| < 50°/s` (motor casi parado)
- Umbral de parada: `|err| ≤ 0.5°` (antes 0.4°).

### Contexto
- Motor llegaba a 45° con buena oscilación inicial pero la corrección de retorno lo llevaba a −90° o más. Causa: `Kd` insuficiente para frenar la velocidad de cruce + `PWM_MIN` añadiendo energía durante las oscilaciones.

---

## [1.5.0] — 2026-04-28

### Cambiado
- **Modo PD puro**: `Ki` establecido en `0.0` para eliminar windup integral como fuente de inestabilidad. El motor alcanzaba el setpoint (45°) pero la energía acumulada por el integrador durante la aproximación causaba un overshoot que crecía en cada ciclo hasta perder el control.
- **Ganancias ajustadas para amortiguación crítica** sobre el Premotec 990412016913:
  - `Kp`: 0.8 → **0.4**
  - `Ki`: 0.01 → **0.0** (desactivado temporalmente)
  - `Kd`: 0.05 → **0.20** (incrementado 4× para frenar oscilaciones)

### Proceso de sintonización recomendado (a partir de esta versión)
1. Estabilizar con PD puro (`Ki=0`): ajustar `Kp` y `Kd` hasta obtener respuesta sobreamortiguada o críticamente amortiguada.
2. Una vez estable, introducir `Ki` de forma incremental desde `0.003` para eliminar error estático residual.
3. Verificar que Ki no reintroduce oscilaciones antes de aumentar.

---

## [1.4.0] — 2026-04-28

### Corregido
- **Retroalimentación positiva (fuga del motor)**: el PID empujaba en la misma dirección que el error creciente, causando que el motor se alejara indefinidamente del setpoint en lugar de converger. Causa raíz: la dirección positiva del motor era opuesta a la dirección positiva del encoder.

### Añadido
- **Constante `MOTOR_DIR`** (`1` / `-1`): invierte la salida del PID hacia `setMotor()` sin modificar la lógica de control ni el encoder. Valor predeterminado: `-1` (invertido para el Premotec 990412016913 con la conexión OUT1/OUT2 actual). Ajustable en una sola línea si se invierte el cableado del motor.

---

## [1.3.0] — 2026-04-28

### Cambiado
- **Control PID: derivada sobre la medición** (`-d(pos)/dt`) en lugar de sobre el error (`d(error)/dt`).
  - Elimina el pico de control (*derivative kick*) al cambiar el setpoint bruscamente.
  - Previene arranque a PWM máximo al activar modo PID con posición alejada del setpoint.
- **Ganancias PID ajustadas** para motor Premotec 990412016913 (18 V nominal, operado a 15 V):
  - `Kp`: 2.0 → **0.8**
  - `Ki`: 0.04 → **0.01**
  - `Kd`: 0.03 → **0.05**
- **`resetPid()`**: ahora inicializa `prevPos` con la posición actual del encoder, evitando transitorio de derivada en el primer ciclo tras un reset o cambio de modo.

### Añadido
- Variable `prevPos` (posición anterior en grados) para cálculo de derivada sobre la medición.

---

## [1.2.0] — 2026-04-27

### Cambiado
- **`COMMAND_TIMEOUT_MS`**: 1500 ms → **10 000 ms** para facilitar pruebas interactivas sin que el failsafe detenga el motor entre comandos.
- **Zona muerta del PID**: umbral de parada refinado a `|err| ≤ 0.4°` y forzado de `PWM_MIN` para `|err| > 0.8°`, evitando oscilación permanente cerca del setpoint.

### Corregido
- **GPIO34 / GPIO35**: cambiados de `INPUT_PULLUP` a `INPUT`.  
  GPIO34 y GPIO35 son pines *input-only* en el ESP32-WROOM-32; no disponen de resistencia pull-up interna. La llamada a `gpio_pullup_en` generaba un error de boot. Se usan resistencias externas de 4.7 kΩ en el lado HV del level shifter.

---

## [1.1.0] — 2026-04-27

### Añadido
- **Wrappers de compatibilidad LEDC** para soportar tanto ESP32 Arduino Core v2 (`ledcSetup` / `ledcAttachPin`) como v3 (`ledcAttachChannel`), seleccionados automáticamente en tiempo de compilación mediante `#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)`.

### Corregido
- **`Adafruit_INA219.h` no encontrado**: inclusión condicional con `#if defined(__has_include)`. Si la biblioteca no está instalada, se usa una clase stub que devuelve valores nulos y activa el flag `inaOk = false`, permitiendo que el firmware compile y opere sin el sensor.

---

## [1.0.0] — 2026-04-27

### Añadido
- Firmware inicial para ESP32 + L298N + INA219 + LM2596 + level shifter 5V↔3.3V.
- **Modo `USE_ENA_PWM = false`**: PWM generado en IN1/IN2 del L298N con jumper ENA habilitado, sin necesidad de cable al GPIO25 (no disponible en el módulo ESP32-WROOM-32 estándar).
- Control en tres modos: `m0` (stop), `m1` (PWM manual), `m2` (PID posición).
- PID discrecional a 200 Hz con anti-windup por saturación del término integral (`INTEGRAL_LIMIT = 250`).
- Telemetría por puerto serie a 10 Hz: posición (°), conteo de encoder, setpoint, PWM, modo.
- Servidor HTTP (Access Point `QUBE-ESP32`) con endpoints `/state` (JSON) y `/cmd` (GET params).
- Lectura de encoder en cuadratura por interrupciones en GPIO34/GPIO35.
- Medición de bus, corriente y potencia por INA219 vía I2C (GPIO21=SDA, GPIO22=SCL).
- Failsafe: detención automática si no se reciben comandos en `COMMAND_TIMEOUT_MS`.

---

## Pinout de referencia (versión actual)

| Señal | GPIO ESP32 | Observación |
|-------|-----------|-------------|
| L298N IN1 | GPIO26 | PWM dirección + |
| L298N IN2 | GPIO27 | PWM dirección − |
| Encoder A | GPIO34 | Vía Schmitt trigger CD40106BE (doble inversión), Vcc=3.3V |
| Encoder B | GPIO35 | Vía Schmitt trigger CD40106BE (doble inversión), Vcc=3.3V |
| INA219 SDA | GPIO21 | I2C |
| INA219 SCL | GPIO22 | I2C |
| ENA L298N | Jumper | Sin cable al ESP32 |

## Motor de referencia

**Premotec 990412016913** — Motor DC con encoder, 18 V nominal, operado a 15 V con L298N.
Dos conectores de 5 pines (encoder motor + encoder péndulo): VCC, A, GND, B, Index.  
Cable trenzado de 2 pines: M+ / M− (terminales del motor, conectados a OUT1/OUT2 del L298N).
