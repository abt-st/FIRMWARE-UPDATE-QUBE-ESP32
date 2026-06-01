# Modelo Físico del Sistema QUBE Servo — ESP32

**Autor:** Documento técnico para tesis  
**Fecha:** 2026-06-01  
**Versión del firmware:** v1.19.0+  
**Plataforma:** ESP32-WROOM-32 + L298N + INA219 + LM2596  

---

## Índice

1. [Descripción General del Sistema](#1-descripción-general-del-sistema)
2. [Modelo Físico del Motor DC](#2-modelo-físico-del-motor-dc)
3. [Modelo del Encoder Cuadratura](#3-modelo-del-encoder-cuadratura)
4. [Modelo del Puente H (L298N)](#4-modelo-del-puente-h-l298n)
5. [Modelo del Péndulo Rotatorio Invertido](#5-modelo-del-péndulo-rotatorio-invertido)
6. [Modelo de Alimentación Eléctrica](#6-modelo-de-alimentación-eléctrica)
7. [Modelo de Señales y Ruido](#7-modelo-de-señales-y-ruido)
8. [Sistema de Control PID](#8-sistema-de-control-pid)
9. [Control LQR por Espacio de Estados](#9-control-lqr-por-espacio-de-estados)
10. [Estrategia de Swing-Up Energético](#10-estrategia-de-swing-up-energético)
11. [Guía de Ajuste y Sintonización](#11-guía-de-ajuste-y-sintonización)
12. [Parámetros del Firmware Actual](#12-parámetros-del-firmware-actual)
13. [Criterios de Validación Experimental](#13-criterios-de-validación-experimental)
14. [Referencias](#14-referencias)

---

## 1. Descripción General del Sistema

El sistema QUBE Servo modernizado es una plataforma educativa de control de sistemas rotatorios que emula funcionalmente al Quanser QUBE-Servo a una fracción del costo (~$40–70 USD vs. $2,500–3,500 USD).

### 1.1 Arquitectura de Bloques

```
                    ┌──────────────────────────────────────────────────┐
                    │            QUBE SERVO MODERNIZADO                │
                    └──────────────────────────────────────────────────┘

  ┌─────────┐    ┌──────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐
  │  Fuente  │───►│  INA219  │───►│  L298N  │───►│ Motor DC │◄──►│ Encoder  │
  │  12V DC  │    │ (I2C)    │    │(H-Bridge)│    │+ Péndulo │    │ Cuad.A/B │
  └─────────┘    └──────────┘    └─────────┘    └──────────┘    └──────────┘
       │                                             │                │
       ▼                                             │                │
  ┌──────────┐                                        │                │
  │  LM2596  │──── 5V ──►┌──────────┐                │                │
  │  (Buck)  │            │  ESP32   │◄───────────────┘                │
  └──────────┘            │ WROOM-32 │◄────────────────────────────────┘
                          │          │
                          │ GPIO 26/27──► L298N IN1/IN2 (PWM)
                          │ GPIO 34/35──► Encoder servo A/B
                          │ GPIO 32/33──► Encoder péndulo A/B
                          │ GPIO 21/22──► INA219 SDA/SCL (I2C)
                          └─────┬────┘
                                │ WiFi AP / HTTP REST
                                ▼
                          ┌──────────┐
                          │ GUI      │
                          │ Python   │
                          └──────────┘
```

### 1.2 Especificaciones del Sistema Completo

| Parámetro | Valor |
|-----------|-------|
| Microcontrolador | ESP32-WROOM-32 (Dual-core 240 MHz) |
| Driver de motor | L298N (H-bridge dual) |
| Sensor de corriente | INA219 (I2C, 0x40) |
| Regulador | LM2596 (Buck, 5V @ 3A) |
| Motor | DC con encoder Premotec 990412016913 |
| Encoder CPR | 2048 counts/rev (X4 → 8192 counts/rev) |
| Frecuencia de control | 200 Hz (5 ms) |
| PWM | 20 kHz, 8-bit (0–255) |
| Comunicación | WiFi AP (192.168.4.1), HTTP REST |

---

## 2. Modelo Físico del Motor DC

### 2.1 Ecuaciones de Movimiento

Un motor de corriente directa (DC) se modela mediante dos ecuaciones acopladas: la ecuación eléctrica del devanado de armadura y la ecuación mecánica del rotor.

#### Ecuación Eléctrica (Armadura)

$$
V_a = R_a \cdot i_a + L_a \cdot \frac{di_a}{dt} + e_b
$$

Donde:
- $V_a$ = voltaje aplicado a la armadura [V]
- $R_a$ = resistencia del devanado de armadura [Ω]
- $L_a$ = inductancia del devanado de armadura [H]
- $i_a$ = corriente de armadura [A]
- $e_b$ = fuerza contraelectromotriz (back-EMF) [V]

La fuerza contraelectromotriz es proporcional a la velocidad angular:

$$
e_b = K_e \cdot \omega
$$

Donde $K_e$ es la constante de back-EMF [V·s/rad] y $\omega$ es la velocidad angular [rad/s].

#### Ecuación Mecánica (Rotor)

$$
J \cdot \frac{d\omega}{dt} = \tau_m - b \cdot \omega - \tau_{ext}
$$

Donde:
- $J$ = momento de inercia del rotor + carga [kg·m²]
- $\tau_m$ = torque motor [N·m]
- $b$ = coeficiente de fricción viscosa [N·m·s/rad]
- $\tau_{ext}$ = torque de carga externa [N·m]

El torque del motor es proporcional a la corriente:

$$
\tau_m = K_t \cdot i_a
$$

Para un motor SI consistente, $K_t = K_e$ (en unidades coherentes).

#### Modelo en Espacio de Estados (Motor DC)

Definiendo el vector de estados $x = [i_a, \omega]^T$ y entrada $u = V_a$:

$$
\begin{bmatrix}
\dot{i_a} \\
\dot{\omega}
\end{bmatrix}
=
\begin{bmatrix}
-\frac{R_a}{L_a} & -\frac{K_e}{L_a} \\
\frac{K_t}{J} & -\frac{b}{J}
\end{bmatrix}
\begin{bmatrix}
i_a \\
\omega
\end{bmatrix}
+
\begin{bmatrix}
\frac{1}{L_a} \\
0
\end{bmatrix}
V_a
$$

### 2.2 Modelo Simplificado (Región de Operación)

En la región de operación típica del QUBE (frecuencias de control ≪ frecuencia eléctrica), se puede asumir $L_a \cdot di_a/dt \approx 0$, obteniendo un modelo de primer orden:

$$
\tau_m \cdot \dot{\omega} + \omega = K_m \cdot V_a
$$

Donde:
- $\tau_m = \frac{J \cdot R_a}{K_t \cdot K_e + R_a \cdot b}$ = constante de tiempo mecánica [s]
- $K_m = \frac{K_t}{K_t \cdot K_e + R_a \cdot b}$ = ganancia estática del motor [rad/s/V]

**En la práctica**, los parámetros $K_t$, $b$, $J$ se estiman experimentalmente excitando el motor con un escalón de voltaje PWM y registrando la velocidad (encoder).

### 2.3 Modelo en el Dominio de la Frecuencia

Aplicando la transformada de Laplace al modelo simplificado:

$$
G_{motor}(s) = \frac{\Omega(s)}{V_a(s)} = \frac{K_m}{\tau_m \cdot s + 1}
$$

Para posición ($\theta = \int \omega \, dt$):

$$
G_{pos}(s) = \frac{\Theta(s)}{V_a(s)} = \frac{K_m}{s \cdot (\tau_m \cdot s + 1)}
$$

### 2.4 Constantes y Parámetros Estimados

| Parámetro | Símbolo | Rango típico | Unidades | Método de estimación |
|-----------|---------|-------------|----------|---------------------|
| Constante de torque | $K_t$ | 0.01–0.05 | N·m/A | Escalón de corriente |
| Constante back-EMF | $K_e$ | 0.01–0.05 | V·s/rad | Curva velocidad-voltaje |
| Resistencia armadura | $R_a$ | 1–10 | Ω | Multímetro estático |
| Inductancia armadura | $L_a$ | 0.1–1.0 | mH | LCR meter |
| Inercia rotor | $J$ | 1e-6–1e-4 | kg·m² | Péndulo libre |
| Fricción viscosa | $b$ | 1e-5–1e-3 | N·m·s/rad | Decaimiento libre |
| Fricción estática | $T_f$ | 0.001–0.01 | N·m | Umbral de movimiento |

### 2.5 Diagrama de Bloques del Motor

```
                 ┌───────────────────────────────────┐
                 │           MOTOR DC                 │
                 │                                   │
 V_a ──►(+)─────┤  1/R_a  ──► K_t ──►  1/(Js+b) ──┤──► ω
         ▲       │                                   │    │
         │       │       ◄──── K_e ◄─────────────────┘    │
         │       └───────────────────────────────────┘    │
         │                                                │
         │                                                ▼
         │                                         θ = ω/s
         │                                                │
         └────────────────────────────────────────────────┘
                      (retroalimentación negativa)
```

---

## 3. Modelo del Encoder Cuadratura

### 3.1 Principio de Operación

Un encoder óptico incremental de dos canales (A y B) genera pulsos en cuadratura. Los flancos de ambas señales permiten 4 estados por ciclo fundamental, multiplicando la resolución por 4 (decodificación X4).

### 3.2 Resolución

$$
\text{Resolución angular} = \frac{360°}{N_{CPR} \times 4}
$$

Para el encoder Premotec con $N_{CPR} = 2048$:

$$
\text{Resolución} = \frac{360°}{2048 \times 4} = \frac{360°}{8192} \approx 0.044°
$$

### 3.3 Conversión de Cuentas a Ángulo

$$
\theta_{raw} = D_{enc} \times C \times \frac{360°}{N_{CPR}}
$$

$$
\theta = \theta_{raw} - \theta_{offset}
$$

Donde:
- $D_{enc}$ = dirección del encoder (+1 o -1)
- $C$ = contador acumulado de cuentas
- $N_{CPR}$ = cuentas por revolución del encoder
- $\theta_{offset}$ = offset de cero definido por el usuario

### 3.4 Estimación de Velocidad Angular

La velocidad se estima por diferencias finitas y se suaviza con un filtro EMA:

$$
\omega_{raw}(k) = -\frac{\theta(k) - \theta(k-1)}{T_s}
$$

$$
\hat{\omega}(k) = \alpha \cdot \omega_{raw}(k) + (1 - \alpha) \cdot \hat{\omega}(k-1)
$$

Donde:
- $T_s$ = período de muestreo (5 ms @ 200 Hz)
- $\alpha$ = factor de suavizado EMA ($\alpha = 0.12$ para servo, $\alpha = 0.15$ para péndulo)

### 3.5 Tabla de Decodificación Cuadratura (X4)

```
Estado anterior → Estado actual | ΔCuentas
───────────────────────────────────────────
    00 → 01                     |   +1
    01 → 00                     |   -1
    01 → 11                     |   +1
    11 → 01                     |   -1
    11 → 10                     |   +1
    10 → 11                     |   -1
    10 → 00                     |   +1
    00 → 10                     |   -1
    (transiciones inválidas)    |    0
```

### 3.6 Limitaciones y Riesgos

| Problema | Causa | Solución |
|----------|-------|---------|
| Pérdida de pulsos | Polling más lento que transiciones | PCNT (hardware counter) o ISR |
| Edges falsos por ruido | Conmutación PWM, escobillas | Schmitt trigger + RC filter |
| Alias de muestreo | $f_{sampling} < 2 \times f_{encoder}$ | Aumentar frecuencia o usar ISR |

**Criterio de Nyquist para encoder:**

$$
f_{muestreo} > 2 \times f_{encoder,max}
$$

$$
f_{encoder,max} = \frac{N_{CPR} \times 4 \times \omega_{max}}{360}
$$

Para 400 RPM y 2048 CPR:

$$
f_{encoder,max} = \frac{2048 \times 4 \times 400}{60} \approx 54{,}613 \text{ edges/s}
$$

$$
f_{muestreo,requerido} > 109{,}226 \text{ Hz}
$$

**El polling a 200 Hz genera alias severo.** Se requiere PCNT o ISR para conteo preciso.

---

## 4. Modelo del Puente H (L298N)

### 4.1 Topología

El L298N es un puente H dual que permite controlar la dirección y magnitud del voltaje aplicado al motor.

```
            V_s (12V)
             │
     ┌───────┴───────┐
     │               │
  ┌──┴──┐         ┌──┴──┐
  │ Q1  │         │ Q3  │
  │(PNP)│         │(PNP)│
  └──┬──┘         └──┬──┘
     │    OUT1    OUT2│
     ├───────┬────────┤
     │    ┌──┴──┐     │
     │    │MOTOR│     │
     │    │ DC  │     │
     │    └──┬──┘     │
     ├───────┴────────┤
  ┌──┴──┐         ┌──┴──┐
  │ Q2  │         │ Q4  │
  │(NPN)│         │(NPN)│
  └──┬──┘         └──┬──┘
     │               │
     └───────┬───────┘
            GND
```

### 4.2 Modulación PWM

El control se realiza por modulación de ancho de pulso (PWM):

$$
V_{motor,avg} = D \times V_s
$$

Donde:
- $D$ = ciclo de trabajo ($D \in [0, 1]$)
- $V_s$ = voltaje de alimentación del motor

Para PWM diferencial (IN1/IN2):

| IN1 | IN2 | Movimiento |
|-----|-----|-----------|
| PWM | 0 | Giro horario (velocidad proporcional) |
| 0 | PWM | Giro antihorario |
| 0 | 0 | Freno (brake) |
| 1 | 1 | Freno (brake) |

### 4.3 Pérdidas en el L298N

$$
V_{out} = V_{in} - V_{drop,transistor} \times 2
$$

| Parámetro | Valor | Notas |
|-----------|-------|-------|
| Caída de voltaje (saturación) | ~2.0 V (1.0 V × 2 transistores) | A 2A |
| Resistencia RDS(on) | ~0.53 Ω por transistor | A 25°C |
| Disipación máxima | 25 W (con disipador) | Sin disipador: ~2W |
| Corriente máxima por canal | 2 A (continuo), 3 A (pico) | Con disipador |

### 4.4 Modelo del L298N como Bloque

$$
V_{motor} = \begin{cases}
D \cdot (V_s - 2V_{drop}) & \text{si } D > 0 \text{ (adelante)} \\
-D \cdot (V_s - 2V_{drop}) & \text{si } D < 0 \text{ (atrás)}
\end{cases}
$$

La zona muerta del motor (deadband) se modela como:

$$
u_{eff} = \begin{cases}
u & \text{si } |u| > PWM_{min} \\
0 & \text{si } |u| \leq PWM_{min}
\end{cases}
$$

---

## 5. Modelo del Péndulo Rotatorio Invertido

### 5.1 Descripción del Sistema

El péndulo rotatorio invertido consiste en un péndulo simple articulado al final de un brazo rotatorio. El motor DC acciona el brazo, y el péndulo puede colgar libremente hacia abajo (estable) o mantenerse en posición vertical invertida (inestable).

### 5.2 Coordenadas Generalizadas

- $\theta$: ángulo del brazo del servo (posición del motor) [rad]
- $\alpha$: ángulo del péndulo respecto a la vertical ascendente [rad]

**Convención de signos:**
- $\alpha = 0$: péndulo en la vertical invertida (equilibrio inestable)
- $\alpha = \pi$: péndulo colgando (estable)

### 5.3 Ecuaciones de Euler-Lagrange

El Lagrangiano del sistema es $\mathcal{L} = T - V$, donde $T$ es la energía cinética y $V$ la energía potencial.

#### Energía Cinética

$$
T = \frac{1}{2}(J_{arm} + m_p L^2)\dot{\theta}^2 + \frac{1}{2}J_p \dot{\alpha}^2 + m_p L \cdot d \cdot \dot{\theta} \cdot \dot{\alpha} \cdot \cos(\alpha)
$$

Donde:
- $J_{arm}$ = momento de inercia del brazo servo [kg·m²]
- $m_p$ = masa del péndulo [kg]
- $L$ = distancia del eje del motor al eje del péndulo [m]
- $d$ = distancia del eje del péndulo al centro de masa [m]
- $J_p$ = momento de inercia del péndulo sobre su eje [kg·m²]

#### Energía Potencial

$$
V = m_p \cdot g \cdot d \cdot \cos(\alpha)
$$

#### Ecuaciones de Movimiento

Aplicando Euler-Lagrange $\frac{d}{dt}\frac{\partial \mathcal{L}}{\partial \dot{q_i}} - \frac{\partial \mathcal{L}}{\partial q_i} = Q_i$:

**Para $\theta$ (brazo):**

$$
(J_{arm} + m_p L^2)\ddot{\theta} + m_p L d \cdot \ddot{\alpha} \cos(\alpha) - m_p L d \cdot \dot{\alpha}^2 \sin(\alpha) = \tau - b_1 \dot{\theta}
$$

**Para $\alpha$ (péndulo):**

$$
m_p L d \cdot \ddot{\theta} \cos(\alpha) + J_p \ddot{\alpha} - m_p g d \sin(\alpha) = -b_2 \dot{\alpha}
$$

Donde:
- $\tau$ = torque aplicado por el motor [N·m]
- $b_1$ = fricción viscosa del brazo [N·m·s/rad]
- $b_2$ = fricción viscosa del péndulo [N·m·s/rad]

### 5.4 Modelo Linealizado (cerca de $\alpha = 0$)

Para el control de estabilización, se linealiza alrededor del equilibrio inestable ($\alpha = 0$, $\dot{\alpha} = 0$):

Usando las aproximaciones $\sin(\alpha) \approx \alpha$, $\cos(\alpha) \approx 1$, y descartando términos de segundo orden:

$$
\begin{bmatrix}
\ddot{\theta} \\
\ddot{\alpha}
\end{bmatrix}
=
\begin{bmatrix}
a_{11} & a_{12} \\
a_{21} & a_{22}
\end{bmatrix}
\begin{bmatrix}
\dot{\theta} \\
\dot{\alpha}
\end{bmatrix}
+
\begin{bmatrix}
b_1 \\
b_2
\end{bmatrix}
\alpha
+
\begin{bmatrix}
c_1 \\
c_2
\end{bmatrix}
\tau
$$

Donde los coeficientes se derivan de:

$$
\Delta = (J_{arm} + m_p L^2) J_p - (m_p L d)^2
$$

$$
a_{11} = \frac{-b_1 J_p}{\Delta}, \quad
a_{12} = \frac{b_2 m_p L d}{\Delta}
$$

$$
a_{21} = \frac{b_1 m_p L d}{\Delta}, \quad
a_{22} = \frac{-b_2(J_{arm} + m_p L^2)}{\Delta}
$$

$$
b_1 = \frac{m_p g d (J_{arm} + m_p L^2)}{\Delta}, \quad
b_2 = \frac{-m_p g d \cdot m_p L d}{\Delta}
$$

$$
c_1 = \frac{J_p}{\Delta}, \quad
c_2 = \frac{-m_p L d}{\Delta}
$$

### 5.5 Modelo de Estado Linealizado

Definiendo $x = [\theta, \alpha, \dot{\theta}, \dot{\alpha}]^T$ y $u = \tau$:

$$
\dot{x} = A \cdot x + B \cdot u
$$

$$
A = \begin{bmatrix}
0 & 0 & 1 & 0 \\
0 & 0 & 0 & 1 \\
0 & b_1 & a_{11} & a_{12} \\
0 & b_2 & a_{21} & a_{22}
\end{bmatrix}, \quad
B = \begin{bmatrix}
0 \\ 0 \\ c_1 \\ c_2
\end{bmatrix}
$$

### 5.6 Valores Numéricos Estimados (Premotec 990412016913)

| Parámetro | Símbolo | Valor estimado | Unidades |
|-----------|---------|---------------|----------|
| Masa péndulo | $m_p$ | 0.025 | kg |
| Distancia pivot-CM | $d$ | 0.065 | m |
| Distancia motor-pivot | $L$ | 0.078 | m |
| Inercia péndulo | $J_p$ | 2.0 × 10⁻⁵ | kg·m² |
| Inercia brazo | $J_{arm}$ | 1.0 × 10⁻⁴ | kg·m² |
| Gravedad | $g$ | 9.81 | m/s² |
| Fricción brazo | $b_1$ | 1.0 × 10⁻³ | N·m·s/rad |
| Fricción péndulo | $b_2$ | 5.0 × 10⁻⁴ | N·m·s/rad |

> ⚠️ **Nota:** Estos valores son estimaciones iniciales. Se requiere identificación experimental con datos del sistema real.

---

## 6. Modelo de Alimentación Eléctrica

### 6.1 Topología de Potencia

```
Fuente 12V ──┬── INA219 (serie) ──► L298N VS (motor 12V)
             │
             └── LM2596 (buck) ──► 5V rail
                                      ├── ESP32 VIN (→ 3.3V AMS1117)
                                      ├── L298N VSS (lógica)
                                      ├── Encoder VCC
                                      └── CD40106BE VCC
```

### 6.2 LM2596 — Conversor Buck

**Ecuación fundamental:**

$$
V_{out} = V_{in} \times D_{buck}
$$

Donde $D_{buck}$ es el ciclo de trabajo interno del regulador.

**Características clave:**

| Parámetro | Valor |
|-----------|-------|
| Entrada | 4.5V–40V |
| Salida | 1.23V–37V (ajustable) |
| Corriente de salida | 3A (continuo) |
| Frecuencia de conmutación | 150 kHz |
| Eficiencia típica | 80–92% |
| Ripple de salida | <50 mV p-p (con filtro adecuado) |

### 6.3 INA219 — Sensor de Corriente

El INA219 mide voltaje de bus, corriente (via shunt) y potencia calculada.

**Ecuaciones de medición:**

$$
V_{shunt} = I \times R_{shunt}
$$

$$
I = \frac{V_{shunt}}{R_{shunt,interno}}
$$

$$
P = V_{bus} \times I
$$

El rango del INA219 es configurable:

| Rango | LSB Corriente | LSB Voltaje | Resolución |
|-------|--------------|-------------|------------|
| ±32 mA | 0.01 mA | 0.04 mV | Alta |
| ±320 mA | 0.1 mA | 0.4 mV | Media |
| ±3.2 A | 1 mA | 4 mV | Baja |

### 6.4 Red de Desacoplo

```
                  470µF          100µF          10µF ceramic
Fuente 12V ──┬──┤├──┬──┤├──┬──┤├──┬── V_s (L298N)
             │       │       │       │
             │     100nF×4   │     100nF×2
             │       │       │       │
GND ─────────┴───────┴───────┴───────┴── GND
```

---

## 7. Modelo de Señales y Ruido

### 7.1 Fuentes de Ruido Identificadas

| Fuente | Amplitud | Frecuencia | Mecanismo |
|--------|----------|------------|-----------|
| L298N PWM switching | ~100 mV pico | 20 kHz ±5 kHz | Conmutación de transistores |
| LM2596 switching | ~50 mV pico | 150 kHz | Ripple de salida |
| Motor brush commutation | ~200 mV pico | Irregular | Chisporroteo de escobillas |
| Ripple 5V rail | ~30 mV p-p | 100 Hz | Rizado de fuente |

### 7.2 Modelo del Filtro EMA

El filtro Exponential Moving Average se usa en firmware para suavizar la velocidad estimada:

$$
y(k) = \alpha \cdot x(k) + (1 - \alpha) \cdot y(k-1)
$$

**Respuesta en frecuencia:**

$$
|H(f)| = \frac{\alpha}{\sqrt{(1 - \cos(2\pi f T_s))^2 \cdot (1-\alpha)^2 + (\alpha + (1-\alpha)\cos(2\pi f T_s))^2}}
$$

**Frecuencia de corte (−3 dB):**

$$
f_c \approx \frac{\alpha}{2\pi \cdot T_s \cdot (1 - \alpha)}
$$

Para $\alpha = 0.12$ y $T_s = 5$ ms:

$$
f_c \approx \frac{0.12}{2\pi \times 0.005 \times 0.88} \approx 4.35 \text{ Hz}
$$

### 7.3 Modelo del Filtro RC para Encoder

$$
H_{RC}(s) = \frac{1}{1 + s \cdot R \cdot C}
$$

$$
f_{c,RC} = \frac{1}{2\pi \cdot R \cdot C}
$$

Para $R = 470\,\Omega$ y $C = 100\,\text{nF}$:

$$
f_{c,RC} = \frac{1}{2\pi \times 470 \times 100 \times 10^{-9}} \approx 3{,}386 \text{ Hz}
$$

---

## 8. Sistema de Control PID

### 8.1 Ecuación del PID Continuo

$$
u(t) = K_p \cdot e(t) + K_i \cdot \int_0^t e(\tau)\,d\tau + K_d \cdot \frac{de(t)}{dt}
$$

Donde $e(t) = r(t) - y(t)$ es el error entre el setpoint y la medición.

### 8.2 Implementación Discreta (Firmware)

El PID se implementa con aproximaciones de diferencias finitas y un filtro EMA en la derivada.

#### Término Proporcional

$$
P = K_p \cdot e(k)
$$

#### Término Integral (con anti-windup)

$$
I(k) = I(k-1) + e(k) \cdot T_s
$$

$$
I(k) = \text{constrain}(I(k), -I_{max}, I_{max})
$$

$$
\text{Salida integral} = K_i \cdot I(k)
$$

**Condición de habilitación de la integral (firmware v1.17.0+):**

La integral solo se acumula cuando:
- $|e(k)| < 45°$ (servo) o $|e(k)| < 90°$ (péndulo)
- $|\omega(k)| < 60°/\text{s}$ (servo) o $|\omega(k)| < 120°/\text{s}$ (péndulo)

Si alguna condición se viola, $I(k) = 0$.

#### Término Derivativo (con filtro EMA)

En lugar de derivar el error, se deriva la posición para evitar "derivative kick" al cambiar el setpoint:

$$
\omega_{raw}(k) = -\frac{y(k) - y(k-1)}{T_s}
$$

$$
\hat{\omega}(k) = \alpha \cdot \omega_{raw}(k) + (1 - \alpha) \cdot \hat{\omega}(k-1)
$$

$$
\text{Salida derivativa} = K_d \cdot \hat{\omega}(k)
$$

> **Nota:** El signo negativo se debe a que la derivada de la posición se usa como retroalimentación negativa.

#### Salida del Controlador

$$
u(k) = K_p \cdot e(k) + K_i \cdot I(k) + K_d \cdot \hat{\omega}(k)
$$

$$
\text{PWM}(k) = \text{MOTOR\_DIR} \times u(k)
$$

### 8.3 Protecciones Implementadas

#### Zona Muerta (Deadband)

$$
\text{Si } |e(k)| \leq 0.8° \text{ (servo) o } |e(k)| \leq 0.5° \text{ (péndulo):}
$$
$$
\text{PWM} = 0
$$

#### Límite de PWM Mínimo (Anti-stiction)

$$
\text{Si } |PWM| < PWM_{min} \text{ y } |e(k)| > umbral:
$$
$$
PWM = \text{signo}(PWM) \times PWM_{min}
$$

#### Saturación Adaptativa del PWM

El PWM máximo se reduce progresivamente al acercarse al setpoint:

| Error | PWM máximo |
|-------|-----------|
| > 20° | 100 |
| < 20° | 80 |
| < 10° | 55 |
| < 5° | 35 |

### 8.4 Diagrama de Bloques del PID

```
                                     ┌──────────────────────────────┐
                                     │          MOTOR DC             │
 r(k) ──►(+)──► PID ──► PWM ──► L298N ──►│  G(s) = Km/(τs+1) │──► θ
          ▲     │                    │     └──────────┬─────────────┘
          │     │                    │                │
          │     └────────────────────┼────────────────┘
          │                          │
          └──────────────────────────┘
                   Encoder + Conversión
```

### 8.5 Análisis de Estabilidad

Para el sistema en lazo cerrado con PID, la función de transferencia del lazo es:

$$
L(s) = C(s) \cdot G(s) = \left(K_p + \frac{K_i}{s} + K_d \cdot s \cdot \frac{\alpha}{1 + (1-\alpha) \cdot s \cdot T_s}\right) \cdot \frac{K_m}{s(\tau_m s + 1)}
$$

**Criterio de estabilidad de Bode:**
- Margen de ganancia > 6 dB
- Margen de fase > 30°

**Criterio de Nyquist:** La curva de Nyquist no debe encerrar el punto (−1, 0).

---

## 9. Control LQR por Espacio de Estados

### 9.1 Formulación

El controlador LQR (Linear Quadratic Regulator) minimiza una función de costo cuadrática:

$$
J = \int_0^{\infty} \left(x^T Q x + u^T R u\right) dt
$$

Donde:
- $Q$ = matriz de peso del estado (positiva semidefinida)
- $R$ = peso del esfuerzo de control (positiva definida)

### 9.2 Ganancia Óptima

La ganancia $K$ se obtiene resolviendo la ecuación de Riccati algebraica:

$$
A^T P + P A - P B R^{-1} B^T P + Q = 0
$$

$$
K = R^{-1} B^T P
$$

### 9.3 Implementación en Firmware

El vector de estados se define como:

$$
x = [\theta, \alpha, \dot{\theta}, \dot{\alpha}]^T
$$

Donde:
- $\theta$ = posición del servo (brazo) [grados]
- $\alpha$ = ángulo del péndulo desde la vertical [grados]
- $\dot{\theta}$ = velocidad angular del servo [°/s]
- $\dot{\alpha}$ = velocidad angular del péndulo [°/s]

**Ley de control:**

$$
u = -(K_1 \cdot \theta + K_2 \cdot \alpha + K_3 \cdot \dot{\theta} + K_4 \cdot \dot{\alpha})
$$

### 9.4 Ganancias Actuales del Firmware

| Ganancia | Símbolo | Valor | Interpretación |
|----------|---------|-------|---------------|
| $K_1$ | `lqr_K1` | 1.0 | Peso de posición servo |
| $K_2$ | `lqr_K2` | 25.0 | Peso de ángulo péndulo |
| $K_3$ | `lqr_K3` | 0.5 | Peso de velocidad servo |
| $K_4$ | `lqr_K4` | 3.0 | Peso de velocidad péndulo |

> ⚠️ **Nota:** Estas ganancias son valores iniciales. La síntesis LQR formal requiere el modelo linealizado calibrado con parámetros experimentales.

### 9.5 Protecciones

- Si $|\alpha| > 150°$, el PWM se pone a 0 (el péndulo está lejos de la vertical; no aplicar torque).
- El PWM se satura en $[-PWM_{max}, PWM_{max}]$.

---

## 10. Estrategia de Swing-Up Energético

### 10.1 Problema

El péndulo invertido tiene dos equilibrios: $\alpha = 0$ (inestable) y $\alpha = \pi$ (estable). El LQR solo funciona cerca de $\alpha = 0$. Se necesita una estrategia para elevar el péndulo desde la posición colgando hasta la vertical.

### 10.2 Método de Bombeo de Energía (Quanser)

La energía total del péndulo (respecto a la posición invertida) es:

$$
E = \frac{1}{2} J_p \dot{\alpha}^2 + m_p g d (1 - \cos\alpha)
$$

La energía de referencia (en el equilibrio inestable) es:

$$
E_r = 2 \cdot m_p \cdot g \cdot d
$$

El controlador de energía aplica:

$$
u = k_e \cdot (E - E_r) \cdot \text{sign}(\dot{\alpha} \cdot \cos\alpha)
$$

Donde:
- $k_e$ = ganancia del controlador de energía
- $\text{sign}(\dot{\alpha} \cdot \cos\alpha)$ = dirección de bombeo

### 10.3 Lógica de Transición

1. **Fase de excitación:** Si el péndulo está muy quieto ($|\dot{\alpha}| < 0.1$ rad/s), aplicar un "kick" para iniciar oscilación.
2. **Bombeo de energía:** Usar la ley de control de energía hasta que $E \approx E_r$.
3. **Transición a LQR:** Cuando el péndulo está cerca de la vertical ($|\alpha - 180°| < \text{threshold}$), cambiar a modo LQR.

### 10.4 Diagrama de Estados

```
           ┌─────────────┐
           │  m5: SWING  │
           │  - Excitación│
           │  - Bombeo E  │
           └──────┬──────┘
                  │ |α - 180°| < threshold
                  ▼
           ┌─────────────┐
           │  m4: LQR    │
           │  - Balance   │
           │  - Estab.   │
           └──────┬──────┘
                  │ |α| > 150° (pérdida)
                  ▼
           ┌─────────────┐
           │  m5: SWING  │
           │  (reintento)│
           └─────────────┘
```

### 10.5 Parámetros del Swing-Up

| Parámetro | Símbolo | Valor | Unidades |
|-----------|---------|-------|----------|
| Masa péndulo | $m_p$ | 0.025 | kg |
| Distancia pivot-CM | $d$ | 0.065 | m |
| Inercia péndulo | $J_p$ | 2.0 × 10⁻⁵ | kg·m² |
| Ganancia energía | $k_e$ | 0.5 | (ajustable) |
| Umbral de balance | — | 20° | grados |

---

## 11. Guía de Ajuste y Sintonización

### 11.1 Método de Sintonización PID para el Servo

#### Paso 1: Solo Proporcional (Ki = 0, Kd = 0)

1. Empezar con $K_p = 0.1$.
2. Aumentar $K_p$ gradualmente hasta que el sistema oscile sostenidamente.
3. Anotar $K_{p,osc}$ (ganancia de oscilación) y $T_{osc}$ (período de oscilación).

**Regla de Ziegler-Nichols ( closed-loop):**

| Controlador | $K_p$ | $T_i$ | $T_d$ |
|------------|-------|-------|-------|
| P | $0.5 K_{p,osc}$ | — | — |
| PI | $0.45 K_{p,osc}$ | $T_{osc}/1.2$ | — |
| PID | $0.6 K_{p,osc}$ | $T_{osc}/2$ | $T_{osc}/8$ |

#### Paso 2: Agregar Derivativo

- Si hay oscilación: aumentar $K_d$ para amortiguar.
- Si hay overshoot excesivo: aumentar $K_d$.
- Si el sistema es lento: reducir $K_d$.

**Valores iniciales recomendados para el QUBE:**

| Ganancia | Rango típico | Efecto |
|----------|-------------|--------|
| $K_p$ | 0.3 – 1.5 | Velocidad de respuesta vs. overshoot |
| $K_i$ | 0.0 – 0.2 | Elimina error estacionario vs. windup |
| $K_d$ | 0.02 – 0.2 | Amortiguación vs. sensibilidad a ruido |

#### Paso 3: Agregar Integral

- Solo si hay error estacionario persistente.
- Empezar con $K_i$ muy bajo (0.001).
- Aumentar gradualmente.
- **Siempre** usar anti-windup ($I_{max} = 250$).

### 11.2 Método de Sintonización para el Péndulo

El péndulo tiene dinámica más rápida y es inestable. Usar ganancias más agresivas:

| Ganancia | Rango típico | Efecto |
|----------|-------------|--------|
| $K_{p,pend}$ | 5 – 30 | Rigidez del balance |
| $K_{i,pend}$ | 0.1 – 2.0 | Elimina offset |
| $K_{d,pend}$ | 0.5 – 5.0 | Amortiguación |

### 11.3 Síntesis LQR

Para sintetizar las ganancias LQR, se necesita:

1. **Identificar parámetros** del sistema real ($K_t$, $b$, $J$, etc.)
2. **Construir el modelo linealizado** $A$, $B$
3. **Elegir $Q$ y $R$:**

$$
Q = \text{diag}(q_1, q_2, q_3, q_4), \quad R = [r]
$$

| Parámetro | Interpretación | Efecto de aumentar |
|-----------|---------------|-------------------|
| $q_1$ ($\theta$) | Penaliza posición servo | Brazo más rígido |
| $q_2$ ($\alpha$) | Penaliza ángulo péndulo | Balance más preciso |
| $q_3$ ($\dot{\theta}$) | Penaliza velocidad servo | Reduce oscilaciones |
| $q_4$ ($\dot{\alpha}$) | Penaliza velocidad péndulo | Amortigua péndulo |
| $r$ ($u$) | Penaliza esfuerzo de control | Reduce consumo, respuesta más lenta |

4. **Resolver Riccati** con `scipy.linalg.lqr(A, B, Q, R)` o MATLAB.

### 11.4 Parámetros de Filtrado

| Parámetro | Símbolo | Valor | Efecto |
|-----------|---------|-------|--------|
| Suavizado velocidad servo | $\alpha$ | 0.12 | Más bajo → más suave, más lag |
| Suavizado velocidad péndulo | $\alpha_{pend}$ | 0.15 | Idem |
| Suavizado corriente INA219 | — | 0.9 / 0.1 | Filtro EMA de corriente |

### 11.5 Troubleshooting de Sintonización

| Síntoma | Causa probable | Solución |
|---------|---------------|---------|
| Oscilación sostenida | $K_p$ demasiado alto | Reducir $K_p$ o aumentar $K_d$ |
| Overshoot > 30% | $K_d$ insuficiente | Aumentar $K_d$ en 50% |
| Error estacionario > 2° | $K_i = 0$ o muy bajo | Aumentar $K_i$ gradualmente |
| Motor vibrando en reposo | Ruido en derivada | Aumentar $\alpha$ (más filtrado) |
| Lazo diverge | Polaridad incorrecta | Cambiar `MOTOR_DIR` |
| Integral crece sin control | Windup | Verificar $I_{max}$ y condiciones |
| Péndulo no balancea | $K_2$ muy bajo | Aumentar `lqr_K2` |
| Péndulo oscila en LQR | $K_4$ insuficiente | Aumentar `lqr_K4` |
| Swing-up no alcanza vertical | $k_e$ muy bajo | Aumentar `ke_gain` |
| Transición LQR falla | Threshold muy bajo | Aumentar `balance_threshold` |

---

## 12. Parámetros del Firmware Actual

### 12.1 PID Servo (Modo 2)

| Parámetro | Variable | Valor |
|-----------|----------|-------|
| Ganancia proporcional | `Kp` | 3.0 |
| Ganancia integral | `Ki` | 0.5 |
| Ganancia derivativa | `Kd` | 0.15 |
| Filtro EMA velocidad | `VEL_ALPHA` | 0.12 |
| Límite anti-windup | `INTEGRAL_LIMIT` | 250.0 |
| PWM mínimo | `PWM_MIN` | 12 |
| PWM máximo | `PWM_MAX` | 100 |
| Banda muerta | deadband | ±0.8° |
| Dirección motor | `MOTOR_DIR` | -1 |

### 12.2 PID Péndulo (Modo 3)

| Parámetro | Variable | Valor |
|-----------|----------|-------|
| Ganancia proporcional | `Kp_pend` | 15.0 |
| Ganancia integral | `Ki_pend` | 0.5 |
| Ganancia derivativa | `Kd_pend` | 2.0 |
| Filtro EMA velocidad | `VEL_ALPHA_PEND` | 0.15 |

### 12.3 LQR (Modo 4)

| Parámetro | Variable | Valor |
|-----------|----------|-------|
| Ganancia posición servo | `lqr_K1` | 1.0 |
| Ganancia ángulo péndulo | `lqr_K2` | 25.0 |
| Ganancia velocidad servo | `lqr_K3` | 0.5 |
| Ganancia velocidad péndulo | `lqr_K4` | 3.0 |

### 12.4 Swing-Up (Modo 5)

| Parámetro | Variable | Valor |
|-----------|----------|-------|
| Ganancia energía | `ke_gain` | 0.5 |
| Umbral de balance | `balance_threshold` | 20° |
| Masa péndulo | `PEND_MASS` | 0.025 kg |
| Distancia pivot-CM | `PEND_LENGTH` | 0.065 m |
| Inercia péndulo | `PEND_INERTIA` | 2.0 × 10⁻⁵ kg·m² |

### 12.5 Modos de Operación

| Modo | Código | Descripción |
|------|--------|-------------|
| STOP | m0 | Motor deshabilitado |
| PWM Manual | m1 | PWM fijo (sin lazo) |
| PID Posición Servo | m2 | Control de posición del brazo |
| PID Péndulo | m3 | Control de posición del péndulo |
| LQR | m4 | Control óptimo péndulo invertido |
| Swing-Up | m5 | Bombeo de energía + transición a LQR |

---

## 13. Criterios de Validación Experimental

### 13.1 Respuesta al Escalón (Servo, Modo 2)

| Métrica | Objetivo | Método |
|---------|----------|--------|
| Tiempo de subida ($t_r$) | < 1 s | 10%–90% del setpoint |
| Overshoot ($M_p$) | < 25% | $(y_{max} - y_{ss}) / y_{ss} \times 100$ |
| Tiempo de establecimiento ($t_s$) | < 3 s | Dentro de ±2% del setpoint |
| Error estacionario ($e_{ss}$) | < 2° | Valor en régimen |
| Oscilaciones | Ninguna sostenida | Observación visual + datos |

### 13.2 Respuesta al Escalón (Péndulo, Modo 3)

| Métrica | Objetivo | Método |
|---------|----------|--------|
| Capacidad de mantener ángulo | ±30° sin caída | Setpoint fijo por 30 s |
| Oscilación en régimen | < ±3° | Amplitud pico a pico |

### 13.3 Balance LQR (Modo 4)

| Métrica | Objetivo | Método |
|---------|----------|--------|
| Tiempo de balance | < 5 s desde excitación | Desde liberación manual |
| Mantenimiento vertical | > 60 s sin intervención | Observación |
| Perturbación | Recuperación de empuje manual | Prueba cualitativa |

### 13.4 Swing-Up (Modo 5)

| Métrica | Objetivo | Método |
|---------|----------|--------|
| Tiempo de swing-up | < 15 s | Desde colgando hasta vertical |
| Tasa de éxito | > 80% | 10 intentos consecutivos |
| Transición a LQR | Suave, sin colapso | Cambio automático observable |

---

## 14. Referencias

### Papers Académicos

1. Akhtaruzzaman, M., & Shafie, A. A. (2010). Modeling and control of a rotary inverted pendulum using various methods. *IEEE ICMA 2010*. DOI: 10.1109/ICMA.2010.5589450

2. STMicroelectronics. (2019). *Introduction to Integrated Rotary Inverted Pendulum v2*. Educational Curriculum.

3. Åström, K. J., & Furuta, K. (2000). Swinging up a pendulum by energy control. *Automatica*, 36(2), 287–295.

### Datasheets

4. Espressif Systems. (2024). *ESP32-WROOM-32 Datasheet* (Rev. 3.3).

5. STMicroelectronics. (2024). *L298 Dual Full-Bridge Driver* (Rev. 24).

6. Texas Instruments. (2024). *INA219 Current/Power Monitor* (SBOS400H).

7. Texas Instruments. (2024). *LM2596 Step-Down Voltage Regulator* (SNVS033C).

### Proyectos de Referencia

8. ebrahimabdelghfar. (2023). *Rotary-Inverted-Pendulum*. GitHub. [Referencia académica LQR]

9. Ezward. (2018–2024). *Esp32CameraRover2*. GitHub. [Framework motor control]

10. wty-yy. (2025). *arduino_pid_controlled_motor*. GitHub. [PID + L298N]

### Textos de Control

11. Ogata, K. (2010). *Modern Control Engineering* (5th ed.). Prentice Hall.

12. Franklin, G. F., Powell, J. D., & Emami-Naeini, A. (2015). *Feedback Control of Dynamic Systems* (7th ed.). Pearson.

---

*Documento generado: 2026-06-01 | Basado en firmware v1.19.0+ y documentación del proyecto QUBE Servo ESP32*
