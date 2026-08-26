# Investigación Profunda: Estabilización de Señales en QUBE Servo ESP32
## Control de Ruido, Filtrado y Acondicionamiento para Retroalimentación Confiable

**Fecha de Investigación:** 2026-04-29  
**Contexto:** Post-implementación HW-FIX-1 (encoder open-drain + pull-ups); optimización de lazo de control  
**Objetivo:** Desarrollar estrategia integral de mitigación de ruido para mejorar precision de retroalimentación de encoder y confiabilidad de controlador PID

---

## TABLA DE CONTENIDOS

1. [Identificación de Fuentes de Ruido](#1-identificación-de-fuentes-de-ruido)
2. [Análisis de Filtros RC para Entradas de Encoder](#2-análisis-de-filtros-rc-para-entradas-de-encoder)
3. [Mitigación de Ripple de Power Supply](#3-mitigación-de-ripple-de-power-supply)
4. [Estrategia de Grounding (Star Ground)](#4-estrategia-de-grounding-star-ground)
5. [Timing Quadrature y Jitter](#5-timing-quadrature-y-jitter)
6. [Validación Experimental y Mediciones](#6-validación-experimental-y-mediciones)
7. [Recomendaciones de Componentes](#7-recomendaciones-de-componentes)
8. [Checklist de Implementación](#8-checklist-de-implementación)

---

## 1. Identificación de Fuentes de Ruido

### 1.1 Clasificación de Ruido en el Sistema

#### **Ruido de Alta Frecuencia (100 kHz – 20 MHz)**
**Origen:** Switching del L298N (PWM @ 20 kHz), LM2596 buck converter (switching ≈ 1.5 MHz)

- **Manifestación en encoder:** Transitorios RF acoplados a través de GND común, generan "jitter" en lectura
- **Amplitud típica:** 50–200 mV pico en líneas de GND
- **Impacto:** Falsos edges en decodificación cuadratura si threshold es cercano a jitter amplitude

**Mitigación esperada con filtro RC:** -20 dB/década después de fc

#### **Ruido de Baja Frecuencia (10 Hz – 10 kHz)**
**Origen:** Ripple de power supply (LM2596), transitorios de current transient cuando L298N cambia dirección

- **Manifestación en encoder:** Offset lentamente variable en líneas A/B, falsas transiciones si se usan thresholds muy ajustados
- **Amplitud típica:** 10–50 mV en 5V rail (0.2–1% ripple)
- **Impacto:** Indirecto (a través de variación de VDD → umbral GPIO fluctúa)

**Mitigación esperada:** Bypass capacitors locales de bajo ESR

#### **Ruido 1/f (Flicker Noise)**
**Origen:** Variaciones de temperatura, deriva lenta de componentes

- **Manifestación:** Drift lento de offset de encoder (0.1–1° por minuto)
- **Escala temporal:** Minutos a horas
- **Impacto:** Acumulación de error de posición integrado, sesgo de offset

**Mitigación:** Calibración periódica, offset tracking en firmware

#### **Ruido Impulsivo (Spikes)**
**Origen:** Commutación del motor DC (escobillas), switching abrupt del L298N, diodos de recuperación

- **Manifestación:** Pulsos de 100–500 ns de amplitud 0.5–2 V en cableado
- **Impacto:** Riesgo MÁS ALTO para decodificación cuadratura (edges falsos instantáneos)
- **Prevención:** RC filtering, shielded cables, ferrite clamps

---

### 1.2 Análisis Cuantitativo de Presupuesto de Ruido

#### Setup Actual (Post HW-FIX-1):
```
Fuente de ruido              | Amplitud típica | Frecuencia    | Atenuación objetivo
─────────────────────────────┼─────────────────┼───────────────┼─────────────────────
L298N PWM switching (20 kHz) | 100 mV pico     | 20 kHz ± 5kHz | -30 dB (factor 30×)
LM2596 switching (1.5 MHz)   | 50 mV pico      | 1.5 MHz       | -40 dB (factor 100×)
Motor brush commutation      | 200 mV pico     | Irregular     | -20 dB (factor 10×)
Power supply ripple (5V)     | 30 mV pico-p    | 100 Hz line   | -10 dB (factor 3×)
GPIO input noise floor       | 5 mV RMS        | 1 MHz BW      | Inherente
─────────────────────────────┴─────────────────┴───────────────┴─────────────────────

Objetivo combinado: 
  Total noise referido a GPIO ≤ 10 mV RMS 
  (corresponde a ±0.2° de incertidumbre en encoder, ≈1/5 de LSB)
```

---

## 2. Análisis de Filtros RC para Entradas de Encoder

### 2.1 Topología de Filtro RC Pasivo

#### **Primera Opción: RC Low-Pass (Simple)**

```
     Encoder A (open-drain)
            │
            ├──[R_filter]──┬─────── GPIO34
            │             │
           4.7k           ┴ C_filter
            │             │
            ├────────────GND
            │
     +3.3V  ┴ 4.7k pull-up
```

**Componentes típicos:**
- `R_filter = 1 kΩ` (en serie con el GPIO)
- `C_filter = 100 nF` (capacitor de filtro a GND)
- `R_pull_up = 4.7 kΩ` (existente, pull-up de 3.3V)

**Función de Transferencia:**
```
fc = 1 / (2π × R × C) = 1 / (2π × 1kΩ × 100nF) ≈ 1.59 kHz
```

**Características:**
- Atenuación @ 20 kHz (L298N PWM): -20 dB/década × 1.25 decades ≈ -25 dB (factor 17×) ✅
- Atenuación @ 1.5 MHz (LM2596): -40 dB/década × 3.7 decades ≈ -74 dB (factor 5000×) ✅
- Phase shift @ fc: -45°
- Phase shift @ 20 kHz: ≈ -87° (borde de Nyquist para quadrature @ tipicamente 5 ms polling)

**Respuesta al Step (Critical Analysis for Quadrature):**
```
Rise time (10%-90%): τ ≈ 0.35 / fc ≈ 0.22 ms = 220 µs
Settling time (0.5% tolerance): ≈ 5τ ≈ 1.1 ms

Max motor speed (Premotec @ 18V, sin carga): ~400 RPM = ~6.67 RPS
Encoder period @ 2048 CPR: T_period = 1 / (2048 × 6.67) ≈ 73 µs
Quadrature edge spacing: Δt ≈ 18 µs (1/4 period)

ISSUE: Settling time de 1.1 ms >> 18 µs entre edges
→ Quadrature decoder vería "falsos" edges durante ringing de RC
```

**Conclusión:** RC simple de 1 kΩ / 100 nF es demasiado lenta para cuadratura X4

---

#### **Opción Mejorada: RC Optimizado de Atenuación Media**

```
R_filter = 470 Ω
C_filter = 100 nF
fc = 1 / (2π × 470Ω × 100nF) ≈ 3.4 kHz
```

**Características revisadas:**
- Atenuación @ 20 kHz: -20 dB/década × 0.77 decades ≈ -15 dB (factor 5.6×) ⚠️ Marginal
- Atenuación @ 1.5 MHz: ≈ -62 dB (adecuado)
- Rise time (10%-90%): ≈ 100 µs ✅ (< 18 µs quadrature spacing, MARGINAL)

**Ventaja:** Transitorios más rápidos, menor riesgo de false edges

---

#### **Opción Recomendada: Active Buffer con Schmitt Trigger**

**Topología recomendada para máxima integridad:**

```
     Encoder A (open-drain)
            │
            ├──[4.7kΩ]────┬─────────┬────────────┐
            │             │        │            │
           GND           4.7k    100nF      [SN74LVC1G17] Schmitt Trigger Buffer
            │             │        │        (push-pull CMOS)
            ├────────────GND       │            │
            │                      │            └────── GPIO34 (clean digital)
            ├── +3.3V             GND
            │    (pull-up)
```

**Componentes:**
- Pull-up: 4.7 kΩ a 3.3 V (existente)
- Filtro RC previo: 470 Ω en serie + 100 nF a GND (atenúa spike RF)
- Buffer Schmitt Trigger: SN74LVC1G17 (8 pines, single gate, hysteresis ≈ 0.5V)

**Ventajas:**
- ✅ Schmitt trigger elimina metastabilidad incluso con ringing lento
- ✅ Salida push-pull limpia (no open-drain)
- ✅ Hysteresis previene false edges de ruido de baja amplitud
- ✅ Buffering activo restaura slew rate rápido (< 5 ns rise time)

**Desventajas:**
- Requiere chip adicional (pero bajo costo ~$0.30)
- Consumo insignificante (< 1 mA static)

**Recomendación: Implementar esta topología en PCB Rev2.0**

---

### 2.2 Análisis de Filtro Digital Complementario

#### **Majority Voting (Software)**

Si se usa polling en lugar de interrupts, se puede implementar:

```cpp
// En updateEncoderPolling():
// Capturar estado 3 veces consecutivas con pequeño delay
int a1 = digitalRead(PIN_ENC_A);  // Muestra 1
delayMicroseconds(5);
int a2 = digitalRead(PIN_ENC_A);  // Muestra 2
delayMicroseconds(5);
int a3 = digitalRead(PIN_ENC_A);  // Muestra 3

int a_filtered = (a1 + a2 + a3 >= 2) ? 1 : 0;  // Voting
```

**Ventajas:**
- Sin componentes adicionales
- Suprime spikes de 5-10 µs
- Reduce jitter de ±1 LSB a ±0

**Desventajas:**
- Overhead computacional (3× lectura de GPIO)
- Latencia adicional de ~10 µs (tolerable si control period es > 100 µs)

**Recomendación:** Implementar si disponible CPU headroom

---

## 3. Mitigación de Ripple de Power Supply

### 3.1 Análisis Actual de LM2596 y 5V Rail

#### **Características del LM2596:**
- Voltaje de entrada típico: 12–18 V (batería vehicular)
- Voltaje de salida: 5 V (regulated)
- Corriente de salida máx: 3 A
- Frecuencia de switching: ≈ 1.5 MHz (típica)
- Ripple de salida sin filtrado: 50–100 mV pico-a-pico (specs típicas del LM2596)

#### **Impacto en ESP32 y Encoders:**
```
VDD_ESP32 = 5V ± 50mV (1% ripple)
└─ Regulator interno de 3.3V: 5V → 3.3V (lineal o buck)
   └─ VDD_GPIO = 3.3V ± 10–20mV (adicional ripple)

Si GPIO tiene 5mV de ripple, y Schmitt trigger hysteresis es 0.5V:
└─ Margen de ruido = 0.5V / 5mV = 100× → Seguro
```

**Conclusión:** Ripple de LM2596 NO ES CRÍTICO si se implementa bypass adecuado

### 3.2 Diseño de Red de Bypass Capacitivos

#### **Arquitectura Recomendada de Power Distribution:**

```
[12-18V Fuente] 
    │
    ├── [LM2596] ──→ 5V Output
    │
    ├── C_bulk_5V (470 µF, ESR < 0.2Ω)
    ├── C_bulk_5V (100 µF, ESR < 0.1Ω)
    ├── C_bypass_5V (10 µF, ceramic X7R, ESR < 0.05Ω)
    └── C_bypass_5V (100 nF, ceramic X7R × 4 unidades)
            │
            ├─→ [ESP32 VDD]
            │   ├── C_local_esp32 (10 µF ceramic)
            │   └── C_local_esp32 (100 nF × 2)
            │
            ├─→ [INA219 VIN]
            │   └── C_local_ina (100 nF)
            │
            └─→ [L298N GND / +5V]
                ├── C_motor_5v (100 µF, ESR < 0.1Ω)
                └── C_motor_5v (100 nF × 2)
```

**Valores y Rationale:**

| Capacitor | Valor | Tipo | ESR máx | Ubicación | Propósito |
|---|---|---|---|---|
| C_bulk_1 | 470 µF | Aluminum electrolytic | 0.2 Ω | Salida LM2596 | Almacenamiento de carga, ripple baja frecuencia |
| C_bulk_2 | 100 µF | Aluminum electrolytic | 0.1 Ω | Cerca C_bulk_1 | Redundancia + ESR más bajo |
| C_bypass_10u | 10 µF | Ceramic X7R | 0.05 Ω | Placa cerca ESP32 | Transitorios de current fast (µs) |
| C_bypass_100n | 100 nF | Ceramic X7R × 4 | 0.02 Ω c/u | Disperso en PCB | Atenuación de ripple > 100 kHz |
| C_local_esp32 | 10 µF | Ceramic X7R | 0.05 Ω | Pin VDD ESP32 | Desacoplamiento local |
| C_local_esp32_2 | 100 nF | Ceramic X7R × 2 | 0.02 Ω | Pins VDD ESP32 | Ripple HF |
| C_ina219 | 100 nF | Ceramic X7R | 0.02 Ω | Pin VIN INA219 | Desacoplamiento sensor |
| C_motor | 100 µF | Aluminum | 0.1 Ω | L298N input | Absorber transitorios motor |
| C_motor_bypass | 100 nF | Ceramic × 2 | 0.02 Ω c/u | L298N input | Ripple HF motor |

**Impedancia de Plano Total (objetivo):**
```
Zmax = 1 / (ωC) where ω = 2π × f

@ 1.5 MHz (LM2596 switching):
  Z = 1 / (2π × 1.5M × 100n) ≈ 1 Ω ← Adecuado (< 10 Ω target)

@ 20 kHz (L298N PWM):
  Z = 1 / (2π × 20k × 100µ) ≈ 0.08 Ω ← Excelente
```

**Implementación Práctica:**
1. Colocar C_bulk tan cerca como sea posible del pin de salida del LM2596
2. Usar vías múltiples (≥ 2) desde cada capacitor a planos de 5V y GND
3. Dispersar los 100 nF cerca de cada consumidor principal (ESP32, INA219, L298N)
4. NO crear "stubs" largos; enrutar en paralelo al plano principal

---

### 3.3 Ferrite Bead para Ruido de Alta Frecuencia

#### **Alternativa/Complemento a RC Filter:**

```
5V Output (LM2596)
    │
    ├── [Ferrite Bead, Z @ 100MHz ≈ 1000Ω]
    │   (típ: FB-1206P800 o similar 0805, Impedancia 800Ω @ 100MHz)
    │
    ├── C_bulk, C_bypass
    │
    └── ESP32 & Co.
```

**Selectores de Ferrite Bead:**
- **FB-1206P800** (SMD 0805): Z=800Ω @ 100MHz, muy usado, bajo costo
- **BLM21BD600** (Murata): Z=600Ω @ 100MHz, menor atenuación
- **FB-1206P1000** (SMD 0805): Z=1000Ω @ 100MHz, máxima atenuación

**Ventaja sobre RC:**
- No introduce fase lenta (RC introduce -90° @ fc, ferrite tiene characteristics plana en banda)
- Adecuado para transitorios rápidos
- No afecta respuesta step de encoder (fc >> 1.5 MHz)

**Recomendación:** Usar ferrite bead EN SERIE CON 5V output del LM2596 + bypass capacitors

---

## 4. Estrategia de Grounding (Star Ground)

### 4.1 Conceptos de Star Ground

**Problema de Grounding Convencional:**
```
Topología MALA (Ground loops):
┌─────────────────────────────────────────┐
│  Motor +  ────→ [L298N] ──→ Motor -     │
│       │                          │      │
│   [GND 1] ────────────┬──────── [GND 2]│  ← Loop: iL × Rline ↑↓ en todas las señales
│                       │                 │
│       [ESP32] ←──[GND 3]               │
└─────────────────────────────────────────┘
                ↑
        Múltiples caminos GND
        → corriente de motor circulating
        → induce voltaje en GND de encoder
        → ruido acoplado a señales lógicas
```

**Topología BUENA (Star Ground):**
```
┌─────────────────────────────────────────┐
│                                         │
│  Motor + ────→ [L298N] ──→ Motor -     │
│   |                             |      │
│   └─────→ [GND] ←─────────────└       │  ← Return directo
│              ▲ (STAR POINT)            │
│              │                         │
│         [LM2596] Common                │
│         (todas las corrientes          │
│          retornan en un punto)         │
│              ▲                         │
│              │                         │
│    [ESP32 GND] ←─────────────┐        │
│    [INA219 GND] ←───┐        │        │
│    [Encoder GND]    └────────┘        │
│                                         │
└─────────────────────────────────────────┘
```

### 4.2 Implementación Física para QUBE

#### **Paso 1: Identificar Star Point**

- **Star Point físico:** Pad de GND en el LM2596 (entrada común, donde todas las corrientes se regresan)
- **Conexiones radiantes desde Star:**
  1. Motor GND (-) → LM2596 GND
  2. L298N GND → LM2596 GND (vía corta, grosor de cable > 1 mm²)
  3. ESP32 GND pin (analógico) → LM2596 GND
  4. INA219 GND → LM2596 GND
  5. Encoder GND → LM2596 GND (opcionalmente con resistencia de amortiguamiento 100Ω)

#### **Paso 2: Evitar Loops de GND**

```
INCORRECTO (no hacer):
ESP32 GND ──→ L298N GND ──→ Motor GND ──→ LM2596 GND
(serie de GND connections)

CORRECTO (hacer):
ESP32 GND ──┐
L298N GND ──┼─→ LM2596 GND (STAR)
Motor GND ──┤
Encoder GND─┘
(todas radiantes desde star point)
```

#### **Paso 3: Gestión de Retorno de Corriente de Motor**

La corriente del motor (~2 A pico) fluye:
```
Batería(+) → LM2596 → Motor(+) → [Motor] → Motor(-) → L298N GND → LM2596 GND → Batería(-)
```

**Critical path:** Motor(-) → L298N GND → LM2596 GND
- Resistencia máxima permitida: R < V_drop / I = 0.1V / 2A = 0.05 Ω
- Cable recomendado: AWG 16 (0.5-1 mm²) mínimo, no más de 20 cm

**Impacto de no hacerlo:**
- Si Rmotorgnd = 0.1 Ω y I = 2 A → V_drop = 0.2 V
- Este offset aflecta el GND de referencia de los ADC del ESP32
- Encoder reading drifts de ±5° o más debido a threshold shift

---

### 4.3 Gestión de Ruido Diferencial de Señal

#### **Para Encoder A/B:**

```
Encoder lado:
A/B ──┬─→ GPIO34/35
      │
      └─→ GND (Encoder GND)

Mejor práctica: Retornar Encoder GND directamente a Star Point CON capacitor local:
A/B ──┬─→ GPIO34/35
      │
      └─→ [C_filter 100nF] ──→ GND Local (cerca del connector)
                                   │
                                   └─→ [R_damping 100Ω] ──→ Star Point GND
```

**Resistor de amortiguamiento (100Ω):**
- Reduce transitorios de corriente cuando Encoder se conecta/desconecta
- Acopla low impedance localmente (C_filter) pero previene ground bounce en cambios abruptos
- Costo: ~0.5V @ 5mA (negligible)

---

## 5. Timing Quadrature y Jitter

### 5.1 Análisis de Jitter en Decodificación Cuadratura

#### **Fuentes de Jitter:**

1. **Timing Jitter del Encoder Mecánico** (inherente)
   - Motor DC con escobillas tiene commutación irregular
   - Encoder integrado en motor → pequeña variación en timing de edges (±5-10 µs típico)
   - Impacto: error de posición acumulado 0.1–1° por revolución

2. **Software Polling Jitter**
   - Control loop corre en main() con timer software
   - Interrupts del WiFi/BLE pueden causar jitter de ±10-100 µs en polling
   - Impacto: edges pueden ser leídos out-of-order en casos extremos

3. **Propagation Delay del Filtro RC**
   - Introduce delay correlacionado en A y B (pequeño si mismo RC)
   - Puede invertir fase relativa de A vs B en transiciones

#### **Estrategia de Medición:**

Si acceso a oscilloscopio:
```
1. Capturar ambos canales (Encoder A, Encoder B) @ 100 MS/s (10 ns resolution)
2. Motor corriendo a velocidad constante (ej. 50 RPM)
3. Medir rise/fall time de cada edge: Δt_rise / Δt_fall
   → Objetivo: < 100 ns (< 5% de edge spacing @ 2048 CPR)
4. Medir skew entre A y B (diferencia en timing de edges)
   → Objetivo: < 50 ns
5. Medir ripple de power supply (5V rail) mientras motor corre
   → Objetivo: < 50 mV pico-a-pico
```

#### **Sin Oscilloscopio (Estimación de Software):**

```cpp
// En updateEncoderPolling(), capturar timestamps:
if (oldA != newA || oldB != newB) {
  uint32_t now = micros();
  uint32_t dt_since_last_edge = now - lastEdgeTime;
  lastEdgeTime = now;
  
  // Si dt_since_last_edge < 5 µs → probablemente false edge (ruido)
  if (dt_since_last_edge < 5) {
    // Descartar o aplicar votación mayoritaria
    skipThisEdge = true;
  }
}
```

### 5.2 Análisis de Capacidad de Muestreo Temporal

#### **Period de Polling Actual (v1.14.0):**
```
// Estimado a partir de loop() timing:
// Si CONTROL_PERIOD_US = 5000 µs (5 ms):
//   f_polling = 1 / 5ms = 200 Hz

// Max motor speed teórico: 400 RPM = 6.67 RPS
// Encoder @ 2048 CPR: 6.67 × 2048 = 13,653 edges/sec

// Nyquist: f_polling debe ser > 2 × 13,653 = 27,306 Hz
// ACTUAL: 200 Hz << 27,306 Hz → ALIAS CRÍTICO!
```

**¡PROBLEMA IDENTIFICADO!** Si el polling es lento, la cuadratura puede no capturar todos los edges.

#### **Solución Recomendada:**

```cpp
// OPCIÓN A: Aumentar freq de polling a ≥ 1 kHz (1 ms period)
// → Usa interrupción del timer (Timer0/Timer1 del ESP32)
#define CONTROL_PERIOD_US 1000  // 1 kHz

// OPCIÓN B: Activar interrupts del encoder (USE_ENCODER_INTERRUPTS = true)
// → Captura garantizada en cada edge, sin alias
attachInterrupt(PIN_ENC_A, isr_enc_a, CHANGE);
attachInterrupt(PIN_ENC_B, isr_enc_b, CHANGE);

// OPCIÓN C: Usar PCNT (Pulse Counter) del ESP32
// → Hardware counter, no requiere ISR en software
// Típicamente 0-32 bits, evento en overflow
```

**Recomendación para v1.15.0+:** Cambiar a USE_ENCODER_INTERRUPTS = true (sin cambiar USE_ENCODER_POLLING) → captura dual (polling respaldo, interrupts primario)

---

## 6. Validación Experimental y Mediciones

### 6.1 Protocolo de Medición Recomendado

#### **Test 1: Respuesta al Step de Posición**

```
Procedimiento:
1. Modo manual (m1): esperar motor en reposo
2. Aplicar PWM fijo: p100 durante 2 segundos
3. Capturar telemetría JSON @ 10 Hz (~20 muestras)
4. Detener (p0)
5. Medir: acceleration profile, settling time, overshoot

Métricas esperadas (post-fix):
  Rise time (10%-90%): 0.5–1.5 seg
  Settling time (±2°): < 3 seg
  Overshoot: < 10°
  Ripple @ estacionario: ±3–5°
```

#### **Test 2: Ruido de Posición en Setpoint Constante**

```
Procedimiento:
1. PID mode (m2): s0 (setpoint 0°)
2. Capturar 60 segundos de telemetría
3. Calcular:
   - Mean: E[POS]
   - Std Dev: σ[POS]
   - Min/Max excursion
   - ACF (autocorrelation function) para detectar periodicidad

Métricas esperadas (post-fix):
  σ[POS] < 2° (ruido RMS)
  No periodicidad @ 20 kHz (L298N PWM)
  Sin drift > 1° per 60 sec
```

#### **Test 3: Transiente Rápido**

```
Procedimiento:
1. PID mode (m2): s0
2. Cambiar setpoint: s90 en t=0
3. Capturar transiente completo hasta settling
4. Medir:
   - Time to 63.2% (τ): ~1 / Kp estimate
   - Time to 90%: ~3τ
   - Overshoot: peak - setpoint

Métricas esperadas (post-Kp=0.75):
  Time to 63.2%: 0.8–1.2 seg (Kp auth. ↑)
  Time to 90%: 2.5–3.5 seg
  Overshoot: 5–15° (acceptable para educacional)
```

#### **Test 4: Ripple de Power Supply (si acceso a multímetro)**

```
Procedimiento:
1. Modo PID activo (m2)
2. Motor girando @ 50 RPM constant
3. Medir 5V rail con multímetro en AC coupling
4. Grabar durante 10 seg, anotar pico-a-pico

Métrica esperada:
  Ripple @ 5V rail < 100 mV pico-a-pico (2% tolerance)
```

---

### 6.2 Checklist de Medición Hardware (Oscilloscopio)

Si disponible:

```
□ Canal 1: Encoder A (GPIO34)
□ Canal 2: Encoder B (GPIO35)
□ Trigger: Rising edge en Encoder A

Capturar 10 transiciones consecutivas:
  ✓ Rise/Fall time de A
  ✓ Rise/Fall time de B
  ✓ Skew entre A y B
  ✓ Overshoot / Ringing
  ✓ Ruido HF durante transición
  
Canal 3 (si disponible): 5V rail
  ✓ Ripple peak-to-peak
  ✓ Forma de onda (serra triangular típica de buck)
  
Medidas recomendadas:
  - A @ motor speed 50 RPM, 100 RPM, 200 RPM, 400 RPM
  - Comparar antes/después de instalar RC filter
  - Comparar con/sin ferrite bead
```

---

## 7. Recomendaciones de Componentes

### 7.1 Lista de Compra (BOM) para Hardening de Señal

#### **Opción Mínima (Implementación Rápida):**

| Componente | Valor | Cantidad | Costo Est. (USD) | Función |
|---|---|---|---|---|
| Resistor | 4.7 kΩ 1/4W | 2 | $0.02 | Pull-up encoder (existente) |
| Resistor | 470 Ω 1/4W | 2 | $0.04 | Serie con GPIO (RC filter) |
| Capacitor | 100 nF ceramic X7R | 5 | $0.10 | Bypass / filtro |
| Capacitor | 10 µF ceramic X7R | 1 | $0.10 | Desacoplamiento local |
| **Total Mínimo** | - | - | **$0.26** | Mejora ruido ~-15 dB |

#### **Opción Recomendada (Máxima Estabilidad):**

| Componente | Valor | Cantidad | Costo Est. (USD) | Función |
|---|---|---|---|---|
| Resistor | 4.7 kΩ 1/4W | 2 | $0.02 | Pull-up encoder |
| Resistor | 470 Ω 1/4W | 2 | $0.04 | RC pre-filter |
| Resistor | 100 Ω 1/4W | 1 | $0.02 | GND damping |
| Capacitor | 100 nF ceramic X7R | 8 | $0.16 | Bypass estratégicos |
| Capacitor | 10 µF ceramic X7R | 3 | $0.30 | Desacoplamiento local |
| Capacitor | 100 µF aluminum | 2 | $0.20 | Bulk ripple (5V rail) |
| Capacitor | 470 µF aluminum | 1 | $0.30 | Bulk ripple principal |
| Ferrite Bead | FB-1206P800 | 1 | $0.15 | Atenuación HF LM2596 |
| IC Buffer | SN74LVC1G17 | 1 | $0.30 | Schmitt trigger A/B (optional) |
| **Total Recomendado** | - | - | **$1.49** | Mejora ruido ~-30 to -40 dB |

#### **Opción Full Stack (Máxima Robustez + EMI):**

Incluye:
- Todo de Opción Recomendada +
- Shielded twisted-pair cable para encoder (1 m)
- Ferrite clamp para motor power wires
- Separated analog/digital planes en PCB
- **Total: ~$4-5**

---

### 7.2 Proveedores y Alternativas de Componentes

**Resistores / Capacitores (genéricos):**
- Digikey, Mouser, Amazon Basics
- Cualquier 1/4W metal film para resistores
- Cualquier X7R ceramic para bypass (evitar Y5V si posible, tienen mala estabilidad temp)

**Ferrite Bead:**
- Murata BLM21BD600 (recomendado)
- TDK FB-1206P800
- Würth 742 792 series

**IC Buffer Schmitt Trigger:**
- Texas Instruments SN74LVC1G17 (recommended, pinout simple)
- NXP 74LVC1G17 (equivalente)
- Disponible en 8-pin DIP o SMD TSOP8

---

## 8. Checklist de Implementación

### 8.1 Hardware Changes (PCB Rev2.0 o wire-wrap)

**Phase 1: Minimal (1-2 horas)**
- [ ] Remover level shifter (ya hecho en HW-FIX-1)
- [ ] Verificar pull-ups 4.7 kΩ en A/B a 3.3V (ya hecho)
- [ ] Agregar capacitores bypass 100 nF cerca ESP32 VDD (2 unidades)
- [ ] Agregar capacitor 100 µF en 5V rail cerca LM2596 output

**Phase 2: Medium (3-4 horas)**
- [ ] Agregare resistencias serie 470 Ω en encoder A y B (entre pull-up y GPIO)
- [ ] Agregar capacitor 100 nF en serie con resistencia (RC filter)
- [ ] Implementar Star Ground desde LM2596 common
- [ ] Re-cable motor (-) y L298N GND con cable grueso (< 0.05 Ω)
- [ ] Medir ripple de 5V rail (debe ser < 50 mV pico-a-pico)

**Phase 3: Advanced (PCB layout, 6-8 horas)**
- [ ] Diseñar PCB Rev2.0 con separated analog/digital planes
- [ ] Incluir SN74LVC1G17 Schmitt trigger buffer para encoder A/B
- [ ] Agregar ferrite bead en 5V output del LM2596
- [ ] Aumentar poly frequency del ESP32 a ≥ 1 kHz (cambiar CONTROL_PERIOD_US a 1000)

---

### 8.2 Firmware Changes (v1.15.1+)

**Priority 1: Enable Encoder Interrupt Mode**
```cpp
const bool USE_ENCODER_INTERRUPTS = true;   // Was: false
const bool USE_ENCODER_POLLING = true;      // Keep both for robustness

// Añadir ISR handlers:
void IRAM_ATTR isr_enc_a() {
  updateEncoderPolling();  // Dispara decodificación cuadratura
}

void IRAM_ATTR isr_enc_b() {
  updateEncoderPolling();  // Dispara decodificación cuadratura
}

// En setup():
attachInterrupt(PIN_ENC_A, isr_enc_a, CHANGE);
attachInterrupt(PIN_ENC_B, isr_enc_b, CHANGE);
```

**Priority 2: Optional Digital Majority Voting**
```cpp
// Si CPU headroom disponible, agregar voting en updateEncoderPolling()
int a1 = digitalRead(PIN_ENC_A);
delayMicroseconds(3);  // Pequeño delay
int a2 = digitalRead(PIN_ENC_A);
int a_filtered = (a1 == a2) ? a1 : lastA;  // Consenso o mantiene anterior
```

**Priority 3: Increase Polling Frequency (si no se usan interrupts)**
```cpp
// Cambiar en setup():
#define CONTROL_PERIOD_US 1000  // De 5000 µs a 1000 µs → 1 kHz polling
```

**Priority 4: Telemetry Expansion (debugging)**
```cpp
// Agregar en telemetry JSON:
"enc_edge_interval_us": lastEdgeInterval,  // Time between encoder edges
"enc_noise_flags": encoderNoiseCount,      // Count of filtered edges
"pwm_5v_ripple_mv": estimated_ripple,      // Calc from ADC noise
```

---

### 8.3 Testing & Validation Plan

**Week 1: Hardware Modification**
- [ ] Implement Phase 1 + Phase 2 changes
- [ ] Measure ripple, verify test 1 (response step)
- [ ] Verify test 2 (noise at setpoint)

**Week 2: Firmware Updates**
- [ ] Implement Priority 1 + Priority 2 (ISR + voting)
- [ ] Test at 1 kHz polling rate
- [ ] Run test 3 (rapid transient)

**Week 3: Advanced Optimization**
- [ ] Design PCB Rev2.0 with Schmitt trigger
- [ ] Validate with oscilloscope (if available)
- [ ] Final telemetry validation over 1-hour continuous run

---

## APÉNDICE: Referencias y Recursos

### A.1 Documentación de Componentes

- **LM2596 Datasheet:** ti.com/product/LM2596
- **ESP32-WROOM-32 Datasheet:** esp32.com/docs
- **L298N Driver Module:** st.com/content/st_com/en/products/motor-drivers/stepper-motor-drivers/l298
- **INA219 Datasheet:** ti.com/product/INA219
- **SN74LVC1G17 Datasheet:** ti.com/product/SN74LVC1G17

### A.2 Libros y Papers Recomendados

1. "High-Speed Digital Design: A Handbook of Black Magic" - Howard W. Johnson & Martin Graham
   - Cap 5: Transmission Lines and Digital Signals
   - Cap 7: Grounding and Power Distribution

2. "Analog Circuit Design: Discrete and Integrated" - Walt Kester
   - Cap 4: Analog Signal Conditioning

3. "The Art of Electronics" - Paul Horowitz & Winfield Hill
   - Cap 5: Operational Amplifiers
   - Cap 13: Digital Logic

### A.3 Online Resources

- Analog Devices Filter Design Tool: www.analog.com/designtools
- TI Signal Conditioning App Note: ti.com/lit/an/slya013
- Arduino Encoder Library Documentation: arduino.cc/reference

---

## CONCLUSIONES

La estabilización integral de señales para QUBE Servo requiere un enfoque multi-capa:

1. **Topología de Señal**: Open-drain encoder + pull-ups de 4.7 kΩ a 3.3V (ya implementado)
2. **Filtrado Activo**: Schmitt trigger buffer + RC prefilter (recomendado para Rev2.0)
3. **Power Distribution**: Star grounding + bypass capacitors estratégicos (fase 2)
4. **Software Robustez**: ISR + majority voting + telemetría de diagnóstico (v1.15.1+)
5. **Validación Experimental**: Mediciones de timing, ripple, y respuesta transiente

**Impacto Esperado:**
- Ruido de encoder: -15 a -40 dB (depende de nivel de implementación)
- Estabilidad de PID: Convergencia suave sin oscillación bang-bang
- Confiabilidad operacional: > 99% uptime sin dropout de encoder

**Timeline:**
- Fase 1 (minimal): Implementable en 1-2 horas, mejora ~50%
- Fases 1+2 (medium): 4-6 horas total, mejora ~80%
- Fases 1+2+3 (full): Requiere PCB redesign, mejora ~95%

---

**Documento preparado:** 2026-04-29  
**Version:** 1.0  
**Revisor:** Sistema de investigación QUBE  
**Próxima actualización:** Después de implementación Phase 2 (experimental data)
