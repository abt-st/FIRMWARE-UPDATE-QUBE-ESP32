---
title: "Investigación Unificada: Modernización QUBE Servo"
subtitle: "Arquitectura ESP32 + LM2596 + INA219 + L298N"
author: "Documento técnico consolidado para tesis"
date: "2026-05-26"
lang: "es-ES"
toc: true
toc-depth: 3
numbersections: true
---

# Investigación Unificada de la Modernización del QUBE Servo

**Fecha:** 2026-05-26  
**Proyecto:** Modernización de plataforma QUBE Servo con arquitectura abierta de bajo costo  
**Alcance:** Consolidación de investigación técnica, experimental y académica en un solo documento  
**Fuentes:** `old resources/INVESTIGACION INICIAL.md`, `old resources/INVESTIGACION_DETALLADA_MODERNIZACION_QUBE_2026.md`, `old resources/INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md`, `docs/Investigacion.md`

---

## 1. Resumen Ejecutivo

### 1.1 Pregunta Central

¿Existe un proyecto abierto que integre exactamente la combinación **ESP32 + LM2596 + INA219 + L298N** para emulación tipo QUBE Servo?

### 1.2 Respuesta Breve

**No se identificó una implementación abierta integral con esa combinación exacta.**  
Sin embargo, existe evidencia suficiente de viabilidad por bloques y subsistemas:

- Control de motor DC con encoder en lazo cerrado: ✅ 53+ proyectos
- Telemetría eléctrica por INA219: ✅ 74+ proyectos
- Conversión buck LM2596 para alimentación: ✅ 44+ proyectos
- Integración embebida con ESP32 + supervisión por GUI: ✅ 41+ proyectos

### 1.3 Conclusión Principal

La arquitectura propuesta es **viable, replicable y con potencial de aporte original para tesis**, debido a la ausencia de una referencia abierta completa y a la posibilidad de documentar metodología reproducible extremo a extremo.

---

## 2. Contexto, Motivación y Aporte Académico

Los sistemas comerciales tipo QUBE tienen alto valor didáctico pero costo elevado ($2,500–$3,500 USD). La propuesta abierta busca:

- **Reducir barrera de acceso económico** a ~$40–70 USD (98% de reducción)
- **Mantener rigor de control e instrumentación** con PID + LQR
- **Habilitar trazabilidad de decisiones técnicas** mediante CHANGELOG y documentación
- **Integrar telemetría energética** (INA219) para análisis experimental

### Aporte esperado para tesis

1. Metodología de modernización reproducible
2. Base experimental para comparar control clásico (PID) y control por estados (LQR)
3. Evidencia de integración hardware + firmware + datos
4. Ruta clara de evolución hacia péndulo invertido completo

---

## 3. Estado del Arte Consolidado

### 3.1 Búsqueda Sistemática en GitHub

Se realizó una búsqueda exhaustiva en GitHub (Abril–Mayo 2026) con los siguientes resultados:

| Término de búsqueda | Resultados | Proyectos relevantes |
|---------------------|------------|---------------------|
| `L298N PID control` | 53 | 4 |
| `ESP32 DC motor control speed` | 41 | 5 |
| `INA219 power monitoring` | 74 | 6 |
| `rotary pendulum system control` | 20 | 6 |
| `buck converter power supply` | 44 | 3 |
| `ESP32 + L298N + INA219` | **0** | **Ninguno** |

### 3.2 Proyectos de Referencia por Componente

#### Control PID + L298N (53 proyectos)

| Repositorio | Autor | Año | Similitud | Notas |
|-------------|-------|-----|-----------|-------|
| `arduino_pid_controlled_motor` | wty-yy | 2025 | Alta | PID + encoder + L298N, bien documentado |
| `Speed-Control-of-DC-Motor-Using-Arduino-and-L298N` | Hagar633 | 2025 | Alta | Tesis validada, documentación educativa |
| `ROS_Arduino_PID_DC_Motors` | bekirbostanci | 2020 | Media | ROS overkill para QUBE |
| `self-balancing-bot` | osasinrobotics | 2026 | Media | Sin encoder, usa MPU6050 |

