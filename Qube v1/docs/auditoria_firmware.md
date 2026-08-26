# Auditoría del firmware ESP32 — QUBE Servo

> **Estado de aplicación (2026-07-28).** Fase 0 completa (0.1–0.3; falta 0.4 commit
> y 0.5 trazas de referencia, que requieren decisión y banco). Fase 1: aplicados
> 1.1, 1.2, 1.3, 1.4, 1.7 y parte de la Fase 2 (2.1–2.4, 2.6, 2.7). Pendientes:
> 1.5 (delays en handlers async), 1.6 (auth de endpoints), 1.8 (calado sin INA219),
> 2.5 (snprintf), Fase 3 y Fase 4.
> El firmware compila (`pio run -e esp32dev`, sin warnings del sketch) pero
> **nada de esto se validó en hardware**. Ver "Riesgos de lo ya aplicado" al final.

Fecha: 2026-07-28
Alcance: `src/firmware/` (principalmente `esp32_qube/esp32_qube.ino`, 2840 líneas),
`platformio.ini`, `.github/workflows/ci.yml`, herramientas Python de `src/firmware/`.
Estado del árbol: rama con cambios sin commitear tras el revert BTS7960→L298N (v1.52.0).

Método: lectura completa del `.ino`, verificación de cada hallazgo por búsqueda de
símbolos (conteo de referencias) y trazado de alcanzabilidad de ramas. **No hubo
ejecución en hardware**: todo lo que sigue es estático. Los hallazgos F1–F5 predicen
comportamiento en banco y deberían confirmarse ahí antes de citarlos en la tesis.

---

## Resumen

El firmware funciona y tiene un nivel de comentario muy por encima del promedio —
varias decisiones difíciles (PCNT, coexistencia AP+STA, orden de arranque del I2C,
convención de observación RL) están documentadas en el propio código con el porqué.
El problema no es la falta de cuidado, es la **acumulación**: seis controladores,
tres protocolos y once revisiones de hardware conviven en un solo archivo, y las
capas nuevas se agregaron encima de las viejas sin retirar las que quedaron sin
efecto.

Eso produjo tres clases de deuda:

1. **Código que se cree activo y no lo es.** El caso grave es el swing-up (F1): corre
   con la velocidad del péndulo fija en cero, lo que deja inalcanzable toda la rama de
   bombeo resonante y sin efecto el parámetro `ke_gain`. Hay además ramas completas de
   los modos 4 y 6 que un guard global posterior volvió inalcanzables (F4).
2. **Salidas tempranas que saltan el failsafe.** Diez `return;` dentro del despacho de
   modos salen de `loop()` antes del watchdog de comandos y de la telemetría; uno de
   ellos engancha la protección por tensión de forma permanente (F2, F3).
3. **Parámetros no reconstruibles.** ~40 literales de control incrustados en los lazos
   frente a un bloque de constantes que en buena parte está muerto (F13, F14). Para una
   tesis esto es lo más caro: el controlador reportado no se puede reconstruir leyendo
   la sección de parámetros.

Prioridad: **F1 primero** (afecta lo que se puede afirmar del swing-up), luego F2–F5
(seguridad de operación), después la limpieza.

---

## Hallazgos

Severidad: 🔴 corrección · 🟠 seguridad/operación · 🟡 mantenibilidad · ⚪ tooling

### 🔴 F1 — El swing-up (modo 5) corre con velocidad del péndulo ≡ 0

`swing_filteredVelAlpha` se declara en `esp32_qube.ino:319` y **sus únicas cuatro
asignaciones son `= 0.0f`** (líneas 991, 2685, 2749, 2760). No existe ninguna línea que
la calcule a partir del encoder. En `esp32_qube.ino:2661`:

```cpp
const float alpha_dot = swing_filteredVelAlpha;  // ≡ 0.0f, siempre
```

`prevPosPend` (`:317`), la variable que existe justamente para esa derivada, se escribe
en `:2662` y nunca se lee. El filtro se perdió en alguna refactorización y quedó el
andamiaje.

