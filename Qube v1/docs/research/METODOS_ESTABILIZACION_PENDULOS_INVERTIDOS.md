# Métodos de Estabilización para Péndulos Invertidos Rotatorios

**Fecha:** 2026-06-16
**Contexto:** QUBE Servo modernizado con ESP32-WROOM-32 + BTS7960
**Estado actual del firmware:** PID + LQR + Swing-Up energético (v1.19.0+)

---

## Índice

1. [Estado Actual del QUBE](#1-estado-actual-del-qube)
2. [Clasificación de Métodos de Control](#2-clasificación-de-métodos-de-control)
3. [Métodos Clásicos Lineales](#3-métodos-clásicos-lineales)
4. [Métodos No Lineales](#4-métodos-no-lineales)
5. [Métodos Basados en Inteligencia Artificial](#5-métodos-basados-en-inteligencia-artificial)
6. [Métodos de Óptimo y Predictivo](#6-métodos-de-óptimo-y-predictivo)
7. [Estrategias de Swing-Up](#7-estrategias-de-swing-up)
8. [Controladores Híbridos](#8-controladores-híbridos)
9. [Implementaciones en Hardware Embebido](#9-implementaciones-en-hardware-embebido)
10. [Repositorios de Referencia en GitHub](#10-repositorios-de-referencia-en-github)
11. [Comparativa de Métodos](#11-comparativa-de-métodos)
12. [Recomendaciones para el QUBE ESP32](#12-recomendaciones-para-el-qube-esp32)
13. [Referencias](#13-referencias)

---

## 1. Estado Actual del QUBE

El firmware v1.19.0+ implementa tres estrategias de control:

| Método | Estado | Descripción |
|--------|--------|-------------|
| **PID** | Implementado | Control clásico con zona muerta, filtro EMA en derivada, saturación PWM |
| **LQR** | Implementado | Regulador cuadrático lineal con 4 estados (theta_servo, alpha, omega_servo, omega_pendulo) |
| **Swing-Up** | Implementado | Bombeo de energía basado en método Quanser con transición a LQR |

**Parámetros LQR actuales del firmware:**

| Ganancia | Símbolo | Valor |
|----------|---------|-------|
| Posición servo | K_theta | 2.0 |
| Ángulo péndulo | K_alpha | 35.0 |
| Velocidad servo | K_omega_s | 0.8 |
| Velocidad péndulo | K_omega_p | 3.5 |

**Limitaciones conocidas:**
- El LQR solo es válido en una región lineal alrededor de alpha = 0
- El swing-up no siempre logra la captura (catch) estable
- Ruido en encoder degrada la estimación de velocidad
- Sin rechazo activo de perturbaciones externas

---

## 2. Clasificación de Métodos de Control

Los métodos de estabilización para péndulos invertidos rotatorios (RIP) se clasifican en:

```
Métodos de Control para RIP
├── Clásicos Lineales
│   ├── PID (Proporcional-Integral-Derivativo)
│   ├── LQR (Linear Quadratic Regulator)
│   ├── LQG (LQR + Filtro de Kalman)
│   └── Control por ubicación de polos
├── No Lineales
│   ├── SMC (Sliding Mode Control)
│   ├── Backstepping
│   ├── Feedback Linealization
│   └── Control por pasividad
├── Inteligencia Artificial
│   ├── Fuzzy Logic (FLC)
│   ├── Redes Neuronales (ANN/RNN)
│   ├── Reinforcement Learning (RL)
│   └── Control adaptativo neuronal
├── Óptimo/Predictivo
│   ├── MPC (Model Predictive Control)
│   ├── NMPC (Nonlinear MPC)
│   └── Tube-based MPC
└── Híbridos
    ├── Swing-Up (energético) + LQR
    ├── Swing-Up + SMC
    ├── Fuzzy-LQR
    ├── Fuzzy-SMC
    └── NN-LQR
```

**Fuentes:** Hazem & Bingül (2023), Hernandez et al. (2024), Huynh et al. (2024)

---

## 3. Métodos Clásicos Lineales

### 3.1 PID (Proporcional-Integral-Derivativo)

**Principio:** Control por retroalimentación de error con tres acciones.

```
u(t) = Kp * e(t) + Ki * integral(e(t)) + Kd * de(t)/dt
```

**Ventajas para QUBE:**
- Simple de implementar en ESP32 (ya implementado)
- No requiere modelo matemático preciso
- Bajo costo computacional (~10 operaciones por ciclo a 200 Hz)
- Intuición física para sintonización

**Desventajas:**
- No óptimo en ningún sentido
- Sensible a ruido en la derivada (requiere filtrado)
- No maneja bien la no linealidad del péndulo lejos del equilibrio
- Zona muerta necesaria para evitar chatter

**Implementación actual en firmware:**
- Filtro EMA en la derivada (alpha = 0.15)
- Zona muerta configurable
- Saturación PWM [-255, 255]

**Referencia:** Implementación discreta estándar con backward Euler.

---

### 3.2 LQR (Linear Quadratic Regulator)

**Principio:** Minimiza una función de costo cuadrática J = integral(x'Qx + u'Ru) dt.

**Ecuación de Riccati:**
```
A'P + PA - PBR^(-1)B'P + Q = 0
K = R^(-1)B'P
```

**Ventajas para QUBE:**
- Ya implementado en firmware
- Garantía de estabilidad para el sistema linealizado
- Sintonización sistemática mediante matrices Q y R
- Respuesta rápida y bien amortiguada cerca del equilibrio

**Desventajas:**
- Solo válido en la región lineal (|alpha| < ~15°)
- Requiere modelo de espacio de estados preciso
- No rechaza perturbaciones sin integrador
- Sensible a errores de modelamiento

**Estado actual:** Implementado con ganancias fijas. Protección si |alpha| > 150°.

**Mejora potencial:** Scheduling de ganancias (gain scheduling) para operar en múltiples puntos de operación.

---

### 3.3 LQG (Linear Quadratic Gaussian)

**Principio:** LQR + Filtro de Kalman para estimación óptima de estados con ruido.

**Ventajas:**
- Estimación óptima de estados con ruido de medición
- Mejor desempeño que LQR puro con encoders ruidosos
- Separa diseño de estimador y controlador (principio de separación)

**Desventajas:**
- Mayor complejidad computacional (multiplicación de matrices 4x4)
- Requiere modelo de ruido (matrices Q_n, R_n)
- Sin garantías de robustez (LQG no es robusto por diseño)

**Relevancia para QUBE:** Plata et al. (2025) compararon LQG en microcontroladores de bajo costo, encontrando que es viable en STM32 y ESP32 a 200 Hz.

**Referencia:** Huynh et al. (2024) - "A Survey of LQG over MPC and LQR Control for Rotary Inverted Pendulum"

---

## 4. Métodos No Lineales

### 4.1 SMC (Sliding Mode Control)

**Principio:** Forzar el sistema a permanecer en una superficie de deslizamiento definida s(x) = 0.

**Ley de control típica:**
```
u = u_eq + u_sw
u_eq = -G^(-1) * (f(x) + lambda * dx/dt)  // control equivalente
u_sw = -K * sgn(s)                          // conmutación
```

**Ventajas:**
- Robustez inherente a perturbaciones y incertidumbre
- Funciona en toda la región no lineal (no solo cerca del equilibrio)
- Diseño relativamente sistemático
- Convergencia finita a la superficie de deslizamiento

**Desventajas:**
- **Chattering** (oscilación de alta frecuencia) - problemático con motor DC y PWM
- Requiere conocimiento del modelo no lineal
- Mayor esfuerzo de control que LQR
- Puede causar desgaste del motor por conmutación rápida

**Mitigación de chattering:**
- Sigmoidal en vez de sgn()
- Super-twisting SMC (segunda orden)
- Boundary layer alrededor de la superficie

**Aplicación al QUBE:** Nagarajan & Victoire (2023) propusieron un PID-SMC optimizado para RIP que reduce el chattering manteniendo robustez.

**Referencia:** Bajrami et al. (2021) - "Control theory application for swing up and stabilisation of rotating inverted pendulum" (Symmetry)

---

### 4.2 Backstepping

**Principio:** Diseño recursivo de controladores de Lyapunov, construyendo la ley de control paso a paso para cada variable de estado.

**Ventajas:**
- Manejo sistemático de no linealidades
- Función de Lyapunov garantiza estabilidad
- Se puede combinar con SMC (backstepping-SMC)
- Funciona para sistemas de múltiples entradas

**Desventajas:**
- Complejidad de diseño crece con el orden del sistema
- Requiere modelo matemático completo
- "Explosión de términos" (term explosion) en sistemas de alto orden
- Mayor costo computacional que LQR

**Aplicación al QUBE:** Vo et al. (2020) demostraron backstepping para RIP con swing-up y balanceo experimental. Mofid et al. (2023) propusieron backstepping adaptativo con SMC de tiempo finito.

**Referencia:** Vo et al. (2020) - "Back-stepping control for rotary inverted pendulum" (JTE)

---

### 4.3 Feedback Linealization

**Principio:** Transformar el sistema no lineal en uno lineal mediante cambio de coordenadas, luego aplicar control lineal.

**Ventajas:**
- Elimina no linealidades exactamente (no aproximación)
- Permite usar técnicas lineales en el sistema transformado
- Tracking preciso de trayectorias

**Desventajas:**
- Requiere modelo exacto del sistema
- Sensible a errores de modelamiento
- Puede requerir diferenciación numérica
- No siempre posible (condiciones de involución)

**Aplicación al QUBE:** Se usa frecuentemente como etapa de swing-up junto con controladores lineales para la estabilización (Nguyen et al., 2021).

---

### 4.4 Control por Pasividad (Passivity-Based)

**Principio:** Diseñar el controlador para que el sistema en lazo cerrado sea pasivo (disipa energía).

**Ventajas:**
- Estabilidad garantizada por propiedades energéticas
- Natural para el swing-up (bombeo de energía)
- Robustez inherente a incertidumbres paramétricas

**Desventajas:**
- Diseño menos intuitivo que PID/LQR
- Limitado a estructuras pasivas
- Puede ser conservador

**Referencia:** Vo et al. (2024) - "Comparative study of swing-up controllers: passivity-based swing-up control and sliding mode technique" (IEEE)

---

## 5. Métodos Basados en Inteligencia Artificial

### 5.1 Fuzzy Logic Control (FLC)

**Principio:** Control basado en reglas lingüísticas IF-THEN con conjuntos difusos.

**Ventajas:**
- No requiere modelo matemático
- Incorpora conocimiento experto directamente
- Manejo natural de no linealidades
- Fácil de ajustar manualmente

**Desventajas:**
- Difícil garantizar estabilidad formalmente
- Número de reglas crece exponencialmente con variables
- Sintonización manual de funciones de membresía
- Subóptimo comparado con métodos basados en modelo

**Variantes para RIP:**
- **Fuzzy-LQR:** Fuzzy para swing-up, LQR para estabilización (Abdullah et al., 2021)
- **Fuzzy-SMC:** Fuzzy para ajustar ganancias del SMC (Nguyen et al., 2024)
- **Type-2 Fuzzy:** Manejo de incertidumbre en las reglas

**Referencia:** Abdullah et al. (2021) - "Swing up and stabilization control of rotary inverted pendulum based on energy balance, fuzzy logic, and LQR controllers"

---

### 5.2 Redes Neuronales Artificiales (ANN)

**Principio:** Aproximadores universales que aprenden la ley de control a partir de datos.

**Ventajas:**
- Aprenden mapeos no lineales complejos
- Pueden ser entrenados offline y ejecutados en tiempo real
- Se adaptan a cambios en el sistema

**Desventajas:**
- Sin garantías formales de estabilidad (requiere verificación adicional)
- Necesitan datos de entrenamiento
- Costo computacional variable (depende de arquitectura)
- Riesgo de sobreajuste

**Aplicaciones recientes:**
- **LQR-NN:** Red neuronal que aproxima las ganancias LQR óptimas (Nghi et al., 2022)
- **NN para identificación:** Identificación del modelo del RIP (de Carvalho et al., 2021)
- **NN adaptativo:** Control adaptativo con compensación de oscilación (Zabihifar et al., 2020)
- **Verificación SOS:** Detailleur et al. (2024) verificaron estabilidad de controlador NN mediante SOS

**Referencia clave:** Nghi et al. (2022) - "A LQR neural network control approach for fast stabilizing rotary inverted pendulums" (Int J Precis Eng)

---

### 5.3 Reinforcement Learning (RL)

**Principio:** El agente aprende una política óptima por prueba y error, maximizando recompensa acumulada.

**Ventajas:**
- No requiere modelo del sistema
- Puede descubrir estrategias no intuitivas
- Se adapta a variaciones del sistema en tiempo real

**Desventajas:**
- Entrenamiento costoso (miles de episodios)
- Transferencia sim-to-real problemática
- Sin garantías de estabilidad durante aprendizaje
- Requiere simulación o hardware seguro para exploración

**Implementaciones:**
- **Stable Baselines3:** Furuta pendulum (Armandpl/furuta en GitHub) usa PPO/SAC
- **Q-learning discreto:** Para sintonización de parámetros PID
- **Deep RL:** Para swing-up directo sin separación swing-up/stabilization

**Referencia:** Hernandez et al. (2024) - "Modeling, simulation, and control of a rotary inverted pendulum: A reinforcement learning-based control approach" (Modelling)

---

## 6. Métodos de Óptimo y Predictivo

### 6.1 MPC (Model Predictive Control)

**Principio:** Optimizar la trayectoria futura del sistema en un horizonte finito, aplicando solo el primer paso del control.

**Formulación:**
```
min J = sum_{k=0}^{N} [x(k)'Qx(k) + u(k)'Ru(k)]
sujeto a: x(k+1) = f(x(k), u(k))
          u_min <= u(k) <= u_max
          x_min <= x(k) <= x_max
```

**Ventajas:**
- Manejo explícito de restricciones (saturación PWM, límites de ángulo)
- Preview de referencia (útil para tracking)
- Estabilidad garantizada con terminal cost
- Puede manejar no linealidades (NMPC)

**Desventajas:**
- **Alto costo computacional** - problema de optimización en cada paso de tiempo
- Requiere modelo preciso
- Difícil implementar en ESP32 a 200 Hz sin optimización extrema
- Tiempo de ejecución variable (problemático para tiempo real)

**Viabilidad en ESP32:**
- Farkhooi (2025) implementó MPC embebido para Furuta pendulum
- Mahamud (2024) demostró MPC en microcontrolador para RIP
- Rios-Norena et al. (2022) implementó MPC óptimo en Arduino para péndulo doble
- **Factible** con horizonte corto (N=5-10), formulación explícita (explicit MPC), o código generado

**Referencia:** Farkhooi (2025) - "Embedded Model Predictive Control of the Furuta Pendulum" (KTH)

---

### 6.2 NMPC (Nonlinear MPC)

**Principio:** MPC con modelo no lineal completo del sistema.

**Ventajas:**
- Opera en toda la región no lineal (incluye swing-up)
- Puede unificar swing-up y estabilización en un solo controlador
- Mejor desempeño que MPC lineal

**Desventajas:**
- Mucho más costoso computacionalmente que MPC lineal
- Solver no lineal (IPOPT, ACADOS) difícil de portar a ESP32
- Convergencia no garantizada del solver

**Referencia:** Prado et al. (2020) - "Intelligent Swing-Up and Robust Stabilization via Tube-based Nonlinear Model Predictive Control for A Rotational Inverted-Pendulum System"

---

## 7. Estrategias de Swing-Up

El swing-up es la fase de elevar el péndulo desde la posición colgante (alpha = pi) hasta la vecindad del equilibrio inestable (alpha = 0), donde el controlador de balanceo toma el control.

### 7.1 Método de Bombeo de Energía (Quanser)

**Ya implementado en el QUBE.** Basado en la diferencia entre la energía actual y la energía de referencia.

```
E_ref = mgl (energía en posición vertical)
E = 0.5 * m * l^2 * alpha_dot^2 + mgl * cos(alpha)
u = K_ec * (E - E_ref) * sign(alpha_dot * cos(alpha))
```

**Referencia:** Método estándar de Quanser, documentado en MODELO_FISICO_SISTEMA_QUBE.md Sección 10.

---

### 7.2 Swing-Up Difuso (Fuzzy Swing-Up)

**Principio:** Usar lógica difusa para suavizar la transición y ajustar la intensidad del bombeo.

**Ventaja:** Elimina discontinuidades en la ley de control, reduce overshoot al llegar al equilibrio.

**Referencia:** Kim & Park (2025) - "Energy-based Fuzzy Swing Up and Relaxed Balancing Control for a Rotary Inverted Pendulum" (IEEE)

---

### 7.3 Swing-Up por Pasividad

**Principio:** Diseñar la ley de swing-up como un intercambio de energía pasivo, garantizando que la energía del péndulo converge al valor deseado.

**Ventaja:** Estabilidad garantizada durante toda la fase de swing-up.

**Referencia:** Vo et al. (2024) - comparan passivity-based vs energy-based + SMC.

---

### 7.4 Swing-Up por Reinforcement Learning

**Principio:** Entrenar un agente RL para aprender la política de swing-up óptima.

**Ventaja:** No requiere modelo analítico, puede descubrir estrategias eficientes.

**Desventaja:** Requiere mucho entrenamiento, transferencia sim-to-real.

**Referencia:** Armandpl/furuta (GitHub) usa StableBaselines3 con PPO.

---

### 7.5 Swing-Up Unificado (MPC/NMPC)

**Principio:** Un solo controlador MPC maneja tanto swing-up como estabilización, cambiando la referencia de trayectoria.

**Ventaja:** Sin zona muerta en la transición, manejo suave de restricciones.

**Referencia:** Prado et al. (2020), Farkhooi (2025)

---

## 8. Controladores Híbridos

Los controladores híbridos combinan dos o más métodos para aprovechar las ventajas de cada uno. Son los más populares en la literatura reciente.

### 8.1 Swing-Up (Energético) + LQR

**Ya implementado en el QUBE.** Es el enfoque más común y probado.

**Patrón:**
```
if |alpha| > threshold:
    swing_up_control()    // Bombeo de energía
else:
    lqr_control()         // Estabilización lineal
```

**Referencia:** Método estándar en la mayoría de proyectos RIP.

---

### 8.2 Swing-Up + SMC

**Patrón:** Swing-up energético + SMC para estabilización robusta.

**Ventaja:** El SMC rechaza perturbaciones mejor que el LQR.

**Referencia:** Bajrami et al. (2021), Vo et al. (2024)

---

### 8.3 Fuzzy-LQR

**Patrón:** Lógica difusa para swing-up, LQR para estabilización.

**Ventaja:** Suaviza la transición, reduce oscilaciones al capturar el péndulo.

**Referencia:** Abdullah et al. (2021)

---

### 8.4 Fuzzy-SMC

**Patrón:** Fuzzy ajusta las ganancias del SMC online.

**Ventaja:** Reduce chattering adaptativamente.

**Referencia:** Nguyen et al. (2024) - "Optimized fuzzy logic and sliding mode control for stability and disturbance rejection in rotary inverted pendulum" (Scientific Reports)

---

### 8.5 NN-LQR

**Patrón:** Red neuronal que aproxima las ganancias LQR óptimas para diferentes condiciones.

**Ventaja:** LQR adaptativo sin resolver Riccati en tiempo real.

**Referencia:** Nghi et al. (2022)

---

### 8.6 Backstepping-SMC

**Patrón:** Backstepping para diseño recursivo + SMC para robustez.

**Ventaja:** Convergencia finita + robustez.

**Referencia:** Mofid et al. (2023) - "Adaptive finite-time command-filtered backstepping sliding mode control"

---

## 9. Implementaciones en Hardware Embebido

### 9.1 Comparativa de Plataformas

| Plataforma | MCU | Frecuencia | RAM | Flash | Ejemplo |
|------------|-----|-----------|-----|-------|---------|
| **ESP32** | Xtensa dual-core | 240 MHz | 520 KB | 4 MB | QUBE actual |
| **STM32F302** | ARM Cortex-M4 | 72 MHz | 32 KB | 128 KB | Waszak & Langowski (2020) |
| **STM32F4** | ARM Cortex-M4F | 168 MHz | 192 KB | 1 MB | Edukit (wjkaiser) |
| **Arduino Mega** | ATmega2560 | 16 MHz | 8 KB | 256 KB | Rios-Norena et al. (2022) |
| **Teensy 4.0** | ARM Cortex-M7 | 600 MHz | 1024 KB | 2 MB | Proyectos de alto rendimiento |

**Referencia:** Plata et al. (2025) - "Comparative Evaluation of Low-Cost Microcontrollers for Real-Time Control on an Inverted Pendulum" (IEEE)

---

### 9.2 Costo Computacional por Método (estimado para ESP32 @ 200 Hz)

| Método | Operaciones/ciclo | Tiempo estimado (ESP32) | Factible? |
|--------|-------------------|------------------------|-----------|
| PID | ~15 mul + 5 add | < 10 us | **Sí** (ya implementado) |
| LQR (4 estados) | ~16 mul + 12 add | < 20 us | **Sí** (ya implementado) |
| LQG (4 estados + Kalman) | ~60 mul + 40 add | < 50 us | **Sí** |
| SMC | ~20 mul + 10 add | < 30 us | **Sí** |
| Fuzzy (3 vars, 9 reglas) | ~50 mul + 30 add | < 40 us | **Sí** |
| Backstepping | ~40 mul + 20 add | < 50 us | **Sí** |
| ANN (4-8-4) | ~48 mul + 40 add | < 50 us | **Sí** |
| MPC (N=5, lineal) | ~200 mul + 100 add | < 500 us | **Tal vez** (límite) |
| NMPC (N=5, no lineal) | > 1000 mul | > 2 ms | **No** (sin optimizar) |
| RL (inference only) | Variable | < 100 us (red pequeña) | **Sí** |

**Nota:** Los tiempos son estimaciones. El ESP32 a 240 MHz con FPU por software puede hacer ~50 MFLOPS. El período de control a 200 Hz es 5000 us.

---

### 9.3 Consideraciones para Implementación en ESP32

**Restricciones del ESP32:**
- **Sin FPU hardware** - operaciones float son software (~10x más lento que int)
- **WiFi puede interferir** con timing de control (core 0 vs core 1)
- **PWM 8-bit** limita la resolución del control
- **Ruido en ADC** afecta lecturas de INA219
- **ISR de encoder** puede causar jitter si es muy frecuente

**Recomendaciones:**
1. Usar **fixed-point arithmetic** si el método es intensivo en flotantes
2. Ejecutar control en **Core 1** (libre de WiFi)
3. Usar **PCNT hardware** para encoder (no polling)
4. Considerar **incremento de frecuencia** de control a 500 Hz si el método lo requiere

---

## 10. Repositorios de Referencia en GitHub

### 10.1 Proyectos con Hardware Similar al QUBE

| Repositorio | Hardware | Métodos | Similitud QUBE |
|-------------|----------|---------|----------------|
| [Armandpl/furuta](https://github.com/Armandpl/furuta) | Custom + encoder + motor DC | RL (PPO/SAC), simulación | Alta (>80%) |
| [wjkaiser/Edukit_RIP](https://github.com/wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project) | STM32 + stepper motor | LQR, PID, MATLAB/Simulink | Alta (>80%) |
| [ferrolho/rotary-inverted-pendulum](https://github.com/ferrolho/rotary-inverted-pendulum) | Custom + Arduino | LQR | Media (60%) |
| [Shankari02/RIP_using_LQR](https://github.com/Shankari02/Rotary_Inverted_Pendulum_using_LQR) | MATLAB/Simulink | LQR | Media (50%) |
| [ebrahimabdelghfar/RIP](https://github.com/ebrahimabdelghfar/Rotary-Inverted-Pendulum) | MATLAB | PID, LQR | Media (50%) |

### 10.2 Proyectos con Métodos Avanzados

| Repositorio | Método | Descripción |
|-------------|--------|-------------|
| [akshaykhadse/sliding-mode-inverted-pendulum](https://github.com/akshaykhadse/sliding-mode-inverted-pendulum) | SMC + LQR | Simulink, comparativo |
| [ayansengupta17/Inverted-Pendulum-Control](https://github.com/ayansengupta17/Inverted-Pendulum-Control) | Varios | Control de péndulo invertido |
| [em0sh/rdip](https://github.com/em0sh/rdip) | Custom | Péndulo invertido rotatorio |
| [kaidegit/RotaryInvertedPendulum](https://github.com/kaidegit/RotaryInvertedPendulum) | Custom | Hardware + control |
| [tommasomarroni/rotary-inverted-pendulum](https://github.com/tommasomarroni/rotary-inverted-pendulum) | Custom | Implementación completa |

---

## 11. Comparativa de Métodos

### 11.1 Tabla Comparativa General

| Método | Robustez | No linealidad | Costo computacional | Facilidad de diseño | Garantía estabilidad | Tracking |
|--------|----------|---------------|--------------------|--------------------|---------------------|----------|
| **PID** | Baja | No | Muy bajo | Alta | Limitada | Regular |
| **LQR** | Media | Local | Bajo | Media | Sí (local) | Buena |
| **LQG** | Media | Local | Medio | Media | Sí (local) | Buena |
| **SMC** | **Alta** | **Sí** | Bajo | Media | Sí | Buena |
| **Backstepping** | Media | **Sí** | Medio | Baja | Sí (Lyapunov) | Buena |
| **Fuzzy** | Media | **Sí** | Medio | Media | Limitada | Regular |
| **ANN** | Media | **Sí** | Variable | Baja | No (sin verificación) | Buena |
| **MPC** | Media | **Sí** | Alto | Baja | Sí (con terminal) | **Excelente** |
| **RL** | Variable | **Sí** | Variable | Baja | No | Variable |

### 11.2 Tabla Comparativa para Swing-Up

| Método Swing-Up | Convergencia | Suavidad | Robustez | Complejidad |
|-----------------|-------------|----------|----------|-------------|
| **Energético (Quanser)** | Garantizada* | Regular | Media | Baja |
| **Fuzzy** | Buena | **Alta** | Media | Media |
| **Pasividad** | **Garantizada** | Buena | **Alta** | Media |
| **RL** | Variable | Buena | Variable | Alta |
| **MPC unificado** | Buena | **Alta** | Media | Alta |

*Condiciones: modelo aproximado correcto, ganancia suficiente.

---

## 12. Recomendaciones para el QUBE ESP32

### 12.1 Mejoras de Bajo Esfuerzo (Implementación directa)

1. **LQG en lugar de LQR** - Agregar filtro de Kalman para mejor estimación de estados con ruido de encoder. Factible en ESP32, mejora desempeño sin cambiar hardware.

2. **Gain Scheduling del LQR** - Calcular ganancias LQR para múltiples puntos de operación (diferentes velocidades del servo) e interpolar. Reduce error en operación dinámica.

3. **SMC como alternativa al LQR** - Sliding mode con sigmoidal (sin chattering) para mayor robustez a perturbaciones. Costo computacional similar al LQR.

### 12.2 Mejoras de Medio Esfuerzo

4. **Fuzzy Swing-Up** - Reemplazar el swing-up energético por un controlador difuso para suavizar la transición y mejorar la tasa de captura.

5. **Backstepping** - Diseñar controlador backstepping para la fase de swing-up, combinado con LQR para estabilización.

6. **ANN-LQR adaptativo** - Entrenar una red neuronal pequeña (4-8-4) offline para aproximar ganancias LQR óptimas en diferentes condiciones.

### 12.3 Mejoras de Alto Esfuerzo (Investigación)

7. **MPC embebido** - Implementar MPC lineal con horizonte corto (N=5-10) usando código generado (CASADI + EMBEDDED MPC). Requiere optimización significativa.

8. **Reinforcement Learning** - Entrenar agente RL en simulación y transferir al hardware real. Usar Stable Baselines3 para entrenamiento.

9. **Controlador Híbrido Completo** - Fuzzy swing-up + SMC estabilización + Kalman filter para estimación. Máximo desempeño con garantías de robustez.

### 12.4 Priorización Recomendada

| Prioridad | Método | Impacto | Esfuerzo | Riesgo |
|-----------|--------|---------|----------|--------|
| **1** | Filtro de Kalman (LQG) | Alto | Medio | Bajo |
| **2** | Gain Scheduling LQR | Medio | Bajo | Bajo |
| **3** | SMC (sigmoidal) | Alto | Medio | Medio |
| **4** | Fuzzy Swing-Up | Medio | Medio | Bajo |
| **5** | ANN-LQR adaptativo | Alto | Alto | Medio |
| **6** | MPC embebido | Alto | Alto | Alto |

---

## 13. Referencias

### Papers Académicos (Ordenados por relevancia)

1. **Hazem, Z.B. & Bingül, Z.** (2023). "Comprehensive review of different pendulum structures in engineering applications." *IEEE Access*. — Survey completo de estructuras de péndulos y métodos de control.

2. **Huynh, P.H. et al.** (2024). "A Survey of LQG over MPC and LQR Control for Rotary Inverted Pendulum." *Engineering & Management*. — Comparativo LQG vs MPC vs LQR.

3. **Hernandez, R. et al.** (2024). "Modeling, simulation, and control of a rotary inverted pendulum: A reinforcement learning-based control approach." *Modelling*. — RL aplicado a RIP.

4. **Nguyen, N.P. et al.** (2021). "A nonlinear hybrid controller for swinging-up and stabilizing the rotary inverted pendulum." *Nonlinear Dynamics*. — Controlador híbrido swing-up + estabilización.

5. **Nguyen, T.V.A. et al.** (2024). "Optimized fuzzy logic and sliding mode control for stability and disturbance rejection in rotary inverted pendulum." *Scientific Reports*. — Fuzzy-SMC optimizado.

6. **Abdullah, M. et al.** (2021). "Swing up and stabilization control of rotary inverted pendulum based on energy balance, fuzzy logic, and LQR controllers." *Int. J. of Modelling and Control*. — Energético + Fuzzy + LQR.

7. **Nghi, H.V. et al.** (2022). "A LQR neural network control approach for fast stabilizing rotary inverted pendulums." *Int J Precis Eng*. — LQR-NN para RIP.

8. **Nagarajan, A. & Victoire, A.A.** (2023). "Optimization reinforced PID-sliding mode controller for rotary inverted pendulum." *IEEE Access*. — PID-SMC optimizado.

9. **Bajrami, X. et al.** (2021). "Control theory application for swing up and stabilisation of rotating inverted pendulum." *Symmetry*. — SMC para swing-up y estabilización.

10. **Peng, Q.** (2025). "Enhanced Stability and Control of Rotary Inverted Pendulum Systems Using Deep Learning Control Approach." *J. Electrical Eng. & Tech.* — Deep learning para RIP.

11. **Vo, M.T. et al.** (2020). "Back-stepping control for rotary inverted pendulum." *J. Technical Education*. — Backstepping experimental.

12. **Mofid, O. et al.** (2023). "Adaptive finite-time command-filtered backstepping sliding mode control for stabilization of a disturbed rotary-inverted-pendulum." *Int. J. of Modelling and Control*. — Backstepping-SMC adaptativo.

13. **Gupta, N. & Dewan, L.** (2025). "Adaptive neural network-based sliding mode control of rotary inverted pendulum system." *J. of Control and Decision*. — NN-SMC adaptativo.

14. **Ouahab, B. et al.** (2025). "Prescribed performance-based hierarchical fast terminal sliding mode control for a rotary inverted pendulum." *J. of Vibration and Control*. — SMC de terminal rápido.

15. **Kim, D.B. et al.** (2023). "Neural-network based swing-up and stabilization control of rotary inverted pendulum systems." *IFAC-PapersOnLine*. — NN para swing-up.

16. **Vo, M.T. et al.** (2024). "Comparative study of swing-up controllers: passivity-based swing-up control and sliding mode technique combined energy-based method." *IEEE*. — Comparativo swing-up.

17. **Kim, K.S. & Park, P.G.** (2025). "Energy-based Fuzzy Swing Up and Relaxed Balancing Control for a Rotary Inverted Pendulum." *IEEE*. — Fuzzy swing-up.

18. **Nguyen, T.V.A. et al.** (2025). "Integrating disturbance handling into control strategies for swing-up and stabilization of rotary inverted pendulum." *J. of Automation, Mobile Robotics & Intelligent Systems*. — Manejo de perturbaciones.

### Papers sobre Implementación Embebida

19. **Farkhooi, S.** (2025). "Embedded Model Predictive Control of the Furuta Pendulum." *KTH*. — MPC embebido en microcontrolador.

20. **Mahamud, S.** (2024). "Embedded control of a rotary inverted pendulum." *Aalto University*. — MPC embebido para RIP.

21. **Plata, M.A.S. et al.** (2025). "Comparative Evaluation of Low-Cost Microcontrollers for Real-Time Control on an Inverted Pendulum." *IEEE 7th Conf.* — Comparativo de microcontroladores para control de péndulo.

22. **Khandeparkar, A.** (2023). "Embedded Control of a Rotary Inverted Pendulum." *KTH*. — Interfaz embebida para RIP.

23. **Da Silva, R.M. et al.** (2026). "Classical and Sliding Mode Controllers Applied to the Reaction Wheel Inverted Pendulum." *IEEE*. — SMC embebido.

24. **Waszak, M. & Langowski, R.** (2020). "An automatic self-tuning control system design for an inverted pendulum." *IEEE Access*. — Auto-sintonización en STM32.

25. **Rios-Norena, L.A. et al.** (2022). "Real-time optimal embedded control of a double inverted pendulum." *IAENG*. — MPC óptimo en Arduino.

26. **Prado, A. et al.** (2020). "Intelligent Swing-Up and Robust Stabilization via Tube-based Nonlinear Model Predictive Control for A Rotational Inverted-Pendulum System." *Revista Politécnica*. — NMPC tube-based.

27. **Detailleur, A. et al.** (2024). "Synthesis and SOS-based Stability Verification of a Neural-Network-Based Controller for a Two-wheeled Inverted Pendulum." *arXiv*. — Verificación de estabilidad NN.

28. **de Carvalho, A. et al.** (2021). "Rotary inverted pendulum identification for control by paraconsistent neural network." *IEEE*. — Identificación NN para RIP.

29. **Zabihifar, S.H. et al.** (2020). "Robust control based on adaptive neural network for Rotary inverted pendulum with oscillation compensation." *Neural Computing and Applications*. — NN adaptativo.

### Repositorios GitHub

30. **Armandpl/furuta** — RL (PPO/SAC) para Furuta pendulum, Python + Stable Baselines3.
31. **wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project** — STM32 + MATLAB/Simulink, LQR/PID.
32. **akshaykhadse/sliding-mode-inverted-pendulum** — SMC + LQR en Simulink.
33. **ferrolho/rotary-inverted-pendulum** — Implementación Arduino + LQR.
34. **Shankari02/Rotary_Inverted_Pendulum_using_LQR** — LQR en MATLAB.
35. **kaidegit/RotaryInvertedPendulum** — Hardware + control custom.

---

## Apéndice A: Diagrama de Decisión de Método de Control

```
¿El péndulo está cerca del equilibrio (|alpha| < 15°)?
├── SÍ → ¿Hay perturbaciones frecuentes?
│   ├── SÍ → SMC o LQG
│   └── NO → LQR (actual) o LQG
└── NO → ¿Está colgando (|alpha| > 150°)?
    ├── SÍ → Swing-Up
    │   ├── Método actual: Energético (Quanser)
    │   ├── Mejora: Fuzzy swing-up
    │   └── Avanzado: RL o MPC unificado
    └── NO → Transición
        ├── Método actual: Cambio abrupto a LQR
        └── Mejora: Gain scheduling o fuzzy transición
```

---

## Apéndice B: Glosario

| Término | Definición |
|---------|------------|
| **RIP** | Rotary Inverted Pendulum (Péndulo Invertido Rotatorio) |
| **LQR** | Linear Quadratic Regulator |
| **LQG** | Linear Quadratic Gaussian (LQR + Kalman) |
| **MPC** | Model Predictive Control |
| **NMPC** | Nonlinear MPC |
| **SMC** | Sliding Mode Control |
| **FLC** | Fuzzy Logic Controller |
| **ANN** | Artificial Neural Network |
| **RL** | Reinforcement Learning |
| **EMA** | Exponential Moving Average |
| **SOS** | Sum of Squares (verificación de estabilidad) |
| **HIL** | Hardware-in-the-Loop |
| **CPR** | Counts Per Revolution (encoder) |

---

*Documento generado: 2026-06-16 | Basado en investigación académica y repositorios GitHub*
