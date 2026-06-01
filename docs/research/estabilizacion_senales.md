# Investigación: Estabilización de Señales en QUBE Servo ESP32

**Fuente:** `old resources/SIGNAL_STABILIZATION_INVESTIGATION.md` (2026-04-29)  
**Objetivo:** Desarrollar estrategia integral de mitigación de ruido para mejorar precisión de retroalimentación de encoder y confiabilidad del controlador PID

---

## 1. Fuentes de Ruido Identificadas

### 1.1 Clasificación por Frecuencia

| Tipo | Frecuencia | Origen | Amplitud típica | Impacto |
|------|-----------|--------|----------------|---------|
| Alta (RF) | 100 kHz–20 MHz | L298N PWM (20 kHz), LM2596 (1.5 MHz) | 50–200 mV pico | Jitter en decodificación cuadratura |
| Baja | 10 Hz–10 kHz | Ripple LM2596, transientes L298N | 10–50 mV | Offset en líneas A/B |
| 1/f (Flicker) | < 1 Hz | Variación térmica, deriva componentes | 0.1–1°/min | Drift de posición |
| Impulsivo | 100–500 ns | Conmutación motor DC (escobillas) | 0.5–2 V | **Riesgo mayor**: edges falsos en cuadratura |

### 1.2 Presupuesto de Ruido

| Fuente | Amplitud | Frecuencia | Atenuación objetivo |
|--------|----------|------------|---------------------|
| L298N PWM | 100 mV pico | 20 kHz ±5 kHz | -30 dB (factor 30×) |
| LM2596 | 50 mV pico | 1.5 MHz | -40 dB (factor 100×) |
| Motor brush | 200 mV pico | Irregular | -20 dB (factor 10×) |
| Ripple 5V rail | 30 mV p-p | 100 Hz | -10 dB (factor 3×) |

**Objetivo combinado:** Ruido referido a GPIO ≤ 10 mV RMS (±0.2° de incertidumbre en encoder)

---

## 2. Filtros RC para Entradas de Encoder

### 2.1 Topología Simple (No Recomendada)

```ascii
Encoder A ──┬──[R_filter=1kΩ]──┬──── GPIO34
            │                  │
           4.7k                ┴ C_filter=100nF
            │                  │
            ├─────────────────GND
            │
      +3.3V ┴ 4.7k pull-up
```

**fc = 1 / (2π × 1kΩ × 100nF) ≈ 1.59 kHz**  
**Rise time ≈ 220 µs >> 18 µs spacing entre edges de cuadratura**  
**Conclusión:** ❌ Demasiado lento para cuadratura X4

### 2.2 RC Optimizado (Alternativa)

- `R_filter = 470 Ω`, `C_filter = 100 nF`
- `fc ≈ 3.4 kHz`
- Atenuación @ 20 kHz: ~ -15 dB (factor 5.6×) ⚠️ Marginal
- Rise time ≈ 100 µs (comparable al spacing de cuadratura)

### 2.3 Topología Recomendada: Schmitt Trigger Buffer

```
Encoder A ──┬──[4.7kΩ]────┬──────────────────┬─────────┐
            │             │          │       │         │
           GND           4.7k      100nF   [SN74LVC1G17]
            │             │          │     Schmitt Trigger
            ├────────────GND         │         │
            │                       GND        └──── GPIO34
            ├── +3.3V (pull-up)
```

**Ventajas:**
- ✅ Schmitt trigger elimina metastabilidad (hysteresis ≈ 0.5 V)
- ✅ Salida push-pull limpia, slew rate < 5 ns
- ✅ Hysteresis previene false edges por ruido de baja amplitud
- **Costo:** ~$0.30 por chip

---

## 3. Mitigación de Ripple de Power Supply

### 3.1 Red de Bypass Capacitivos Recomendada

```
[12-18V Fuente] → [LM2596] → 5V Output
                   │
                   ├── C_bulk_5V (470 µF, ESR < 0.2Ω)
                   ├── C_bulk_5V (100 µF, ESR < 0.1Ω)
                   ├── C_bypass_5V (10 µF, ceramic X7R)
                   └── C_bypass_5V (100 nF × 4)
                           │
                  ┌────────┴────────┐
                  │                 │
            [ESP32 VDD]      [INA219 VIN]
          C_local_10µF      C_local_100nF
          C_local_100nF×2
```