#### ESP32 + Control Motor DC (41 proyectos)

| Repositorio | Autor | Stars | Año | Notas |
|-------------|-------|-------|-----|-------|
| **Esp32CameraRover2** | Ezward | 46 ⭐ | 2018–2024 | Framework maduro, closed-loop, web interface |
| PID-Motor-Controller | beanjamminb | — | 2025 | ESP32 + TB6612FNG, en desarrollo |
| ESP32_Motor_control | aimeiz | — | 2025 | RTOS + encoder + parámetros persistentes |

**Hallazgo Principal:** EzRover (46 ⭐) es el más relevante: closed-loop speed control, encoder feedback, WebSocket, arquitectura RTOS.

#### INA219 + Telemetría de Potencia (74 proyectos)

| Repositorio | Tipo | Stars | Notas |
|-------------|------|-------|-------|
| **Adafruit_INA219** | Librería oficial | 229 ⭐ | Librería estándar, MIT license |
| INA (Zanduino) | Librería múltiple INA2xx | 168 ⭐ | Más robusta para producción |
| INA219_WE | Librería alternativa | 53 ⭐ | Bien documentada |
| pi_ina219 | Python (RPi) | 117 ⭐ | Soporte Raspberry Pi |
| RobTillaart/INA219 | Librería Arduino | 32 ⭐ | Alternativa lightweight |

**Hallazgo:** INA219 tiene soporte maduro y múltiples librerías validadas.

#### Sistemas Educativos Rotatorios (20 proyectos)

| Repositorio | Tipo | Hardware | Año | Notas |
|-------------|------|----------|-----|-------|
| **Rotary-Inverted-Pendulum** | MATLAB+Arduino | Arduino + L298N + encoder | 2023 | ⭐ Referencia académica LQR |
| RotaryPendulumControl | MATLAB | — | 2023 | Control con observador de estado |
| Applied-Control-Systems-Module | LabVIEW | — | 2023 | LQR, MPC |
| Motor-Pendulum-Control | MATLAB/Simulink | — | 2025 | PID de péndulo rotatorio |

**Hallazgo Crítico:** El proyecto **ebrahimabdelghfar/Rotary-Inverted-Pendulum** (2023) es una VALIDACIÓN ACADÉMICA completa que usa Arduino + L298N + encoder, documentando modelado matemático, estimación de parámetros, control LQR y validación experimental.

### 3.3 Brecha Detectada

No se encontró una implementación abierta que combine en un solo pipeline:

- ✅ ESP32 como núcleo de control
- ✅ L298N como etapa de potencia
- ✅ INA219 como canal energético integrado
- ✅ Regulación buck LM2596
- ✅ Flujo completo de validación experimental con documentación consolidada

**Conclusión:** Esta combinación es **INÉDITA** y representa una oportunidad de contribución académica original.

---

## 4. Arquitectura Técnica Propuesta

### 4.1 Diagrama de Bloques

```
ENTRADA: 12-24V (batería o PSU)
    │
    ├── [LM2596 Buck Converter] ──→ 5V para ESP32 + sensores
    │
    ├── [ESP32-WROOM-32]
    │   ├─ GPIO 26/27 → L298N IN1/IN2 (PWM + dirección)
    │   ├─ GPIO 34/35 → Encoder servo A/B
    │   ├─ GPIO 32/33 → Encoder péndulo A/B (futuro)
    │   ├─ GPIO 21/22 → INA219 SDA/SCL (I2C)
    │   └─ UART USB   → Depuración/telemetría
    │
    ├── [L298N Motor Driver]
    │   ├─ IN1/IN2: Dirección + PWM
    │   ├─ ENA: Jumper habilitado (opción recomendada)
    │   └─ OUT1/OUT2: Motor DC
    │
    ├── [INA219 Current Sensor] (I2C)
    │   ├─ VIN+ / VIN-: High-side sensing
    │   └─ Dirección I2C: 0x40 (A0=GND, A1=GND)
    │
    └── [Encoder + Motor DC]
        └─ Pulsos A/B → GPIO ESP32 + decodificación cuadratura X4
```

