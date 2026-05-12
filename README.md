> Plataforma de control educativo de péndulo rotatorio invertido basada en **ESP32 + L298N + INA219 + LM2596**, con encoders duales (servo + péndulo), telemetría de potencia en tiempo real y conectividad WiFi/BLE nativa. Alternativa open-source al Quanser QUBE Servo por ~$70 USD frente a los $2,500–$3,500 USD del original.

---

## Tabla de Contenidos

- [Motivación](#motivación)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Hardware Requerido](#hardware-requerido)
- [Pinout y Conexiones](#pinout-y-conexiones)
- [Encoders Duales](#encoders-duales)
- [Acondicionamiento de Señal](#acondicionamiento-de-señal)
- [Telemetría de Potencia (INA219)](#telemetría-de-potencia-ina219)
- [Control PID en Lazo Cerrado](#control-pid-en-lazo-cerrado)
- [Firmware](#firmware)
- [Instalación](#instalación)
- [Calibración](#calibración)
- [Resultados y Validación](#resultados-y-validación)
- [Problemas Conocidos y Soluciones](#problemas-conocidos-y-soluciones)
- [Roadmap](#roadmap)
- [Referencias](#referencias)
- [Licencia](#licencia)

---

## Motivación

El **Quanser QUBE Servo** es una plataforma educativa de referencia para laboratorios de control moderno (LQR, PID, control en espacio de estado). Su principal limitación es el costo: entre **$2,500 y $3,500 USD**, lo que lo hace inaccesible para la mayoría de instituciones de educación media y superior en Latinoamérica.

Este proyecto propone una modernización completa del sistema usando componentes de bajo costo disponibles globalmente, manteniendo:

- Control en lazo cerrado con realimentación de posición angular
- Telemetría de voltaje, corriente y potencia en tiempo real
- Conectividad inalámbrica (WiFi + BLE) para monitoreo remoto
- **Encoders duales**: uno en el eje del servo (posición del motor) y uno en el eje del péndulo (posición del brazo rotatorio)
- Compatibilidad con Arduino IDE y librerías estándar

El resultado es una plataforma funcional por **$40–$70 USD** (sin batería), documentada completamente y publicada como open-source para la comunidad educativa.

---

## Arquitectura del Sistema

```
┌──────────────────────────────────────────────────────────────────────┐
│  FUENTE 12V (batería LiPo 3S o PSU de laboratorio)                   │
│                                                                      │
│  (+12V) ──┬── VIN+ ──[INA219]── VIN- ──── L298N VS                   │
│           │                                   │                      │
│         [LM2596]                         OUT1─┤                      │
│           │                              OUT2─┤── Motor DC           │
│         (+5V) ──── ESP32 VIN             IN1 ─┤── GPIO26             │
│                         │                IN2 ─┤── GPIO27             │
│                    [3.3V int]            ENA ─┤── Jumper ON          │
│                         │                                            │
│               GPIO21 ───┤── INA219 SDA                               │
│               GPIO22 ───┤── INA219 SCL                               │
│               GPIO34 ───┤──[100Ω]──[4.7kΩ↑3.3V]── Encoder Servo A    │
│               GPIO35 ───┤──[100Ω]──[4.7kΩ↑3.3V]── Encoder Servo B    │
│               GPIO32 ───┤──[100Ω]──[4.7kΩ↑3.3V]── Encoder Péndulo A  │
│               GPIO33 ───┤──[100Ω]──[4.7kΩ↑3.3V]── Encoder Péndulo B  │
│                                                                      │
│  GND ──── L298N GND ──── ESP32 GND ──── INA219 GND                   │
└──────────────────────────────────────────────────────────────────────┘
```

### Flujo de datos

```
Encoder Servo  ──┐
                 ├──► ESP32 (FreeRTOS)
Encoder Péndulo ─┘        │
                           ├── PID loop (200 Hz)
INA219 (I2C) ─────────────┤
                           ├── Telemetría JSON (Serial / WebSocket)
L298N (PWM) ◄─────────────┘
```

---

## Hardware Requerido

| Componente | Especificación | Cantidad | Precio aprox. |
|---|---|---|---|
| **ESP32-WROOM-32** | Dual-core 240MHz, WiFi+BLE | 1 | $6–10 USD |
| **L298N** | Dual H-bridge, 2A/canal, 5–35V | 1 | $1.50–3 USD |
| **INA219** | Monitor I2C, 0–26V, ±3.2A | 1 | $2–4 USD |
| **LM2596** | Buck converter ajustable, 3A | 1 | $1–3 USD |
| **Motor DC + reductor** | 12V, 25W, 100–300 RPM | 1 | $15–30 USD |
| **Encoder servo** | Incremental, open-drain, ≥200 CPR | 1 | Incluido en motor |
| **Encoder péndulo** | Incremental, open-drain, ≥200 CPR | 1 | $5–15 USD |
| **Resistores 4.7 kΩ** | Pull-up para encoders (×4) | 4 | < $0.10 USD |
| **Resistores 100 Ω** | Filtro RC encoders (×4) | 4 | < $0.10 USD |
| **Capacitores 10 nF** | Filtro RC encoders (×4) | 4 | < $0.10 USD |
| **Capacitor 100 µF** | Filtro salida LM2596 | 1 | < $0.20 USD |
| **Fuente 12V** | LiPo 3S o PSU laboratorio | 1 | Variable |

**Costo total estimado (sin fuente):** $35–70 USD  
**Comparación:** Quanser QUBE Servo = $2,500–$3,500 USD

---

## Pinout y Conexiones

### Tabla completa pin por pin (común a ambos modos)

| Subsistema | Origen | Destino | Notas |
|---|---|---|---|
| Potencia motor | Fuente 12V (+) | L298N VS | Alimentación del puente H |
| Potencia motor | GND fuente | L298N GND | GND común obligatorio |
| Lógica L298N | LM2596 5V | L298N 5V | Según jumper del módulo |
| Motor DC | L298N OUT1 | Motor terminal (+) | Salida de potencia |
| Motor DC | L298N OUT2 | Motor terminal (−) | Salida de potencia |
| Control motor | ESP32 GPIO26 | L298N IN1 | Señal de control canal A |
| Control motor | ESP32 GPIO27 | L298N IN2 | Señal de control canal A |
| Control motor | ENB (canal B) | L298N ENB | Segundo enable del módulo; no usado en configuración de un motor |
| Encoder servo | Pin A | 4.7 kΩ pull-up a 3.3V → GPIO34 | Open-drain |
| Encoder servo | Pin B | 4.7 kΩ pull-up a 3.3V → GPIO35 | Open-drain |
| Encoder servo | GND | GND común | Referencia compartida |
| Encoder servo | +5V | Alimentación encoder | Cable del conector original |
| Encoder péndulo | Pin A | 4.7 kΩ pull-up a 3.3V → GPIO32 | Open-drain |
| Encoder péndulo | Pin B | 4.7 kΩ pull-up a 3.3V → GPIO33 | Open-drain |
| Encoder péndulo | GND | GND común | Referencia compartida |
| Encoder péndulo | +5V | Alimentación encoder | Fuente auxiliar 5V |
| INA219 | ESP32 GPIO21 | INA219 SDA | I2C datos |
| INA219 | ESP32 GPIO22 | INA219 SCL | I2C reloj |
| INA219 | ESP32 3V3 | INA219 VCC | No conectar a 5V |
| INA219 | GND común | INA219 GND | Referencia común |
| INA219 | (+) batería / LM2596 IN | INA219 VIN+ | Antes del L298N |
| INA219 | L298N VS (pin 8) | INA219 VIN− | Después del shunt |
| Debug serial | USB ESP32 | PC / monitor serie | UART0 por USB |

### Cableado de ENA (elige una sola opción)

| Opción | Qué hacer con jumper ENA | Conexión ENA (pin señal) | Cuándo usar |
|---|---|---|---|
| A (recomendada, simple) | Dejar puesto | No conectar al ESP32 | Si controlas el motor por IN1/IN2 |
| B (alternativa) | Retirar jumper | ESP32 GPIO25 → ENA (señal) | Si quieres PWM directo por ENA |

> **Importante:** El bloque ENA tiene 2 pines físicos: ENA (señal) y +5V. Con jumper puesto quedan puenteados. Si retiras el jumper, conecta GPIO25 solo al pin ENA (señal), nunca al pin +5V.

### Configuración de pines ESP32

```
Pin     │ Función              │ Tipo         │ Notas
────────┼──────────────────────┼──────────────┼───────────────────────
GPIO21  │ I2C SDA              │ Bidireccional │ Pull-up interno
GPIO22  │ I2C SCL              │ Salida       │ Pull-up interno
GPIO25  │ L298N ENA (PWM)      │ Salida       │ Solo en opción B (jumper ENA retirado)
NC      │ L298N ENB            │ N/A          │ Segundo canal del L298N, no usado en este montaje
GPIO26  │ L298N IN1            │ Salida       │ Control canal A
GPIO27  │ L298N IN2            │ Salida       │ Control canal A
GPIO32  │ Encoder péndulo A    │ Entrada      │ Pull-up externo 4.7kΩ
GPIO33  │ Encoder péndulo B    │ Entrada      │ Pull-up externo 4.7kΩ
GPIO34  │ Encoder servo A      │ Entrada      │ Pull-up externo 4.7kΩ (input-only)
GPIO35  │ Encoder servo B      │ Entrada      │ Pull-up externo 4.7kΩ (input-only)
```

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.
> **Nota ENA/ENB:** El L298N tiene dos pines enable: ENA (canal A, OUT1/OUT2) y ENB (canal B, OUT3/OUT4).

---

## Encoders Duales

Este proyecto implementa realimentación de posición angular mediante **dos encoders incrementales independientes**:

### Encoder 1 — Eje del Servo (Motor DC)

Mide la posición y velocidad angular del eje del motor después del reductor. Permite al controlador PID conocer en todo momento dónde se encuentra el actuador.

- **GPIO:** 34 (canal A), 35 (canal B)
- **Resolución típica:** 200–2048 CPR (counts per revolution)
- **Decodificación:** Cuadratura X4 por interrupciones hardware
- **Salida:** posición en grados (`pos_servo`), velocidad en rad/s (`vel_servo`)

### Encoder 2 — Eje del Péndulo (Brazo Rotatorio)

Mide la posición angular del brazo del péndulo respecto a la vertical. Es la variable de estado principal para control de péndulo invertido.

- **GPIO:** 32 (canal A), 33 (canal B)
- **Resolución típica:** 200–2048 CPR
- **Decodificación:** Cuadratura X4 por interrupciones hardware
- **Salida:** posición en grados (`pos_pendulo`), velocidad en rad/s (`vel_pendulo`)
- **Referencia:** 0° = posición inferior (colgando), ±180° = posición superior (invertido)

### Decodificación cuadratura X4

```cpp
// Tabla de decodificación cuadratura (QUAD_LUT)
// Estado anterior [A_prev, B_prev] + Estado actual [A, B]
// Resultado: +1 (avance), -1 (retroceso), 0 (sin cambio / error)

const int8_t QUAD_LUT[16] = {
    0, -1, +1,  0,
   +1,  0,  0, -1,
   -1,  0,  0, +1,
    0, +1, -1,  0
};
```

### Variables de estado exportadas (JSON)

```json
{
  "t":       1234567,
  "pos_s":   45.2,
  "vel_s":   3.14,
  "cnt_s":   2048,
  "pos_p":   -12.5,
  "vel_p":   0.78,
  "cnt_p":   -128,
  "pwm":     180,
  "v_bus":   11.8,
  "i_ma":    450.2,
  "p_mw":    5312.4,
  "mode":    2
}
```

---

## Acondicionamiento de Señal

### Problema: encoders open-drain

Los encoders de tipo incremental (y específicamente el Premotec 990412016913 usado en el QUBE Servo original) tienen salida **open-drain (NPN)**:

- Estado bajo (activo): transistor interno conduce → 0 V en la línea
- Estado alto (inactivo): transistor corta → línea flota (Hi-Z)

Sin pull-up externo, la línea queda en tensión indeterminada (~1.5 V con capacitancia parasita), lo que impide al ESP32 discriminar entre "0" y "1".

### Soluciones evaluadas

| Topología | Tensión estado alto | Resultado |
|---|---|---|
| Level shifter 5V→3.3V (7 MΩ) | ~1.5 V (indeterminado) | ❌ RC demasiado lento |
| Divisor 4.7kΩ / 8.2kΩ | 15–40 mV (open-drain Hi-Z) | ❌ Confirma open-drain |
| **Pull-up 4.7 kΩ a 3.3 V** | **3.3 V (limpio)** | **✅ Implementado** |

### Esquema de acondicionamiento final (por canal, ×4)

```
ESP32 3V3
    │
  [4.7kΩ]  ← pull-up externo
    │
    ├──── Encoder canal (open-drain)
    │          │
  [100Ω]       └── conduce a GND en estado bajo; Hi-Z en alto
    │
    ├──── GPIOxx (ESP32 INPUT)
    │
  [10nF]   ← filtro RC (fc ≈ 159 kHz)
    │
   GND
```

**Frecuencia de corte del filtro:**

$$f_c = \frac{1}{2\pi \cdot 100\,\Omega \cdot 10\,\text{nF}} \approx 159\,\text{kHz}$$

Esta frecuencia es suficientemente alta para no degradar señales de encoder a velocidades normales de operación (< 10 kHz), y suficientemente baja para eliminar glitches de RF y switching del L298N (~40 kHz).

---

## Telemetría de Potencia (INA219)

El INA219 se conecta en serie con la línea de alimentación del L298N para medir en tiempo real:

- **Voltaje de bus** (`v_bus`): tensión de la batería / fuente (0–26 V)
- **Corriente** (`i_ma`): corriente consumida por el motor (±3200 mA)
- **Potencia** (`p_mw`): potencia instantánea calculada por el chip

### Posición en el circuito

```
Batería (+) ──── VIN+ ──[shunt INA219]── VIN- ──── L298N VS
Batería (−) ──────────────────────────────────────── GND común
```

### Configuración I2C

```cpp
#include <Wire.h>
#include <Adafruit_INA219.h>

Adafruit_INA219 ina219(0x40);  // A0=GND, A1=GND → 0x40

void setup() {
    Wire.begin(21, 22);   // SDA=GPIO21, SCL=GPIO22
    ina219.begin();
    ina219.setCalibration_32V_2A();  // Rango máximo: 32V, 2A
}
```

### Usos del dato de potencia

- Detección de sobrecarga del motor (protección térmica por software)
- Estimación de eficiencia del sistema (potencia mecánica vs eléctrica)
- Logging para identificación de parámetros del motor (Km, Kb)
- Correlación PID: `error` vs `potencia consumida`

---

## Control PID en Lazo Cerrado

### Modos de operación

| Modo | Código | Descripción |
|---|---|---|
| Libre | `m0` | Motor deshabilitado, encoders activos |
| Velocidad constante | `m1` | PWM fijo, sin lazo |
| PID posición servo | `m2` | Setpoint en grados, lazo cerrado servo |
| PID posición péndulo | `m3` | Setpoint en grados, lazo cerrado péndulo |
| LQR (péndulo invertido) | `m4` | Control en espacio de estados (futuro) |

### Implementación PID (modo m2 / m3)

```cpp
float pid_compute(float setpoint, float measured, float dt) {
    float error = setpoint - measured;

    integral += error * dt;
    integral = constrain(integral, -INTEGRAL_MAX, INTEGRAL_MAX);  // anti-windup

    float derivative = (error - prev_error) / dt;
    derivative = alpha * derivative + (1.0f - alpha) * prev_derivative;  // EMA filter

    prev_error = error;
    prev_derivative = derivative;

    return Kp * error + Ki * integral + Kd * derivative;
}
```

### Parámetros por defecto (punto de partida)

| Parámetro | Servo | Péndulo |
|---|---|---|
| `Kp` | 2.0 | 5.0 |
| `Ki` | 0.1 | 0.05 |
| `Kd` | 0.05 | 0.2 |
| `alpha` (EMA Kd) | 0.12 | 0.10 |
| Frecuencia loop | 200 Hz | 200 Hz |

> Los parámetros deben sintonizarse experimentalmente para cada instalación física. Ver sección [Calibración](#calibración).

---

## Firmware

### Estructura del proyecto

```
firmware/
├── main/
│   ├── main.cpp              ← Punto de entrada, tasks FreeRTOS
│   ├── encoder.cpp / .h      ← ISR cuadratura X4, ambos encoders
│   ├── motor.cpp / .h        ← PWM L298N, dirección, frenado
│   ├── pid.cpp / .h          ← Controlador PID con anti-windup + EMA
│   ├── ina219.cpp / .h       ← Lectura I2C, calibración, filtrado
│   ├── telemetry.cpp / .h    ← JSON serializer, Serial + WebSocket
│   └── config.h              ← Pines, constantes, ganancias default
├── platformio.ini            ← Configuración PlatformIO
└── README.md
```

### Tasks FreeRTOS

| Task | Core | Prioridad | Período | Función |
|---|---|---|---|---|
| `task_control` | Core 1 | 5 | 5 ms (200 Hz) | Leer encoders, PID, escribir PWM |
| `task_ina219` | Core 0 | 3 | 10 ms (100 Hz) | Leer INA219, filtrar, actualizar estado |
| `task_telemetry` | Core 0 | 2 | 50 ms (20 Hz) | Serializar estado a JSON, enviar |
| `task_wifi` | Core 0 | 1 | Event-driven | WebSocket server, comandos |

### Comandos por Serial / WebSocket

```json
// Cambiar modo
{"cmd": "mode", "val": 2}

// Cambiar setpoint (grados)
{"cmd": "sp_servo", "val": 45.0}
{"cmd": "sp_pendulo", "val": 0.0}

// Cambiar ganancias PID
{"cmd": "pid", "kp": 2.5, "ki": 0.1, "kd": 0.08}

// Solicitar estado
{"cmd": "status"}

// Reset encoders
{"cmd": "enc_reset"}
```

---

## Instalación

### Requisitos

- [PlatformIO](https://platformio.org/) (recomendado) o Arduino IDE ≥ 2.0
- Board: `esp32dev` (ESP32-WROOM-32)
- Librerías:
  - `Adafruit INA219` (≥ 1.2.0)
  - `ArduinoJson` (≥ 7.0)
  - `AsyncTCP` + `ESPAsyncWebServer` (para WebSocket, opcional)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/<usuario>/qube-esp32.git
cd qube-esp32

# 2. Instalar dependencias (PlatformIO)
pio pkg install

# 3. Compilar y flashear
pio run --target upload

# 4. Abrir monitor serie (115200 baud)
pio device monitor --baud 115200
```

### Ajuste del LM2596 antes de conectar el ESP32

1. Conectar el LM2596 a la fuente de 12V **sin ninguna carga**.
2. Medir con multímetro entre `OUT+` y `OUT−`.
3. Girar el potenciómetro hasta leer exactamente **5.00 V**.
4. Conectar el ESP32 (pin `VIN`).

> ⚠️ Nunca aplicar más de 5.5 V al pin `VIN` del ESP32-WROOM-32, ni alimentar el pin `3V3` desde una fuente externa.

---

## Calibración

### 1. Verificación de encoders

Al arrancar en modo `m0` (libre), el terminal serie debe mostrar:

```
[ENC] Servo   CNT=0   POS=0.00°
[ENC] Pendulo CNT=0   POS=0.00°
```

Girar manualmente cada eje y verificar que `CNT` incremente/decremente con la dirección esperada.

### 2. Dirección del motor

Si al aplicar PWM positivo el encoder servo retrocede (feedback positivo), corregir con:

```cpp
// config.h
#define MOTOR_DIR  (-1)   // +1 o -1
```

O bien invertir físicamente los cables `OUT1`/`OUT2` del L298N.

### 3. CPR (Counts Per Revolution)

Medir el CPR real del encoder:

```bash
# Enviar comando para girar exactamente una vuelta lenta y leer CNT final
{"cmd": "calibrate_cpr"}
```

Actualizar en `config.h`:

```cpp
#define ENC_SERVO_CPR    2048   // Counts por revolución mecánica
#define ENC_PENDULO_CPR  1024
```

### 4. Sintonización PID (método Ziegler-Nichols)

1. Establecer `Ki = 0`, `Kd = 0`
2. Incrementar `Kp` hasta que el sistema oscile con amplitud constante → ese es `Ku` (ganancia última)
3. Medir el período de oscilación → `Tu`
4. Calcular ganancias clásicas:

$$K_p = 0.6 \cdot K_u \qquad K_i = \frac{2 K_p}{T_u} \qquad K_d = \frac{K_p \cdot T_u}{8}$$

5. Ajustar `alpha` del filtro EMA para suavizar `Kd` si hay ruido de cuantización.

---

## Resultados y Validación

### Comparativa de rendimiento

| Métrica | Arduino Uno + L298N | ESP32 + L298N (este proyecto) | Quanser QUBE |
|---|---|---|---|
| Frecuencia de control | ~100 Hz | **200 Hz** | 1000 Hz |
| Encoders simultáneos | 1 (limitado) | **2** | 2 |
| Telemetría de potencia | No | **Sí (INA219)** | Sí |
| Conectividad inalámbrica | No | **WiFi + BLE** | Ethernet |
| Costo | ~$35 USD | **~$70 USD** | ~$3,000 USD |
| Swing-up automático | No | En desarrollo | Sí |

### Validación experimental del encoder (post fix HW-FIX-1)

| Métrica | Antes (level shifter 7MΩ) | Después (pull-up 4.7kΩ) |
|---|---|---|
| `enc_a` | Ruido (~1.5V indeterminado) | Transiciones limpias 0V / 3.3V |
| `CNT` servo | ±0 cambio/min | +2048 counts/revolución |
| `POS` servo | 0.0° (fijo) | 0° → 360° → 0° continuo |
| Convergencia PID | No (sin feedback) | Sí (±2° en 2–3 s) |

---

## Problemas Conocidos y Soluciones

### HW-FIX-1: Encoder open-drain con level shifter de alta impedancia

**Síntoma:** `CNT` no actualiza aunque el eje gire.  
**Causa:** Level shifter genérico 5V→3.3V con ~7 MΩ de impedancia. La constante RC con capacitancia parasita (~50–100 pF) produce τ ≈ 350–700 µs, demasiado lento para transitorios de encoder.  
**Solución:** Eliminar el level shifter. Instalar pull-up 4.7 kΩ a 3.3V en cada canal. Ver esquema en [Acondicionamiento de Señal](#acondicionamiento-de-señal).

### HW-FIX-2: GPIO34/35 sin `INPUT_PULLUP`

**Síntoma:** Error de boot al llamar `pinMode(34, INPUT_PULLUP)`.  
**Causa:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32, sin pull-up interno.  
**Solución:** Usar siempre `pinMode(34, INPUT)` y proveer pull-ups externos.

### SW-FIX-1: Ruido de cuantización en término derivativo

**Síntoma:** Con `Kd` alto y muestreo a 200 Hz, el término derivativo oscila violentamente.  
**Causa:** ±1–2 counts de ruido en el encoder generan velocidades aparentes que dominan `Kd`.  
**Solución:** Filtro EMA sobre la velocidad estimada (`alpha ≈ 0.12`) antes de multiplicar por `Kd`.

### SW-FIX-2: Dirección del motor vs encoder

**Síntoma:** El lazo PID diverge inmediatamente.  
**Causa:** La conexión física OUT1/OUT2 → M+/M− produce retroalimentación positiva.  
**Solución:** Constante `MOTOR_DIR = -1` en `config.h`, o invertir cables M+/M−.

---

## Roadmap

- [x] Control PID posición servo (encoder 1)
- [x] Telemetría INA219 (V, I, P)
- [x] Fix acondicionamiento señal open-drain (HW-FIX-1)
- [ ] Integración encoder péndulo (encoder 2) — **en progreso**
- [ ] Control PID posición péndulo (modo m3)
- [ ] Control LQR péndulo invertido (modo m4)
- [ ] Swing-up automático (modo m5)
- [ ] Dashboard web en tiempo real (WebSocket)
- [ ] Logging en SPIFFS / tarjeta SD
- [ ] Identificación de parámetros del motor desde firmware
- [ ] Paper académico comparativo vs Quanser QUBE

---

## Referencias

### Proyectos de referencia

- [Esp32CameraRover2 — Ezward](https://github.com/Ezward/Esp32CameraRover2) — Framework de control closed-loop para ESP32 (46 stars)
- [Rotary-Inverted-Pendulum — ebrahimabdelghfar](https://github.com/ebrahimabdelghfar/Rotary-Inverted-Pendulum) — Validación académica con LQR + Arduino + L298N
- [arduino_pid_controlled_motor — wty-yy](https://github.com/wty-yy/arduino_pid_controlled_motor) — PID + encoder bien documentado
- [Adafruit_INA219](https://github.com/adafruit/Adafruit_INA219) — Librería oficial INA219

### Datasheets

- [L298 Dual Full-Bridge Driver — STMicroelectronics](https://www.st.com/resource/en/datasheet/l298.pdf)
- [LM2596 Step-Down Voltage Regulator — Texas Instruments](https://www.ti.com/product/LM2596)
- [INA219 Current/Power Monitor — Texas Instruments](https://www.ti.com/product/INA219)

### Papers académicos

- Akhtaruzzaman, M., & Shafie, A. A. (2010). Modeling and control of a rotary inverted pendulum using various methods. *IEEE ICMA 2010*. https://doi.org/10.1109/ICMA.2010.5589450
- STMicroelectronics. (2019). *Introduction to Integrated Rotary Inverted Pendulum* (v2).

---

## Licencia

MIT License — ver [LICENSE](LICENSE) para detalles.

---

*Última actualización: Mayo 8, 2026*