Consecuencias, todas dentro del modo 5:

| Línea | Código | Efecto real |
|---|---|---|
| 2771 | `if (fabsf(alpha_dot) < SWINGUP_QUIET_THRESHOLD_RADPS)` | siempre verdadero → **siempre** toma la rama "péndulo quieto" |
| 2779-2795 | bombeo resonante + ganancia adaptativa | **rama inalcanzable** |
| 2691 | `brake_pwm = (alpha_dot > 0) ? -PWM_MAX : PWM_MAX` | siempre `+PWM_MAX`: el freno anti-spin ignora el sentido del giro y en un sentido lo **acelera** |
| 2741 | `recover_brake = -0.4f * alpha_dot` | 0 → recovery es coast, no el frenado proporcional documentado |
| 2767 | `damping = -(0.3+0.7·d) * alpha_dot` | 0 → la disipación de 165°→vertical no hace nada |
| 2701 | `verySlow = vel_raw_dps < 30.0f` | siempre verdadero → la transición a LQR sólo depende del ángulo |
| 2718 | `E_current = ½·J·α̇² + mgl(1−cos α)` | pierde el término cinético |

Es decir: **el modo 5 es hoy un barrido sinusoidal de referencia de servo a 2 Hz y ±40°
en lazo abierto** (`:2773-2776`), no un swing-up por energía.