### 4.2 Flujo de Información

```
Referencia → Controlador PID (ESP32, 200 Hz)
                 ↓
           Acción PWM en L298N
                 ↓
           Dinámica del motor DC
                 ↓
           Encoder → realimenta posición/velocidad
           INA219 → contexto energético (V, I, P)
                 ↓
           Estado consolidado → GUI Python + registro CSV
```

### 4.3 Comparación con Alternativas

| Aspecto | Arquitectura Propuesta | Arduino+L298N | Quanser QUBE |
|---------|----------------------|---------------|--------------|
| **Costo** | **$40–70 USD** | $30–40 USD | $2,500–3,500 USD |
| **Conectividad** | WiFi + BLE nativa | Opcional (shield) | Ethernet |
| **Procesamiento** | Dual-core, 240 MHz | Single-core, 16 MHz | DSP dedicado |
| **Telemetría potencia** | INA219 digital (I2C) | Shunt + ADC | Sensores integrados |
| **Frecuencia control** | **200 Hz** (FreeRTOS) | ~100 Hz | 1000 Hz |
| **Encoders** | **2** (servo + péndulo) | 1 (limitado) | 2 |
| **Curva aprendizaje** | Media | Baja | Alta (MATLAB) |

---

## 5. Integración Eléctrica Consolidada

### 5.1 Asignación de Pines (Versión Actual)

| Señal | GPIO ESP32 | Tipo | Destino | Notas |
|-------|-----------|------|---------|-------|
| L298N IN1 | GPIO26 | Salida (PWM) | Control dirección positiva |
| L298N IN2 | GPIO27 | Salida (PWM) | Control dirección negativa |
| L298N ENA | — | Jumper | Habilitado (sin cable al ESP32) |
| Encoder servo A | GPIO34 | Entrada | Pull-up 4.7 kΩ a 3.3 V (open-drain) |
| Encoder servo B | GPIO35 | Entrada | Pull-up 4.7 kΩ a 3.3 V (open-drain) |
| Encoder péndulo A | GPIO32 | Entrada | Futuro (pull-up según tipo) |
| Encoder péndulo B | GPIO33 | Entrada | Futuro (pull-up según tipo) |
| INA219 SDA | GPIO21 | I2C | Bus I2C |
| INA219 SCL | GPIO22 | I2C | Bus I2C |

### 5.2 Conexión de Potencia

```
Fuente 12V (+) ──┬── VIN+ [INA219] VIN- ──── L298N VS (12V)
                 │
                 ├── LM2596 IN
                 │      └── LM2596 OUT (5V) ──── ESP32 VIN
                 │                            ──── L298N 5V (lógica)
                 │
GND fuente  ─────┴── GND común (estrella)
                    ├── L298N GND
                    ├── ESP32 GND
                    ├── INA219 GND
                    └── Encoder GND
```

### 5.3 Acondicionamiento de Señal del Encoder (HW-FIX-1)

**Problema:** El encoder del servo Premotec 990412016913 tiene salida **open-drain** (NPN). El level shifter de 7 MΩ original producía señal indeterminada (~1.5 V) que el ESP32 no podía discriminar.

**Solución:** Pull-up de 4.7 kΩ a 3.3 V directo en cada canal A/B.

