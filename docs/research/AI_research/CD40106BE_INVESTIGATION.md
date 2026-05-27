# Investigación: CD40106BE — Schmitt Trigger Hex Inversor para Acondicionamiento de Señal

**Fecha:** 2026-05-27  
**Proyecto:** Modernización QUBE Servo (ESP32 + L298N + INA219)  
**Propósito:** Evaluar la implementación del CD40106BE como etapa de acondicionamiento de señales digitales en la arquitectura QUBE.  
**Estado:** Investigación preliminar — propuesta técnica

---

## Índice

1. [¿Qué es el CD40106BE?](#1-qué-es-el-cd40106be)
2. [Características Técnicas Clave](#2-características-técnicas-clave)
3. [Problemas Detectados en la Señal del Encoder](#3-problemas-detectados-en-la-señal-del-encoder)
4. [Caso de Uso 1: Acondicionamiento de Encoder (Canales A/B)](#4-caso-de-uso-1-acondicionamiento-de-encoder-canales-ab)
5. [Caso de Uso 2: Oscilador para Watchdog/Timing](#5-caso-de-uso-2-oscilador-para-watchdogtiming)
6. [Caso de Uso 3: Debounce de Botones/Interruptores](#6-caso-de-uso-3-debounce-de-botonesinterruptores)
7. [Caso de Uso 4: Adaptación de Niveles Lógicos 5V → 3.3V](#7-caso-de-uso-4-adaptación-de-niveles-lógicos-5v--33v)
8. [Esquema de Integración Propuesto](#8-esquema-de-integración-propuesto)
9. [Evaluación de Riesgos y Limitaciones](#9-evaluación-de-riesgos-y-limitaciones)
10. [Conclusión y Recomendación](#10-conclusión-y-recomendación)
11. [Referencias](#11-referencias)

---

## 1. ¿Qué es el CD40106BE?

El **CD40106BE** es un integrado CMOS de la familia 4000 que contiene **6 inversores independientes con entrada Schmitt Trigger** (Schmitt trigger hex inverter). Fabricado por Texas Instruments, onsemi, STMicroelectronics y otros.

| Propiedad | Descripción |
|-----------|-------------|
| **Tipo** | Hex Schmitt Trigger Inverter (6 inversores) |
| **Paquete** | DIP-14 (CD40106BE), SOIC-14 (CD40106BM) |
| **Tensión de alimentación** | 3 V a 18 V (rango completo CMOS) |
| **Tecnología** | CMOS estándar |
| **Corriente de salida** | ~1.6 mA sink/source típico a 5 V |
| **Tiempo de propagación** | ~60–120 ns típico a 10 V |
| **Disipación** | Muy baja (~µW en estático) |
| **Temperatura** | -55 °C a +125 °C |

### Pinout (DIP-14)

```
         +--------+
  A_IN 1 |        | 14 Vcc (3-18V)
  A_OUT 2 |        | 13 F_IN
  B_IN 3 |        | 12 F_OUT
  B_OUT 4 |  40106 | 11 E_IN
  C_IN 5 |        | 10 E_OUT
  C_OUT 6 |        | 9  D_IN
   GND 7 |        | 8  D_OUT
         +--------+
```

### ¿Qué hace un Schmitt Trigger?

A diferencia de una compuerta lógica estándar con un solo umbral de conmutación (~1.5 V para TTL, ~1.5 V para CMOS 5V), el **Schmitt Trigger tiene dos umbrales**:

- **VT+ (umbral positivo):** Tensión a la cual la salida cambia de HIGH a LOW (flanco ascendente)
- **VT- (umbral negativo):** Tensión a la cual la salida cambia de LOW a HIGH (flanco descendente)
- **Histéresis (ΔVT):** Diferencia entre VT+ y VT- (típicamente 0.8–2.0 V)

Esta histéresis elimina el **rebote eléctrico** en señales ruidosas o de transición lenta, produciendo flancos limpios.

---

## 2. Características Técnicas Clave

### 2.1 Umbrales de conmutación (Texas Instruments CD40106B)

| Vcc | VT+ (típico) | VT- (típico) | Histéresis ΔVT (típico) |
|-----|-------------|-------------|------------------------|
| 5 V | 2.9 V | 2.1 V | 0.8 V |
| 10 V | 5.8 V | 4.2 V | 1.6 V |
| 15 V | 8.7 V | 6.3 V | 2.4 V |

### 2.2 Características relevantes para QUBE

| Parámetro | Valor | Implicancia |
|-----------|-------|-------------|
| Tensión mínima de operación | 3 V | Puede operar con lógica 3.3 V del ESP32 |
| Tensión máxima | 18 V | Compatible con bus de 12 V del sistema |
| Histéresis típica a 5 V | 0.8 V | Rechaza ruido de hasta ±400 mV en la entrada |
| Histéresis típica a 12 V | 2.0 V | Robusto para señales de encoder en bus de potencia |
| Fanout TTL a 5 V | ~2 cargas LS | Suficiente para excitar 1–2 GPIO de ESP32 |
| Inmunidad a ruido | Muy alta (CMOS con histéresis) | Ideal para ambiente de motor DC con conmutación L298N |

### 2.3 Ventajas frente a soluciones alternativas

| Solución | Ventajas | Desventajas |
|----------|----------|-------------|
| **CD40106BE** | Histéresis ajustable por Vcc, 6 canales, bajo costo (~$0.50 USD), ampliamente disponible, tolerante a 5–12 V | Mayor espacio físico (DIP-14), consumo ligeramente mayor que soluciones SMD |
| Divisor resistivo puro | Simple, sin componente activo | Sin histéresis, sin limpieza de ruido, nivel lógico marginal |
| Level shifter dedicado (TXS0102) | Bidireccional, SMD pequeño | Sin histéresis, sensible a velocidad de transición, más caro |
| Optoacoplador | Aislamiento galvánico | Más caro, mayor consumo, más partes externas |
| Discretos (transistores + R) | Flexible | Muchos componentes, difícil de sintonizar |

---

## 3. Problemas Detectados en la Señal del Encoder

El proyecto ha documentado múltiples incidentes de **nivel lógico insuficiente** y **ruido** en los canales A/B del encoder (GPIO34/GPIO35 del ESP32):

| Problema | Descripción | Registro |
|----------|-------------|----------|
| **Divisor 4.7kΩ/8.2kΩ producía 35–40 mV** | Nivel alto insuficiente para detección | CHANGELOG |
| **Salida open-drain sin pull-up efectivo** | El encoder no podía sostener nivel alto | docs/research/ |
| **Encoder push-pull 5V** | Con divisor 10kΩ/10kΩ se obtenía ~2.5V (marginal) | INVESTIGACION.md |
| **Ruido de conmutación L298N** | Los transitorios del H-bridge se acoplan a las líneas del encoder | (presencia de filtrado en firmware) |
| **Filtrado por software (VEL_ALPHA = 0.12)** | Se aplica filtro paso-bajo en derivada, pero no elimina falsos flancos | Firmware línea 141 |

### 3.1 Síntomas en el firmware actual

En `esp32_qube_l298n.ino`:

- **Línea 141:** Se usa `VEL_ALPHA = 0.12` para filtrar la velocidad derivada, indicando ruido presente en la medición de posición.
- **Línea 127-128:** Existen flags `USE_ENCODER_INTERRUPTS` y `USE_ENCODER_POLLING` para manejar el encoder, lo que sugiere que se exploraron distintas estrategias de lectura.
- **Línea 721-722:** `GPIO34/GPIO35` son pines solo-entrada sin pull-up interno, lo que los hace susceptibles a ruido si la señal externa no es robusta.
- **Línea 798-799:** El filtro paso-bajo `filteredVel = VEL_ALPHA * rawVel + (1.0 - VEL_ALPHA) * filteredVel` es una solución por software para un problema que podría resolverse en hardware.

---

## 4. Caso de Uso 1: Acondicionamiento de Encoder (Canales A/B)

### 4.1 Problema

La señal del encoder incremental (Premotec 990412016913) presenta:
- Transiciones lentas (especialmente si la salida es open-drain con pull-up débil)
- Ruido acoplado por conmutación del L298N (20 kHz PWM)
- Posibles falsos flancos que incrementan `encoderCount` erróneamente

### 4.2 Solución con CD40106BE

**Topología propuesta:**

```
Encoder A ──► [CD40106BE INV1] ──► GPIO34 (ESP32)
Encoder B ──► [CD40106BE INV2] ──► GPIO35 (ESP32)
```

**Detalle del circuito:**

```
Vcc (5V LM2596) ──► CD40106BE pin 14
GND              ──► CD40106BE pin 7

Canal A:
  Encoder A ──► 10kΩ pull-up a 3.3V ──► pin 1 (IN1) ──► pin 2 (OUT1) ──► GPIO34
                                           │
                                        100nF ──► GND (filtro pasivo adicional)

Canal B:
  Encoder B ──► 10kΩ pull-up a 3.3V ──► pin 3 (IN2) ──► pin 4 (OUT2) ──► GPIO35
                                           │
                                        100nF ──► GND (filtro pasivo adicional)
```

**Nota sobre inversión:** El CD40106BE es un inversor. La señal del encoder se invierte, pero para la decodificación en cuadratura solo importan los flancos, no la polaridad absoluta. Si se requiere la polaridad original, se puede pasar por un segundo inversor (INV3 e INV4) para recuperar la fase.

**Alternativa sin inversión (doble inversión por canal):**

```
Encoder A ──► INV1 ──► INV2 ──► GPIO34
Encoder B ──► INV3 ──► INV4 ──► GPIO35
```

Esto usa 4 de los 6 inversores disponibles, dejando 2 para otros usos.

### 4.3 Beneficios

1. **Histéresis de 0.8 V (a 5 V):** Rechaza ruido de hasta ±400 mV en la entrada
2. **Flancos limpios:** Tiempo de subida/bajada < 100 ns (independiente de la pendiente de entrada)
3. **Aislamiento de impedancia:** El CD40106BE presenta alta impedancia de entrada (CMOS) y baja impedancia de salida, desacoplando el encoder del ESP32
4. **Transiciones rápidas:** Sin riesgo de falsos conteos por "glitches" en zona de transición lenta

### 4.4 Consideraciones

- La salida del CD40106BE a 5 V produce ~4.5–5.0 V en HIGH, mientras que el ESP32 opera a 3.3 V y sus GPIO no son tolerantes a 5 V (GPIO34/GPIO35 son solo-entrada y **no** toleran 5 V).
- **Solución:** Alimentar el CD40106BE a **3.3 V** en lugar de 5 V, o usar un divisor resistivo (10kΩ/10kΩ) a la salida de cada inversor para reducir de ~5 V a ~2.5 V.
- **Recomendación:** Alimentar el CD40106BE a 3.3 V directamente desde el regulador del ESP32. A 3.3 V la histéresis será menor (~0.5 V) pero sigue siendo superior a cero. Ver sección 7.

---

## 5. Caso de Uso 2: Oscilador para Watchdog/Timing

### 5.1 Problema

El firmware actual usa `millis()` y `micros()` para temporización del lazo de control (200 Hz) y telemetría (10 Hz). No existe un watchdog externo que pueda resetear el ESP32 si el firmware se cuelga.

### 5.2 Solución con CD40106BE

Se puede configurar un inversor del CD40106BE como **oscilador de relajación**:

```
                 +--- R1 (100kΩ) ---+
                 |                   |
                 +--- [INV1] ───────-+
                 |                   |
                C1                 Salida a
               (10nF)             ESP32 GPIO
                 |
                GND
```

**Frecuencia típica:** f ≈ 1 / (2.2 × R1 × C1) ≈ 1 / (2.2 × 100kΩ × 10nF) ≈ 450 Hz

**Aplicaciones:**
- Watchdog heartbeat para monitorear que el ESP32 responde
- Temporizador auxiliar independiente del oscilador principal del ESP32
- Generación de interrupción periódica externa

### 5.3 Limitación

El ESP32 ya tiene temporizadores internos de hardware. Este caso de uso tiene **baja prioridad** a menos que se implemente un watchdog externo de seguridad.

---

## 6. Caso de Uso 3: Debounce de Botones/Interruptores

### 6.1 Problema

Si se implementan botones físicos (paro de emergencia, inicio/stop, calibración), los contactos mecánicos generan rebote eléctrico que el ESP32 puede interpretar como múltiples pulsaciones.

### 6.2 Solución con CD40106BE

```
  Vcc (3.3V)
     │
     R (10kΩ pull-up)
     │
Botón ───── INx ──► OUTx ──► GPIO_ESP32
     │
    GND
```

La histéresis del Schmitt Trigger elimina el rebote sin necesidad de filtrado por software. El condensador externo es opcional; la histéresis interna suele ser suficiente para contactos mecánicos estándar (< 10 ms de rebote).

---

## 7. Caso de Uso 4: Adaptación de Niveles Lógicos 5V → 3.3V

### 7.1 Problema

El encoder del servo Premotec opera a 5 V (push-pull confirmado en pruebas de banco). El ESP32 GPIO34/GPIO35 opera a 3.3 V y **no tolera 5 V**. Actualmente se usa un divisor resistivo (10kΩ/10kΩ) que reduce de ~4.7 V a ~2.35 V, nivel marginal que además no provee histéresis.

### 7.2 Solución con CD40106BE alimentado a 3.3 V

```
Encoder 5V ──► INVx (CD40106BE @ Vcc=3.3V) ──► GPIO ESP32 (3.3V directo)
```

**¿Por qué funciona?** Aunque el encoder emite 5 V, la entrada del CD40106BE CMOS es de alta impedancia y tolera hasta Vcc+0.5 V según datasheet (con limitación de corriente). Alimentando el chip a 3.3 V:

- **VT+** ≈ 0.7 × Vcc ≈ 2.3 V → la señal de 5 V supera este umbral con margen
- **VT-** ≈ 0.3 × Vcc ≈ 1.0 V → la señal baja a 0 V
- **Salida:** Oscila entre 0 V y 3.3 V → compatible con ESP32

**Advertencia:** Algunos fabricantes especifican que la entrada no debe exceder Vcc. Para mayor seguridad, usar un divisor resistivo a la entrada (por ejemplo 10kΩ en serie) que limite la corriente en caso de sobretensión. Alternativamente, se puede usar un diodo Schottky (BAT54) de sujeción a Vcc.

### 7.3 Topología recomendada (con protección)

```
Encoder 5V ──┬── R1 (1kΩ) ──┬── INx (CD40106BE @ Vcc=3.3V) ── OUTx ── GPIO ESP32
             │               │
             │              D1 ──► Vcc (BAT54 Schottky, cátodo a Vcc)
             │               │
             │              5.1V Zener ──► GND (protección transitorio)
             │
            R2 (10kΩ) ──► GND (pull-down por si encoder en alta impedancia)
```

Versión simplificada (recomendada para prototipo):

```
Encoder 5V ──┬── R_series (2.2kΩ) ──┬── INx (CD40106BE @ Vcc=3.3V)
             │                       │
            R_pd (10kΩ) ──► GND    100nF ──► GND
```

- R_series limita corriente en caso de sobretensión
- R_pd establece nivel bajo conocido cuando el encoder está en alta impedancia
- C bypass filtra ruido HF

---

## 8. Esquema de Integración Propuesto

### 8.1 Diagrama de bloques completo

```
┌──────────────────────────────────────────────────────────────────┐
│                      BUS 12V DC                                 │
└──────┬───────────────────────┬──────────────────────────┬───────┘
       │                       │                          │
       ▼                       ▼                          ▼
   LM2596                   L298N                     Encoder servo
   (12V→5V)                 (H-Bridge)                (5V push-pull)
       │                       │                          │
       ▼                       │                     ┌────┴────┐
   Reg 3.3V                   │                     │CD40106BE│
   (ESP32)                    │                     │ (3.3V)  │
       │                       │                     └────┬────┘
       ▼                       ▼                          ▼
   ESP32-WROOM            Motor DC                  GPIO34/GPIO35
   ┌───────┐               (Premotec)                    ▲
   │INA219 │                                             │
   │ (I2C) │                                        Flancos limpios
   └───────┘                                        con histéresis 0.5V
```

### 8.2 Conexiones propuestas

| Señal | Origen | Destino | Componente intermedio |
|-------|--------|---------|----------------------|
| Encoder A | Servo (5V) | CD40106BE pin 1 (IN1) | R_series 2.2kΩ + R_pd 10kΩ |
| Encoder A (limpia) | CD40106BE pin 2 (OUT1) | ESP32 GPIO34 | Directa (3.3V) |
| Encoder B | Servo (5V) | CD40106BE pin 3 (IN2) | R_series 2.2kΩ + R_pd 10kΩ |
| Encoder B (limpia) | CD40106BE pin 4 (OUT2) | ESP32 GPIO35 | Directa (3.3V) |
| Alimentación CD40106BE | Regulador 3.3V ESP32 | CD40106BE pin 14 | Filtro 100nF a GND |
| GND | GND común | CD40106BE pin 7 | Conexión estrella |
| Reserva INV5 | Libre para oscilador/backup | CD40106BE pin 9,10 | Futuro |
| Reserva INV6 | Libre para botón/backup | CD40106BE pin 11,12 | Futuro |

### 8.3 Esquemático detallado

```
                 3.3V
                  │
                 ┌┤  (proveniente de regulador ESP32)
                 │
                ─┴─ 100nF
                ─┬─ (cerámico, bypass)
                 │
                 ▼
         ┌─────────────┐
         │   CD40106BE │
         │  (Vcc=3.3V) │
         │             │
ENC_A ──┬┤1 IN1    Vcc│14 ──── 3.3V
        │ │           │
        │ └┤2 OUT1     │
        │   │           │
        │   └──────┬────┘── GPIO34 (ESP32)
        │           │
       ─┴─ 100nF   │
       ─┬─ (filtro) │
        │           │
ENC_B ──┬┤3 IN2     │
        │ │           │
        │ └┤4 OUT2   │
        │   │         │
        │   └────┬────┘── GPIO35 (ESP32)
        │         │
       ─┴─ 100nF │
       ─┬─ GND   │
        │        │
        └─┤7 GND │
          └──────┘
             │
            GND
```

**Detalle de entrada con protección:**

```
ENC_A (5V) ──── R1 (2.2kΩ) ────┬──── IN1 (CD40106BE pin 1)
                               │
                              R2 (10kΩ) ──── GND
                               │
                              C1 (100nF) ──── GND
```

---

## 9. Evaluación de Riesgos y Limitaciones

### 9.1 Riesgos técnicos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| **Entrada > Vcc** en CD40106BE | Media | Puede dañar el chip si excede límite absoluto (Vcc+0.5V) | R_series limitadora + diodo Schottky opcional |
| **Histéresis reducida a 3.3V** | Alta | ~0.5 V en lugar de 0.8 V a 5 V | Sigue siendo mejor que 0 V (sin histéresis) |
| **Inversión de fase** | Cierta | La salida del inversor es negada | Usar par de inversores para recuperar fase, o ajustar firmware para invertir |
| **Espacio en protoboard/PCB** | Media | DIP-14 requiere más espacio que SMD | Usar CD40106BM (SOIC-14) si es necesario |
| **Consumo adicional** | Baja | ~1 µW estático, ~1 mW dinámico a 1 kHz | Irrelevante frente al motor DC (~10 W) |

### 9.2 Limitaciones

1. **No es un aislador galvánico:** El CD40106BE no provee aislamiento. Si se requiere aislamiento entre potencia y lógica, usar optoacopladores (6N137, HCPL-2630).
2. **Frecuencia máxima limitada:** Tiempo de propagación ~60–120 ns → frecuencia máxima práctica ~4–8 MHz. Para encoder de servo (máximo ~10 kHz por canal en QUBE), es más que suficiente.
3. **Corriente de salida baja:** ~1.6 mA sink/source a 5 V. Suficiente para excitar 1–2 GPIO de ESP32 (impedancia CMOS), pero insuficiente para LED indicador sin buffer adicional.

### 9.3 Comparación con solución actual

| Aspecto | Sin CD40106BE (divisor puro) | Con CD40106BE |
|---------|------------------------------|----------------|
| Histéresis | 0 V | 0.5 V (a 3.3 V) / 0.8 V (a 5 V) |
| Protección contra ruido L298N | Ninguna | Excelente |
| Nivel lógico a ESP32 | Marginal (~2.35 V) | 3.3 V compatible |
| Complejidad de partes | Mínima (2 resistencias) | Moderada (1 IC + 4 R + 3 C) |
| Costo incremental | ~$0.02 USD | ~$0.50–1.00 USD |
| Tiempo de implementación | Inmediato | 1–2 horas (protoboard) |
| Mejora esperada en conteo | — | Alta (eliminación de falsos flancos) |

---

## 10. Conclusión y Recomendación

### 10.1 Veredicto

**✅ Recomendado — Alta prioridad**

El CD40106BE aborda directamente los problemas documentados de **nivel lógico insuficiente** y **ruido en encoder** que han afectado al proyecto desde sus inicios. Es una solución de hardware simple, de bajo costo y alta efectividad.

### 10.2 Recomendaciones de implementación

| Prioridad | Implementación | Dificultad | Beneficio |
|-----------|---------------|------------|-----------|
| **Crítica** | Acondicionar canales A/B del encoder con 2 inversores | Baja | Elimina falsos flancos, mejora precisión de posición |
| **Recomendada** | Alimentar CD40106BE a 3.3V (desde regulador ESP32) | Baja | Salida directa a GPIO protegida |
| **Opcional** | Usar 2 inversores extra para recuperar fase original | Baja | Mantiene polaridad si es necesaria |
| **Futuro** | Implementar botón de paro con debounce por Schmitt | Baja | Seguridad |

### 10.3 Próximos pasos sugeridos

1. **Adquirir CD40106BE** (DIP-14) + protoboard + resistencias 2.2kΩ/10kΩ + capacitores 100nF
2. **Montar circuito en protoboard** según esquema de la sección 8
3. **Verificar con osciloscopio:** Comparar señal del encoder directa vs. acondicionada
4. **Probar con firmware existente:** Verificar que `encoderCount` ya no presente valores erráticos
5. **Evaluar si se necesita ajuste de polaridad** (MOTOR_DIR, encoderDir)
6. **Si funciona en protoboard:** Migrar a PCB o protoboard permanente

### 10.4 Costo estimado

| Componente | Cantidad | Costo unitario | Costo total |
|------------|----------|---------------|-------------|
| CD40106BE (DIP-14) | 1 | ~$0.50 | $0.50 |
| Resistencias 2.2kΩ 1/4W | 2 | ~$0.02 | $0.04 |
| Resistencias 10kΩ 1/4W | 2 | ~$0.02 | $0.04 |
| Capacitores 100nF cerámico | 3 | ~$0.05 | $0.15 |
| **Total** | | | **~$0.73 USD** |

---

## 11. Referencias

1. **Texas Instruments CD40106B Datasheet** — [SCHS034I](https://www.ti.com/lit/ds/symlink/cd40106b.pdf) — Schmitt-Trigger Inverters
2. **onsemi CD40106BC Datasheet** — CD40106BC — Hex Schmitt-Trigger Inverters
3. **STMicroelectronics HCF40106** — Hex Schmitt Trigger
4. **Horowitz & Hill, The Art of Electronics, 3rd ed.** — Cap. 9: Schmitt Triggers
5. **AN-140 - Schmitt Trigger Oscillator** — Texas Instruments Application Note
6. **CHANGELOG del proyecto QUBE** — Registro de incidentes de encoder con nivel lógico insuficiente
7. **INVESTIGACION.md** — Documento principal de investigación del proyecto QUBE (sección encoder)
8. **esp32_qube_l298n.ino** — Firmware actual: líneas 127-128, 141, 721-722, 798-799

---

*Documento generado como parte de la investigación técnica del proyecto QUBE Servo - Modernización con arquitectura abierta.*