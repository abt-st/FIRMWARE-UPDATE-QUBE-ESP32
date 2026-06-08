# QUBE ESP32

Plataforma de control educativo de péndulo rotatorio invertido basada en **ESP32 + BTS7960 + INA219 + LM2596 + CD40106BE**, con encoders duales, telemetría de potencia en tiempo real y conectividad WiFi. Alternativa open-source al Quanser QUBE Servo por **~$70 USD** frente a los $2,500–$3,500 USD del original.

---

## Tabla de Contenidos

1. [Motivación](#motivación)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Hardware Requerido](#hardware-requerido)
4. [Pinout y Conexiones](#pinout-y-conexiones)
5. [Acondicionamiento de Señal — Schmitt Trigger + RC](#acondicionamiento-de-señal--schmitt-trigger--rc)
6. [Control PID en Lazo Cerrado](#control-pid-en-lazo-cerrado)
7. [Firmware](#firmware)
8. [Instructivo de Uso](#instructivo-de-uso)
9. [Calibración](#calibración)
10. [Resultados y Validación](#resultados-y-validación)
11. [Problemas Conocidos y Soluciones](#problemas-conocidos-y-soluciones)
12. [Roadmap](#roadmap)
13. [Documentación Adicional](#documentación-adicional)
14. [Referencias](#referencias)
15. [Licencia](#licencia)

---

## Motivación

### El problema del péndulo rotatorio invertido

El **péndulo rotatorio invertido** es uno de los problemas clásicos más importantes en ingeniería de control. Consiste en un péndulo articulado en el extremo de un brazo rotatorio impulsado por un motor DC. El objetivo es mantener el péndulo en posición **vertical invertida** (hacia arriba), una posición inherentemente inestable — cualquier perturbación mínima lo hace caer.

**Por qué es un problema difícil:**

1. **Sistema inestable por naturaleza** — El equilibrio vertical arriba es un punto de silla en el espacio de fases. Sin control activo, el péndulo cae en fracciones de segundo.
2. **Un actuador, dos variables** — El motor del servo es el único actuador, pero debe controlar simultáneamente el ángulo del brazo (θ) y el ángulo del péndulo (α). Esto lo convierte en un sistema **SISO con dinámica acoplada**.
3. **No linealidad** — La dinámica del péndulo involucra funciones trigonométricas (`sin(α)`, `cos(α)`) que hacen el control más complejo que un sistema lineal simple.
4. **Restricciones físicas** — El motor tiene límites de voltaje, corriente y velocidad. El brazo tiene un rango de movimiento limitado. Estas restricciones deben considerarse en el diseño del controlador.

**Aplicaciones reales:**

Los métodos usados para resolver este problema se aplican directamente a:

- Robots manipuladores industriales
- Sistemas de estabilización de drones y aeronaves
- Vehículos autónomos (balance de robots bípedos)
- Sistemas de posicionamiento de antenas y paneles solares
- Control de actuadores en sistemas aeroespaciales

### El sistema QUBE-Servo de Quanser

El **Quanser QUBE-Servo** es una plataforma educativa de referencia fabricada por Quanser (Canadá) diseñada específicamente para enseñar control moderno en universidades. El sistema consta de:

- **Un servo motor DC** con encoder óptico de alta resolución
- **Un brazo rotatorio** (el eje del servo)
- **Un péndulo** articulado en el extremo del brazo (módulo opcional)

El sistema tiene **dos grados de libertad**: el ángulo del servo (θ) y el ángulo del péndulo (α). El servo es el actuador único — todo el control se hace moviendo el brazo rotatorio para influenciar el péndulo.

**Los 7 laboratorios que Quanser diseña con el QUBE-Servo:**

| # | Lab                                      | Qué enseña                                             |
| - | ---------------------------------------- | -------------------------------------------------------- |
| 1 | **Momento de inercia**             | Calcular J del péndulo (analítica + experimental)      |
| 2 | **Modelado del péndulo**          | Verificar convenciones de signos HW ↔ modelo            |
| 3 | **Modelado en espacio de estados** | Representación matricial del sistema linealizado        |
| 4 | **Balance con PD**                 | Control clásico para estabilizar el péndulo arriba     |
| 5 | **Pole Placement**                 | Diseño de control por estados con ubicación de polos   |
| 6 | **LQR**                            | Control óptimo por regulador cuadrático lineal         |
| 7 | **Swing-up**                       | Control no lineal por energía para levantar el péndulo |

### Las dos fases del problema de control

El problema completo del péndulo rotatorio invertido se divide en **dos fases** que deben resolverse en secuencia:

#### Fase 1: Swing-up (levantamiento)

- **Situación inicial:** péndulo colgando hacia abajo (posición estable)
- **Objetivo:** hacer oscilar el péndulo hasta que llegue a la vertical arriba
- **Método:** control basado energía — se inyecta energía al sistema hasta alcanzar la energía del equilibrio arriba: `E_r = 2·m·g·l`
- **El brazo del servo oscila** para bombear energía al péndulo
- **Desafío:** el algoritmo debe ser robusto a perturbaciones y funcionar desde cualquier posición inicial

#### Fase 2: Balance (estabilización)

- **Situación:** péndulo cerca de la vertical arriba (dentro de un umbral angular)
- **Objetivo:** mantenerlo vertical sin que caiga
- **Método:** control lineal por estados (LQR o pole placement) que usa las 4 variables de estado: `[θ, α, θ_dot, α_dot]`
- **El servo se mueve** para contrarrestar cualquier perturbación
- **Desafío:** el controlador debe ser rápido y preciso para contrarrestar la gravedad en tiempo real

### El problema de accesibilidad económica

El Quanser QUBE-Servo tiene un costo de **$2,500–$3,500 USD**, lo que lo hace inaccesible para la mayoría de instituciones de educación media y superior en Latinoamérica. Esta barrera económica limita:

- El acceso a laboratorios de control moderno
- La formación práctica de estudiantes en ingeniería de control
- La investigación en sistemas embebidos de control en tiempo real
- La replicabilidad de experimentos en instituciones con presupuestos limitados

### Nuestra propuesta: una alternativa open-source

Este proyecto propone una **modernización completa del sistema** usando componentes de bajo costo disponibles globalmente, manteniendo:

- Control en lazo cerrado con realimentación de posición angular
- Telemetría de voltaje, corriente y potencia en tiempo real (INA219)
- Conectividad inalámbrica (WiFi) para monitoreo remoto
- **Encoders duales**: uno en el eje del servo (posición del motor) y uno en el eje del péndulo (posición del brazo rotatorio)
- Compatibilidad con Arduino IDE y librerías estándar
- **Implementación completa de swing-up + balance** con los mismos métodos que Quanser

**Comparación directa:**

| Aspecto                  | Quanser QUBE-Servo                  | Nuestra propuesta               |
| ------------------------ | ----------------------------------- | ------------------------------- |
| **Costo**          | $2,500–$3,500 USD                  | **$40–70 USD**           |
| **Plataforma**     | DSP propietario                     | ESP32 open-source               |
| **Software**       | MATLAB/Simulink (requiere licencia) | Python + Arduino IDE (gratuito) |
| **Telemetría**    | Sensores integrados                 | INA219 digital (I2C)            |
| **Control**        | PID + LQR + Swing-up                | **PID + LQR + Swing-up**  |
| **Encoders**       | 2 (servo + péndulo)                | **2 (servo + péndulo)**  |
| **Conectividad**   | Ethernet/USB                        | **WiFi + BLE nativa**     |
| **Documentación** | Courseware proprietario             | **Open-source completa**  |

El resultado es una plataforma funcional por **~$70 USD** (98% de reducción de costo), documentada completamente y publicada como open-source para la comunidad educativa.

---

## Arquitectura del Sistema

### Diagrama de bloques general

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    QUBE SERVO MODERNIZADO                                │
│                    ESP32 + BTS7960 + INA219 + LM2596 + CD40106BE         │
└──────────────────────────────────────────────────────────────────────────┘

ENTRADA: 12V (LiPo 3S o PSU de laboratorio)
    │
    ├── [LM2596 Buck Converter] ──→ 5V rail para lógica
    │       │
    │       ├── ESP32 VIN (5V → 3.3V interno AMS1117)
    │       ├── BTS7960 VCC (lógica)
    │       └── Encoder VCC (5V)
    │
    ├── [INA219] High-side current sensing
    │       VIN+ ← 12V fuente
    │       VIN- → BTS7960 VS (12V motor)
    │       I2C: SDA=GPIO21, SCL=GPIO22
    │
    ├── [ESP32-WROOM-32] Núcleo de control
    │       ├── Core 1: Control PID @ 200 Hz
    │       ├── Core 0: Telemetría + WiFi
    │       ├── GPIO26 → BTS7960 RPWM (adelante)
    │       ├── GPIO27 → BTS7960 LPWM (reversa)
    │       ├── GPIO34 → Encoder Servo A → Schmitt + RC
    │       ├── GPIO35 → Encoder Servo B → Schmitt + RC
    │       ├── GPIO32 → Encoder Péndulo A → Schmitt + RC
    │       ├── GPIO33 → Encoder Péndulo B → Schmitt + RC
    │       └── USB-UART → PC (depuración + GUI)
    │
    ├── [BTS7960 Dual Half-Bridge] Etapa de potencia
    │       ├── RPWM/LPWM: PWM directo (ENA habilitado)
    │       ├── M+/M- → Motor DC
    │       └── VS: 12V desde INA219 VIN-
    │
    └── [Motor DC + Encoder] Actuador
            ├── M+ / M- (BTS7960 M+/M-)
            └── Encoder: A/B + GND + VCC (5V)
```

### Conexión de potencia

```
                    ┌──────────────────────────────────────┐
                    │          TOPOLOGÍA DE POTENCIA        │
                    └──────────────────────────────────────┘

Fuente 12V (+) ──┬── VIN+ [INA219] VIN- ──── BTS7960 VS (12V motor)
                 │
                 ├── LM2596 IN+
                 │      └── LM2596 OUT+ (5V) ──── ESP32 VIN
                 │                             ──── BTS7960 VCC (lógica)
                 │                             ──── Encoder VCC (5V)
                 │                             ──── CD40106BE Vcc (3.3V)
                 │
Fuente GND  ─────┴── GND común (topología estrella)
                    ├── BTS7960 GND
                    ├── LM2596 IN-
                    ├── ESP32 GND (pin GND)
                    ├── INA219 GND
                    ├── CD40106BE GND (pin 7)
                    └── Encoder GND
```

**Requisitos de potencia:**

- Cable de retorno motor: AWG 16 mínimo (R < 0.05 Ω)
- GND común en topología estrella (NO en cadena)
- Bypass capacitors: 470 µF + 100 µF en rail 5V
- Capacitor 100 nF cerca del BTS7960 (bypass)

### Flujo de datos

```
                          ESP32 (FreeRTOS)
                         ┌──────────────────┐
Encoder Servo ─────►     │                  │
(GPIO34/35 + Schmitt)    │  task_control    │──► BTS7960 (PWM → Motor)
                         │  200 Hz          │
Encoder Péndulo ────►    │                  │
(GPIO32/33 + Schmitt)    └────────┬─────────┘
                                  │
                    INA219 (I2C)───┤──► task_ina219 (100 Hz)
                    (GPIO21/22)    │
                                  │
                                  ├──► task_telemetry (10 Hz)
                                  │         │
                                  │         ├──► Serial (USB → PC)
                                  │         └──► WiFi (HTTP REST)
                                  │
                                  └──► task_wifi (event-driven)
```

---

## Hardware Requerido

| Componente                    | Especificación                      | Cantidad | Precio aprox.     |
| ----------------------------- | ------------------------------------ | -------- | ----------------- |
| **ESP32-WROOM-32**      | Dual-core 240 MHz, WiFi+BLE          | 1        | $6–10 USD        |
| **BTS7960**             | Dual Half-Bridge (IBT-2), 43A pico, 10A cont. | 1        | $2–5 USD          |
| **INA219**              | Monitor I2C, 0–26 V, ±3.2 A        | 1        | $2–4 USD         |
| **LM2596**              | Buck converter ajustable, 3 A        | 1        | $1–3 USD         |
| **CD40106BE**           | Hex Schmitt Trigger Inverter, DIP-14 | 1        | ~$0.50 USD        |
| **Motor DC + reductor** | 12 V, 25 W, 100–300 RPM             | 1        | $15–30 USD       |
| **Encoder servo**       | Incremental, open-drain, ≥200 CPR   | 1        | Incluido en motor |
| **Encoder péndulo**    | Incremental, open-drain, ≥200 CPR   | 1        | $5–15 USD        |
| **Resistores 4.7 kΩ**  | Pull-up para encoders (×4)          | 4        | < $0.10 USD       |
| **Resistores 10 kΩ**   | Filtro RC post-Schmitt (×4)         | 4        | < $0.10 USD       |
| **Capacitores 10 nF**   | Filtro RC post-Schmitt a GND (×4)   | 4        | < $0.10 USD       |
| **Capacitor 100 nF**    | Bypass Vcc CD40106BE                 | 1        | < $0.05 USD       |
| **Capacitor 100 µF**   | Filtro salida LM2596                 | 1        | < $0.20 USD       |
| **Fuente 12V**          | LiPo 3S o PSU laboratorio            | 1        | Variable          |

**Costo total estimado (sin fuente):** $35–70 USD
**Comparación:** Quanser QUBE Servo = $2,500–$3,500 USD

---

## Pinout y Conexiones

### Tabla completa pin por pin

| Subsistema       | Origen                   | Destino                                                | Notas                                |
| ---------------- | ------------------------ | ------------------------------------------------------ | ------------------------------------ |
| Potencia motor   | Fuente 12 V (+)          | BTS7960 VS                                               | Alimentación del half-bridge        |
| Potencia motor   | GND fuente               | BTS7960 GND                                              | GND común obligatorio               |
| Lógica BTS7960  | LM2596 5 V               | BTS7960 VCC                                              | Lógica del módulo IBT-2            |
| Motor DC         | BTS7960 M+               | Motor terminal (+)                                     | Salida de potencia                   |
| Motor DC         | BTS7960 M-               | Motor terminal (−)                                    | Salida de potencia                   |
| Control motor    | ESP32 GPIO26             | BTS7960 RPWM                                              | PWM adelante                        |
| Control motor    | ESP32 GPIO27             | BTS7960 LPWM                                              | PWM reversa                        |
| Encoder servo    | Canal A                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO34 | Ver acondicionamiento                |
| Encoder servo    | Canal B                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO35 | Ver acondicionamiento                |
| Encoder servo    | GND / +5V                | GND común / Alimentación                             | Referencia compartida                |
| Encoder péndulo | Canal A                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO32 | Ver acondicionamiento                |
| Encoder péndulo | Canal B                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO33 | Ver acondicionamiento                |
| Encoder péndulo | GND / +5V                | GND común / Fuente auxiliar 5 V                       | Referencia compartida                |
| INA219           | ESP32 GPIO21             | INA219 SDA                                             | I2C datos                            |
| INA219           | ESP32 GPIO22             | INA219 SCL                                             | I2C reloj                            |
| INA219           | ESP32 3V3                | INA219 VCC                                             | No conectar a 5 V                    |
| INA219           | GND común               | INA219 GND                                             | Referencia común                    |
| INA219           | (+) batería / LM2596 IN | INA219 VIN+                                            | Antes del BTS7960                    |
| INA219           | BTS7960 VS              | INA219 VIN−                                           | Después del shunt                   |
| Schmitt          | CD40106BE pin 14         | ESP32 3V3                                              | Vcc = 3.3 V (salida compatible GPIO) |
| Schmitt          | CD40106BE pin 7          | GND común                                             | Tierra del chip                      |
| Schmitt          | 100 nF                   | Pin 14 a pin 7                                         | Bypass, lo más cerca del chip       |
| Debug serial     | USB ESP32                | PC / monitor serie                                     | UART0 por USB                        |

### Configuración de pines ESP32

```
Pin     │ Función               │ Tipo         │ Notas
────────┼───────────────────────┼──────────────┼──────────────────────────────
GPIO21  │ I2C SDA               │ Bidireccional│ Pull-up interno
GPIO22  │ I2C SCL               │ Salida       │ Pull-up interno
GPIO25  │ BTS7960 EN (habilitar) │ Salida       │ Solo opción B (pull-up interno)
GPIO26  │ BTS7960 RPWM           │ Salida       │ PWM adelante
GPIO27  │ BTS7960 LPWM           │ Salida       │ PWM reversa
GPIO32  │ Encoder péndulo A     │ Entrada      │ Schmitt + RC (10 kΩ/10 nF)
GPIO33  │ Encoder péndulo B     │ Entrada      │ Schmitt + RC (10 kΩ/10 nF)
GPIO34  │ Encoder servo A       │ Entrada      │ Schmitt + RC (10 kΩ/10 nF), input-only
GPIO35  │ Encoder servo B       │ Entrada      │ Schmitt + RC (10 kΩ/10 nF), input-only
```

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.

### Cableado de EN

| Opción                   | Conexión EN              | Cuándo usar        |
| ------------------------- | ------------------------ | ------------------- |
| **A (recomendada)** | No conectar (pull-up interno) | PWM directo por RPWM/LPWM |
| B (alternativa)           | ESP32 GPIO25 → EN       | Control por software del enable |

> **Importante:** El módulo IBT-2 tiene pines R_EN y L_EN que habilitan cada half-bridge. Vienen pull-up por defecto. Solo conectar GPIO25 si necesitas control por software del enable.

---

## Acondicionamiento de Señal — Schmitt Trigger + RC

### Problema: encoders open-drain

Los encoders (Premotec 990412016913) tienen salida **open-drain (NPN)**:

- **Estado bajo:** transistor conduce → 0 V
- **Estado alto:** transistor corta → línea flota (Hi-Z)

Sin acondicionamiento, la señal es susceptible a ruido de conmutación PWM, rebotes mecánicos y glitches que generan cuentas espurias en el encoder.

### Circuito implementado: CD40106BE + filtro RC

El circuito de acondicionamiento combina **Schmitt Trigger** (histéresis para rechazo de ruido) con un **filtro RC pasivo** (atenuación de alta frecuencia) en cada canal del encoder:

```
                                     CD40106BE
                                ┌──────────────────┐
Encoder A (~5V) ────────────────┤ pin 1  (IN_A)    │
                		│        (OUT_A) pin 2 ├──┐
  		                │                  │   │  │
   	                        │        (IN_B) pin 3 ◄─┘
                                │        (OUT_B) pin 4 ├──► 10kΩ ──┬──► GPIO34
                                │                  │              │
                                │                  │            10nF
                                │                  │              │
                                │                  │             GND
                                │                  │
Encoder B (~5V) ────────────────┤ pin 5  (IN_C)    │
                                │        (OUT_C) pin 6 ├──┐
                                │                  │  │  │
                                │        (IN_D) pin 9 ◄─┘
                                │        (OUT_D) pin 8 ├──► 10kΩ ──┬──► GPIO35
                                │                  │              │
                                │                  │            10nF
                                │                  │              │
         GND ───────────────────┤ pin 7       pin 14├──── 3.3V   GND
                                └──────────────────┘
                                       │
                                   100nF (bypass Vcc)
                                       │
                                      GND
```

**Por canal (replicado ×4 para servo A/B + péndulo A/B):**

```
                            CD40106BE                    Filtro RC
                           ┌─────────┐

Encoder (~5V) ──► IN_A ──►│ INV_A   │
                  (pin 1)  │         │──► OUT_A (pin 2) ──┐
                           │  INV_B  │                     │
                           │         │◄── IN_B (pin 3) ◄──┘
                           │         │
                           │         │──► OUT_B (pin 4) ──[10kΩ]──┬──► GPIO
                                                   (doble inversión) │
                                                                 [10nF]
                                                                     │
                                                                    GND
```

### ¿Por qué este circuito?

| Etapa                                  | Función                                | Efecto                          |
| -------------------------------------- | --------------------------------------- | ------------------------------- |
| **Pull-up 4.7 kΩ**              | Convierte open-drain a niveles lógicos | Señal: 0 V / 3.3 V             |
| **Schmitt Trigger (doble inv.)** | Histéresis ~0.5 V (a 3.3 V Vcc)        | Elimina glitches y rebotes      |
| **Filtro RC (10 kΩ + 10 nF)**   | Atenuación de alta frecuencia          | Filtro anti-alias, τ = 100 µs |

**Filtro RC:**

- τ = R × C = 10 kΩ × 10 nF = **100 µs**
- f_c = 1 / (2π × τ) ≈ **1.59 kHz**
- Atenua ruido de conmutación PWM (>20 kHz) y transitorios de alta frecuencia
- No afecta señales de encoder en rango operativo (<50 kHz para 400 RPM)

**Schmitt Trigger:**

| Parámetro                   | CD40106BE @ 3.3 V Vcc | Efecto                                                    |
| ---------------------------- | --------------------- | --------------------------------------------------------- |
| Umbral alto (VT+)            | ~2.3 V                | Se activa cuando la señal**supera** este valor     |
| Umbral bajo (VT−)           | ~1.0 V                | Se desactiva cuando la señal**baja** de este valor |
| **Histéresis (ΔVT)** | **~1.3 V**      | **Zona muerta que rechaza ruido**                   |
| Tiempo de propagación       | ~80–150 ns           | Salida digital limpia y rápida                           |

### Características del CD40106BE

| Propiedad           | Valor                                       |
| ------------------- | ------------------------------------------- |
| Tipo                | Hex Schmitt Trigger Inverter (6 inversores) |
| Paquete             | DIP-14                                      |
| Alimentación       | 3 V a 18 V (rango completo CMOS)            |
| Corriente de salida | ~1.6 mA sink/source a 3.3 V                 |
| Disipación         | Muy baja (~µW en estático)                |
| Costo               | ~$0.50 USD                                  |

**Pinout (DIP-14):**

```
          +--------+
  A_IN 1  |        | 14 Vcc (3.3V)
  A_OUT 2 |        | 13 F_IN
  B_IN 3  |        | 12 F_OUT
  B_OUT 4 |  40106 | 11 E_IN
  C_IN 5  |        | 10 E_OUT
  C_OUT 6 |        | 9  D_IN
   GND 7  |        | 8  D_OUT
          +--------+
```

### Uso de los 6 inversores

| Inversor      | Pines      | Uso                                                     | Estado          |
| ------------- | ---------- | ------------------------------------------------------- | --------------- |
| INV_A + INV_B | 1→2→3→4 | Encoder servo canal A (doble inversión + RC → GPIO34) | **Usado** |
| INV_C + INV_D | 5→6→9→8 | Encoder servo canal B (doble inversión + RC → GPIO35) | **Usado** |
| INV_E         | 11→10     | Reservado — oscilador watchdog / botón de paro        | Libre           |
| INV_F         | 13→12     | Reservado — debounce de botones / expansión           | Libre           |

> **Importante:** Alimentar el CD40106BE a **3.3 V** (desde el pin 3V3 del ESP32) para salida directa compatible con GPIO. La salida será **~3.3 V** (limitada por Vcc), seguro para los GPIO del ESP32 (máximo tolerado: 3.6 V).

### Alimentación y bypass

```
3.3V (ESP32) ──┬── CD40106BE pin 14 (Vcc)
               │
              100nF ── GND  (bypass, lo más cerca del pin 14)
               │
              GND ──── CD40106BE pin 7
```

> **Sobre el capacitor de bypass (100 nF):** Conectar **entre pin 14 (Vcc) y pin 7 (GND)**, lo más cerca posible del chip. Cuando las compuertas del CD40106BE conmutan, dibujan picos de corriente del rail 3.3V. Sin el capacitor, estos transitorios generan glitches en el voltaje de alimentación que pueden afectar al ESP32, ya que ambos comparten el mismo rail.

### Componentes del acondicionamiento (×4 canales)

| Componente         | Valor               | Cantidad | Costo                |
| ------------------ | ------------------- | -------- | -------------------- |
| CD40106BE          | Hex Schmitt Trigger | 1        | ~$0.50               |
| Resistores 4.7 kΩ | Pull-up encoder     | 4        | < $0.10              |
| Resistores 10 kΩ  | Serie filtro RC     | 4        | < $0.10              |
| Capacitores 10 nF  | Filtro RC a GND     | 4        | < $0.10              |
| Capacitor 100 nF   | Bypass Vcc          | 1        | < $0.05              |
| **Total**    |                     |          | **~$0.85 USD** |

### Comparativa de topologías

| Topología                       | Histéresis            | Glitches             | Filtro HF                | Velocidad max     | Costo            |
| -------------------------------- | ---------------------- | -------------------- | ------------------------ | ----------------- | ---------------- |
| Pull-up solamente                | No                     | Posibles             | No                       | ~10 kHz           | ~$0.05           |
| Pull-up + Schmitt                | Sí (~1.3 V)           | Eliminados           | No                       | >100 kHz          | ~$0.55           |
| **Pull-up + Schmitt + RC** | **Sí (~1.3 V)** | **Eliminados** | **Sí (1.59 kHz)** | **>50 kHz** | **~$0.85** |

---

## Control PID en Lazo Cerrado

### Modos de operación

| Modo                   | Código | Descripción                              |
| ---------------------- | ------- | ----------------------------------------- |
| Libre                  | `m0`  | Motor deshabilitado, encoders activos     |
| PWM manual             | `m1`  | PWM fijo, sin lazo                        |
| PID posición servo    | `m2`  | Setpoint en grados, lazo cerrado servo    |
| PID posición péndulo | `m3`  | Setpoint en grados, lazo cerrado péndulo |
| LQR péndulo invertido | `m4`  | Control en espacio de estados             |
| Swing-up               | `m5`  | Levantamiento del péndulo por energía   |

### Implementación PID

> La derivada se calcula **sobre la medición** (no sobre el error) para evitar derivative kick al cambiar setpoint.

```cpp
// Derivada sobre la medición con filtro EMA
const float rawVel = -(pos - prevPos) / dt;
filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;

float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
```

### Parámetros por defecto

| Parámetro           | Servo (m2) | Péndulo (m3) | LQR (m4) |
| -------------------- | ---------- | ------------- | -------- |
| `Kp`               | 3.0        | 15.0          | —       |
| `Ki`               | 0.5        | 0.5           | —       |
| `Kd`               | 0.15       | 2.0           | —       |
| `VEL_ALPHA` (EMA)  | 0.12       | 0.15          | —       |
| `K1` (θ servo)    | —         | —            | 1.0      |
| `K2` (α péndulo) | —         | —            | 25.0     |
| `K3` (θ')         | —         | —            | 0.5      |
| `K4` (α')         | —         | —            | 3.0      |

> Los parámetros se han sintonizado experimentalmente. Ver [Calibración](#calibración).

---

## Firmware

### Estructura del proyecto

```
src/firmware/
├── esp32_qube_l298n/
│   ├── esp32_qube_l298n.ino   ← Firmware principal (~1350 líneas)
│   └── credentials.h          ← WiFi STA (gitignored)
└── platformio.ini             ← Configuración PlatformIO
```

### Tasks FreeRTOS

| Task               | Core   | Prioridad | Período       | Función                |
| ------------------ | ------ | --------- | -------------- | ----------------------- |
| `task_control`   | Core 1 | 5         | 5 ms (200 Hz)  | Leer encoders, PID, PWM |
| `task_ina219`    | Core 0 | 3         | 10 ms (100 Hz) | Leer INA219, filtrar    |
| `task_telemetry` | Core 0 | 2         | 100 ms (10 Hz) | JSON → Serial/WiFi     |

### Endpoints HTTP

#### GET /state

Retorna JSON con el estado completo del sistema (servo + péndulo + INA219):

```json
{
  "mode": 2,
  "count": 1024, "position_deg": 15.2, "setpoint_deg": 20.0, "error_deg": 4.8,
  "pend_count": -128, "pend_position_deg": -2.3, "pend_setpoint_deg": 0.0, "pend_error_deg": 2.3,
  "pwm": 45,
  "ina_ok": true, "v_bus": 11.8, "i_ma": 350.0, "p_mw": 4130.0
}
```

#### GET /cmd

| Parámetro                   | Tipo   | Descripción               |
| ---------------------------- | ------ | -------------------------- |
| `m`                        | 0–5   | Modo de operación         |
| `s`                        | float  | Setpoint servo (grados)    |
| `sp`                       | float  | Setpoint péndulo (grados) |
| `p`                        | int    | PWM manual (−255 a 255)   |
| `kp`, `ki`, `kd`       | float  | PID gains servo            |
| `kpp`, `kip`, `kdp`    | float  | PID gains péndulo         |
| `lqr1`–`lqr4`           | float  | LQR gains                  |
| `ke`                       | float  | Ganancia swing-up          |
| `bt`                       | float  | Umbral transición LQR     |
| `cpr`                      | float  | Counts per revolution      |
| `ed`                       | −1, 1 | Dirección encoder         |
| `z`                        | 1      | Zero position servo        |
| `zp`                       | 1      | Zero position péndulo     |
| `x`                        | 1      | Paro de emergencia         |
| `wifi_ssid`, `wifi_pass` | str    | Guardar credenciales WiFi  |
| `wifi_reconnect`           | 1      | Reconectar WiFi            |

### Comandos HTTP de uso frecuente

```bash
# Leer estado
curl -s http://192.168.4.1/state

# Modos: m0=stop, m1=PWM, m2=PID servo, m3=PID péndulo, m4=LQR, m5=swing-up
curl "http://192.168.4.1/cmd?m=2&s=20"        # PID servo, setpoint 20°
curl "http://192.168.4.1/cmd?m=4"              # LQR péndulo invertido
curl "http://192.168.4.1/cmd?m=5"              # Swing-up

# Ajustar PID servo
curl "http://192.168.4.1/cmd?kp=3.0&ki=0.5&kd=0.15"

# Ajustar PID péndulo
curl "http://192.168.4.1/cmd?kpp=15.0&kip=0.5&kdp=2.0"

# Ajustar LQR
curl "http://192.168.4.1/cmd?lqr1=1&lqr2=25&lqr3=0.5&lqr4=3"

# Swing-up
curl "http://192.168.4.1/cmd?m=5&ke=0.5&bt=20"

# Paro de emergencia
curl "http://192.168.4.1/cmd?x=1"
```

---

## Instructivo de Uso

Guía paso a paso para poner en funcionamiento el sistema completo.

### 1. Prerrequisitos

#### Software

| Herramienta                                  | Propósito                | Instalación                                   |
| -------------------------------------------- | ------------------------- | ---------------------------------------------- |
| **Python ≥ 3.12**                     | GUI y análisis de datos  | [python.org](https://www.python.org/downloads/)   |
| **[uv](https://docs.astral.sh/uv/)**      | Gestor de paquetes Python | `pip install uv`                             |
| **[PlatformIO](https://platformio.org/)** | Compilar firmware ESP32   | Extensión VSCode o `pip install platformio` |
| **Git**                                | Clonar repositorio        | [git-scm.com](https://git-scm.com/)               |

#### Hardware mínimo

| Componente                  | Estado mínimo                       |
| --------------------------- | ------------------------------------ |
| ESP32-WROOM-32              | Conectado por USB                    |
| Fuente 12 V (LiPo 3S o PSU) | Alimentando el BTS7960                 |
| BTS7960 + LM2596              | Regulador ajustado a 5 V             |
| Motor DC + encoder          | Conectado al BTS7960                   |
| CD40106BE + componentes RC  | Acondicionamiento de señal          |
| Encoder péndulo (opcional) | Solo para modos `m3`/`m4`/`m5` |
| INA219 (opcional)           | Solo para telemetría de potencia    |

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
2. Conectar solo el LM2596 a la fuente de 12 V
3. Medir con multímetro entre `OUT+` y `OUT−`
4. Girar el potenciómetro hasta leer **5.00 V** exactos
5. Recién conectar el ESP32 al pin `VIN`

> ⚠️ Nunca aplicar más de 5.5 V al pin `VIN` del ESP32.

---

### 4. Compilar y flashear el firmware

#### Opción A: PlatformIO (recomendado)

```bash
cd src/firmware
pio pkg install                   # Instalar dependencias
pio run                           # Compilar
pio run --target upload           # Flashear al ESP32
pio device monitor --baud 115200  # Monitor serie
```

#### Opción B: Arduino IDE

1. Abrir `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino`
2. **Tools → Board → ESP32 Arduino → ESP32 Dev Module**
3. Seleccionar puerto COM
4. Instalar librerías: `INA219_WE`, `ArduinoJson`, `AsyncTCP`, `ESPAsyncWebServer`
5. Click **Upload**
6. Abrir Monitor Serie a 115200 baud

#### Verificación

Al encender, el monitor serie debe mostrar:

```
=== QUBE ESP32 + BTS7960 + INA219 ===
[ENC] Servo   CNT=0   POS=0.00°
[ENC] Pendulo CNT=0   POS=0.00°
[INA219] V=11.8V  I=0mA  P=0mW
[WIFI] Conectado a: QUBE-ESP32  IP: 192.168.4.1
[MODO] Libre (m0)
```

---

### 5. Conexión WiFi

#### Modo AP (por defecto)

- **SSID:** `QUBE-ESP32` / **Pass:** `qube1234`
- **IP:** `192.168.4.1`
- Conectar tu PC/telefono directamente a la red del ESP32

#### Modo STA (Station)

- Editar `credentials.h` con tus credenciales y recompilar
- O configurar vía HTTP: `/cmd?wifi_ssid=Red&wifi_pass=Clave`
- Reconectar: `/cmd?wifi_reconnect=1`

> ⚠️ Las credenciales STA se guardan en NVS del ESP32. El archivo `credentials.h` está en `.gitignore`.

---

### 6. Modos de operación

| Modo   | Comando HTTP | Descripción                                   |
| ------ | ------------ | ---------------------------------------------- |
| `m0` | `/cmd?m=0` | Libre — motor deshabilitado, encoders activos |
| `m1` | `/cmd?m=1` | PWM manual —`/cmd?p=100`                    |
| `m2` | `/cmd?m=2` | PID posición servo —`/cmd?s=20`            |
| `m3` | `/cmd?m=3` | PID posición péndulo —`/cmd?sp=0`         |
| `m4` | `/cmd?m=4` | LQR péndulo invertido                         |
| `m5` | `/cmd?m=5` | Swing-up por energía                          |

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
3. **PWM** — señal de control (−255 a +255)
4. **Potencia** — corriente (mA) y voltaje bus (V) del INA219

**Panel de control:**

- Modo de operación (6 radios: STOP, PWM, PID Servo, PID Péndulo, LQR, Swing-up)
- Setpoint servo y péndulo (grados)
- PID gains servo y péndulo (Kp, Ki, Kd)
- LQR gains (K1–K4)
- Swing-up gains (ke, threshold)
- Zero Servo / Zero Péndulo / Reset / STOP
- Exportar CSV

---

### 8. Flujo típico de trabajo

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
│ 6. CALIBRAR PID      Ziegler-Nichols → Ku, Tu → ganancias   │
├─────────────────────────────────────────────────────────────┤
│ 7. MONITOREAR        GUI (make run) o curl /state           │
├─────────────────────────────────────────────────────────────┤
│ 8. REGISTRAR         Exportar CSV desde GUI                 │
└─────────────────────────────────────────────────────────────┘
```

---

### 9. Tests y desarrollo

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

### 10. Solución rápida de problemas

| Síntoma                           | Causa probable                     | Solución                                         |
| ---------------------------------- | ---------------------------------- | ------------------------------------------------- |
| `CNT` no cambia al girar encoder | Falta pull-up o Schmitt trigger    | Verificar pull-up 4.7 kΩ + Schmitt + RC          |
| Error de boot al usar GPIO34/35    | `INPUT_PULLUP` en pin input-only | Usar solo `INPUT` + pull-up externo             |
| PID diverge inmediatamente         | Motor invertido                    | Cambiar `MOTOR_DIR = -1` en firmware            |
| Derivativo oscila con ruido        | `Kd` demasiado alto              | Aumentar `alpha` del filtro EMA (0.12–0.20)    |
| ESP32 no responde por WiFi         | IP incorrecta                      | Verificar SSID/IP, usar modo AP `192.168.4.1`   |
| GUI no muestra datos               | IP mal configurada                 | Revisar `ESP32_IP` en `src/qube_ui/client.py` |
| `VIN` se calienta                | Voltaje > 5.5 V                    | Ajustar LM2596 a 5.00 V con multímetro           |
| Señal encoder ruidosa a alta RPM  | Filtro RC insuficiente             | Verificar 10 kΩ + 10 nF post-Schmitt             |

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
// En el firmware:
#define MOTOR_DIR  (-1)   // +1 o -1
```

O invertir cables `M+`/`M-` del BTS7960.

### 3. CPR (Counts Per Revolution)

```cpp
// Ajustar según tu encoder:
#define ENC_SERVO_CPR    2048
#define ENC_PENDULO_CPR  1024
```

### 4. Sintonización PID (Ziegler-Nichols)

1. `Ki = 0`, `Kd = 0`
2. Incrementar `Kp` hasta oscilación con amplitud constante → `Ku`
3. Medir período de oscilación → `Tu`
4. Calcular:

$$
K_p = 0.6 \cdot K_u \qquad K_i = \frac{2 K_p}{T_u} \qquad K_d = \frac{K_p \cdot T_u}{8}
$$

5. Ajustar `alpha` del filtro EMA si hay ruido en `Kd`.

---

## Resultados y Validación

### Comparativa de rendimiento

| Métrica                  | Arduino Uno + BTS7960      | ESP32 + BTS7960 (este proyecto) | Quanser QUBE |
| ------------------------- | ------------------------ | ----------------------------- | ------------ |
| Frecuencia de control     | ~100 Hz                  | **200 Hz**              | 1000 Hz      |
| Encoders simultáneos     | 1 (limitado)             | **2**                   | 2            |
| Telemetría de potencia   | No                       | **Sí (INA219)**        | Sí          |
| Conectividad inalámbrica | No                       | **WiFi + BLE**          | Ethernet     |
| Swing-up automático      | No                       | **Sí (modo 5)**        | Sí          |
| Costo                     | ~$35 USD | **~$70 USD** | ~$3,000 USD                   |              |

### Validación del encoder (post HW-FIX)

| Métrica         | Antes (sin acondicionamiento) | Después (Schmitt + RC)          |
| ---------------- | ----------------------------- | -------------------------------- |
| Señal encoder   | Ruido (~1.5 V indeterminado)  | Transiciones limpias 0 V / 3.3 V |
| `CNT` servo    | ±0 cambio/min                | +2048 counts/revolución         |
| `POS` servo    | 0.0° (fijo)                  | 0° → 360° → 0° continuo     |
| Convergencia PID | No (sin feedback)             | Sí (±2° en 2–3 s)            |

---

## Problemas Conocidos y Soluciones

### HW-FIX-1: Encoder open-drain sin acondicionamiento

**Síntoma:** `CNT` no actualiza aunque el eje gire.
**Causa:** Level shifter de alta impedancia (~7 MΩ) o pull-up insuficiente.
**Solución:** Pull-up 4.7 kΩ a 3.3 V + Schmitt trigger CD40106BE + filtro RC (10 kΩ / 10 nF).

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
**Solución:** `MOTOR_DIR = -1` en firmware o invertir cables M+/M-.

---

## Roadmap

- [X] Control PID posición servo (encoder 1)
- [X] Telemetría INA219 (V, I, P)
- [X] Fix acondicionamiento señal open-drain (HW-FIX-1)
- [X] Schmitt trigger CD40106BE para encoders (GPIO34/35)
- [X] Filtro RC post-Schmitt (10 kΩ / 10 nF) para cada canal
- [X] Swing-up por energía (modo 5)
- [X] WiFi STA no-bloqueante + credenciales gitignored
- [X] GUI con modos LQR y Swing-up
- [ ] Integración encoder péndulo (encoder 2) — **en progreso**
- [ ] Control PID posición péndulo (modo m3) — validación
- [ ] Control LQR péndulo invertido (modo m4) — validación
- [ ] Dashboard web en tiempo real (WebSocket)
- [ ] Logging en SPIFFS / tarjeta SD
- [ ] Identificación de parámetros del motor
- [ ] PCB Rev2.0 con acondicionamiento integrado

---

## Documentación Adicional

| Documento                | Ubicación                                                                | Descripción                                          |
| ------------------------ | ------------------------------------------------------------------------- | ----------------------------------------------------- |
| Arquitectura del sistema | [`docs/arquitectura.md`](docs/arquitectura.md)                             | Diagramas detallados, pinout completo, FreeRTOS tasks |
| Modelo físico           | [`docs/MODELO_FISICO_SISTEMA_QUBE.md`](docs/MODELO_FISICO_SISTEMA_QUBE.md) | Ecuaciones del motor, encoder, péndulo, PID y LQR    |
| Investigación           | [`docs/research/`](docs/research/)                                         | Papers, estado del arte, acondicionamiento de señal  |
| Validación científica  | [`docs/validation/`](docs/validation/)                                     | Marco científico, checklist, matriz de referencias   |
| Changelog                | [`CHANGELOG.md`](CHANGELOG.md)                                             | Historial de versiones del firmware                   |
| Experimentos             | [`experiments/`](experiments/)                                             | Datos CSV y notas de experimentos                     |

---

## Referencias

### Proyectos de referencia

- [Esp32CameraRover2 — Ezward](https://github.com/Ezward/Esp32CameraRover2) — Framework closed-loop ESP32
- [Rotary-Inverted-Pendulum — ebrahimabdelghfar](https://github.com/ebrahimabdelghfar/Rotary-Inverted-Pendulum) — LQR + Arduino
- [arduino_pid_controlled_motor — wty-yy](https://github.com/wty-yy/arduino_pid_controlled_motor) — PID + encoder documentado
- [INA219_WE](https://github.com/wollewald/INA219_WE) — Librería INA219 (activamente mantenida)

### Datasheets

- [BTS7960 — Infineon](https://www.infineon.com/dgdl/Infineon-BTS7960-DS-v01_00-en.pdf?fileId=5546d462518a448701518a525e3d3786)
- [LM2596 — Texas Instruments](https://www.ti.com/product/LM2596)
- [INA219 — Texas Instruments](https://www.ti.com/product/INA219)
- [CD40106B — Texas Instruments](https://www.ti.com/lit/ds/symlink/cd40106b.pdf)

### Papers académicos

- Akhtaruzzaman, M., & Shafie, A. A. (2010). Modeling and control of a rotary inverted pendulum using various methods. *IEEE ICMA 2010*. https://doi.org/10.1109/ICMA.2010.5589450
- STMicroelectronics. (2019). *Introduction to Integrated Rotary Inverted Pendulum* (v2).

### Documentación interna

- [Investigación CD40106BE](docs/research/ai_research/investigacion_cd40106be.md) — Schmitt trigger para acondicionamiento de señal
- [Estabilización de señales](docs/research/estabilizacion_senales.md) — Filtros y mitigación de ruido
- [CHANGELOG](CHANGELOG.md) — Historial de versiones del firmware

---

## Licencia

MIT License — ver [LICENSE](LICENSE) para detalles.

---

*Última actualización: 8 de junio, 2026*