### 3.2 Ferrite Bead para Ruido HF

```
5V Output (LM2596) → [Ferrite Bead, Z@100MHz≈800Ω] → ESP32 & Co.
```

Recomendado: FB-1206P800 (SMD 0805) o Murata BLM21BD600

---

## 4. Estrategia de Grounding (Star Ground)

### 4.1 Topología Incorrecta (Ground Loops)

```
Motor + ──→ [L298N] ──→ Motor -
    │                         │
[GND 1] ─────────┬──────── [GND 2]  ← Loop: corrientes circulan por GND común
                 │
         [ESP32] ←──[GND 3]
```

### 4.2 Topología Correcta (Star Ground)

```
ESP32 GND ──┐
L298N GND ──┼─→ LM2596 GND (STAR POINT)
Motor GND ──┤
Encoder GND─┘
```

**Requerimiento:** Resistencia de retorno motor: R < 0.1V / 2A = 0.05 Ω → cable AWG 16 mínimo

---

## 5. Análisis de Jitter y Capacidad de Muestreo

### 5.1 Problema de Alias con Polling

- Frecuencia de polling actual: **200 Hz**
- Frecuencia máxima de encoder (2048 CPR @ 400 RPM): **13,653 edges/s**
- **Nyquist requerido: f_polling > 27,306 Hz**
- **Actual: 200 Hz << 27,306 Hz → ALIAS CRÍTICO**

### 5.2 Solución: Interrupciones + PCNT

```cpp
// Opción A: ISR para encoder
attachInterrupt(PIN_ENC_A, isr_enc_a, CHANGE);
attachInterrupt(PIN_ENC_B, isr_enc_b, CHANGE);

// Opción B: PCNT (Pulse Counter) del ESP32 (recomendado)
// Hardware counter, sin overhead de ISR en software
```

---

## 6. Filtrado Digital Complementario

### 6.1 Majority Voting (Software)

```cpp
int a1 = digitalRead(PIN_ENC_A);
delayMicroseconds(5);
int a2 = digitalRead(PIN_ENC_A);
int a_filtered = (a1 == a2) ? a1 : lastA;  // Consenso simple
```

### 6.2 Filtro EMA en Velocidad

```cpp
// Implementado en firmware v1.7.0+
filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;
// VEL_ALPHA = 0.12 → suavizado ≈ 8 muestras a 200 Hz
```

---

## 7. BOM para Hardening de Señal

| Componente | Valor | Cantidad | Costo | Función |
|-----------|-------|---------|-------|---------|
| Resistor | 4.7 kΩ | 2 | $0.02 | Pull-up encoder |
| Resistor | 470 Ω | 2 | $0.04 | Serie GPIO (RC filter) |
| Resistor | 100 Ω | 1 | $0.02 | GND damping |
| Capacitor | 100 nF X7R | 8 | $0.16 | Bypass estratégicos |
| Capacitor | 10 µF X7R | 3 | $0.30 | Desacoplo local |
| Capacitor | 100 µF alum. | 2 | $0.20 | Bulk ripple |
| Capacitor | 470 µF alum. | 1 | $0.30 | Bulk principal |
| Ferrite Bead | FB-1206P800 | 1 | $0.15 | Atenuación HF |
| IC Buffer | SN74LVC1G17 | 1 | $0.30 | Schmitt trigger |
| **Total** | | | **$1.49** | |

---

## 8. Conclusiones

La estabilización integral de señales para QUBE Servo requiere un enfoque multi-capa:

1. **Topología de señal**: Open-drain encoder + pull-ups 4.7 kΩ a 3.3 V (✅ implementado)
2. **Filtrado activo**: Schmitt trigger buffer + RC prefilter (recomendado para PCB Rev2.0)
3. **Power distribution**: Star grounding + bypass capacitivos estratégicos
4. **Software robustez**: ISR + majority voting + telemetría de diagnóstico
5. **Validación experimental**: Mediciones de timing, ripple y respuesta transiente

**Impacto esperado:** Ruido de encoder reducido -15 a -40 dB, estabilidad PID mejorada significativamente.

---

*Documento preparado: 2026-04-29 | Actualizado: 2026-05-26*