```
ESP32 3V3
    │
    ├──[4.7kΩ]──┬── GPIO34 (INPUT)
    │            │
    │     Encoder A (open-drain)
    │            │ ← conduce a GND en estado bajo; Hi-Z en estado alto
    │           GND
    │
    └──[4.7kΩ]──┬── GPIO35 (INPUT)
                 │
          Encoder B (open-drain)
                 │
                GND
```

**Resultado:** Señal limpia 0 V / 3.3 V, CNT incrementa monótonamente, PID converge en 2–3 segundos.

**Actualización (2026-05-13):** En nuevas pruebas de banco, el encoder del servo se validó como compatible con **push-pull 5V** en el punto de toma actual. En reposo se midió hasta **4.7 V** y con divisor **10 kΩ / 10 kΩ** se obtuvo ~**2.5 V** estable en GPIO.

---

## 6. Control PID en Lazo Cerrado

### 6.1 Implementación

```cpp
float pid_compute(float setpoint, float measured, float dt) {
    float error = setpoint - measured;
    
    // Anti-windup: integral limitada
    integral += error * dt;
    integral = constrain(integral, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
    
    // Derivada con filtro EMA (suavizado de ruido de cuantización)
    float derivative = (error - prev_error) / dt;
    derivative = VEL_ALPHA * derivative + (1.0f - VEL_ALPHA) * prev_derivative;
    
    prev_error = error;
    prev_derivative = derivative;
    
    return Kp * error + Ki * integral + Kd * derivative;
}
```

### 6.2 Ganancias por Versión (Evolución de Sintonización)

| Versión | Kp | Ki | Kd | Notas |
|---------|----|----|----|-------|
| 1.3.0 | 0.8 | 0.01 | 0.05 | Primer ajuste funcional |
| 1.5.0 | 0.4 | 0.0 | 0.20 | PD puro para amortiguación |
| 1.6.0 | 0.25 | 0.0 | 0.45 | Subamortiguación corregida |
| 1.7.0 | 0.35 | 0.0 | 0.18 | Filtro EMA en velocidad (α=0.25) |
| 1.8.0 | 0.55 | 0.0 | 0.06 | Filtro más suave (α=0.12) |
| 1.9.0 | 0.50 | 0.002 | 0.06 | Integral reintroducida |
| 1.10.0 | 0.42 | 0.0 | 0.06 | Integración condicionada (|err|<8°) |
| 1.15.0 | 0.75 | 0.0 | 0.06 | PWM_MIN reducido (28→12) |
| **1.17.0** | **0.75** | **0.15** | **0.06** | Integral habilitada, zona 45° |

### 6.3 Parámetros Actuales (v1.17.0)

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| Kp | 0.75 | Ganancia proporcional |
| Ki | 0.15 | Ganancia integral |
| Kd | 0.06 | Ganancia derivativa |
| VEL_ALPHA | 0.12 | Factor de filtro EMA para velocidad |
| INTEGRAL_LIMIT | 250 | Límite anti-windup |
| PWM_MIN | 12 | PWM mínimo para superar fricción |
| DEADBAND | 0.8° | Banda muerta de posición |
| CONTROL_PERIOD | 5 ms (200 Hz) | Período del lazo de control |

### 6.4 Métricas de Rendimiento (de datos experimentales)

| Métrica | Valor | Condición |
|---------|-------|-----------|
| Convergencia a setpoint | 2–3 segundos | Setpoint 45°, Kp=0.75 |
| Overshoot | ~10–20% | Aceptable para educación |
| Error estacionario | < 2° | Con Ki=0.15 activo |
| Estabilidad en régimen | Excelente | Sin oscilaciones sostenidas |
| Reproducibilidad | Confirmada | 5 sesiones de datos |

---

## 7. Telemetría de Potencia (INA219)

### 7.1 Configuración I2C

```cpp
#include <Wire.h>
#include <Adafruit_INA219.h>

Adafruit_INA219 ina219(0x40);  // A0=GND, A1=GND → 0x40

void setup() {
    Wire.begin(21, 22);   // SDA=GPIO21, SCL=GPIO22
    ina219.begin();
    ina219.setCalibration_32V_2A();
}
```

