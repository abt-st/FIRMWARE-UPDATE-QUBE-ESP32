# CHANGELOG — Firmware QUBE Servo ESP32 + L298N

Registro de cambios del firmware `esp32_qube_l298n.ino` para la modernización de la plataforma QUBE Servo en el marco de la tesis.

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
| Encoder A | GPIO34 | Vía level shifter 5V→3.3V, pull-up 4.7 kΩ en HV |
| Encoder B | GPIO35 | Vía level shifter 5V→3.3V, pull-up 4.7 kΩ en HV |
| INA219 SDA | GPIO21 | I2C |
| INA219 SCL | GPIO22 | I2C |
| ENA L298N | Jumper | Sin cable al ESP32 |

## Motor de referencia

**Premotec 990412016913** — Motor DC con encoder, 18 V nominal, operado a 12 V con L298N.  
Dos conectores de 5 pines (encoder motor + encoder péndulo): VCC, A, GND, B, Index.  
Cable trenzado de 2 pines: M+ / M− (terminales del motor, conectados a OUT1/OUT2 del L298N).
