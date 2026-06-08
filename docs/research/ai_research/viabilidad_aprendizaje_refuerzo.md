# Aprendizaje por Refuerzo para el Sistema QUBE Servo — Investigación de Viabilidad

**Fecha:** 2026-06-01  
**Objetivo:** Evaluar la viabilidad de aplicar aprendizaje por refuerzo (RL) a los sistemas de control del proyecto QUBE Servo ESP32  
**Fuentes:** Investigación bibliográfica 2023–2026 (papers, proyectos GitHub, documentación oficial)

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Estado del Arte: RL para Péndulo Rotatorio](#2-estado-del-arte-rl-para-péndulo-rotatorio)
3. [Algoritmos de RL Aplicables](#3-algoritmos-de-rl-aplicables)
4. [Arquitectura de Entrenamiento Sim-to-Real](#4-arquitectura-de-entrenamiento-sim-to-real)
5. [Restricciones del ESP32 para Inferencia](#5-restricciones-del-esp32-para-inferencia)
6. [Librerías y Herramientas](#6-librerías-y-herramientas)
7. [Diseño del Entorno para el QUBE](#7-diseño-del-entorno-para-el-qube)
8. [Función de Recompensa](#8-función-de-recompensa)
9. [Estrategia Recomendada por Sistema de Control](#9-estrategia-recomendada-por-sistema-de-control)
10. [Pipeline de Implementación](#10-pipeline-de-implementación)
11. [Comparativa: RL vs. Control Clásico](#11-comparativa-rl-vs-control-clásico)
12. [Referencias](#12-referencias)

---

## 1. Resumen Ejecutivo

### Veredicto: ✅ VIABLE con restricciones

El aprendizaje por refuerzo **es técnicamente viable** para el sistema QUBE Servo, con las siguientes condiciones:

| Aspecto | Viabilidad | Complejidad |
|---------|-----------|------------|
| Entrenamiento (simulación) | ✅ Alta | Media |
| Entrenamiento (en hardware real) | ✅ Posible | Alta |
| Inferencia en ESP32 | ⚠️ Factible con redes pequeñas | Media-Alta |
| Swing-up + balance del péndulo | ✅ Demostrado por Quanser y otros | Alta |
| Control de posición del servo | ⚠️ El PID ya es suficiente | Baja |
| Sintonización automática de PID (RL) | ✅ Muy prometedora | Media |

**Recomendación principal:** Comenzar con **RL para sintonización automática de PID** (menor riesgo, mayor impacto inmediato), avanzar hacia **swing-up + balance** del péndulo invertido.

---

## 2. Estado del Arte: RL para Péndulo Rotatorio

### 2.1 Proyectos de Referencia Directa

| Proyecto | Hardware | Algoritmo | Resultado | Año |
|----------|----------|-----------|-----------|-----|
| **Quanser QUBE-Servo 3** | QUBE-Servo 3 + MATLAB/Simulink | DDPG | Balance exitoso en hardware | 2026 |
| **MathWorks QUBE-Servo 2** | QUBE-Servo 2 + Raspberry Pi | SAC (swing-up) + PPO (mode select) | Swing-up + balance completo | 2021–2025 |
| **ShawnHymel/pendulum-rl** | STEVAL-EDUKIT01 + ESP32 | PPO | Entrenamiento en hardware real + inferencia en ESP32 | 2024 |
| **LExCI Framework** | dSPACE MABX III + RLlib | PPO y DDPG | Pendulum swing-up en RCP system | 2023 |
| **RLtools** | ESP32, Teensy, Crazyflie | PPO, SAC, TD3 | Entrenamiento + inferencia en microcontroladores | 2024 |
| **KyawLinnKhant/IMP_MJC_RL** | MuJoCo sim → hardware | Deep RL | Pendulum invertido | 2024 |

### 2.2 Resultados Clave de la Literatura

1. **Quanser demostró** (2026) que DDPG puede balancear el QUBE-Servo 3 en hardware real, con un tiempo de balance < 0.4 s en simulación.

2. **MathWorks demostró** (2021–2025) un sistema híbrido: SAC para swing-up + PPO para selección de modo, implementado en Raspberry Pi con QUBE-Servo 2.

3. **ShawnHymel demostró** (2024) entrenamiento de PPO directamente en un hardware ESP32-STEVAL, con inferencia local del agente.

4. **RLtools** (2024) demostró que las redes RL pequeñas pueden ejecutarse en ESP32 con tiempos de inferencia de **< 1 ms**, suficiente para control a 200 Hz.

5. **LExCI** (2023) probó que PPO y DDPG convergen con la misma calidad en un sistema embebido real (dSPACE) que en Python puro.

---

## 3. Algoritmos de RL Aplicables

### 3.1 Comparativa de Algoritmos

| Algoritmo | Tipo | Acción | Ventajas | Desventajas | Applicabilidad QUBE |
|-----------|------|--------|----------|-------------|---------------------|
| **PPO** | On-policy | Continua/Discreta | Estable, bien probado, convergencia confiable | Requiere muchos samples, no reutiliza datos | ⭐⭐⭐⭐⭐ Swing-up, balance |
| **SAC** | Off-policy | Continua | Muestra eficiente, entropía regularizada | Más parámetros, puede ser inestable | ⭐⭐⭐⭐⭐ Swing-up (Mejor elección) |
| **DDPG** | Off-policy | Continua | Simple, bien entendido | Sensible a hiperparámetros, overestimation bias | ⭐⭐⭐⭐ Balance |
| **TD3** | Off-policy | Continua | Mejora DDPG, reduce overestimation | Más complejo que DDPG | ⭐⭐⭐⭐ Balance |
| **DQN** | On-policy | Discreta | Simple | Solo acciones discretas (no aplica directamente) | ⭐⭐ Solo PWM discreto |

### 3.2 Recomendación por Tarea

| Tarea | Algoritmo Recomendado | Justificación |
|-------|----------------------|---------------|
| **Swing-up del péndulo** | **SAC** | Mejor uso de muestras, entropía ayuda exploración |
| **Balance del péndulo** | **PPO o DDPG** | Estabilidad probada en QUBE por Quanser/MathWorks |
| **Selección de modo** | **PPO** (discreto) | Decide cuándo cambiar de swing-up a balance |
| **Sintonización PID** | **PPO o SAC** | Optimización de hiperparámetros como RL |
| **Control de posición servo** | No recomendado | PID existente ya es óptimo para esta tarea |

---

## 4. Arquitectura de Entrenamiento Sim-to-Real

### 4.1 Pipeline General

```
┌─────────────────────────────────────────────────────────────┐
│                    FASE 1: SIMULACIÓN                        │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ Modelo   │───►│ Entorno  │───►│ Agente RL│              │
│  │ No Lineal│    │ Gym-like │    │ (PPO/SAC)│              │
│  │ (MuJoCo/ │    │          │    │          │              │
│  │  Simulink│    │ Reward   │    │ Entrena  │              │
│  │  Custom) │    │ Function │    │ en GPU   │              │
│  └──────────┘    └──────────┘    └────┬─────┘              │
│                                       │                     │
│                              ┌────────▼────────┐            │
│                              │ Modelo ONNX     │            │
│                              │ (red neuronal   │            │
│                              │  exportada)      │            │
│                              └────────┬────────┘            │
└───────────────────────────────────────┼─────────────────────┘
                                        │
┌───────────────────────────────────────┼─────────────────────┐
│                    FASE 2: DESPLIEGUE  │                     │
│                                       │                     │
│  ┌────────────────────────────────────▼──────────────────┐  │
│  │              Conversión a C/C++                        │  │
│  │  ONNX → TFLite Micro / Edge Impulse / RLtools         │  │
│  │  Cuantización INT8 para reducir RAM/Flash              │  │
│  └────────────────────────┬──────────────────────────────┘  │
│                           │                                 │
│  ┌────────────────────────▼──────────────────────────────┐  │
│  │         Inferencia en ESP32                            │  │
│  │  Observación → Red neuronal → Acción (PWM)            │  │
│  │  Frecuencia: 200 Hz (5 ms)                            │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Modelo No Lineal del QUBE para Simulación

Para entrenar en simulación se necesita un modelo del sistema. El modelo ya está documentado en `docs/MODELO_FISICO_SISTEMA_QUBE.md`:

**Ecuaciones del péndulo rotatorio:**

$$
(J_{arm} + m_p L^2)\ddot{\theta} + m_p L d \cdot \ddot{\alpha} \cos(\alpha) - m_p L d \cdot \dot{\alpha}^2 \sin(\alpha) = \tau - b_1 \dot{\theta}
$$

$$
m_p L d \cdot \ddot{\theta} \cos(\alpha) + J_p \ddot{\alpha} - m_p g d \sin(\alpha) = -b_2 \dot{\alpha}
$$

### 4.3 Entorno Gym-Compatible

Se debe crear un entorno compatible con Gymnasium (estándar de la industria):

```python
import gymnasium as gym
import numpy as np

class QubeServoEnv(gym.Env):
    """
    Entorno del péndulo rotatorio QUBE Servo.
    
    Observación: [theta, alpha, theta_dot, alpha_dot]  (4 dimensiones)
    Acción: [torque]  (1 dimensión, continua, rango [-1, 1])
    """
    
    metadata = {"render_modes": ["human"], "render_fps": 50}
    
    def __init__(self):
        super().__init__()
        
        # Espacio de observación: [θ, α, θ̇, α̇]
        self.observation_space = gym.spaces.Box(
            low=np.array([-np.pi, -np.pi, -10.0, -10.0]),
            high=np.array([np.pi, np.pi, 10.0, 10.0]),
            dtype=np.float32
        )
        
        # Espacio de acción: torque normalizado [-1, 1]
        self.action_space = gym.spaces.Box(
            low=-1.0, high=1.0, shape=(1,), dtype=np.float32
        )
        
        # Parámetros del sistema (valores del firmware)
        self.dt = 0.005          # 200 Hz
        self.m_p = 0.025         # kg
        self.d = 0.065           # m (pivot to CM)
        self.L = 0.078           # m (motor to pivot)
        self.J_p = 2e-5          # kg·m²
        self.J_arm = 1e-4        # kg·m²
        self.g = 9.81            # m/s²
        self.b1 = 1e-3           # N·m·s/rad (fricción brazo)
        self.b2 = 5e-4           # N·m·s/rad (fricción péndulo)
        self.tau_max = 0.05      # N·m (torque máximo motor)
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # Inicialización aleatoria para generalización
        self.theta = self.np_random.uniform(-0.1, 0.1)    # ±5.7°
        self.alpha = self.np_random.uniform(-0.2, 0.2)    # ±11.5°
        self.theta_dot = 0.0
        self.alpha_dot = 0.0
        self.steps = 0
        return self._get_obs(), {}
    
    def step(self, action):
        torque = float(action[0]) * self.tau_max
        
        # Ecuaciones de movimiento (integración Runge-Kutta 4)
        state = np.array([self.theta, self.alpha, 
                         self.theta_dot, self.alpha_dot])
        new_state = self._rk4_step(state, torque)
        
        self.theta, self.alpha, self.theta_dot, self.alpha_dot = new_state
        self.steps += 1
        
        # Recompensa
        reward = self._compute_reward()
        
        # Terminación
        terminated = (
            abs(self.alpha) > np.pi or   # péndulo cayó
            abs(self.theta) > np.pi/3    # brazo fuera de rango
        )
        truncated = self.steps >= 1000   # 5 segundos
        
        return self._get_obs(), reward, terminated, truncated, {}
    
    def _rk4_step(self, state, torque):
        """Integración Runge-Kutta 4to orden."""
        def derivs(s, u):
            th, al, th_d, al_d = s
            sin_a, cos_a = np.sin(al), np.cos(al)
            
            Delta = (self.J_arm + self.m_p * self.L**2) * self.J_p - \
                    (self.m_p * self.L * self.d * cos_a)**2
            
            th_dd = ((self.J_p * (u - self.b1 * th_d + 
                     self.m_p * self.L * self.d * al_d**2 * sin_a)) -
                     self.m_p * self.L * self.d * cos_a * 
                     (self.m_p * self.g * self.d * sin_a - self.b2 * al_d)) / Delta
            
            al_dd = (((self.J_arm + self.m_p * self.L**2) * 
                     (self.m_p * self.g * self.d * sin_a - self.b2 * al_d) +
                     self.m_p * self.L * self.d * cos_a * 
                     (u - self.b1 * th_d + self.m_p * self.L * self.d * 
                      al_d**2 * sin_a))) / Delta
            
            return np.array([th_d, al_d, th_dd, al_dd])
        
        k1 = derivs(state, torque)
        k2 = derivs(state + 0.5 * self.dt * k1, torque)
        k3 = derivs(state + 0.5 * self.dt * k2, torque)
        k4 = derivs(state + self.dt * k3, torque)
        
        return state + (self.dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
    
    def _compute_reward(self):
        """Recompensa cuadrática (similar a Quanser)."""
        r_theta = 10.0 * self.theta**2      # penaliza brazo lejos de 0
        r_alpha = 50.0 * self.alpha**2       # penaliza péndulo lejos de vertical
        r_vel = 0.1 * (self.theta_dot**2 + self.alpha_dot**2)
        r_energy = 0.01 * (self.tau_max * 0.5)**2  # penaliza esfuerzo
        
        return -(r_theta + r_alpha + r_vel + r_energy)
    
    def _get_obs(self):
        return np.array([
            self.theta, self.alpha,
            self.theta_dot, self.alpha_dot
        ], dtype=np.float32)
```

---

## 5. Restricciones del ESP32 para Inferencia

### 5.1 Recursos Hardware

| Recurso | ESP32-WROOM-32 | Requerimiento RL inferencia |
|---------|----------------|---------------------------|
| RAM | 520 KB SRAM | < 50 KB para red pequeña |
| Flash | 4 MB | < 200 KB para modelo cuantizado |
| CPU | Dual-core 240 MHz Xtensa | Inferencia en ~0.5–2 ms |
| FPU | F32 en ambos cores | Aceleración nativa |
| Período de control | 5 ms (200 Hz) | Inferencia < 5 ms |

### 5.2 Tamaño de Red Neuronal Aceptable

Para correr inferencia a 200 Hz en ESP32, la red debe ser pequeña:

| Arquitectura | Parámetros | RAM (F32) | RAM (INT8) | Tiempo inferencia |
|-------------|-----------|-----------|------------|-------------------|
| [4] → [32] → [1] | 193 | ~1 KB | ~300 B | < 0.1 ms |
| [4] → [64] → [32] → [1] | 2,497 | ~10 KB | ~3 KB | < 0.5 ms |
| [4] → [128] → [64] → [1] | 8,961 | ~36 KB | ~9 KB | < 1 ms |
| [4] → [256] → [128] → [1] | 35,329 | ~140 KB | ~35 KB | < 2 ms |

**Recomendación:** Usar `[4] → [64] → [32] → [1]` (2,497 parámetros) como punto de partida. Suficiente para representar una política no lineal, cabe en RAM con margen.

### 5.3 Opciones de Inferencia en ESP32

| Método | Ventaja | Desventaja | Biblioteca |
|--------|---------|------------|------------|
| **Edge Impulse** | Fácil integración, exporta a Arduino | Dependencia externa | edgeimpulse.com |
| **TFLite Micro** | Oficial Google, bien documentado | Requiere conversión ONNX→TFLite | tflite-micro |
| **RLtools** | Más rápido, sin dependencias, puro C++ | C++ template-heavy, curva aprendizaje | github.com/rl-tools/rltools |
| **C++ manual** | Máximo control, mínimo overhead | Hay que escribir forward pass | — |
| **ONNX Runtime** | Flexible | Pesado para ESP32 | onnxruntime |

### 5.4 Código de Inferencia (C++ Manual)

```cpp
// Inferencia de red neuronal simple en ESP32
// Arquitectura: [4] → [64] → [32] → [1]
// Pesos cuantizados INT8, dequantización a F32

struct TinyPolicy {
    // Pesos y biases (almacenados en Flash/PROGMEM)
    const float W1[64][4];   // 256 floats
    const float b1[64];       // 64 floats
    const float W2[32][64];   // 2048 floats
    const float b2[32];       // 32 floats
    const float W3[1][32];    // 32 floats
    const float b3[1];        // 1 float
    
    // Buffer para activaciones intermedias
    float hidden1[64];
    float hidden2[32];
    
    float forward(const float obs[4]) {
        // Capa 1: ReLU
        for (int i = 0; i < 64; i++) {
            float sum = b1[i];
            for (int j = 0; j < 4; j++) {
                sum += W1[i][j] * obs[j];
            }
            hidden1[i] = sum > 0.0f ? sum : 0.0f;  // ReLU
        }
        
        // Capa 2: ReLU
        for (int i = 0; i < 32; i++) {
            float sum = b2[i];
            for (int j = 0; j < 64; j++) {
                sum += W2[i][j] * hidden1[j];
            }
            hidden2[i] = sum > 0.0f ? sum : 0.0f;  // ReLU
        }
        
        // Capa de salida: tanh (acción acotada)
        float sum = b3[0];
        for (int j = 0; j < 32; j++) {
            sum += W3[0][j] * hidden2[j];
        }
        
        // tanh aproximado
        float x = sum;
        float x2 = x * x;
        float tanh_approx = x * (27.0f + x2) / (27.0f + 9.0f * x2);
        
        return tanh_approx;  // Rango [-1, 1]
    }
};
```

**Tiempo estimado de inferencia:** ~0.3 ms en ESP32 @ 240 MHz (mucho menor que el período de 5 ms).

---

## 6. Librerías y Herramientas

### 6.1 Para Entrenamiento (Python)

| Librería | Algoritmos | Ventaja | GitHub Stars |
|----------|-----------|---------|-------------|
| **Stable-Baselines3** | PPO, SAC, TD3, DDPG | Fácil de usar, bien documentado | 10K+ |
| **RLtools** | PPO, SAC, TD3 | Entrenamiento 76× más rápido que otros | 1K+ |
| **CleanRL** | PPO, SAC, DDPG | Single-file, transparente | 6K+ |
| **Tianshou** | PPO, SAC, DDPG | Modular, PyTorch | 8K+ |
| **Ray/RLlib** | Todos | Distribuido, escalable | 35K+ |

### 6.2 Para Despliegue en ESP32

| Herramienta | Método | Flujo |
|-------------|--------|-------|
| **RLtools** | C++ puro, header-only | Entrena en PC → Compila para ESP32 directamente |
| **Edge Impulse** | ONNX → Arduino library | Entrena en Python → Exporta ONNX → Edge Impulse → .ino |
| **TFLite Micro** | ONNX → TFLite → C array | Entrena en Python → tflite conversion → `const unsigned char model[]` |
| **Manual** | Exportar pesos como header | Entrena en Python → `np.savetxt` → `const float weights[]` |

### 6.3 Herramientas para Simulación del Modelo

| Herramienta | Tipo | Ventaja |
|-------------|------|---------|
| **Custom Gymnasium env** | Python puro | Flexibilidad total, sin dependencias |
| **MuJoCo** | Simulador físico | Alta fidelidad, estándar en RL |
| **MATLAB/Simulink** | Simulador con Simscape | Validado por Quanser, integración directa con hardware |
| **PyBullet** | Simulador gratuito | Buena física, fácil de usar |

---

## 7. Diseño del Entorno para el QUBE

### 7.1 Definición del MDP

| Componente | Definición |
|-----------|------------|
| **Estados (S)** | $[\theta, \alpha, \dot{\theta}, \dot{\alpha}]$ — posición brazo, ángulo péndulo, velocidades |
| **Acciones (A)** | $[u]$ — torque motor normalizado ∈ [-1, 1] → PWM real |
| **Transiciones (P)** | Ecuaciones de Euler-Lagrange (modelo no lineal) |
| **Recompensa (R)** | Cuadrática con penalización de esfuerzo (ver §8) |
| **Terminal** | Péndulo cae (|α| > π) o brazo fuera de rango (|θ| > 60°) |

### 7.2 Tipos de Entorno

| Entorno | Objetivo | Observaciones | Acciones |
|---------|----------|---------------|----------|
| `QubeSwingUp-v0` | Elevar péndulo desde colgando hasta vertical | [θ, α, θ̇, α̇] | [torque] |
| `QubeBalance-v0` | Mantener péndulo vertical | [θ, α, θ̇, α̇] | [torque] |
| `QubeFull-v0` | Swing-up + balance completo | [θ, α, θ̇, α̇] | [torque] |
| `QubePIDTune-v0` | Optimizar Kp, Ki, Kd | [error, integral, derivative] | [ΔKp, ΔKi, ΔKd] |

---

## 8. Función de Recompensa

### 8.1 Recompensa Cuadrática (Recomendada para Balance)

Basada en la usada por Quanser para el QUBE-Servo 3:

$$
r(\theta, \alpha, \dot{\theta}, \dot{\alpha}, u) = -\left(
    q_1 \cdot \theta^2 +
    q_2 \cdot \alpha^2 +
    q_3 \cdot \dot{\theta}^2 +
    q_4 \cdot \dot{\alpha}^2 +
    r_1 \cdot u^2
\right)
$$

**Pesos recomendados (balance):**

| Peso | Valor | Interpretación |
|------|-------|---------------|
| $q_1$ | 10.0 | Penaliza brazo lejos de 0° |
| $q_2$ | 50.0 | Penaliza péndulo lejos de vertical (prioridad máxima) |
| $q_3$ | 0.1 | Penaliza velocidad del brazo |
| $q_4$ | 0.1 | Penaliza velocidad del péndulo |
| $r_1$ | 0.01 | Penaliza esfuerzo de control |

### 8.2 Recompensa para Swing-Up

$$
r = -q_\alpha \cdot (1 - \cos(\alpha)) - r_1 \cdot u^2 + r_{bonus} \cdot \mathbb{1}[|\alpha - \pi| < \epsilon]
$$

| Peso | Valor | Interpretación |
|------|-------|---------------|
| $q_\alpha$ | 10.0 | Penaliza energía potencial (mínima en vertical) |
| $r_1$ | 0.01 | Penaliza esfuerzo |
| $r_{bonus}$ | 100.0 | Bonificación por alcanzar vertical |

### 8.3 Señales de Parada (Stop Signals)

Episodio se termina prematuramente si:
- $|\theta| > 60°$ (brazo fuera de rango seguro)
- $|\alpha| > 10°$ desde vertical (solo en modo balance)
- $|u| > u_{max}$ (saturación de motor)

Estas señales aceleran el entrenamiento evitando episodios inútiles.

---

## 9. Estrategia Recomendada por Sistema de Control

### 9.1 Péndulo Rotatorio Invertido: Swing-Up + Balance

**Estado actual del proyecto:** El firmware tiene modos 4 (LQR) y 5 (swing-up energético) que funcionan con parámetros fijos.

**Propuesta RL:** Reemplazar el control de energía fijo por una política aprendida.

#### Enfoque A: RL Completo (SAC) — Más ambicioso

```
Entrenamiento offline (Python):
1. Crear entorno Gym del QUBE no lineal
2. Entrenar SAC para swing-up + balance en un solo agente
3. Función de recompensa: cuadrática + bonificación de energía
4. ~100K–500K pasos de entrenamiento (~30 min en GPU)

Despliegue:
1. Exportar política como ONNX
2. Convertir a C++ (RLtools o Edge Impulse)
3. Inferencia en ESP32 a 200 Hz
4. Modo 4/5 del firmware usa la política RL en vez de LQR/energía
```

#### Enfoque B: RL + Control Clásico Híbrido — Más seguro (Recomendado)

```
1. Usar PID/LQR existente para balance (modo 4)
2. Entrenar SAC solo para swing-up (modo 5)
3. PPO para decidir cuándo cambiar de swing-up a balance
4. Transición suave entre controladores

Ventaja: Si el RL falla, el PID/LQR toma control
```

**Esto es exactamente lo que hizo MathWorks con el QUBE-Servo 2:**
- SAC para swing-up
- PPO para selección de modo
- PID/LQR para balance

### 9.2 Sintonización Automática de PID

**Estado actual:** Los parámetros PID se ajustan manualmente.

**Propuesta RL:** Usar RL para encontrar óptimos Kp, Ki, Kd.

```python
class PIDTuneEnv(gym.Env):
    """
    Entorno para sintonización de PID.
    
    Observación: [error, integral_error, derivative_error, pos, vel]
    Acción: [ΔKp, ΔKi, ΔKd]  (cambios en ganancias)
    Recompensa: basada en métricas de respuesta (overshoot, ts, ess)
    """
    
    def step(self, action):
        # Aplicar nuevas ganancias al sistema real/simulado
        self.Kp += action[0] * 0.1
        self.Ki += action[1] * 0.01
        self.Kd += action[2] * 0.01
        
        # Ejecutar episodio con escalón de setpoint
        # Calcular métricas
        reward = self._reward_from_metrics(
            overshoot, settling_time, steady_state_error
        )
        
        return obs, reward, done, truncated, info
```

**Ventaja:** El RL puede encontrar ganancias que un humano tardaría horas en ajustar.

### 9.3 Control de Posición del Servo

**No se recomienda RL para esta tarea.** El PID existente con parámetros bien ajustados (Kp=3.0, Ki=0.5, Kd=0.15) ya logra:
- Convergencia en 2–3 segundos
- Overshoot 10–20%
- Error estacionario < 2°

RL no mejoraría significativamente estas métricas para una tarea tan simple. El beneficio de RL está en tareas con dinámicas más complejas (péndulo invertido, swing-up).

---

## 10. Pipeline de Implementación

### 10.1 Fase 1: Simulación (2–3 semanas)

```
Semana 1:
├── Implementar entorno Gymnasium del QUBE
├── Validar modelo contra datos experimentales existentes
└── Verificar que la simulación reproduce el comportamiento real

Semana 2:
├── Entrenar SAC para swing-up en simulación
├── Entrenar PPO para balance en simulación
└── Ajustar función de recompensa

Semana 3:
├── Combinar agentes (híbrido RL + PID)
├── Validar en simulación con perturbaciones
└── Exportar modelo ONNX
```

### 10.2 Fase 2: Despliegue (2–3 semanas)

```
Semana 4:
├── Convertir modelo ONNX a C++ (RLtools o Edge Impulse)
├── Implementar inferencia en firmware ESP32
├── Benchmark: tiempo de inferencia vs. período de control

Semana 5:
├── Probar en hardware real (modo seguro, PWM limitado)
├── Validar comportamiento con perturbaciones manuales
└── Ajustar parámetros de normalización

Semana 6:
├── Comparar RL vs. LQR vs. PID en métricas
├── Documentar resultados
└── Decidir si RL reemplaza o complementa control clásico
```

### 10.3 Fase 3: Optimización (1–2 semanas)

```
Semana 7-8:
├── Entrenamiento con domain randomization (sim-to-real)
├── Fine-tuning en hardware real (si es necesario)
├── Cuantización y optimización de la red
└── Documentación final
```

---

## 11. Comparativa: RL vs. Control Clásico

| Criterio | PID | LQR | RL (SAC/PPO) |
|----------|-----|-----|-------------|
| **Complejidad de implementación** | Baja | Media | Alta |
| **Requiere modelo del sistema** | No | Sí (linealizado) | No (aprende de interacción) |
| **Rendimiento óptimo** | Bueno | Óptimo (lineal) | Potencialmente mejor (no lineal) |
| **Robustez a perturbaciones** | Media | Media-Alta | Alta (si se entrena bien) |
| **Adaptabilidad** | Estático | Estático | Adaptativo |
| **Requiere entrenamiento** | No | No | Sí (horas/días) |
| **Costo computacional inferencia** | Mínimo (~0.01 ms) | Bajo (~0.05 ms) | Medio (~0.3–1 ms) |
| **Garantías de estabilidad** | Sí (teoría clásica) | Sí (teoría óptima) | No (empírico) |
| **Requiere identificación de parámetros** | No | Sí | No |
| **Mejor para swing-up** | No (requiere lógica adicional) | No (solo funciona cerca del equilibrio) | **Sí** |
| **Mejor para balance** | Sí (si está bien ajustado) | **Sí** | Sí (pero overkill) |

### 11.1 Cuándo Usar RL

| Escenario | RL es beneficial | RL es overkill |
|-----------|-----------------|----------------|
| Swing-up de péndulo | **Sí** | — |
| Balance con perturbaciones Unknown | **Sí** | — |
| Sintonización automática de PID | **Sí** | — |
| Control de posición simple | — | **Sí** (PID basta) |
| Sistema lineal conocido | — | **Sí** (LQR es óptimo) |
| Modelo no disponible | **Sí** | — |
| Condiciones cambiantes | **Sí** | — |

### 11.2 Beneficio Académico

Usar RL en el QUBE Servo ofrece un **aporte académico significativo**:

1. **Metodología de sim-to-real transfer** para sistemas embebidos de bajo costo
2. **Comparativa directa** PID vs. LQR vs. RL en la misma plataforma
3. **Contribución original**: Nadie ha documentado RL en ESP32 + BTS7960 + INA219
4. **Relevancia**: RL para control es un campo de investigación activo (2024–2026)

---

## 12. Referencias

### Papers y Artículos

1. Quanser. (2026). Using the Reinforcement Learning Toolbox™ to Balance the Qube-Servo 3 Inverted Pendulum. *Quanser Blog*.

2. MathWorks. (2021–2025). Reinforcement Learning: training and deploying a policy to control inverted pendulum with QUBE-Servo 2. *GitHub*.

3. Eschmann, J., Albani, D., & Loianno, G. (2024). RLtools: A Fast, Portable Deep Reinforcement Learning Library for Continuous Control. *JMLR*, 25.

4. Andert, J. et al. (2023). LExCI: A Framework for Reinforcement Learning with Embedded Systems. *arXiv:2312.02739*.

5. Schulman, J. et al. (2017). Proximal Policy Optimization Algorithms. *arXiv:1707.06347*.

6. Haarnoja, T. et al. (2018). Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning. *ICML 2018*.

7. Fujimoto, S. et al. (2018). Addressing Function Approximation Error in Actor-Critic Methods. *ICML 2018* (TD3).

### Proyectos GitHub

8. ShawnHymel/pendulum-rl — TinyRL: Entrenamiento RL en hardware ESP32 real.

9. mathworks/Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2 — SAC + PPO para QUBE-Servo 2.

10. rl-tools/rltools — Librería C++ para RL en microcontroladores.

11. Stable-Baselines3 — https://github.com/DLR-RM/stable-baselines3

---

*Documento generado: 2026-06-01 | Investigación de viabilidad de Aprendizaje por Refuerzo para QUBE Servo ESP32*
