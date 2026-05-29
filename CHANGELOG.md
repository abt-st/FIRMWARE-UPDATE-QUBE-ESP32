# CHANGELOG — QUBE ESP32 (Firmware + Documentación)

Registro de cambios del firmware `esp32_qube_l298n.ino` y documentación del proyecto para la modernización de la plataforma QUBE Servo en el marco de la tesis.

---

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
- **Ganancias PID ajustadas** para motor Premotec 990412016913 (18 V nominal, operado a 12 V):
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

**Premotec 990412016913** — Motor DC con encoder, 18 V nominal, operado a 12 V con L298N.  
Dos conectores de 5 pines (encoder motor + encoder péndulo): VCC, A, GND, B, Index.  
Cable trenzado de 2 pines: M+ / M− (terminales del motor, conectados a OUT1/OUT2 del L298N).
