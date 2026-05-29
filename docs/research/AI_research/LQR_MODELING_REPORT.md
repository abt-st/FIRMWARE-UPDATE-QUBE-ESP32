# 📐 Informe: Modelado y Diseño de Controlador LQR para el QUBE Servo ESP32

**Fecha:** 2026-05-29  
**Autor:** Asistente de Investigación AI  
**Proyecto:** Modernización QUBE Servo con arquitectura ESP32 + L298N + INA219  
**Alcance:** Modelado matemático, diseño LQR, implementación en ESP32, comparación con PID

---

## 📋 Índice

1. [Introducción](#1-introducción)
2. [Modelado Matemático del Sistema](#2-modelado-matemático-del-sistema)
3. [Representación en Espacio de Estados](#3-representación-en-espacio-de-estados)
4. [Diseño del Controlador LQR](#4-diseño-del-controlador-lqr)
5. [Sintonización de Matrices Q y R](#5-sintonización-de-matrices-q-y-r)
6. [Implementación en ESP32](#6-implementación-en-esp32)
7. [Comparación LQR vs PID](#7-comparación-lqr-vs-pid)
8. [Código de Simulación (Python/MATLAB)](#8-código-de-simulación)
9. [Integración con Swing-Up](#9-integración-con-swing-up)
10. [Limitaciones y Consideraciones Prácticas](#10-limitaciones-y-consideraciones-prácticas)
11. [Hoja de Ruta de Implementación](#11-hoja-de-ruta-de-implementación)
12. [Referencias](#12-referencias)

---

## 1. Introducción

### 1.1 ¿Qué es LQR?

**LQR (Linear Quadratic Regulator)** es un método de diseño de controladores óptimos en el dominio del tiempo que minimiza una función de costo cuadrática. A diferencia del control PID clásico, LQR:

- **Opera en espacio de estados** (no en variables individuales)
- **Optimiza globalmente** el compromiso entre rendimiento y esfuerzo de control
- **Garantiza estabilidad** local dentro de la región de linealización
- **Permite manejar múltiples entradas y salidas** (MIMO) naturalmente
- **Tiene fundamentos matemáticos sólidos** (teorema de la ecuación de Riccati)

### 1.2 ¿Por qué LQR para el QUBE Servo?

El QUBE Servo es un **péndulo invertido rotatorio** — un sistema inherentemente inestable que requiere control activo para mantener el péndulo en posición vertical. Las razones para usar LQR:

| Aspecto | PID | LQR |
|---------|-----|-----|
| Número de variables | 1–2 (error + velocidad) | 4+ (estado completo) |
| Manejo de no linealidades | Ad-hoc | Linealización + feedback |
| Garantías de estabilidad | Empírica | Teórica (margen de fase/ganancia) |
| Optimalidad | No garantizada | Garantizada (dado el modelo) |
| Complejidad de sintonización | 3 parámetros (Kp, Ki, Kd) | 2 matrices (Q, R) |
| Manejo de restricciones | Anti-windup manual | Integración natural |

### 1.3 Estado actual del proyecto

El firmware actual (v1.17.0) implementa control PID para posición del servo (modo `m2`). El modo `m4` (LQR) está definido como **futuro** en la arquitectura. Este informe proporciona la base teórica y de implementación para avanzar hacia ese objetivo.

---

## 2. Modelado Matemático del Sistema

### 2.1 Descripción del Sistema

El QUBE Servo emula un péndulo invertido rotatorio compuesto por:

1. **Motor DC** (Premotec 990412016913) con encoder incremental (2048 CPR)
2. **Eje de rotación** (servo) que gira el punto de pivote
3. **Péndulo** (barra rígida) montado en el eje del servo

```
          θ (ángulo péndulo)
          │
          │  ●  ← Centro de masa
          │ /
          │/  α (ángulo del servo/motor)
    ══════╪══════ ← Eje de rotación (servo)
          │
    [  MOTOR DC  ]
    [   L298N    ]
    [   ENCODER  ]
```

### 2.2 Definición de Variables

| Variable | Símbolo | Unidad | Descripción |
|----------|---------|--------|-------------|
| Ángulo del servo | α | rad | Posición angular del motor (medido por encoder) |
| Ángulo del péndulo | θ | rad | Ángulo del péndulo respecto a la vertical (0 = arriba) |
| Velocidad del servo | α̇ | rad/s | Velocidad angular del motor |
| Velocidad del péndulo | θ̇ | rad/s | Velocidad angular del péndulo |
| Torque del motor | τ | N·m | Torque aplicado por el motor |
| Voltaje de entrada | V | V | Voltaje PWM aplicado al L298N |

### 2.3 Parámetros del Sistema

#### Parámetros Físicos (estimar experimentalmente)

| Parámetro | Símbolo | Unidad | Método de estimación |
|-----------|---------|--------|---------------------|
| Masa del péndulo | m | kg | Balanza de precisión |
| Longitud al centro de masa | l | m | Medición geométrica |
| Momento de inercia del péndulo | J_p | kg·m² | oscilación libre / J = m·l²·T²/(4π²) |
| Momento de inercia del rotor | J_m | kg·m² | Hoja de datos del motor |
| Fricción viscosa del motor | b | N·m·s/rad | Ensayo de decaimiento libre |
| Fricción estática del motor | b_s | N·m | Test de torque mínimo |
| Constante del motor (torque) | K_t | N·m/A | Datos del fabricante o ensayo |
| Constante del motor (velocidad) | K_e | V·s/rad | K_e ≈ K_t en SI |
| Resistencia del motor | R | Ω | Multímetro en bornes |
| Factor de conversión PWM→Voltaje | k_pwm | V/duty | V_bus × duty/255 |

#### Parámetros del Encoder

| Parámetro | Valor | Notas |
|-----------|-------|-------|
| CPR (counts per revolution) | 2048 | Configurable con `cpr` |
| Decodificación | X4 (cuadratura) | Resolución efectiva: 8192 counts/rev |
| Resolución angular | 360°/8192 ≈ 0.044° | Suficiente para LQR |

### 2.4 Ecuaciones de Movimiento (Lagrange)

Usando la formulación de Lagrange para el péndulo rotatorio:

#### Energía Cinética (T)

```
T = ½ · J_m · α̇² + ½ · m · l² · θ̇² + m · l² · α̇ · θ̇ · cos(θ) + ½ · J_p · θ̇²
```

Simplificando con J_p ≈ m·l²:

```
T = ½ · J_m · α̇² + m · l² · (α̇² + θ̇² + 2·α̇·θ̇·cos(θ))
```

#### Energía Potencial (V)

```
V = m · g · l · cos(θ)
```

#### Ecuaciones de Lagrange

**Para α (servo/motor):**

```
(J_m + m·l²)·α̈ + m·l²·θ̈·cos(θ) - m·l²·θ̇²·sin(θ) + b·α̇ = τ
```

**Para θ (péndulo):**

```
m·l²·θ̈ + m·l²·α̈·cos(θ) + m·g·l·sin(θ) = 0
```

#### Relación Eléctrica (motor)

```
τ = K_t · i
V_in = R·i + K_e·α̇
```

Donde V_in = k_pwm · u (u es el duty cycle normalizado [-1, 1])

### 2.5 Linealización en el Punto de Equilibrio

El punto de equilibrio inestable es **θ = 0** (péndulo vertical arriba) con α̇ = 0.

Usando las aproximaciones para ángulos pequeños:
- sin(θ) ≈ θ
- cos(θ) ≈ 1
- θ̇² ≈ 0 (términos de segundo orden)

**Ecuaciones linealizadas:**

```
(J_m + m·l²)·α̈ + m·l²·θ̈ + b·α̇ = τ       ... (1)
m·l²·θ̈ + m·l²·α̈ + m·g·l·θ = 0              ... (2)
```

Despejando θ̈ de (2):

```
θ̈ = -α̈ - (g/l)·θ
```

Sustituyendo en (1):

```
(J_m)·α̈ - m·g·l·θ + b·α̇ = τ
```

---

## 3. Representación en Espacio de Estados

### 3.1 Definición del Vector de Estado

El sistema de cuarto orden se define con el vector:

```
x = [α,  α̇,  θ,  θ̇]ᵀ
```

Donde:
- x₁ = α (posición angular del servo)
- x₂ = α̇ (velocidad angular del servo)
- x₃ = θ (ángulo del péndulo, 0 = vertical arriba)
- x₄ = θ̇ (velocidad angular del péndulo)

### 3.2 Forma Matricial

**Modelo de espacio de estados:**

```
ẋ = A·x + B·u
y = C·x + D·u
```

#### Matriz A (dinámica del sistema)

Definiendo:
- J = J_m + m·l² (inercia total del servo)
- Δ = J·J_p - (m·l²)² = J_p·J_m (determinante, siempre > 0)

```
        ┌                                    ┐
        │  0     1          0        0      │
   A =  │  0   -b·J_p/Δ   m²·l⁴·g/Δ   0   │
        │  0     0          0        1      │
        │  0   b·m·l²/Δ  -J·m·g·l/Δ  0   │
        └                                    ┘
```

#### Matriz B (entrada de control)

```
        ┌          ┐
        │    0     │
   B =  │  J_p/Δ   │
        │    0     │
        │ -m·l²/Δ  │
        └          ┘
```

#### Matriz C (salida observada)

Para observar todas las variables de estado:

```
   C = I₄ (matriz identidad 4×4)
```

Para observar solo posición del servo y ángulo del péndulo:

```
        ┌              ┐
   C =  │  1  0  0  0  │
        │  0  0  1  0  │
        └              ┘
```

#### Matriz D

```
   D = 0₄×₁ (vector cero)
```

### 3.3 Forma Discreta (para implementación en ESP32)

Para implementar LQR en un microcontrolador con período de muestreo Ts, se discretiza usando el método de **ZOH (Zero-Order Hold)**:

```
A_d = e^(A·Ts)
B_d = A⁻¹·(A_d - I)·B
```

Aproximación de primer orden (válida para Ts pequeño):

```
A_d ≈ I + A·Ts
B_d ≈ B·Ts
```

Con Ts = 5 ms (200 Hz), la aproximación es suficiente dado que las dinámicas dominantes del sistema están por debajo de 50 Hz.

### 3.4 Verificación de Controlabilidad

El sistema debe ser **completamente controlable** para que LQR funcione. La matriz de controlabilidad:

```
Co = [B, A·B, A²·B, A³·B]
```

Se verifica que **rank(Co) = 4** (rango completo). Esto se cumple siempre que:
- b ≠ 0 (hay fricción en el motor) o m ≠ 0 (hay masa en el péndulo)
- l ≠ 0 (el centro de masa no está en el pivote)

En nuestro caso, todas estas condiciones se cumplen trivialmente.

---

## 4. Diseño del Controlador LQR

### 4.1 Función de Costo

LQR minimiza la función de costo cuadrática:

```
J = ∫₀^∞ [x(t)ᵀ·Q·x(t) + u(t)ᵀ·R·u(t)] dt
```

Donde:
- **Q** = matriz de ponderación del estado (4×4, semidefinida positiva)
- **R** = matriz de ponderación del control (1×1, positiva)

### 4.2 Ley de Control

La solución óptima es una realimentación de estado lineal:

```
u(t) = -K·x(t)
```

Donde **K** es el vector de ganancias de LQR (1×4):

```
K = [K₁, K₂, K₃, K₄]
```

Y la acción de control es:

```
u = -(K₁·α + K₂·α̇ + K₃·θ + K₄·θ̇)
```

### 4.3 Cálculo de K

La ganancia K se obtiene resolviendo la **ecuación de Riccati algebraica de tiempo continuo (CARE)**:

```
Aᵀ·P + P·A - P·B·R⁻¹·Bᵀ·P + Q = 0
```

Donde P es la solución de la ecuación de Riccati (matriz simétrica 4×4). Luego:

```
K = R⁻¹·Bᵀ·P
```

En la práctica, se usa el comando `lqr()` de MATLAB o `scipy.signal.lqr()` de Python.

### 4.4 Interpretación Física de las Ganancias

| Ganancia | Variable | Física | Efecto de incrementar K_i |
|----------|----------|--------|--------------------------|
| K₁ | α (posición servo) | Penaliza posición del servo | Respuesta más agresiva del servo |
| K₂ | α̇ (velocidad servo) | Penaliza velocidad del servo | Amortigua oscilaciones del servo |
| K₃ | θ (ángulo péndulo) | Penaliza desviación del péndulo | Corrige más fuerte el péndulo |
| K₄ | θ̇ (velocidad péndulo) | Penaliza velocidad del péndulo | Amortigua el péndulo |

---

## 5. Sintonización de Matrices Q y R

### 5.1 Estrategia de Sintonización

La elección de Q y R determina el comportamiento del controlador. No existe una única solución "correcta", pero hay principios guía:

#### Paso 1: Matriz Q (ponderación del estado)

**Método 1: Ponderación diagonal directa**

```
Q = diag([q₁, q₂, q₃, q₄])
```

Donde:
- q₁: Peso de posición del servo (penaliza error de posición)
- q₂: Peso de velocidad del servo (amortiguamiento)
- q₃: Peso del ángulo del péndulo (**crítico** — el péndulo debe permanecer vertical)
- q₄: Peso de velocidad del péndulo (amortiguamiento)

**Regla empírica:** El peso del péndulo (q₃) debe ser **mayor** que el del servo (q₁) porque estabilizar el péndulo es más importante que la posición exacta del servo.

**Método 2: Basado en peso (Bryson's Rule)**

```
q_i = 1 / x_max_i²
```

Donde x_max_i es el valor máximo aceptable para la variable i.

| Variable | x_max | q_i = 1/x_max² | Justificación |
|----------|-------|-----------------|---------------|
| α (posición servo) | π rad (180°) | 1/π² ≈ 0.10 | Rango libre del servo |
| α̇ (velocidad servo) | 10 rad/s | 1/100 = 0.01 | Velocidad máxima razonable |
| θ (ángulo péndulo) | π/6 rad (30°) | 36/π² ≈ 3.65 | Región de linealización |
| θ̇ (velocidad péndulo) | 5 rad/s | 1/25 = 0.04 | Velocidad máxima del péndulo |

#### Paso 2: Matriz R (ponderación del control)

```
R = [r]
```

- **r grande** → control suave, respuesta lenta, menor consumo de energía
- **r pequeño** → control agresivo, respuesta rápida, mayor consumo
- **Valor típico inicial:** r = 1, luego ajustar

### 5.2 Configuraciones Recomendadas

#### Configuración 1: Equilibrado (recomendada para inicio)

```python
Q = diag([1.0, 0.1, 10.0, 0.5])
R = [1.0]
```

**Resultado esperado:** K ≈ [K₁, K₂, K₃, K₄] con énfasis en mantener θ ≈ 0.

#### Configuración 2: Agresiva (respuesta rápida)

```python
Q = diag([5.0, 0.5, 50.0, 2.0])
R = [0.1]
```

**Resultado esperado:** Respuesta muy rápida, pero mayor esfuerzo de control (mayor consumo, posibles saturaciones).

#### Configuración 3: Conservadora (bajo consumo)

```python
Q = diag([0.5, 0.05, 5.0, 0.1])
R = [10.0]
```

**Resultado esperado:** Respuesta más lenta, menor consumo, mayor error transitorio.

### 5.3 Proceso de Sintonización Iterativo

```
1. Comenzar con Configuración 1
2. Simular en Python/MATLAB
3. Verificar:
   a. ¿El péndulo se estabiliza? (θ → 0)
   b. ¿El servo llega a la posición deseada? (α → α_ref)
   c. ¿El esfuerzo de control es factible? (|u| ≤ 1)
   d. ¿Hay oscilaciones aceptables? (overshoot < 20%)
4. Ajustar:
   - Si el péndulo cae: incrementar q₃, q₄
   - Si el servo oscila: incrementar q₂
   - Si el control satura: incrementar R
   - Si la respuesta es lenta: decrementar R o incrementar Q
5. Repetir hasta convergencia
```

### 5.4 Referencia de Tracking (Setpoint)

Para que el péndulo siga una referencia de posición del servo (α_ref), se usa **realimentación de referencia**:

```
u = -K·(x - x_ref) + u_ff
```

Donde:
- x_ref = [α_ref, 0, 0, 0]ᵀ (referencia de posición del servo, péndulo vertical)
- u_ff =_feedforward para mantener α_ref (generalmente ≈ 0 en equilibrio)

---

## 6. Implementación en ESP32

### 6.1 Arquitectura del Controlador

```
┌─────────────────────────────────────────────┐
│              ESP32 (FreeRTOS)                │
│                                             │
│  task_control (Core 1, 200 Hz, 5 ms)       │
│  ┌─────────────────────────────────────┐   │
│  │ 1. Leer encoder servo (GPIO34/35)  │   │
│  │ 2. Leer encoder péndulo (GPIO32/33)│   │
│  │ 3. Calcular estados:               │   │
│  │    α  = getServoAngle()            │   │
│  │    α̇  = filteredVelServo          │   │
│  │    θ  = getPendulumAngle()         │   │
│  │    θ̇  = filteredVelPendulum       │   │
│  │ 4. Calcular error de estado:       │   │
│  │    e = x - x_ref                   │   │
│  │ 5. Calcular control:               │   │
│  │    u = -K1*e_α - K2*e_α̇           │   │
│  │        - K3*e_θ - K4*e_θ̇          │   │
│  │ 6. Saturar u ∈ [-1, 1]            │   │
│  │ 7. Aplicar PWM: setMotor(u*255)    │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  task_ina219 (Core 0, 100 Hz, 10 ms)       │
│  └─ Leer INA219, filtrar                    │
│                                             │
│  task_telemetry (Core 0, 20 Hz, 50 ms)     │
│  └─ JSON con estados + control              │
└─────────────────────────────────────────────┘
```

### 6.2 Estructura de Datos en Firmware

```cpp
// ── Estado del sistema ──────────────────────────────────────
struct SystemState {
    float alpha;      // Posición del servo [rad]
    float alpha_dot;  // Velocidad del servo [rad/s]
    float theta;      // Ángulo del péndulo [rad] (0 = vertical arriba)
    float theta_dot;  // Velocidad del péndulo [rad/s]
};

// ── Controlador LQR ────────────────────────────────────────
struct LQRController {
    float K[4];       // Ganancias [K_alpha, K_alpha_dot, K_theta, K_theta_dot]
    float alpha_ref;  // Referencia de posición del servo
    float u;          // Salida de control [-1, 1]
    float u_saturated; // Salida saturada
    bool active;      // Estado del controlador
};

// ── Parámetros del modelo ──────────────────────────────────
struct SystemParams {
    float J_m;     // Momento de inercia del rotor [kg·m²]
    float m;       // Masa del péndulo [kg]
    float l;       // Distancia al centro de masa [m]
    float b;       // Fricción viscosa [N·m·s/rad]
    float g;       // Gravedad [m/s²]
    float R_motor; // Resistencia del motor [Ω]
    float K_t;     // Constante de torque [N·m/A]
    float K_e;     // Constante de fuerza contraelectromotriz [V·s/rad]
};
```

### 6.3 Código Pseudocódigo del Bucle de Control LQR

```cpp
void task_control(void* pvParameters) {
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xPeriod = pdMS_TO_TICKS(5);  // 200 Hz
    
    SystemState state;
    LQRController lqr;
    float prevAlpha = 0.0f;
    float prevTheta = 0.0f;
    
    while (true) {
        // 1. Leer encoders
        float alpha = getServoAngleRad();      // Del encoder servo
        float theta = getPendulumAngleRad();   // Del encoder péndulo
        
        // 2. Estimación de velocidad (diferencia finita + filtro EMA)
        float alpha_dot = (alpha - prevAlpha) / DT;
        float theta_dot = (theta - prevTheta) / DT;
        
        // Filtro EMA para suavizar
        static float alpha_dot_filtered = 0.0f;
        static float theta_dot_filtered = 0.0f;
        const float alpha = 0.15f;  // Factor de filtrado
        
        alpha_dot_filtered = alpha_f * alpha_dot + (1.0f - alpha_f) * alpha_dot_filtered;
        theta_dot_filtered = alpha_f * theta_dot + (1.0f - alpha_f) * theta_dot_filtered;
        
        prevAlpha = alpha;
        prevTheta = theta;
        
        // 3. Calcular error de estado
        float e_alpha = alpha - lqr.alpha_ref;
        float e_alpha_dot = alpha_dot_filtered;
        float e_theta = theta;           // Referencia: θ = 0 (vertical)
        float e_theta_dot = theta_dot_filtered;
        
        // 4. Ley de control LQR
        float u = -(lqr.K[0] * e_alpha 
                   + lqr.K[1] * e_alpha_dot
                   + lqr.K[2] * e_theta 
                   + lqr.K[3] * e_theta_dot);
        
        // 5. Saturación
        lqr.u = u;
        lqr.u_saturated = constrain(u, -1.0f, 1.0f);
        
        // 6. Aplicar PWM
        int pwm = (int)(lqr.u_saturated * PWM_MAX);
        setMotor(pwm * MOTOR_DIR);
        
        // 7. Esperar próximo ciclo
        vTaskDelayUntil(&xLastWakeTime, xPeriod);
    }
}
```

### 6.4 Estimación de Velocidad

La velocidad es crítica para LQR. Hay tres opciones:

#### Opción 1: Diferencia finita (más simple)

```cpp
float velocity = (current_pos - prev_pos) / dt;
```

**Problema:** Ruido de cuantización del encoder amplificado.

#### Opción 2: Filtro EMA (recomendada)

```cpp
float vel_filtered = alpha * vel_raw + (1.0f - alpha) * vel_filtered_prev;
```

Con α = 0.12–0.25 según el ruido. Ya implementado en el firmware actual (`VEL_ALPHA = 0.12`).

#### Opción 3: Observador de estado (óptimo)

Usar un **observador de Luenberger** o **filtro de Kalman** para estimar [α̇, θ̇] a partir de las mediciones de posición:

```cpp
// Observador: x̂̇ = A·x̂ + B·u + L·(y - C·x̂)
// Donde L es la ganancia del observador (se calcula aparte)
```

Esto es más robusto pero requiere calibración adicional del modelo.

### 6.5 Manejo de Saturación (Anti-Windup para LQR)

A diferencia del PID, LQR no tiene un término integral, por lo que no hay windup clásico. Sin embargo, la saturación del PWM puede degradar el rendimiento:

```cpp
// Anti-windup simple: limitar el estado integrado del control
if (abs(u) >= 1.0f) {
    // El control está saturado, no integrar más
    // (esto aplica si se agrega un término de referencia feedforward)
}
```

---

## 7. Comparación LQR vs PID

### 7.1 Tabla Comparativa

| Aspecto | PID (actual) | LQR (propuesto) |
|---------|-------------|-----------------|
| **Variables de estado** | 1 (error de posición) | 4 (α, α̇, θ, θ̇) |
| **Estabilidad** | Empírica | Garantizada (teórica) |
| **Optimalidad** | No | Sí (mínimo costo cuadrático) |
| **Sintonización** | 3 parámetros (Kp, Ki, Kd) | 2 matrices (Q, R) |
| **Requiere modelo** | No | Sí |
| **Manejo MIMO** | Difícil | Natural |
| **Robustez a perturbaciones** | Media | Alta |
| **Consumo computacional** | Muy bajo | Bajo (una multiplicación matricial) |
| **Complejidad de implementación** | Baja | Media |
| **Necesita encoder péndulo** | No (solo servo) | Sí |

### 7.2 Ventajas de LQR para el QUBE

1. **Estabilización del péndulo:** LQR puede mantener el péndulo vertical usando retroalimentación completa del estado, algo que un solo PID no puede hacer sin un modelo del sistema.

2. **Rendimiento óptimo:** Para un modelo dado, LQR garantiza la respuesta óptima en el sentido de minimizar el compromiso entre error y esfuerzo de control.

3. **Margenes de robustez:** LQR garantiza márgenes de ganancia ≥ 60° y margen de amplitud ≥ 6 dB (en el caso continuo).

4. **Extensibilidad:** LQR se extiende naturalmente a:
   - **LQG** (Linear Quadratic Gaussian) para ruido de medición
   - **MPC** (Model Predictive Control) para restricciones explícitas
   - **H₂/H∞** para robustez ante incertidumbres

### 7.3 Cuándo Usar PID vs LQR

| Escenario | PID viable | LQR ventaja |
|-----------|-----------|-------------|
| Control de posición del servo solamente | ✅ Suficiente | No necesario |
| Estabilización del péndulo cerca de la vertical | ✅ Posible (con encoder de péndulo y ganancias bien ajustadas) | Mejor rendimiento y garantías teóricas |
| Swing-up (levantamiento desde reposo) | ⚠️ Requiere estrategia adicional (bombeo de energía) | También requiere estrategia adicional (no lineal) |
| Swing-up + estabilización integral | ⚠️ Posible: bombeo + PID conmutado | Más elegante: bombeo + LQR con scheduler |
| Control dual servo + péndulo (MIMO) | ⚠️ Difícil de sintonizar (múltiples PIDs acoplados) | Natural (un solo controlador para todo el estado) |
| Publicación académica | Válido | Rigor teórico adicional |

> **Nota importante:** Tanto PID como LQR son controladores de **lignealización local** — solo funcionan cerca del punto de equilibrio (θ ≈ 0). Para el levantamiento (swing-up) desde una posición lejana, **ambos** requieren una estrategia de control no lineal separada (típicamente bombeo de energía). La diferencia clave es que LQR ofrece **garantías teóricas de estabilidad** y **optimalidad** dentro de la región de linealización, mientras que PID requiere sintonización empírica pero puede ser igualmente efectivo con la parameterización correcta.

---

## 8. Código de Simulación

### 8.1 Python (SciPy)

```python
"""
Simulación LQR para Péndulo Rotatorio QUBE Servo
Requiere: numpy, scipy, matplotlib
"""

import numpy as np
from scipy import signal
from scipy.linalg import solve_continuous_are
import matplotlib.pyplot as plt

# ── Parámetros del sistema (estimar experimentalmente) ──────
J_m = 1.0e-5      # Momento de inercia del rotor [kg·m²] (estimado)
m = 0.05           # Masa del péndulo [kg]
l = 0.08           # Distancia al centro de masa [m]
b = 1.0e-4         # Fricción viscosa [N·m·s/rad] (estimado)
g = 9.81           # Gravedad [m/s²]
K_t = 0.01         # Constante de torque [N·m/A]
K_e = 0.01         # Constante de FCE [V·s/rad]
R_motor = 5.0      # Resistencia del motor [Ω]
k_pwm = 12.0 / 255.0  # Conversión duty→voltaje (12V bus)

# ── Parámetros derivados ───────────────────────────────────
J_p = m * l**2     # Inercia del péndulo (barra puntual)
J_total = J_m + m * l**2
Delta = J_total * J_p - (m * l**2)**2  # = J_m * J_p

# ── Matrices del sistema continuo ───────────────────────────
# Estado: x = [alpha, alpha_dot, theta, theta_dot]
# Entrada: u (voltaje normalizado [-1, 1])

A = np.array([
    [0, 1, 0, 0],
    [0, -b * J_p / Delta,  (m**2 * l**4 * g) / Delta, 0],
    [0, 0, 0, 1],
    [0, (b * m * l**2) / Delta,  -(J_total * m * g * l) / Delta, 0]
])

B = np.array([
    [0],
    [J_p * k_pwm * K_t / (R_motor * Delta)],
    [0],
    [-m * l**2 * k_pwm * K_t / (R_motor * Delta)]
])

C = np.eye(4)
D = np.zeros((4, 1))

# ── Verificar controlabilidad ───────────────────────────────
Co = signal.ctrb(A, B)
rank_Co = np.linalg.matrix_rank(Co)
print(f"Rango de matriz de controlabilidad: {rank_Co}")
assert rank_Co == 4, "¡Sistema no controlable!"

# ── Diseño LQR ─────────────────────────────────────────────
# Matrices de ponderación
Q = np.diag([1.0, 0.1, 10.0, 0.5])  # [α, α̇, θ, θ̇]
R = np.array([[1.0]])

# Resolver ecuación de Riccati
P = solve_continuous_are(A, B, Q, R)

# Calcular ganancia K
K = np.linalg.inv(R) @ B.T @ P
print(f"Ganancias LQR: K = {K.flatten()}")
print(f"  K_alpha     = {K[0, 0]:.4f}")
print(f"  K_alpha_dot = {K[0, 1]:.4f}")
print(f"  K_theta     = {K[0, 2]:.4f}")
print(f"  K_theta_dot = {K[0, 3]:.4f}")

# ── Verificar estabilidad del sistema cerrado ───────────────
A_cl = A - B @ K
eigenvalues_cl = np.linalg.eigvals(A_cl)
print(f"\nAutovalores del sistema cerrado:")
for i, lam in enumerate(eigenvalues_cl):
    print(f"  λ{i+1} = {lam:.4f}  (Re = {lam.real:.4f})")
assert all(eig.real < 0 for eig in eigenvalues_cl), "¡Sistema inestable!"
print("✓ Todos los autovalores tienen parte real negativa → Sistema estable")

# ── Simulación en tiempo ───────────────────────────────────
dt = 0.005  # 200 Hz
t_final = 3.0
t = np.arange(0, t_final, dt)
n_steps = len(t)

# Estado inicial: péndulo inclinado 15° (0.26 rad)
x0 = np.array([0.0, 0.0, np.radians(15), 0.0])

# Referencia: servo en 0°, péndulo en 0° (vertical)
x_ref = np.array([0.0, 0.0, 0.0, 0.0])

# Simulación
x = np.zeros((n_steps, 4))
u = np.zeros(n_steps)
x[0] = x0

for i in range(n_steps - 1):
    # Error de estado
    e = x[i] - x_ref
    
    # Ley de control LQR
    u[i] = -K @ e
    
    # Saturación del control (PWM limitado)
    u[i] = np.clip(u[i], -1.0, 1.0)
    
    # Dinámica del sistema (Euler forward)
    x_dot = A @ x[i] + B.flatten() * u[i]
    x[i + 1] = x[i] + x_dot * dt

# ── Gráficos ───────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

# Ángulos
axes[0].plot(t, np.degrees(x[:, 0]), label='α (servo)', linewidth=1.5)
axes[0].plot(t, np.degrees(x[:, 2]), label='θ (péndulo)', linewidth=1.5)
axes[0].axhline(y=0, color='k', linestyle='--', alpha=0.3)
axes[0].set_ylabel('Ángulo [°]')
axes[0].set_title('Respuesta del sistema con control LQR')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Velocidades
axes[1].plot(t, np.degrees(x[:, 1]), label='α̇ (servo)', linewidth=1.5)
axes[1].plot(t, np.degrees(x[:, 3]), label='θ̇ (péndulo)', linewidth=1.5)
axes[1].set_ylabel('Velocidad angular [°/s]')
axes[1].legend()
axes[1].grid(True, alpha=0.3)

# Control
axes[2].plot(t, u, label='u (control)', linewidth=1.5, color='red')
axes[2].axhline(y=1, color='k', linestyle=':', alpha=0.5, label='Saturación')
axes[2].axhline(y=-1, color='k', linestyle=':', alpha=0.5)
axes[2].set_ylabel('Control normalizado')
axes[2].set_xlabel('Tiempo [s]')
axes[2].legend()
axes[2].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('lqr_simulation.png', dpi=150)
plt.show()

# ── Métricas de rendimiento ─────────────────────────────────
overshoot_theta = np.max(np.abs(np.degrees(x[:, 2]))) 
settling_idx = np.where(np.abs(np.degrees(x[:, 2])) < 1.0)[0]
settling_time = t[settling_idx[0]] if len(settling_idx) > 0 else t_final

print(f"\n--- Métricas de Rendimiento ---")
print(f"Overshoot θ (inicial): {overshoot_theta:.1f}°")
print(f"Tiempo de establecimiento θ (<1°): {settling_time:.3f} s")
print(f"Error estacionario θ: {np.degrees(x[-1, 2]):.4f}°")
print(f"Control máximo: {np.max(np.abs(u)):.3f}")
```

### 8.2 Sintonización Automática (Python)

```python
"""
Sintonización iterativa de matrices Q y R para LQR
"""

def tune_lqr(A, B, Q_diag, R_val, x0, x_ref, dt, t_final):
    """
    Prueba una configuración LQR y retorna métricas.
    
    Args:
        A, B: Matrices del sistema
        Q_diag: Diagonal de Q como lista [q1, q2, q3, q4]
        R_val: Valor escalar de R
        x0: Estado inicial
        x_ref: Estado de referencia
        dt: Paso temporal
        t_final: Tiempo final de simulación
    
    Returns:
        dict con métricas y ganancias K
    """
    Q = np.diag(Q_diag)
    R = np.array([[R_val]])
    
    try:
        P = solve_continuous_are(A, B, Q, R)
        K = np.linalg.inv(R) @ B.T @ P
    except np.linalg.LinAlgError:
        return None
    
    # Verificar estabilidad
    A_cl = A - B @ K
    if any(eig.real >= 0 for eig in np.linalg.eigvals(A_cl)):
        return None
    
    # Simular
    t = np.arange(0, t_final, dt)
    n = len(t)
    x = np.zeros((n, 4))
    u = np.zeros(n)
    x[0] = x0
    
    for i in range(n - 1):
        e = x[i] - x_ref
        u[i] = np.clip(-K @ e, -1.0, 1.0)
        x_dot = A @ x[i] + B.flatten() * u[i]
        x[i + 1] = x[i] + x_dot * dt
    
    # Métricas
    theta_deg = np.degrees(x[:, 2])
    settling_idx = np.where(np.abs(theta_deg) < 1.0)[0]
    
    return {
        'K': K.flatten(),
        'overshoot_deg': np.max(np.abs(theta_deg)),
        'settling_time': t[settling_idx[0]] if len(settling_idx) > 0 else t_final,
        'steady_state_error': np.abs(theta_deg[-1]),
        'max_control': np.max(np.abs(u)),
        'energy': np.sum(u**2) * dt,  # Energía consumida
    }


# ── Búsqueda en grilla ─────────────────────────────────────
Q3_range = [1, 5, 10, 20, 50]       # Peso del péndulo
R_range = [0.1, 0.5, 1.0, 5.0]      # Peso del control

print("Búsqueda de mejores parámetros LQR...")
print(f"{'Q3':>6} {'R':>6} {'K1':>8} {'K2':>8} {'K3':>8} {'K4':>8} "
      f"{'Overshoot':>10} {'T_settle':>10} {'E_max':>8}")
print("-" * 85)

best_score = float('inf')
best_params = None

for q3 in Q3_range:
    for r in R_range:
        Q_diag = [1.0, 0.1, q3, 0.5]
        result = tune_lqr(A, B, Q_diag, r, x0, np.zeros(4), 0.005, 3.0)
        
        if result is None:
            continue
        
        # Score: penalizar overshoot y tiempo de establecimiento
        score = (result['overshoot_deg'] * 2 + 
                 result['settling_time'] * 10 + 
                 result['max_control'] * 5)
        
        if score < best_score:
            best_score = score
            best_params = (q3, r, result)
        
        print(f"{q3:6.1f} {r:6.1f} "
              f"{result['K'][0]:8.3f} {result['K'][1]:8.3f} "
              f"{result['K'][2]:8.3f} {result['K'][3]:8.3f} "
              f"{result['overshoot_deg']:10.2f} "
              f"{result['settling_time']:10.3f} "
              f"{result['max_control']:8.3f}")

if best_params:
    q3, r, result = best_params
    print(f"\n═══ Mejor configuración ═══")
    print(f"Q = diag([1.0, 0.1, {q3}, 0.5]), R = {r}")
    print(f"K = {result['K']}")
    print(f"Overshoot: {result['overshoot_deg']:.2f}°")
    print(f"Tiempo de establecimiento: {result['settling_time']:.3f} s")
    print(f"Control máximo: {result['max_control']:.3f}")
```

---

## 9. Integración con Swing-Up

### 9.1 Estrategia de Swing-Up

El péndulo no puede estabilizarse con LQR desde cualquier posición. LQR solo funciona cerca del equilibrio (θ ≈ 0). Para posiciones alejadas (θ > ±30°), se necesita una estrategia de **swing-up**:

```
                    ┌─────────────────────┐
                    │    SWING-UP          │
                    │  (energía de bombeo) │
                    │  θ fuera de rango    │
                    └─────────┬───────────┘
                              │ |θ| < umbral
                              ▼
                    ┌─────────────────────┐
                    │  LQR (estabilización)│
                    │  θ cerca de 0        │
                    └─────────────────────┘
```

### 9.2 Métodos de Swing-Up

#### Método 1: Bombeo de Energía (recomendado)

Control basado en la energía del péndulo:

```cpp
// Energía del péndulo (normalizada)
float E = 0.5f * theta_dot * theta_dot - g_over_l * cos(theta);
float E_ref = 0.0f;  // Energía en la posición vertical

// Ley de control de swing-up
if (fabs(theta) > SWINGUP_THRESHOLD) {
    // Bombeo: inyectar energía cuando el péndulo se mueve hacia arriba
    float u_swing = K_swing * theta_dot * sign(sin(theta));
    u = constrain(u_swing, -1.0f, 1.0f);
} else {
    // Zona de transición: usar LQR
    u = -(K[0] * alpha + K[1] * alpha_dot + K[2] * theta + K[3] * theta_dot);
}
```

#### Método 2: Oscilaciones Forzadas

Generar oscilaciones en el servo para inyectar energía progresivamente.

### 9.3 Scheduler de Controladores

```cpp
enum ControlMode {
    CTRL_STOP,      // Motor apagado
    CTRL_PID,       // Control PID (modo m2)
    CTRL_SWINGUP,   // Swing-up (modo m4, fase 1)
    CTRL_LQR,       // LQR estabilización (modo m4, fase 2)
};

ControlMode currentMode = CTRL_STOP;

void updateControlMode(float theta) {
    if (currentMode == CTRL_SWINGUP) {
        if (fabs(theta) < LQR_THRESHOLD) {  // ~15°
            currentMode = CTRL_LQR;
            resetLqrState();  // Reiniciar estado del LQR
        }
    } else if (currentMode == CTRL_LQR) {
        if (fabs(theta) > LQR_THRESHOLD * 1.5) {  // ~22.5°
            currentMode = CTRL_SWINGUP;
        }
    }
}
```

---

## 10. Limitaciones y Consideraciones Prácticas

### 10.1 Limitaciones del Modelo

| Limitación | Impacto | Mitigación |
|------------|---------|------------|
| **Linealización** solo válida para θ pequeño | LQR inestable para |θ| > ~30° | Swing-up + scheduler |
| **Parámetros exactos** desconocidos | Ganancias subóptimas | Identificación experimental |
| **Fricción no lineal** (Coulomb + viscosa) | Error en modelo | Observador de estado |
| **Saturación PWM** | Control limitado | Anti-windup, limitación de Q |
| **Ruido de encoder** | Velocidad errónea | Filtro EMA, Kalman |
| **Retraso de muestreo** | Degradación de fase | Aumentar frecuencia, predecir |

### 10.2 Identificación Experimental de Parámetros

#### Método de Respuesta al Escalón

```
1. Aplicar voltaje fijo V₀ al motor (sin péndulo)
2. Registrar velocidad angular (encoder) vs tiempo
3. Ajustar curva: ω(t) = ω_ss · (1 - e^(-t/τ))
4. Donde:
   - ω_ss = V₀ · K_t / (b · R)  → despejar b
   - τ = J_m · R / (b · R + K_t · K_e)  → despejar J_m
```

#### Método de Oscilación Libre (péndulo)

```
1. Soltar el péndulo desde ángulo pequeño (~10°)
2. Registrar θ(t) (oscilación amortiguada)
3. Ajustar: θ(t) = θ₀ · e^(-ζ·ωn·t) · cos(ωd·t)
4. Donde:
   - ωn = sqrt(g/l)  → validar l
   - ζ = b_pendulum / (2·m·l²·ωn)  → estimar fricción del péndulo
```

### 10.3 Requisitos de Hardware para LQR

| Requisito | Estado actual | Necesario para LQR |
|-----------|--------------|-------------------|
| Encoder servo | ✅ Funcional | Sí |
| Encoder péndulo | ⚠️ Futuro (GPIO32/33) | **Sí, obligatorio** |
| Frecuencia de muestreo | ✅ 200 Hz | Suficiente |
| Resolución encoder | ✅ 2048 CPR (X4) | Suficiente |
| Potencia computacional | ✅ ESP32 240 MHz | Suficiente |
| Comunicación WiFi | ✅ WebSocket | Para telemetría |

### 10.4 Rendimiento Esperado en ESP32

| Métrica | Estimación |
|---------|-----------|
| Tiempo de cálculo LQR | ~5–10 µs |
| Frecuencia de control factible | Hasta 1 kHz |
| Uso de RAM adicional | ~200 bytes (estados + ganancias) |
| Uso de Flash adicional | ~2 KB (código LQR + observador) |

---

## 11. Hoja de Ruta de Implementación

### Fase 1: Preparación (1–2 semanas)

- [ ] **Instalar encoder del péndulo** (GPIO32/33 con pull-ups)
- [ ] **Validar lectura dual** de encoders en firmware
- [ ] **Identificar parámetros** del sistema (m, l, J_m, b, K_t)
- [ ] **Simular LQR** en Python con parámetros estimados
- [ ] **Validar estabilidad** en simulación antes de implementar

### Fase 2: Implementación LQR Básica (2–3 semanas)

- [ ] **Implementar estimación de velocidad** (diferencia + filtro EMA)
- [ ] **Agregar modo m4** al firmware (LQR sin swing-up)
- [ ] **Alinear péndulo vertical manualmente** y probar LQR
- [ ] **Sintonizar Q y R** experimentalmente
- [ ] **Agregar telemetría** de estados para depuración

### Fase 3: Swing-Up + Integración (2–3 semanas)

- [ ] **Implementar swing-up** por bombeo de energía
- [ ] **Crear scheduler** de controladores (swing-up → LQR)
- [ ] **Probar secuencia completa:** reposo → swing-up → estabilización
- [ ] **Ajustar transición** entre controladores

### Fase 4: Validación y Publicación (2–4 semanas)

- [ ] **Comparar LQR vs PID** con métricas cuantitativas
- [ ] **Documentar** parámetros, ganancias y resultados
- [ ] **Registrar datos experimentales** (CSV)
- [ ] **Preparar gráficos** para la tesis
- [ ] **Redactar sección** de control avanzado

---

## 12. Referencias

### Papers Académicos

1. **Akhtaruzzaman, M., & Shafie, A. A.** (2010). "Modeling and control of a rotary inverted pendulum using various methods." *IEEE ICMA 2010*. DOI: 10.1109/ICMA.2010.5589450
   - Modelado Lagrange y control LQR para péndulo rotatorio
   - Referencia principal para el modelado matemático

2. **STMicroelectronics** (2019). "Introduction to Integrated Rotary Inverted Pendulum v2." Educational Curriculum.
   - Guía práctica de identificación de parámetros y sintonización LQR

3. **Åström, K. J., & Furuta, K.** (2000). "Swinging up a pendulum by energy control." *Automatica*, 36(2), 287-295.
   - Fundamento teórico del swing-up por energía

4. **Ogata, K.** (2010). *Modern Control Engineering* (5th ed.). Prentice Hall.
   - Referencia estándar para diseño LQR y espacio de estados

5. **Franklin, G. F., Powell, J. D., & Emami-Naeini, A.** (2015). *Feedback Control of Dynamic Systems* (7th ed.). Pearson.
   - Control digital, discretización ZOH, observadores

### Repositorios de Referencia

6. **ebrahimabdelghfar/Rotary-Inverted-Pendulum** (2023). GitHub.
   - Arduino + L298N + LQR implementado y validado experimentalmente
   - Rango reportado: ±20°, sin swing-up

7. **QUBE-Servo-2 Documentation** — Quanser.
   - Especificaciones del sistema original que se emula

### Librerías y Herramientas

8. **SciPy** — `scipy.signal.lqr()`, `scipy.linalg.solve_continuous_are()`
9. **Control Systems Library for Python** — `control.lqr()`
10. **MATLAB Control System Toolbox** — `lqr()`, `ss()`, `step()`

---

## Anexo A: Glosario

| Término | Definición |
|---------|-----------|
| **LQR** | Linear Quadratic Regulator — controlador óptimo lineal cuadrático |
| **CARE** | Continuous-time Algebraic Riccati Equation |
| **ZOH** | Zero-Order Hold — método de discretización |
| **PWM** | Pulse Width Modulation — modulación por ancho de pulso |
| **EMA** | Exponential Moving Average — filtro paso bajo |
| **CPR** | Counts Per Revolution — pulsos por revolución del encoder |
| **Swing-up** | Estrategia para elevar el péndulo desde reposo hasta la vertical |
| **Anti-windup** | Mecanismo para evitar saturación del término integral |
| **State-space** | Representación matricial del sistema dinámico |
| **Observador** | Estimador de estados no medidos (Luenberger, Kalman) |

---

## Anexo B: Checklist de Implementación

### Hardware
- [ ] Encoder péndulo instalado y validado (GPIO32/33)
- [ ] Pull-ups configurados (4.7 kΩ o según tipo de salida)
- [ ] Conexiones verificadas (sin falsos contactos)
- [ ] Alimentación estable (12V, ripple < 100 mV)

### Firmware
- [ ] Lectura dual de encoders funcionando
- [ ] Estimación de velocidad (α̇, θ̇) con filtro EMA
- [ ] Modo m4 (LQR) agregado al switch de modos
- [ ] Ganancias K configurables por serial/HTTP
- [ ] Saturación de control implementada
- [ ] Telemetría de estados completa

### Simulación
- [ ] Modelo en Python/MATLAB con parámetros estimados
- [ ] LQR simulado y verificado
- [ ] Ganancias K iniciales calculadas
- [ ] Respuesta al escalón validada

### Experimental
- [ ] LQR probado con péndulo alineado vertical
- [ ] Sintonización de Q y R en banco de pruebas
- [ ] Comparación cuantitativa con PID
- [ ] Datos CSV exportados para análisis

---

*Informe generado: 2026-05-29 | Proyecto: QUBE Servo ESP32 Modernization*