### 7.2 Variables Medidas

| Variable | Unidad | Rango | Precisión |
|----------|--------|-------|-----------|
| `v_bus` | V | 0–26 V | ±1% |
| `i_ma` | mA | ±3200 mA | ±1 mA res. |
| `p_mw` | mW | Calculada | V × I |

### 7.3 Filtrado Digital

```cpp
// EMA filter para reducir ruido de conmutación del L298N
float i_filtered = 0.9f * i_filtered_prev + 0.1f * i_measured;
```

---

## 8. Arquitectura de Firmware y GUI

### 8.1 Tasks FreeRTOS

| Task | Core | Prioridad | Período | Función |
|------|------|-----------|---------|---------|
| `task_control` | 1 | 5 | 5 ms (200 Hz) | Leer encoders, PID, escribir PWM |
| `task_ina219` | 0 | 3 | 10 ms (100 Hz) | Leer INA219, filtrar |
| `task_telemetry` | 0 | 2 | 50 ms (20 Hz) | JSON serial, WebSocket |
| `task_wifi` | 0 | 1 | Event-driven | Servidor WebSocket |

### 8.2 Modos de Operación

| Modo | Código | Descripción |
|------|--------|-------------|
| STOP | m0 | Motor deshabilitado, encoders activos |
| PWM Manual | m1 | PWM fijo, sin lazo de control |
| PID Posición | m2 | Setpoint en grados, lazo cerrado |
| PID Péndulo | m3 | Futuro: control con encoder de péndulo |
| LQR | m4 | Futuro: control óptimo en espacio de estados |

### 8.3 GUI Python

La interfaz gráfica (`gui/app.py`) proporciona:

- Monitoreo en tiempo real: posición, setpoint, error, PWM, corriente, voltaje, potencia
- Comandos: modo, setpoint, PWM manual, ganancias PID
- Registro CSV de corridas experimentales
- Ventana de tiempo configurable (5–60 s)
- Visualización de señales seleccionables

---

## 9. Metodología Experimental

### 9.1 Fases

| Fase | Duración | Actividades |
|------|----------|-------------|
| A: Infraestructura | 2–3 semanas | Energía estable, comunicación, sensado básico |
| B: Caracterización actuador | 2–3 semanas | Curva PWM vs velocidad, zona muerta |
| C: Lazo de velocidad | 2–3 semanas | Ajuste progresivo Kp, Ki, Kd |
| D: Lazo de posición | 2–3 semanas | Escalón, rampa, perturbaciones |
| E: Telemetría energética | 1–2 semanas | Correlación esfuerzo-control y consumo |
| F: Integración péndulo | 3–4 semanas | Medición dual, swing-up + estabilización |

### 9.2 Registro Mínimo por Corrida

- Fecha y hora (ISO 8601)
- Versión de firmware
- Parámetros de control (Kp, Ki, Kd)
- Frecuencia de muestreo
- Tipo de referencia (escalón, rampa)
- Métricas calculadas (overshoot, ts, error estacionario)
- Observaciones cualitativas

### 9.3 Sesiones Realizadas

| Sesión | Fecha | Archivo | Modo | Notas |
|--------|-------|---------|------|-------|
| 1 | 2026-05-07 00:32 | `qube_2026-05-07T00_32_35.csv` | m2 | Convergencia inicial |
| 2 | 2026-05-07 00:38 | `qube_2026-05-07T00_38_29.csv` | m2 | Sintonización Ki |
| 3 | 2026-05-07 00:41 | `qube_2026-05-07T00_41_58.csv` | m2 | Validación estabilidad |
| 4 | 2026-05-07 00:58 | `qube_2026-05-07T00_58_12.csv` | m2 | Test cambio setpoint |
| 5 | 2026-05-13 23:32 | `qube_2026-05-13T23_32_49.csv` | m2 | Post HW-FIX-1 |

