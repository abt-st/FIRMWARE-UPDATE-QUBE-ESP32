> **QUBE ESP32** — Plataforma de control educativo de péndulo rotatorio invertido basada en **ESP32 + L298N + INA219 + LM2596**, con encoders duales, telemetría de potencia en tiempo real y conectividad WiFi/BLE. Alternativa open-source al Quanser QUBE Servo por **~$70 USD** frente a los $2,500–$3,500 USD del original.

---

## Tabla de Contenidos

1. [Motivación](#motivación)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Hardware Requerido](#hardware-requerido)
4. [Pinout y Conexiones](#pinout-y-conexiones)
5. [Sensores y Acondicionamiento de Señal](#sensores-y-acondicionamiento-de-señal)
   - [Encoders Duales](#encoders-duales)
   - [Acondicionamiento de Señal](#acondicionamiento-de-señal)
   - [Schmitt Trigger (CD40106BE)](#schmitt-trigger-cd40106be)
   - [Telemetría de Potencia (INA219)](#telemetría-de-potencia-ina219)
6. [Control PID en Lazo Cerrado](#control-pid-en-lazo-cerrado)
7. [Firmware](#firmware)
8. [Instructivo de Uso](#instructivo-de-uso)
9. [Calibración](#calibración)
10. [Resultados y Validación](#resultados-y-validación)
11. [Problemas Conocidos y Soluciones](#problemas-conocidos-y-soluciones)
12. [Roadmap](#roadmap)
13. [Referencias](#referencias)
14. [Licencia](#licencia)

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

### Diagrama de conexión general

```
                         ┌─────────────────────────────────────────────────┐
                         │              FUENTE DE ALIMENTACIÓN 12V          │
                         │          (LiPo 3S o PSU de laboratorio)          │
                         └──────────┬──────────────────────┬───────────────┘
                                    │ (+12V)                │ GND
                          ┌─────────┴─────────┐            │
                          │                   │            │
                          ▼                   │            │
                ┌─────────────────┐           │            │
                │   INA219 (I2C)  │           │            │
                │   Monitor de    │           │            │
                │   potencia      │           │            │
                │                 │           │            │
                │  VIN+ ◄────────┘           │            │
                │  VIN- ─────────────────┐   │            │
                │  GND ──────────────────┼───┼────────────┤
                │  SDA ──────────┐       │   │            │
                │  SCL ─────┐    │       │   │            │
                │  VCC      │    │       │   │            │
                │  (3.3V)   │    │       │   │            │
                └───────────┼────┼───────┼───┼────────────┘
                            │    │       │   │
                   ┌────────┼────┼───────┼───┼────────────────────────┐
                   │  ESP32 │    │       │   │                        │
                   │        │    │       │   │                        │
                   │ GPIO21 ─┘    │       │   │  (SDA I2C)            │
                   │ GPIO22 ──────┘       │   │  (SCL I2C)            │
                   │                       │   │                       │
                   │              VIN ◄────┼───┤  (5V del LM2596)      │
                   │              GND ◄────┼───┤  (tierra común)       │
                   │                       │   │                       │
                   │ GPIO26 ───────────────┼───┼──► L298N IN1          │
                   │ GPIO27 ───────────────┼───┼──► L298N IN2          │
                   │                       │   │                       │
                   │ GPIO34 ──[100Ω]──+────┼───┼── Encoder Servo A     │
                   │                  [4.7kΩ]↑3.3V                     │
                   │ GPIO35 ──[100Ω]──+    │   │  Encoder Servo B      │
                   │                  [4.7kΩ]↑3.3V                     │
                   │ GPIO32 ──[100Ω]──+    │   │  Encoder Péndulo A    │
                   │                  [4.7kΩ]↑3.3V                     │
                   │ GPIO33 ──[100Ω]──+    │   │  Encoder Péndulo B    │
                   │                  [4.7kΩ]↑3.3V                     │
                   └───────────────────────┼───┼────────────────────────┘
                                           │   │
                          ┌────────────────┼───┼──────────────────┐
                          │  L298N (Puente H) │                   │
                          │                │   │                  │
                          │  IN1 ◄─────────┘   │  (desde GPIO26)  │
                          │  IN2 ◄─────────────┘  (desde GPIO27)  │
                          │  VS  ◄──────────────── VIN- del INA219│
                          │                                   │    │
                          │  OUT1 ────────────────────────────┼──┐ │
                          │  OUT2 ─────────────────────────────┘│ │
                          │  GND ◄──────────────────────────────┼─┤
                          └─────────────────────────────────────┘ │
                                                                  │
                                                    ┌─────────────┘
                                                    │  Motor DC
                                                    │  (con encoder
                                                    │   integrado)
                                                    ▼
```

### Conexión detallada del INA219

El INA219 se conecta **en serie** entre la fuente de alimentación y el L298N para medir la corriente que consume el motor:

```
    FUENTE 12V (+)          INA219                  L298N
    ───────────────     ───────────────          ─────────────
                        │           │
        (+12V) ─────────┤ VIN+      │
                        │  (shunt)  │            VS (pin 4)
        (mide corriente │ VIN- ─────┼────────────┤
         y voltaje)     │           │
                        │  GND ─────┼──────┬─────┤ GND (tierra común)
                        │  VCC ─────┼──┐   │     │
                        │  SDA ─────┼──┤   │     │ OUT1 ──► Motor (+)
                        │  SCL ─────┼──┤   │     │ OUT2 ──► Motor (−)
                        └───────────┘  │   │     │
                                       │   │     │ IN1 ◄── GPIO26 (ESP32)
    ESP32                              │   │     │ IN2 ◄── GPIO27 (ESP32)
    ─────────────                      │   │     │
    3V3 ───────────────────────────────┘   │
    GND ───────────────────────────────────┘
    GPIO21 (SDA) ──────────────────────────┘──► INA219 SDA
    GPIO22 (SCL) ─────────────────────────────► INA219 SCL
```

**Claves de conexión:**
- **VIN+/VIN−**: El INA219 va en **serie** con la línea +12V. La corriente del motor pasa por el shunt interno.
- **GND compartido**: Todos los módulos comparten la misma tierra.
- **I2C (SDA/SCL)**: Comunicación digital con el ESP32.
- **VCC**: Alimentado con **3.3V** del ESP32 (no conectar a 5V).

### Flujo de datos

```
                          ESP32 (FreeRTOS)
                         ┌──────────────────┐
Encoder Servo ──────────►│                  │
(GPIO34/35)              │  task_control    │──► L298N (PWM → Motor)
                         │  200 Hz          │
Encoder Péndulo ────────►│                  │
(GPIO32/33)              └────────┬─────────┘
                                  │
                    INA219 (I2C)───┤──► task_ina219 (100 Hz)
                    (GPIO21/22)    │
                                  │
                                  ├──► task_telemetry (10 Hz)
                                  │         │
                                  │         ├──► Serial (USB → PC)
                                  │         └──► WebSocket (WiFi)
                                  │
                                  └──► task_wifi (event-driven)
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
| **CD40106BE** | Hex Schmitt Trigger Inverter, DIP-14 | 1 | ~$0.50 USD |
| **Resistores 4.7 kΩ** | Pull-up para encoders (×4) | 4 | < $0.10 USD |
| **Resistores 100 Ω** | Filtro RC encoders (×4) | 4 | < $0.10 USD |
| **Capacitores 10 nF** | Filtro RC encoders (×4) | 4 | < $0.10 USD |
| **Capacitores 100 nF** | Bypass Schmitt (×1) | 1 | < $0.05 USD |
| **Capacitor 100 µF** | Filtro salida LM2596 | 1 | < $0.20 USD |
| **Fuente 12V** | LiPo 3S o PSU laboratorio | 1 | Variable |

**Costo total estimado (sin fuente):** $35–70 USD  
**Comparación:** Quanser QUBE Servo = $2,500–$3,500 USD

---

## Pinout y Conexiones

### Tabla completa pin por pin

| Subsistema | Origen | Destino | Notas |
|---|---|---|---|
| Potencia motor | Fuente 12V (+) | L298N VS | Alimentación del puente H |
| Potencia motor | GND fuente | L298N GND | GND común obligatorio |
| Lógica L298N | LM2596 5V | L298N 5V | Según jumper del módulo |
| Motor DC | L298N OUT1 | Motor terminal (+) | Salida de potencia |
| Motor DC | L298N OUT2 | Motor terminal (−) | Salida de potencia |
| Control motor | ESP32 GPIO26 | L298N IN1 | Señal de control canal A |
| Control motor | ESP32 GPIO27 | L298N IN2 | Señal de control canal A |
| Control motor | ENB (canal B) | L298N ENB | No usado en configuración de un motor |
| Encoder servo | Pin A | 4.7 kΩ pull-up a 3.3V → GPIO34 | Open-drain |
| Encoder servo | Pin B | 4.7 kΩ pull-up a 3.3V → GPIO35 | Open-drain |
| Encoder servo | GND / +5V | GND común / Alimentación | Referencia compartida |
| Encoder péndulo | Pin A | 4.7 kΩ pull-up a 3.3V → GPIO32 | Open-drain |
| Encoder péndulo | Pin B | 4.7 kΩ pull-up a 3.3V → GPIO33 | Open-drain |
| Encoder péndulo | GND / +5V | GND común / Fuente auxiliar 5V | Referencia compartida |
| INA219 | ESP32 GPIO21 | INA219 SDA | I2C datos |
| INA219 | ESP32 GPIO22 | INA219 SCL | I2C reloj |
| INA219 | ESP32 3V3 | INA219 VCC | No conectar a 5V |
| INA219 | GND común | INA219 GND | Referencia común |
| INA219 | (+) batería / LM2596 IN | INA219 VIN+ | Antes del L298N |
| INA219 | L298N VS (pin 8) | INA219 VIN− | Después del shunt |
| Debug serial | USB ESP32 | PC / monitor serie | UART0 por USB |

### Cableado de ENA

| Opción | Jumper ENA | Conexión ENA | Cuándo usar |
|---|---|---|---|
| **A (recomendada)** | Dejar puesto | No conectar al ESP32 | Control por IN1/IN2 |
| B (alternativa) | Retirar | ESP32 GPIO25 → ENA (señal) | PWM directo por ENA |

> **Importante:** El bloque ENA tiene 2 pines físicos: ENA (señal) y +5V. Con jumper puesto quedan puenteados. Si retiras el jumper, conecta GPIO25 solo al pin ENA (señal), nunca al pin +5V.

### Configuración de pines ESP32

```
Pin     │ Función              │ Tipo         │ Notas
────────┼──────────────────────┼──────────────┼──────────────────────────
GPIO21  │ I2C SDA              │ Bidireccional│ Pull-up interno
GPIO22  │ I2C SCL              │ Salida       │ Pull-up interno
GPIO25  │ L298N ENA (PWM)      │ Salida       │ Solo opción B (jumper retirado)
GPIO26  │ L298N IN1            │ Salida       │ Control canal A
GPIO27  │ L298N IN2            │ Salida       │ Control canal A
GPIO32  │ Encoder péndulo A    │ Entrada      │ Pull-up externo 4.7kΩ
GPIO33  │ Encoder péndulo B    │ Entrada      │ Pull-up externo 4.7kΩ
GPIO34  │ Encoder servo A      │ Entrada      │ Pull-up externo 4.7kΩ (input-only)
GPIO35  │ Encoder servo B      │ Entrada      │ Pull-up externo 4.7kΩ (input-only)
```

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.

---

## Sensores y Acondicionamiento de Señal

### Encoders Duales

Este proyecto implementa realimentación de posición angular mediante **dos encoders incrementales independientes**:

#### Encoder 1 — Eje del Servo (Motor DC)

Mide la posición y velocidad angular del eje del motor después del reductor.

- **GPIO:** 34 (canal A), 35 (canal B)
- **Resolución típica:** 200–2048 CPR (counts per revolution)
- **Decodificación:** Cuadratura X4 por interrupciones hardware
- **Salida:** posición en grados (`pos_servo`), velocidad en rad/s (`vel_servo`)

#### Encoder 2 — Eje del Péndulo (Brazo Rotatorio)

Mide la posición angular del brazo del péndulo respecto a la vertical.

- **GPIO:** 32 (canal A), 33 (canal B)
- **Resolución típica:** 200–2048 CPR
- **Decodificación:** Cuadratura X4 por interrupciones hardware
- **Salida:** posición en grados (`pos_pendulo`), velocidad en rad/s (`vel_pendulo`)
- **Referencia:** 0° = posición inferior (colgando), ±180° = posición superior (invertido)

#### Decodificación cuadratura X4

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

#### Variables de estado exportadas (JSON `/state`)

```json
{
  "mode": 2,
  "count": 1024, "position_deg": 15.2, "setpoint_deg": 20.0, "error_deg": 4.8,
  "pend_count": -128, "pend_position_deg": -2.3, "pend_setpoint_deg": 0.0, "pend_error_deg": 2.3,
  "pwm": 45, "ina_ok": true, "v_bus": 11.8, "i_ma": 350.0, "p_mw": 4130.0
}
```

---

### Acondicionamiento de Señal

#### Problema: encoders open-drain

Los encoders (Premotec 990412016913) tienen salida **open-drain (NPN)**:

- **Estado bajo:** transistor conduce → 0 V
- **Estado alto:** transistor corta → línea flota (Hi-Z)

Sin pull-up, la línea queda en ~1.5V indeterminado.

#### Soluciones evaluadas

| Topología | Tensión estado alto | Resultado |
|---|---|---|
| Level shifter 5V→3.3V (7 MΩ) | ~1.5 V (indeterminado) | ❌ RC demasiado lento |
| Divisor 4.7kΩ / 8.2kΩ | 15–40 mV (Hi-Z) | ❌ Confirma open-drain |
| **Pull-up 4.7 kΩ a 3.3 V** | **3.3 V (limpio)** | **✅ Implementado** |

#### Esquema actual (por canal, ×2)

El circuito de acondicionamiento utiliza **doble inversión** con Schmitt Trigger CD40106BE. El encoder se conecta **directamente** a la entrada del inversor, sin componentes adicionales:

```
Encoder canal (~5V) ──────────┬── CD40106BE IN_A ──► OUT_A ──┐
                              │                               │
                              │              IN_B ──► OUT_B ──┼──► GPIOxx
                              │                      (recupera fase)
                             GND (referencia común)
```

**Señal del encoder (~5V)** → **Schmitt Trigger** (regenera señal limpia de ~3.3V) → **GPIO ESP32**

El Schmitt Trigger toma la señal directa del encoder (~5V) y genera un nivel lógico limpio de **~3.3V** en la salida (limitado por Vcc = 3.3V). La histéresis del Schmitt (~0.5V) elimina glitches y rebotes que causarían cuentas espurias en el encoder.

> ✅ Este circuito está **implementado y funcionando** en la protoboard actual para los canales del encoder servo (GPIO34/GPIO35).

---

### Schmitt Trigger (CD40106BE) — Implementado

> 📄 Ver investigación completa: [`docs/research/ai_research/CD40106BE_INVESTIGATION.md`](docs/research/ai_research/CD40106BE_INVESTIGATION.md)

> ✅ **Estado actual:** El circuito de acondicionamiento con CD40106BE **está implementado** en la protoboard para los canales del encoder servo (A y B). La salida del Schmitt trigger (pin 4 → GPIO34, pin 8 → GPIO35) produce un nivel lógico limpio de **~3.3V**, seguro para el ESP32.

El encoder se conecta directamente a la entrada del Schmitt trigger (5V), que regenera un nivel lógico limpio de **~3.3V** en la salida (limitado por Vcc = 3.3V).

#### ¿Por qué un Schmitt Trigger?

El filtro RC simple **no tiene histéresis**: cuando la señal cruza el umbral lentamente, el ruido genera **rebotes (glitches)** que causan cuentas espurias. El Schmitt Trigger resuelve esto con **dos umbrales de conmutación**:

| Parámetro | CD40106BE @ 5V | CD40106BE @ 3.3V | Efecto |
|---|---|---|---|
| Umbral alto (`VT+`) | ~2.9 V | ~2.3 V | Se activa cuando la señal **supera** este valor |
| Umbral bajo (`VT-`) | ~2.1 V | ~1.0 V | Se desactiva cuando la señal **baja** de este valor |
| **Histéresis (`ΔVT`)** | **~0.8 V** | **~0.5 V** | **Zona muerta que rechaza ruido** |
| Tiempo de propagación | ~60–120 ns | ~80–150 ns | Salida digital limpia y rápida |

#### Características del CD40106BE

| Propiedad | Valor |
|---|---|
| Tipo | Hex Schmitt Trigger Inverter (6 inversores) |
| Paquete | DIP-14 (CD40106BE), SOIC-14 (CD40106BM) |
| Alimentación | 3 V a 18 V (rango completo CMOS) |
| Corriente de salida | ~1.6 mA sink/source a 5V |
| Disipación | Muy baja (~µW en estático) |
| Costo | ~$0.50 USD |

**Pinout (DIP-14):**

```
         +--------+
  A_IN 1 |        | 14 Vcc (3–18V)
  A_OUT 2 |        | 13 F_IN
  B_IN 3 |        | 12 F_OUT
  B_OUT 4 |  40106 | 11 E_IN
  C_IN 5 |        | 10 E_OUT
  C_OUT 6 |        | 9  D_IN
   GND 7 |        | 8  D_OUT
         +--------+
```

#### Circuito de acondicionamiento

Como el CD40106BE es un **inversor**, se usa **doble inversión** (2 inversores en serie) para recuperar la polaridad original. El encoder se conecta directamente a la entrada del chip, sin resistencias adicionales:

```
                          CD40106BE
                     ┌──────────────────┐
Encoder A (~5V) ─────┤ pin 1  (IN_A)    │
                     │        (OUT_A) pin 2 ├──┐
                     │                  │  │  │
                     │        (IN_B) pin 3  │◄─┘
                     │        (OUT_B) pin 4 ├──► GPIO34
                     │                  │      (recupera fase)
                     │                  │
Encoder B (~5V) ─────┤ pin 5  (IN_C)    │
                     │        (OUT_C) pin 6 ├──┐
                     │                  │  │  │
                     │        (IN_D) pin 9  │◄─┘
                     │        (OUT_D) pin 8 ├──► GPIO35
                     │                  │      (recupera fase)
                     │                  │
         GND ────────┤ pin 7       pin 14├──── 3.3V (ESP32)
                     └──────────────────┘
                            │
                        100nF (bypass)
                            │
                           GND
```

**Alimentación:**

```
3.3V (ESP32) ──┬── CD40106BE pin 14 (Vcc)
               │
              100nF ── GND  (bypass, cerca del pin 14)
               │
              GND ──── CD40106BE pin 7
```

> **Importante:** Alimentar el CD40106BE a **3.3V** (desde el pin 3V3 del ESP32) para salida directa compatible con GPIO. La salida será **~3.3V** (limitada por Vcc), seguro para los GPIO del ESP32 (máximo tolerado: 3.6V). A 3.3V la histéresis es ~0.5 V, significativamente mejor que los 0 V sin Schmitt.

> **⚠️ Error común:** Si la salida del Schmitt entrega ~4–5V, significa que el pin 14 (Vcc) está conectado a 5V en lugar de 3.3V. Reconectar a 3V3 del ESP32.

> **Sobre el capacitor de bypass (100nF):** Conectar **entre pin 14 (Vcc) y pin 7 (GND)**, lo más cerca posible del chip. Cuando las compuertas del CD40106BE conmutan, dibujan picos de corriente del rail 3.3V. Sin el capacitor, estos transitorios (aunque breves, ~60–150 ns) generan glitches en el voltaje de alimentación que pueden afectar al ESP32, ya que ambos comparten el mismo rail. En protoboard a baja frecuencia de encoder (<10 kHz) su efecto es menor, pero sigue siendo buena práctica. En PCB Rev2.0 con los 6 inversores activos simultáneamente, el capacitor es **indispensable** para estabilizar la alimentación.

#### Uso de los 6 inversores

| Inversor | Pines | Uso | Estado |
|---|---|---|---|
| INV_A + INV_B | 1→2→3→4 | Encoder servo canal A (doble inversión → GPIO34) | Usado |
| INV_C + INV_D | 5→6→9→8 | Encoder servo canal B (doble inversión → GPIO35) | Usado |
| INV_E | 11→10 | Reservado — oscilador watchdog / botón de paro | Libre |
| INV_F | 13→12 | Reservado — debounce de botones / expansión | Libre |

#### Componentes adicionales

| Componente | Valor | Cantidad | Costo |
|---|---|---|---|
| CD40106BE | Hex Schmitt Trigger | 1 | ~$0.50 |
| Capacitor 100nF | Cerámico X7R (bypass Vcc) | 1 | ~$0.05 |
| **Total** | | | **~$0.55 USD** |

#### Comparativa

| Topología | Histéresis | Glitches | Velocidad max | Costo |
|---|---|---|---|---|
| Pull-up + RC (actual) | No | Posibles | ~10 kHz | ~$0.10 |
| **Pull-up + RC + CD40106BE** | **Sí (~0.5 V)** | **Eliminados** | **>100 kHz** | **~$0.55** |

#### Alternativas de IC

| IC | Tipo | Paquete | Canales | Voltaje | Nota |
|---|---|---|---|---|---|
| **CD40106BE** | Inversor hex Schmitt | DIP-14 | 6 | 3–18V | **Implementado** |
| SN74LVC1G17 | Buffer (no inversor) | SOT-23-5 | 1 | 1.65–5.5V | Alternativa SMD |
| SN74LVC1G14 | Inversor Schmitt | SOT-23-5 | 1 | 1.65–5.5V | Alternativa SMD |

> **Recomendación:** El CD40106BE es ideal para una **PCB dedicada**. Un chip DIP-14 cubre 4 canales de encoder + 2 reservados, todo por ~$0.55 USD (solo el chip + bypass). En protoboard estándar (40 líneas), el montaje del chip + bypass ocupa poco espacio y es sencillo de implementar.

> **Referencias:** [CD40106B Datasheet — TI](https://www.ti.com/lit/ds/symlink/cd40106b.pdf) · [Investigación completa](docs/research/ai_research/CD40106BE_INVESTIGATION.md)

---

### Telemetría de Potencia (INA219)

El INA219 mide en tiempo real:

- **Voltaje de bus** (`v_bus`): tensión de la fuente (0–26 V)
- **Corriente** (`i_ma`): corriente consumida por el motor (±3200 mA)
- **Potencia** (`p_mw`): potencia instantánea calculada por el chip

#### Posición en el circuito

```
Batería (+) ──── VIN+ ──[shunt INA219]── VIN- ──── L298N VS
Batería (−) ──────────────────────────────────────── GND común
```

#### Configuración I2C

```cpp
#include <Wire.h>
#include <INA219_WE.h>

INA219_WE ina219(&Wire, 0x40);  // A0=GND, A1=GND → 0x40

void setup() {
    Wire.begin(21, 22);   // SDA=GPIO21, SCL=GPIO22
    ina219.init();
    ina219.setMeasureMode(INA219_CONTINUOUS);  // Modo continuo
}
```

#### Usos del dato de potencia

- Detección de sobrecarga del motor (protección térmica)
- Estimación de eficiencia (potencia mecánica vs eléctrica)
- Logging para identificación de parámetros del motor (Km, Kb)
- Correlación PID: `error` vs `potencia consumida`

---

## Control PID en Lazo Cerrado

### Modos de operación

| Modo | Código | Descripción |
|---|---|---|
| Libre | `m0` | Motor deshabilitado, encoders activos |
| PWM manual | `m1` | PWM fijo, sin lazo |
| PID posición servo | `m2` | Setpoint en grados, lazo cerrado servo |
| PID posición péndulo | `m3` | Setpoint en grados, lazo cerrado péndulo |
| LQR péndulo invertido | `m4` | Control en espacio de estados (implementado) |

### Implementación PID

> La derivada se calcula **sobre la medición** (no sobre el error) para evitar derivative kick al cambiar setpoint.

```cpp
// Derivada sobre la medición con filtro EMA
const float rawVel = -(pos - prevPos) / dt;
filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;

float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
```

### Parámetros por defecto (v1.20.0)

| Parámetro | Servo | Péndulo |
|---|---|---|
| `Kp` | 3.0 | 15.0 |
| `Ki` | 0.5 | 0.5 |
| `Kd` | 0.15 | 2.0 |
| `VEL_ALPHA` (EMA) | 0.12 | 0.15 |
| Frecuencia loop | 200 Hz | 200 Hz |

**LQR (modo 4):** `K1=1.0` (θ servo), `K2=25.0` (α péndulo), `K3=0.5` (θ'), `K4=3.0` (α')

> Los parámetros se han sintonizado experimentalmente. Ver [Calibración](#calibración).

---

## Firmware

### Estructura del proyecto

```
firmware/
├── esp32_qube_l298n/
│   └── esp32_qube_l298n.ino   ← Firmware principal
├── platformio.ini              ← Configuración PlatformIO
└── README.md
```

### Tasks FreeRTOS

| Task | Core | Prioridad | Período | Función |
|---|---|---|---|---|
| `task_control` | Core 1 | 5 | 5 ms (200 Hz) | Leer encoders, PID, PWM |
| `task_ina219` | Core 0 | 3 | 10 ms (100 Hz) | Leer INA219, filtrar |
| `task_telemetry` | Core 0 | 2 | 100 ms (10 Hz) | JSON → Serial/WiFi |
### Comandos HTTP (query string)

```bash
# Leer estado
curl -s http://192.168.4.1/state

# Modos: m0=stop, m1=PWM, m2=PID servo, m3=PID péndulo, m4=LQR
/cmd?m=2                  # Modo PID servo
/cmd?s=45                 # Setpoint servo 45°
/cmd?sp=0                 # Setpoint péndulo 0°
/cmd?m=4                  # Modo LQR

# PID servo: kp, ki, kd
/cmd?kp=3.0&ki=0.5&kd=0.15

# PID péndulo: kpp, kip, kdp
/cmd?kpp=15.0&kip=0.5&kdp=2.0

# LQR: lqr1-4
/cmd?lqr1=1&lqr2=25&lqr3=0.5&lqr4=3

# Péndulo: zp=zero, op=offset, edp=direccion, cprp=CPR
/cmd?zp=1                 # Zero péndulo

# Otros
/cmd?p=100                # PWM manual (modo 1)
/cmd?x=1                  # Paro de emergencia
/cmd?z=1                  # Zero servo
```

---

## Instructivo de Uso

Guía paso a paso para poner en funcionamiento el sistema completo.

### 1. Prerrequisitos

#### Software

| Herramienta | Propósito | Instalación |
|---|---|---|
| **Python ≥ 3.12** | GUI y análisis de datos | [python.org](https://www.python.org/downloads/) |
| **[uv](https://docs.astral.sh/uv/)** | Gestor de paquetes Python | `pip install uv` |
| **[PlatformIO](https://platformio.org/)** | Compilar firmware ESP32 | Extensión VSCode o `pip install platformio` |
| **Git** | Clonar repositorio | [git-scm.com](https://git-scm.com/) |

#### Hardware mínimo

| Componente | Estado mínimo |
|---|---|
| ESP32-WROOM-32 | Conectado por USB |
| Fuente 12V (LiPo 3S o PSU) | Alimentando el L298N |
| L298N + LM2596 | Regulador ajustado a 5V |
| Motor DC + encoder | Conectado al L298N |
| Encoder péndulo (opcional) | Solo para modo `m3` |
| INA219 (opcional) | Solo para telemetría de potencia |

---

### 2. Clonar y preparar

```bash
git clone https://github.com/abt-st/FIRMWARE-UPDATE-QUBE-ESP32.git
cd FIRMWARE-UPDATE-QUBE-ESP32
uv sync                           # Instalar dependencias Python
make test                         # Verificar (opcional)
```

---

### 3. Ajustar el LM2596 (⚠️ ANTES de conectar el ESP32)

1. **Desconectar** el ESP32 del circuito
2. Conectar solo el LM2596 a la fuente de 12V
3. Medir con multímetro entre `OUT+` y `OUT−`
4. Girar el potenciómetro hasta leer **5.00 V** exactos
5. Recién conectar el ESP32 al pin `VIN`

> ⚠️ Nunca aplicar más de 5.5 V al pin `VIN` del ESP32.

---

### 4. Compilar y flashear el firmware

#### Opción A: PlatformIO (recomendado)

```bash
cd firmware
pio pkg install                   # Instalar dependencias
pio run                           # Compilar
pio run --target upload           # Flashear al ESP32
pio device monitor --baud 115200  # Monitor serie
```

#### Opción B: Arduino IDE

1. Abrir `firmware/esp32_qube_l298n/esp32_qube_l298n.ino`
2. **Tools → Board → ESP32 Arduino → ESP32 Dev Module**
3. Seleccionar puerto COM
4. Instalar librerías: `INA219_WE`, `ArduinoJson`, `AsyncTCP`, `ESPAsyncWebServer`
5. Click **Upload** ▶️
6. Abrir Monitor Serie a 115200 baud

#### Verificación

Al encender, el monitor serie debe mostrar:

```
[BOOT] QUBE ESP32 — v1.x.x
[ENC] Servo   CNT=0   POS=0.00°
[ENC] Pendulo CNT=0   POS=0.00°
[INA219] V=11.8V  I=0mA  P=0mW
[WIFI] Conectado a: QUBE-AP  IP: 192.168.4.1
[MODO] Libre (m0)
```

---

### 5. Conexión WiFi

#### Modo AP (por defecto)

- **SSID:** `QUBE-ESP32` / **Pass:** `qube1234`
- **IP:** `192.168.4.1`
- Conectar tu PC/telefono directamente a la red del ESP32

#### Modo STA (Station)

- Configurar credenciales vía serial: `wifi_ssid<TuRed>`, `wifi_pass<TuClave>`
- El ESP32 obtiene IP por DHCP del router
- Verificar con comando serial: `wifi_info`

> ⚠️ Las credenciales STA se guardan en NVS del ESP32.

---

### 6. Modos de operación

| Modo | Comando HTTP | Descripción |
|---|---|---|
| `m0` | `/cmd?m=0` | Libre — motor deshabilitado, encoders activos |
| `m1` | `/cmd?m=1` | PWM manual — `/cmd?p=100` |
| `m2` | `/cmd?m=2` | PID posición servo — `/cmd?s=20` |
| `m3` | `/cmd?m=3` | PID posición péndulo — `/cmd?sp=0` |
| `m4` | `/cmd?m=4` | LQR péndulo invertido |

---

### 7. Uso de la GUI

```bash
make run                           # Opción 1
uv run python gui/app.py           # Opción 2
```

1. Encender ESP32 con firmware flasheado
2. Conectar PC a la red WiFi del ESP32 (`QUBE-ESP32` / `qube1234`)
3. Abrir la GUI — ingresa IP y haz clic en "Conectar"

**Panel de gráficas (4 subplots):**
1. **Servo** — posición angular y setpoint
2. **Péndulo** — posición angular y setpoint
3. **PWM** — señal de control (-255 a +255)
4. **Potencia** — corriente (mA) y voltaje bus (V) del INA219

**Panel de control:**
- Modo de operación (5 radios: STOP, PWM, PID Servo, PID Péndulo, LQR)
- Setpoint servo y péndulo (grados)
- PID gains servo y péndulo (Kp, Ki, Kd)
- LQR gains (K1-K4)
- Zero Servo / Zero Péndulo / Reset / STOP
- Exportar CSV

---

### 8. Comandos HTTP directos

```bash
# Leer estado (JSON completo con servo + péndulo)
curl -s http://192.168.4.1/state | python -m json.tool

# Modo PID servo + setpoint 20°
curl "http://192.168.4.1/cmd?m=2&s=20"

# Modo LQR péndulo invertido
curl "http://192.168.4.1/cmd?m=4"

# Ajustar PID servo
curl "http://192.168.4.1/cmd?kp=3.0&ki=0.5&kd=0.15"

# Ajustar PID péndulo
curl "http://192.168.4.1/cmd?kpp=15.0&kip=0.5&kdp=2.0"

# Paro de emergencia
curl "http://192.168.4.1/cmd?x=1"
```

---

### 9. Flujo típico de trabajo

```
┌─────────────────────────────────────────────────────────────┐
│ 1. PREPARAR          uv sync && pio pkg install             │
├─────────────────────────────────────────────────────────────┤
│ 2. AJUSTAR LM2596    A 5V (sin ESP32 conectado)             │
├─────────────────────────────────────────────────────────────┤
│ 3. FLASHEAR          pio run --target upload                │
├─────────────────────────────────────────────────────────────┤
│ 4. VERIFICAR         Modo m0 → girar ejes → ver CNT         │
├─────────────────────────────────────────────────────────────┤
│ 5. PROBAR MOTOR      Modo m1 → motor gira                   │
├─────────────────────────────────────────────────────────────┤
│ 6. CALIBRAR PID      Ziegler-Nichols → Ku, Tu → ganancias  │
├─────────────────────────────────────────────────────────────┤
│ 7. MONITOREAR        GUI (make run) o curl /state           │
├─────────────────────────────────────────────────────────────┤
│ 8. REGISTRAR         Exportar CSV desde GUI                 │
└─────────────────────────────────────────────────────────────┘
```

---

### 10. Tests y desarrollo

```bash
make test              # Ejecutar tests (pytest)
make lint              # Verificar errores de código
make format            # Formatear código
make check             # Lint + format (CI)
make typecheck         # Verificación de tipos (pyright)
make clean             # Limpiar archivos temporales
make help              # Ver todos los comandos
```

---

### 11. Solución rápida de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `CNT` no cambia al girar encoder | Falta pull-up o level shifter de alta impedancia | Instalar pull-up 4.7kΩ a 3.3V + Schmitt trigger |
| Error de boot al usar GPIO34/35 | `INPUT_PULLUP` en pin input-only | Usar solo `INPUT` + pull-up externo |
| PID diverge inmediatamente | Motor invertido | Cambiar `MOTOR_DIR = -1` en `config.h` |
| Derivativo oscila con ruido | `Kd` demasiado alto | Aumentar `alpha` del filtro EMA (0.12–0.20) |
| ESP32 no responde por WiFi | IP incorrecta | Verificar SSID/IP, usar modo AP `192.168.4.1` |
| GUI no muestra datos | IP mal configurada | Revisar `ESP32_IP` en `gui/esp32_client.py` |
| `VIN` se calienta | Voltaje > 5.5V | Ajustar LM2596 a 5.00V con multímetro |

---

## Calibración

### 1. Verificación de encoders

Al arrancar en modo `m0` (libre):

```
[ENC] Servo   CNT=0   POS=0.00°
[ENC] Pendulo CNT=0   POS=0.00°
```

Girar manualmente y verificar que `CNT` incremente/decremente correctamente.

### 2. Dirección del motor

Si el encoder retrocede con PWM positivo:

```cpp
// config.h
#define MOTOR_DIR  (-1)   // +1 o -1
```

O invertir cables `OUT1`/`OUT2` del L298N.

### 3. CPR (Counts Per Revolution)

```cpp
// config.h
#define ENC_SERVO_CPR    2048
#define ENC_PENDULO_CPR  1024
```

### 4. Sintonización PID (Ziegler-Nichols)

1. `Ki = 0`, `Kd = 0`
2. Incrementar `Kp` hasta oscilación con amplitud constante → `Ku`
3. Medir período de oscilación → `Tu`
4. Calcular:

$$K_p = 0.6 \cdot K_u \qquad K_i = \frac{2 K_p}{T_u} \qquad K_d = \frac{K_p \cdot T_u}{8}$$

5. Ajustar `alpha` del filtro EMA si hay ruido en `Kd`.

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

### Validación del encoder (post HW-FIX-1)

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
**Causa:** Level shifter 5V→3.3V con ~7 MΩ. τ ≈ 350–700 µs, demasiado lento.  
**Solución:** Eliminar level shifter. Instalar pull-up 4.7 kΩ a 3.3V + Schmitt trigger CD40106BE.

### HW-FIX-2: GPIO34/35 sin `INPUT_PULLUP`

**Síntoma:** Error de boot al llamar `pinMode(34, INPUT_PULLUP)`.  
**Causa:** GPIO34/35 son input-only, sin pull-up interno.  
**Solución:** Usar `pinMode(34, INPUT)` + pull-ups externos.

### SW-FIX-1: Ruido de cuantización en término derivativo

**Síntoma:** Derivativo oscila violentamente con `Kd` alto.  
**Causa:** ±1–2 counts de ruido del encoder.  
**Solución:** Filtro EMA (`alpha ≈ 0.12`) sobre velocidad estimada.

### SW-FIX-2: Dirección del motor vs encoder

**Síntoma:** PID diverge inmediatamente.  
**Causa:** Retroalimentación positiva.  
**Solución:** `MOTOR_DIR = -1` en `config.h` o invertir cables OUT1/OUT2.

---

## Roadmap

- [x] Control PID posición servo (encoder 1)
- [x] Telemetría INA219 (V, I, P)
- [x] Fix acondicionamiento señal open-drain (HW-FIX-1)
- [x] Schmitt trigger CD40106BE para encoders servo (GPIO34/35) — **implementado**
- [ ] Integración encoder péndulo (encoder 2) — **en progreso**
- [ ] Control PID posición péndulo (modo m3)
- [ ] Control LQR péndulo invertido (modo m4)
- [ ] Swing-up automático (modo m5)
- [ ] Dashboard web en tiempo real (WebSocket)
- [ ] Logging en SPIFFS / tarjeta SD
- [ ] Identificación de parámetros del motor
- [ ] Paper académico comparativo vs Quanser QUBE

---

## Referencias

### Proyectos de referencia

- [Esp32CameraRover2 — Ezward](https://github.com/Ezward/Esp32CameraRover2) — Framework closed-loop ESP32
- [Rotary-Inverted-Pendulum — ebrahimabdelghfar](https://github.com/ebrahimabdelghfar/Rotary-Inverted-Pendulum) — LQR + Arduino + L298N
- [arduino_pid_controlled_motor — wty-yy](https://github.com/wty-yy/arduino_pid_controlled_motor) — PID + encoder documentado
- [INA219_WE](https://github.com/wollewald/INA219_WE) — Librería INA219 (activamente mantenida)

### Datasheets

- [L298 — STMicroelectronics](https://www.st.com/resource/en/datasheet/l298.pdf)
- [LM2596 — Texas Instruments](https://www.ti.com/product/LM2596)
- [INA219 — Texas Instruments](https://www.ti.com/product/INA219)
- [CD40106B — Texas Instruments](https://www.ti.com/lit/ds/symlink/cd40106b.pdf)

### Papers académicos

- Akhtaruzzaman, M., & Shafie, A. A. (2010). Modeling and control of a rotary inverted pendulum using various methods. *IEEE ICMA 2010*. https://doi.org/10.1109/ICMA.2010.5589450
- STMicroelectronics. (2019). *Introduction to Integrated Rotary Inverted Pendulum* (v2).

### Documentación interna

- [Investigación CD40106BE](docs/research/ai_research/CD40106BE_INVESTIGATION.md) — Schmitt trigger para acondicionamiento de señal
- [Estabilización de señales](docs/research/SIGNAL_STABILIZATION.md) — Filtros y mitigación de ruido
- [CHANGELOG](CHANGELOG.md) — Historial de versiones del firmware

---

## Licencia

MIT License — ver [LICENSE](LICENSE) para detalles.

---

*Última actualización: Mayo 27, 2026*