**Implicación para la tesis.** `ke_gain`, `KE_GAIN_BASE/BOOST`, `swing_maxAngleAchieved`
y `STALL_TIMEOUT_MS` viven todos dentro de la rama inalcanzable: **no tienen efecto sobre
el comportamiento**. El comentario de `:538` ("Ganancia calibrada en BTS7960: 25% catch
rate, hold 86s") atribuye un resultado medido a un parámetro que el código no lee. El
resultado observado puede ser real; la atribución causal a `ke_gain` no se sostiene. Hay
que revisar cualquier pasaje del documento que presente el swing-up como control por
energía o que reporte un barrido de `ke_gain`.

**Arreglo:** implementar la derivada filtrada del péndulo en el modo 5. La decisión de
diseño es cuál filtro usar — el EMA del modo 4 (`VEL_ALPHA_PEND`, `:318`), el de
convención sim (`rl_vf_alVel`, ya calculado y disponible) o uno propio. Recomiendo
reutilizar el de convención sim: ya está validado contra el simulador y elimina un
tercer estimador de velocidad del archivo.

---

### 🔴 F2 — La protección por tensión puede quedar enganchada

Modo 4 (`:2635-2644`) y modo 5 (`:2804-2815`):

```cpp
if (inaOk && busVoltageV > 0.1f) {
  if (busVoltageV < 12.5f) { pwm = 0; setMotor(0); return; }   // ← sale de loop()
```

Ese `return` sale de `loop()` **antes** del bloque de telemetría (`:3019`), que es el
único lugar donde se llama `updateIna219()` (`:3026`). Con `busVoltageV` congelada por
debajo del umbral, la condición nunca se re-evalúa: motor cortado, telemetría detenida y
INA219 sin refrescar hasta que alguien cambie de modo por HTTP/serial o rebootee. El
corte es correcto; el enganche no.

---

### 🔴 F3 — Diez `return;` en el despacho de modos saltan failsafe y telemetría

Líneas 2462, 2639, 2657, 2735, 2809, 2848, 2882, 2891, 2964. Todas salen de `loop()`
antes de:

- el watchdog de comandos (`:3012`) que detiene el motor en modos 1 y 6, y
- el bloque de telemetría + `updateIna219()` (`:3019-3057`).

Además de F2, el caso relevante es `:2848` (modo 6, |θ| > `HARD_LIMIT`): aplica PWM de
centrado y sale sin pasar por el watchdog. El patrón correcto es calcular `pwmOut` y
tener un único `setMotor()` al cierre del bloque de modo, con `continue`-semántica en
lugar de `return`.

---

### 🔴 F4 — Escalera de límites incoherente: hay ramas inalcanzables en los modos 4 y 6

`SERVO_HARD_LIMIT_DEG = 95.0f` (`:580`) se evalúa en `:2349`, **antes** del despacho, para
todos los modos salvo 0 y 3. Los límites internos de cada modo se escribieron antes de
ese guard y nadie los reconcilió:

| Modo | Límite declarado | Alcanzable |
|---|---|---|
| 6 | `HARD_LIMIT = 110.0f` (`:2842`), rama `:2844-2849` | **nunca** — el corte global a 95° dispara primero |
| 6 | `SAFE_RANGE = 80.0f` (`:2841`) | sí, banda 80–95° |
| 4 | rama `fabsf(pos) > 100.0f` (`:2609-2615`) | **nunca** |
| 4 | rama `> 85.0f` (`:2616-2624`) | sólo banda 85–95° |
| 4 | rama `> 70.0f` (`:2625-2633`) | sí |
| 5 / 7 | freno `fabsf(pos) > 90.0f` (`:2654`, `:2887`) | sólo banda 90–95° |

La escalera efectiva es 70/85/90/95, no la que dice la documentación. Peor: los frenos de
90° de los modos 5 y 7 hacen `return` cada tick mientras están en esa banda de 5°, lo que
reactiva F3 (telemetría e INA congeladas mientras se empuja el brazo hacia el centro).

---

### 🟠 F5 — El modo 7 no resetea su estado estático al re-entrar

`hybrid_lqr` y `hybrid_lqr_start` (`:2906-2907`), `apexCatchMs` y `lockedBrakeDir`
(`:2954-2955`), `lastRlUs7` (`:2879`) son `static` locales de `loop()`. `setMode(7)`
(`:1008-1018`) resetea el buffer de observación, `rl_last_action`, las `lqr_prev*` y
`rl_vf_init` — pero **no** estos cinco. Tras una caída, volver a entrar al modo 7 arranca
con `hybrid_lqr = true` (el lazo cree que está en fase de balance con el péndulo colgando)
y con la ventana de catch ya consumida. Mismo patrón en `lockedBrakeDir` del modo 4
(`:2454`).

---

### 🟠 F6 — Sin INA219 no hay ninguna protección de tensión; los modos 2/6/7 no la tienen nunca

Confirmado en código: el corte por tensión está gateado por `if (inaOk && ...)` y sólo
existe en los modos 4 (`:2635`) y 5 (`:2804`). Los modos 2 (PID), 6 (RL HTTP) y 7 (RL
on-device) pueden calar el motor contra un tope sin ningún corte por tensión ni corriente
— sólo el corte por ángulo de `:2349`, que no ayuda si el calado ocurre dentro del rango.
Esto ya está registrado en las notas del proyecto; queda confirmado y acotado a qué modos.

---

### 🟠 F7 — Bloqueos dentro del contexto de la task async

`delay()` y operaciones de red dentro de handlers de `AsyncWebServer`, que corre en su
propia task y no admite bloqueos:

- `:2241` `/restart` → `delay(500)`
- `:2249` `/format` → `SPIFFS.format()` (bloqueante, segundos) + `delay(500)`
- `:1332` `handleUpdate` → `delay(500)`
- `:1497-1499` `handleCmd?wifi_reconnect` → `WiFi.disconnect(); delay(100); connectStaIfConfigured();`

El último además compite con el guardián de reconexión de `loop()` (`:2321-2327`), que
puede llamar `connectStaIfConfigured()` concurrentemente. Patrón correcto: el handler
levanta un flag y responde; `loop()` ejecuta la acción.

---

### 🟠 F8 — Endpoints destructivos sin autenticación, dos de ellos por GET

- `GET /format` (`:2244`) formatea SPIFFS y reinicia.
- `GET /restart` (`:2239`) reinicia.
- `POST /update` (`:2184`) flashea firmware por OTA, sin credencial.
- `POST /fs` (`:2208`) escribe archivos arbitrarios en SPIFFS.

Que `/format` y `/restart` sean **GET** significa que un prefetch del navegador, un
historial o un `<img src="http://192.168.100.50/format">` en cualquier pestaña los
dispara. `ArduinoOTA` (`:2294`) tampoco tiene `setPassword()`. La clave del AP está fija
en el fuente (`:677`, `qube1234`). En una red de laboratorio el riesgo es bajo, pero
`/format` borra la GUI y obliga a re-subir SPIFFS.

---

### 🟠 F9 — `dt` es nominal, no medido, y no hay métrica de jitter

`:2340` fija `dt = CONTROL_PERIOD_US / 1e6` constante, y `:2334` hace
`lastControlUs += CONTROL_PERIOD_US` sin cota de atraso. Si el lazo se bloquea —escaneo
WiFi de `:2139`, `processSerialCommand()` hasta 50 ms (`:1754`), SPIFFS, una transacción
I2C lenta— el acumulador queda atrasado y después se ejecutan ticks consecutivos con
`dt = 2 ms` asumido pero muestras separadas por microsegundos. Las derivadas y el término
integral se corrompen justo después de cada hipo, y nada lo registra.

Para la tesis esto es también una brecha de evidencia: los 500 Hz son nominales y no hay
ninguna medición del período real. Recomiendo exponer en `/state` el máximo y el
percentil del período de lazo desde el último reset — es una línea de defensa barata en
la defensa oral.

---

### 🟡 F10 — Ley LQR duplicada entre los modos 4 y 7

Modo 4 (`:2465-2646`) y modo 7 (`:2926-2998`): ~45 líneas cada una implementando el mismo
control, con clamps distintos (`-70,70` vs `hybrid_lqr_pwm`) y comentarios que afirman ser
idénticas. El CHANGELOG ya registra un bug de signo nacido exactamente de esta divergencia
(comentario en `:2929-2932`). Es el candidato número uno a extracción.

### 🟡 F11 — Bloque "reset de offset del péndulo" copiado cuatro veces

`:2594-2596`, `:2682-2684`, `:2746-2748`, `:2757-2759` — mismas tres/cuatro líneas.

### 🟡 F12 — `setMotor` / `setMotorDirect` duplican el árbol, con una rama muerta

`:878-937`. `USE_ENA_PWM` es `false` fijo (`:249`) y las tres funciones de motor
(`setMotor`, `setMotorDirect`, `brakeMotor`) llevan cada una su rama ENA completa que no
se puede ejecutar. `setMotor` es exactamente `setMotorDirect(pwm · factor)`.

### 🟡 F13 — Símbolos muertos

Sólo declaración, cero usos: `normalizeAngle()` (`:843`), `brakeMotor()` (`:940`),
`PEND_LIMIT_DEG`, `COMP_FILTER_ALPHA`, `PEND_DAMPING`, `SWINGUP_TRANSITION_VEL_DPS`,
`SWINGUP_KICK_DUTY_FRAC`, `SWINGUP_KICK_PERIOD_MS`, `SWINGUP_PROD_DEADZONE`,
`LQR_FALLBACK_TIME_MS`, `LQR_FALLBACK_ALPHA_DEG`, `LQR_REARM_ALPHA_DEG`,
`LQR_HARDSTOP_DEG`, `LQR_PROTECT_ALPHA_DEG`, `WIFI_CONNECT_TIMEOUT_MS`.
Escritos y nunca leídos: `hybrid_lqr_start`, `lqr_fallbackMs`, `prevPosPend`.

Caso aparte: **`balance_threshold`** (`:551`) es configurable por HTTP (`?bt=`, `:1577`)
y **ningún lazo lo lee**. Es un parámetro publicado en la API que no hace nada — si
alguien lo barrió buscando el umbral de transición, barrió ruido.

### 🟡 F14 — Números mágicos en los lazos de control

Los modos 4/5/6/7 contienen ~40 literales de control (70, 85, 100, 25, 30, 120, 125, 165,
200, 250, 360, 0.10, 0.3, 0.4, 0.5, 2.0, 3.0, 4.0…) mientras arriba existe un bloque de
constantes nombradas que en buena parte está muerto (F13). El efecto combinado es que
**el bloque de parámetros del archivo no describe el controlador que corre**.

### 🟡 F15 — Shadowing de las ganancias del PID

`:2361` declara `float Kp, Ki, Kd;` locales que tapan las globales homónimas, y `:2383`
tiene que escribir `Kp = ::Kp;` para recuperarlas.

### 🟡 F16 — `abs()` sobre `float`

`:2358`, `:2387`, `:2415`, `:2490`, `:2493`, `:2515` usan `abs()` donde el resto del
archivo usa `fabsf()`. Funciona por el macro de Arduino, pero si alguna vez resuelve a
`int abs(int)` trunca silenciosamente — y `abs(alpha)` con `alpha` en grados truncaría
justo en la comparación de gain scheduling del LQR.

### 🟡 F17 — Aritmética de doble precisión en el lazo de 500 Hz

`:2339` usa `fmod` (double) — el ESP32 no tiene FPU de doble precisión, se resuelve por
software en cada tick. Debe ser `fmodf`. `:882` llama `powf(x, 2.0f)` en cada `setMotor()`
para elevar al cuadrado; una multiplicación basta.

### 🟡 F18 — `getStateJson()` construye ~45 concatenaciones de `String`

`:1261-1313`, llamado a 10 Hz desde la task async y también por `/state`. Fragmenta el
heap en corridas largas — precisamente el escenario de las sesiones de entrenamiento RL.
Un `snprintf` sobre buffer estático elimina el problema.

### 🟡 F19 — Documentación desincronizada del código

- Cabecera (`:30-54`): lista sólo `m0..m3` y `m6`; faltan m4 (LQR), m5 (swing-up) y m7
  (RL on-device). En endpoints faltan `/rl_step`, `/update`, `/fs`, `/restart`, `/format`.
- `printHelp()` (`:1734-1745`), que es además la respuesta a cualquier comando serie
  desconocido: no menciona m3 (homing), m6, m7, ni los comandos `q`, `b`, `j`, `y`, `L`.
- Comentario de `setMotor` (`:879-881`): dice `k=120°` y factores 0.80 @60° / 0.64 @90°;
  el código usa 200.0f (`:882`), que da 0.92 y 0.83.

### ⚪ F20 — El firmware no se compila en CI

`.github/workflows/ci.yml` corre ruff y pytest sobre Python. Un `.ino` de 2840 líneas sin
build automático: cualquier error de compilación se descubre en la sesión de banco.

### ⚪ F21 — `pio check` inutilizable

`platformio.ini:42-44`: `--checks=*` junto con `--warnings-as-errors=*` no puede pasar
nunca sobre código Arduino.

### ⚪ F22 — Test único, con jumper físico, sin filtro configurado

`test_filter =` vacío (`platformio.ini:38`) y `test_encoder_pulse_loss/test_main.cpp`
requiere puentear GPIO18→23 y GPIO19→22. No es ejecutable en CI y no está documentado
como procedimiento manual. (Nota menor: los comentarios de `:44-55` de ese archivo dicen
que las unidades PCNT tienen pines fijos; en el ESP32 la matriz GPIO permite mapear
cualquier pin a cualquier unidad.)

### ⚪ F23 — Falta `credentials.h.example`

`credentials.h` está en `.gitignore` (correcto) pero no hay plantilla versionada: un clon
limpio no compila y no hay forma de saber qué símbolos definir
(`DEFAULT_STA_SSID`, `DEFAULT_STA_PASS`).

### ⚪ F24 — Lastre dentro del directorio de fuentes

`esp32_qube/esp32_qube_l298n.ino.bak` (76 KB) y `esp32_qube/policy_weights.h.r6bak`
(71 KB). El historial está en git; estos archivos sólo confunden las búsquedas.

### ⚪ F25 — Cinco herramientas serie superpuestas

`capture.py` (15 KB), `qube_serial_tool.py` (14 KB), `serial_cmd.py` (2 KB),
`monitor_swingup.py` (0,8 KB), `flash.py` (6 KB). Al menos las tres primeras hablan el
mismo protocolo por su cuenta.

### ⚪ F26 — La rama de compatibilidad Arduino 3.x nunca se compila

`platform = espressif32@5.4.0` ⇒ arduino-esp32 2.x, así que la rama
`ESP_ARDUINO_VERSION_MAJOR >= 3` de `pwmAttachCompat` (`:261-268`) es código no compilado.
Inocuo y con valor a futuro, pero conviene saber que no está probado.

### ⚪ F27 — Un archivo de 2840 líneas con nueve responsabilidades

Capa de motor, encoders PCNT, filtro de Kalman, seis controladores, servidor HTTP,
WebSocket, OTA, gestión WiFi/NVS, SPIFFS y CLI serie, todo en `esp32_qube.ino`.

---

## Plan de mejora y limpieza

Ordenado para que cada fase deje el sistema en un estado usable en banco. Las fases 0–1
tocan comportamiento y requieren validación con hardware; 2–4 son a comportamiento
constante y se pueden hacer sin el equipo.

### Fase 0 — Red de seguridad (sin tocar el firmware)

Objetivo: poder refactorizar sin miedo. Ninguna de estas tareas cambia el binario.

| # | Tarea | Resuelve |
|---|---|---|
| 0.1 | Agregar job `pio run -e esp32dev` al CI | F20 |
| 0.2 | Crear `credentials.h.example` y referenciarlo en el README | F23 |
| 0.3 | Acotar `check_flags` a un set que pase (`readability-*,bugprone-*` sin `-warnings-as-errors=*`) | F21 |
| 0.4 | Commitear el trabajo pendiente del revert L298N como baseline etiquetado | — |
| 0.5 | Capturar una corrida de referencia por modo (`capture.py`) como oráculo de regresión | — |

0.5 es el que más rinde: sin trazas de referencia, cualquier refactor del lazo se valida
"a ojo".

### Fase 1 — Corrección (requiere banco)

Un ítem por sesión, verificando en hardware antes de pasar al siguiente.

**1.1 — Restituir la velocidad del péndulo en el modo 5 (F1).** El de mayor impacto.
Propuesta: eliminar `swing_filteredVelAlpha`/`prevPosPend` y consumir `rl_vf_alVel`, que
ya se calcula, está validado contra el simulador y quita un tercer estimador del archivo.
Ojo: `rl_vf_*` sólo se actualiza en modos 6/7, así que hay que tickear
`updateRlObservation()` también en el modo 5 (a 50 Hz, no a 500).
Después: **re-caracterizar `ke_gain` desde cero** — hasta ahora nunca actuó — y revisar en
la tesis todo pasaje que describa el swing-up como control por energía.

**1.2 — Un único punto de salida por tick (F2, F3).** Reemplazar los diez `return;` del
despacho por un `pwmOut` y un `setMotor()` al cierre. Como mínimo, mover
`updateIna219()` y el watchdog de comandos **antes** del despacho de modos, lo que corta
el enganche de brownout aunque los `return` sigan.

**1.3 — Reconciliar la escalera de límites (F4).** Una sola tabla de constantes
(`SERVO_*_DEG`) que ordene 70/85/90/95, borrar las ramas inalcanzables de los modos 4 y 6,
y documentar la escalera efectiva en la cabecera. Si el modo 6 realmente necesita 110°,
la decisión es subir el guard global — no dejar dos números contradictorios.

**1.4 — Resetear el estado del modo 7 en `setMode` (F5).** Sacar `hybrid_lqr`,
`apexCatchMs`, `lockedBrakeDir` y `lastRlUs7` de `static` locales a globales agrupadas en
un `struct`, y limpiarlas en `setMode(7)` junto al resto.

**1.5 — Desbloquear la task async (F7).** Los cuatro handlers levantan un flag
(`pendingRestart`, `pendingFormat`, `pendingWifiReconnect`) que `loop()` atiende.

**1.6 — Cerrar los endpoints destructivos (F8).** `/format` y `/restart` a POST, token
compartido en `credentials.h` para `/format`, `/fs` y `/update`, y `ArduinoOTA.setPassword()`.

**1.7 — Instrumentar el lazo (F9).** `dt` medido en vez de nominal; clamp de atraso
(`if (nowUs - lastControlUs > 5·CONTROL_PERIOD_US) lastControlUs = nowUs;`); exponer en
`/state` el período máximo y el conteo de ticks perdidos desde el último reset.

**1.8 — Protección de calado independiente del INA219 (F6).** Portar el detector de
calado por encoder que ya existe y funciona en el homing (`:1074-1078`: sin avance con par
aplicado durante N ms) a un guard común a todos los modos. Es la única protección que no
depende de un sensor ausente.

### Fase 2 — Limpieza a comportamiento constante (sin banco)

Todo verificable con el build de CI de la fase 0 y las trazas de 0.5.

| # | Tarea | Resuelve |
|---|---|---|
| 2.1 | Borrar los 15 símbolos muertos; **decidir explícitamente** sobre `balance_threshold`: implementarlo o quitarlo de la API | F13 |
| 2.2 | Eliminar la rama `USE_ENA_PWM` y `brakeMotor()`; `setMotor()` → `setMotorDirect(pwm·factor)` | F12 |
| 2.3 | `abs` → `fabsf`, `fmod` → `fmodf`, `powf(x,2)` → `x*x` | F16, F17 |
| 2.4 | Renombrar las locales del modo 2 (`kp_eff`, `ki_eff`, `kd_eff`) y borrar el `::` | F15 |
| 2.5 | `getStateJson()` con `snprintf` sobre buffer estático | F18 |
| 2.6 | Borrar los dos `.bak` del directorio de fuentes | F24 |
| 2.7 | Regenerar cabecera, `printHelp()` y el comentario de `setMotor` contra el código real | F19 |

### Fase 3 — Estructura

**3.1 — Extraer `lqrControl(theta, alpha, velTheta, velAlpha, pwmClamp)`** y usarla desde
los modos 4 y 7 (F10). Elimina la divergencia que ya causó un bug de signo documentado.

**3.2 — Extraer `resetPendulumOffset()`** (F11) y un `struct` de estado por modo que
`setMode()` limpie de forma uniforme (cierra F5 de raíz).

**3.3 — Tabla única de parámetros del controlador** (F14): un `struct ControlParams` con
todos los umbrales y ganancias, y los literales de los lazos reemplazados por sus campos.
Beneficio directo para la tesis: `/state` puede exportar la tabla completa, de modo que
**cada traza capturada queda autodescrita** con los parámetros exactos que la produjeron.

**3.4 — Dividir el `.ino`** (F27) en unidades con interfaz explícita:

```
esp32_qube/
  esp32_qube.ino     setup() / loop() / despacho
  config.h           pines, parámetros, escalera de límites
  motor.h/.cpp       setMotor, saturación, escalera de seguridad
  encoders.h/.cpp    PCNT, offsets, conversiones
  estimator.h/.cpp   filtros de velocidad + Kalman
  control.h/.cpp     PID, LQR, swing-up, homing, RL
  net.h/.cpp         WiFi, HTTP, WS, OTA, SPIFFS
  cli.h/.cpp         comandos serie
```

Se puede hacer incremental: cada archivo extraído es un commit verificado por el build de
CI. **No emprender 3.4 antes de terminar la fase 1** — mover código con bugs de lazo
adentro sólo hace más difícil aislarlos.

**3.5 — Consolidar las herramientas serie** (F25) en un módulo con una capa de protocolo
compartida y subcomandos (`capture`, `monitor`, `cmd`, `flash`).

### Fase 4 — Trazabilidad para la tesis

**4.1** — Generar la cabecera de comandos/endpoints y `printHelp()` desde una sola tabla,
para que no puedan volver a desincronizarse (F19).
**4.2** — Documentar en `docs/` la escalera de límites de seguridad efectiva y qué modo
tiene qué protección, con la tabla de F4/F6. Es material directo para el capítulo de
implementación.
**4.3** — Con 3.3 y 1.7 en su lugar, cada traza queda acompañada de sus parámetros y de la
evidencia de temporización del lazo — que es lo que permite defender el "500 Hz" con un
número medido en vez de una constante del código.

---

## Orden sugerido

```
0.1 0.2 0.3 0.4 0.5      ← sin hardware, habilita todo lo demás
1.1                      ← banco; corrige el swing-up y define qué se puede afirmar
1.2 1.3 1.4              ← banco; seguridad de operación
2.1 … 2.7                ← sin hardware, a comportamiento constante
1.5 1.6 1.7 1.8          ← banco; red y protecciones
3.1 3.2 3.3              ← sin hardware
3.4 3.5                  ← sin hardware, incremental
4.1 4.2 4.3              ← redacción
```

La fase 2 se intercala a propósito: es trabajo sin hardware que se puede adelantar
mientras se espera disponibilidad del banco, y deja el archivo mucho más legible antes de
entrar a 1.5–1.8.

## Riesgos de lo ya aplicado (leer antes de la próxima sesión de banco)

Todo lo aplicado compila y es coherente por lectura, pero **ninguna línea se probó
en el equipo**. Los tres puntos que pueden morder:

1. **El signo del bombeo del modo 5 es una conjetura fundada, no un dato.** Se
   eligió `swing_vel_sign = +1` porque `rl_vf_alVel` tiene la misma convención de
   signo que el LQR del modo 4, que sí está validado en este hardware. Si al
   probar el swing-up el péndulo se queda abajo con PWM alto (el bombeo frena en
   vez de excitar), invertir en caliente con `L12 -1` por serie y anotar cuál
   quedó. **Primera prueba con el brazo despejado y la mano en el corte.**
2. **La rama de bombeo resonante se ejecuta por primera vez.** Con ella entran en
   juego `ke_gain`, `KE_GAIN_BASE/BOOST` y el detector de calado, ninguno de los
   cuales actuó jamás. Los valores actuales no son un punto de partida
   caracterizado: son los que quedaron escritos.
3. **La reordenación del failsafe cambia el instante de la telemetría.** Ahora
   `/state` y el broadcast WS reportan el estado *antes* del cálculo de este tick
   en vez de después. A 10 Hz de telemetría contra 500 Hz de control el desfase es
   de menos de un tick, pero si alguna herramienta de captura correlaciona PWM con
   ángulo muestra a muestra, conviene saberlo.

Aparte: `experiments/2026-06-08_swing/sweep_bt.py` barrió `bt` (que no hacía nada)
con `ke=0.70` (que tampoco). Esa campaña no mide lo que dice medir.

## Lo que esta auditoría no cubre

- **Ejecución en hardware.** Todos los hallazgos son estáticos. F1–F5 predicen
  comportamiento observable y deberían confirmarse en banco antes de citarse en la tesis.
- **Corrección numérica del filtro de Kalman.** `kf_enabled` es `false` por defecto y el
  KF recibe `alpha_raw` (0 = colgando) mientras el LQR opera sobre `alpha` (0 = vertical);
  la linealización de `:415` asume el equilibrio invertido. Hay una discrepancia de marco
  ahí que amerita revisión propia, pero como la función está desactivada no la traté como
  hallazgo de operación.
- **`policy_weights.h`** y la cadena de exportación desde SB3.
- **La GUI** (`data/index.html`, 39 KB).
- **El código Python** de `qube_rl/` y `qube_analysis/`.