---

## 10. Estabilización de Señales y Robustez

### 10.1 Fuentes de Ruido Identificadas

| Fuente | Amplitud típica | Frecuencia | Mitigación |
|--------|----------------|------------|------------|
| L298N PWM switching | 100 mV pico | 20 kHz ±5 kHz | Filtro RC, bypass caps |
| LM2596 switching | 50 mV pico | 1.5 MHz | Ferrite bead + bypass |
| Motor brush commutation | 200 mV pico | Irregular | Shielded cables |
| Power supply ripple | 30 mV p-p | 100 Hz | Bulk capacitors |

### 10.2 Estrategia de Mitigación por Capas

1. **Cableado y tierra**: Star ground, separación de retornos de potencia y señal
2. **Desacoplo**: Capacitancia bulk (470 µF + 100 µF), bypass local (100 nF × 4)
3. **Entrada encoder**: RC filter (470 Ω + 100 nF), Schmitt trigger recomendado para PCB Rev2
4. **Firmware**: ISR + polling dual, filtro EMA en velocidad

### 10.3 Problemas Conocidos y Soluciones

#### HW-FIX-1: Encoder open-drain con level shifter de alta impedancia

- **Síntoma:** CNT no actualiza aunque el eje gire
- **Causa:** Level shifter ~7 MΩ → τ RC ≈ 700 µs (demasiado lento)
- **Solución:** Pull-up 4.7 kΩ a 3.3 V en cada canal

#### SW-FIX-1: Ruido de cuantización en término derivativo

- **Síntoma:** Con Kd alto, oscilación violenta a 200 Hz
- **Causa:** ±1–2 counts de ruido → velocidades aparentes que dominan Kd
- **Solución:** Filtro EMA (α = 0.12) sobre velocidad estimada

#### SW-FIX-2: Dirección del motor vs encoder

- **Síntoma:** Lazo PID diverge inmediatamente
- **Causa:** Conexión OUT1/OUT2 produce retroalimentación positiva
- **Solución:** Constante `MOTOR_DIR = -1` en firmware

---

## 11. Costos y Viabilidad

### 11.1 BOM (Bill of Materials)

| Componente | Cantidad | Costo USD | Disponibilidad |
|------------|----------|-----------|----------------|
| ESP32-WROOM-32 | 1 | $6–10 | ⭐⭐⭐⭐⭐ |
| LM2596 buck converter | 1 | $1–3 | ⭐⭐⭐⭐⭐ |
| INA219 breakout | 1 | $2–4 | ⭐⭐⭐⭐⭐ |
| L298N motor driver | 1 | $1.50–3 | ⭐⭐⭐⭐⭐ |
| Motor DC + encoder | 1 | $15–30 | ⭐⭐⭐⭐ |
| Resistencias varias | Lote | <$1 | ⭐⭐⭐⭐⭐ |
| Capacitores varios | Lote | <$1 | ⭐⭐⭐⭐⭐ |
| **Subtotal (sin fuente)** | | **$26.50–51** | |
| **Con fuente/batería** | | **$50–80** | |

### 11.2 Comparación vs Quanser QUBE

| Factor | Este proyecto | Quanser QUBE | Ventaja |
|--------|--------------|--------------|---------|
| Costo | **$40–70 USD** | $2,500–3,500 USD | **98% menor** |
| Open-source | **Sí** | No | ✅ |
| Telemetría potencia | **INA219** | Integrado | ✅ |
| Escalabilidad | **Alta** | Cerrada | ✅ |
| Comunidad | **Creciente** | Pequeña | ✅ |
| Documentación | Exhaustiva | Profesional | ~ |

---

## 12. Integración del Encoder del Péndulo (Futuro)

### 12.1 Objetivo

Agregar segundo encoder en cuadratura para:
- Medición de ángulo del péndulo
- Estimación de velocidad angular del péndulo
- Base para swing-up y estabilización vertical (LQR)

### 12.2 Arquitectura Recomendada

Prioridad: **dual encoder con periférico PCNT del ESP32**

Ventajas:
- Menor jitter que polling puro
- Menor carga de CPU frente a ISR por ambos canales
- Escalable para mayores frecuencias de borde

### 12.3 Pines Sugeridos

| Señal | GPIO | Notas |
|-------|------|-------|
| PEND_A | GPIO32 | Entrada digital |
| PEND_B | GPIO33 | Entrada digital |
| PEND_Z | GPIO39 | Opcional (index) |

### 12.4 Plan de Implementación

1. Cableado y validación eléctrica (determinar tipo de salida: open-drain o push-pull)
2. Lectura en firmware sin control
3. Calibración CPR y signo
4. Filtrado de velocidad
5. Activación de modo de control dual (m3)

---

## 13. Hoja de Ruta para Tesis

```
Etapa 1: Consolidar base servo (COMPLETADO)
├── Estabilidad de posición/velocidad ✅
├── Pipeline de datos estable ✅
└── Telemetría INA219 funcional ✅

Etapa 2: Identificación de parámetros (EN PROGRESO)
├── Modelo simplificado calibrado con datos reales
└── Estimación de Km, b, J

Etapa 3: Integración del péndulo (Q2 2026)
├── Doble medición angular validada
└── Control PID péndulo (modo m3)

Etapa 4: Control avanzado (Q3 2026)
├── Estrategia de swing-up + LQR (modo m4)
└── Validación experimental completa

Etapa 5: Cierre académico (Q3–Q4 2026)
├── Comparativa contra literatura
├── Paper para IEEE Transactions on Education
└── Anexos de reproducibilidad
```

---

## 14. Criterios de Éxito

- ✅ Control de posición repetible con error estacionario < 2°
- ✅ Telemetría mecánica y energética estable
- ✅ Operación continua sin fallas críticas en sesión ≥ 1 hora
- ✅ Documentación suficiente para replicación por terceros
- ✅ Relación costo/beneficio favorable (98% vs QUBE original)

---

## 15. Referencias

### Papers Académicos

1. Akhtaruzzaman, M., & Shafie, A. A. (2010). Modeling and control of a rotary inverted pendulum using various methods. *IEEE ICMA 2010*. DOI: 10.1109/ICMA.2010.5589450

2. STMicroelectronics. (2019). *Introduction to Integrated Rotary Inverted Pendulum v2*. Educational Curriculum.

### Datasheets

3. Espressif Systems. (2024). *ESP32-WROOM-32 Datasheet* (Rev. 3.3).
4. STMicroelectronics. (2024). *L298 Dual Full-Bridge Driver* (Rev. 24).
5. Texas Instruments. (2024). *INA219 Current/Power Monitor* (SBOS400H, Rev. H).
6. Texas Instruments. (2024). *LM2596 Step-Down Voltage Regulator* (SNVS033C, Rev. C).

### Proyectos GitHub

7. Ezward. (2018–2024). *Esp32CameraRover2*. GitHub.
8. ebrahimabdelghfar. (2023). *Rotary-Inverted-Pendulum*. GitHub.
9. wty-yy. (2025). *arduino_pid_controlled_motor*. GitHub.
10. Hagar633. (2025). *Speed-Control-of-a-DC-Motor-Using-Arduino-and-L298N*. GitHub.

### Librerías

11. Adafruit Industries. (2024). *Adafruit_INA219*. GitHub. 229 ⭐
12. Espressif Systems. (2024). *ESP32 Arduino Core*. GitHub. 13K+ ⭐
13. bblanchon. (2024). *ArduinoJson*. GitHub. 7K+ ⭐

---

*Última actualización: Mayo 26, 2026*