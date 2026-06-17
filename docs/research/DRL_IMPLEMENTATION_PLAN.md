# Plan: Deep Reinforcement Learning para QUBE Servo ESP32

**Fecha:** 2026-06-16
**Objetivo:** Implementar control de péndulo rotatorio invertido mediante DRL (SAC) con pipeline sim-to-real, basado en la arquitectura del repo [Armandpl/furuta](https://github.com/Armandpl/furuta) y la librería [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3).
**Estado:** Plan listo para ejecutar

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Referencias Técnicas](#2-referencias-técnicas)
3. [Arquitectura del Sistema](#3-arquitectura-del-sistema)
4. [Fase 1: Entorno de Simulación Gym](#4-fase-1-entorno-de-simulación-gym)
5. [Fase 2: Modo RL en Firmware ESP32](#5-fase-2-modo-rl-en-firmware-esp32)
6. [Fase 3: Entorno Real Gym](#6-fase-3-entorno-real-gym)
7. [Fase 4: Entrenamiento Sim](#7-fase-4-entrenamiento-sim)
8. [Fase 5: Inferencia en Hardware Real](#8-fase-5-inferencia-en-hardware-real)
9. [Fase 6: Fine-Tuning Sim-to-Real](#9-fase-6-fine-tuning-sim-to-real)
10. [Fase 7: Exportación a ESP32 (opcional)](#10-fase-7-exportación-a-esp32-opcional)
11. [Decisiones de Diseño](#11-decisiones-de-diseño)
12. [Riesgos y Mitigaciones](#12-riesgos-y-mitigaciones)
13. [Criterios de Aceptación](#13-criterios-de-aceptación)
14. [Dependencias](#14-dependencias)
15. [Referencias Bibliográficas](#15-referencias-bibliográficas)

---

## 1. Resumen Ejecutivo

### Qué se va a hacer

Implementar un agente SAC (Soft Actor-Critic) que controle el swing-up y balance del péndulo
rotatorio del QUBE Servo, usando un pipeline sim-to-real:

1. Entrenar en simulación con domain randomization (PC con GPU)
2. Desplegar inferencia vía WiFi HTTP al ESP32
3. Fine-tuning en hardware real

### Por qué SAC

- **Off-policy**: reutiliza datos del replay buffer (eficiente en muestras)
- **Entropía máxima**: exploración natural, crucial para sim-to-real
- **gSDE**: State-Dependent Exploration produce ruido correlacionado con el estado,
  mucho más eficiente que ruido gaussiano para transferencia
- **Probado en Furuta**: el repo Armandpl/furuta demuestra que SAC con gSDE
  logra balance estable en un péndulo rotatorio real con ~200K steps de simulación + 100K fine-tuning

### Qué NO se va a hacer

- No se reemplaza el LQR existente (modo 4) — se complementa
- No se reemplaza el PID servo (modo 2) — el RL solo controla el péndulo
- No se exporta la red al ESP32 todavía (fase 7 es opcional/futura)

---

## 2. Referencias Técnicas

### 2.1 Armandpl/furuta — Repo de referencia principal

- **URL:** https://github.com/Armandpl/furuta (40★, Python)
- **Hardware:** Motor DC 25D/37D + encoder incremental + serial @ 921600 baud
- **Algoritmo:** SAC con gSDE via Stable-Baselines3
- **Pipeline:** QubeDynamics (sim analítico) → FurutaSim (Gym) → SAC train → FurutaReal (serial) → fine-tune
- **Domain randomization:** Parámetros físicos variados cada reset (masas, largos, resistencia motor, back-emf)
- **Wrappers:** HistoryWrapper (obs pasadas), ControlFrequency (50Hz), GentlyTerminating (kill motor), DeadZone (compensar fricción)
- **Reward:** `(1 - cos(α))/2 × θ_reward` — multiplicative, premiza verticalidad + centro
- **Observación:** `[cos θ, sin θ, cos α, sin α, θ̇, α̇]` — codificación trigonométrica
- **Frecuencia:** 50 Hz (control_freq)

### 2.2 Stable-Baselines3 — Librería de RL

- **URL:** https://github.com/DLR-RM/stable-baselines3 (13.4K★, MIT)
- **Versión:** 2.2+ (requiere Python 3.10+, PyTorch 2.8+)
- **Algoritmos implementados:** A2C, DDPG, DQN, HER, PPO, SAC, TD3
- **Extensiones:**
  - SB3-Contrib: TQC, CrossQ, Recurrent PPO, QR-DQN, Maskable PPO
  - SBX (Jax): Variantes 20x más rápidas (DroQ, CrossQ)
- **API:** sklearn-style — `model = SAC("MlpPolicy", env); model.learn(total_timesteps=N)`
- **Exportación:** ONNX, PyTorch JIT (C++), TFLite
- **Tracking:** TensorBoard integrado, W&B opcional
- **Env checker:** `check_env(env)` valida compatibilidad con Gymnasium

### 2.3 Documentación existente en el repo

- `docs/research/ai_research/viabilidad_aprendizaje_refuerzo.md` — Viabilidad RL ya evaluada (✅ VIABLE)
- `docs/research/METODOS_ESTABILIZACION_PENDULOS_INVERTIDOS.md` — Métodos de estabilización
- `docs/research/frecuencias_control_pendulos_quanser.md` — Frecuencias de control
- `docs/MODELO_FISICO_SISTEMA_QUBE.md` — Modelo físico del sistema (ecuaciones de Lagrange)

---

## 3. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PC (Windows/Linux con GPU)                      │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │ QubeDynamics │───►│ QubeSimEnv   │───►│ SAC (SB3)             │  │
│  │ (analítico)  │    │ (Gymnasium)  │    │ - gSDE                │  │ 
│  │              │    │              │    │ - domain randomization│  │
│  │ Parametros   │    │ obs:         │    │ - HistoryWrapper      │  │
│  │ QUBE reales  │    │ [cosθ,sinθ,  │    │ - DeadZone            │  │
│  │ + randomize  │    │  cosα,sinα,  │    │                       │   │
│  │              │    │  θ̇, α̇]       │    │ Entrena 200K steps    │  │
│  └──────────────┘    │ act: [-1,1]  │    │ → model.zip           │  │
│                      └──────────────┘    └──────────┬────────────┘  │
│                                                     │               │
│  ┌──────────────────────────────────────────────────▼───────────┐   │
│  │                    QubeRealEnv (Gymnasium)                   │   │
│  │                                                              │   │
│  │  HTTP GET /rl_state → [θ, α, θ̇, α̇]                           │   │
│  │  HTTP GET /rl_cmd?a=X → PWM [-1,1]                           │   │
│  │  50 Hz control loop                                          │   │
│  │  Fine-tuning 100K steps                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ WiFi (HTTP)
┌──────────────────────────────────────▼──────────────────────────────┐
│                     ESP32-WROOM-32                                  │
│                                                                     │
│  Modo 6 (RL):                                                       │
│    GET /rl_state → JSON {theta, alpha, theta_dot, alpha_dot}        │
│    GET /rl_cmd?a=0.5 → PWM directo al motor                         │
│                                                                     │
│  Modos existentes (NO se modifican):                                │
│    Modo 0: Stop                                                     │
│    Modo 1: PWM manual                                               │
│    Modo 2: PID servo                                                │
│    Modo 3: PID péndulo                                              │
│    Modo 4: LQR péndulo invertido                                    │
│    Modo 5: Swing-up energético                                      │
│                                                                     │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐               │
│  │ L298N   │  │ Encoder │  │ Encoder  │  │ INA219   │               │
│  │ (motor) │  │ servo   │  │ péndulo  │  │ (power)  │               │
│  └─────────┘  └─────────┘  └──────────┘  └──────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Fase 1: Entorno de Simulación Gym

### 4.1 Archivo: `src/qube_rl/envs/qube_dynamics.py`

Modelo analítico del QUBE. Copiar de `furuta/robot.py` → `QubeDynamics`, ajustar parámetros:

```python
@dataclass
class QubeDynamics:
    """Ecuaciones de movimiento del péndulo rotatorio QUBE Servo.
    Resuelve M·q̈ + C(q, q̇) = τ para q̈.
    Parámetros de docs/MODELO_FISICO_SISTEMA_QUBE.md"""

    g: float = 9.81
    # Motor (BTS7960 + Premotec 9904 120 16913)
    Rm: float = 8.4           # Resistencia (Ohm) — rated voltage / stall current
    Rm_std: float = 1.5       # Para domain randomization
    V: float = 12.0           # Voltaje nominal
    km: float = 0.042         # Back-emf constant (V·s/rad)
    km_std: float = 0.01
    stall_torque: float = 0.16  # N·m
    # Brazo rotatorio (servo)
    Mr: float = 0.095         # Masa (kg)
    Mr_std: float = 0.02
    Lr: float = 0.085         # Largo (m)
    Lr_std: float = 0.01
    Dr: float = 5e-6          # Fricción viscosa (N·m·s/rad)
    Dr_std: float = 5e-6
    # Péndulo
    Mp: float = 0.024         # Masa (kg)
    Mp_std: float = 0.003
    Lp: float = 0.129         # Largo (m)
    Lp_std: float = 0.010
    Dp: float = 1e-6          # Fricción viscosa (N·m·s/rad)
    Dp_std: float = 5e-7

    # NOTA: Los valores exactos deben calibrarse con el hardware real.
    # Los _std controlan cuánto varían en domain randomization.
    # Valores más altos → más robusto pero más lento para converger.
```

**Métodos:**

- `randomize()` — Muestrear parámetros de distribuciones normales
- `__call__(state, action)` → `(thdd, aldd)` — Ecuaciones de movimiento
- `_init_const()` — Precomputar constantes (Jr, Jp, c[0..4])

### 4.2 Archivo: `src/qube_rl/envs/qube_sim.py`

Entorno Gymnasium para simulación. Basado en `furuta/rl/envs/furuta_sim.py`:

```python
class QubeSimEnv(gym.Env):
    """Entorno de simulación del QUBE Servo para RL."""

    metadata = {"render_modes": ["rgb_array"], "render_fps": 50}

    # Espacios
    # observation: [cos(θ), sin(θ), cos(α), sin(α), θ̇, α̇]  — 6 dims
    # action: [-1.0, 1.0]  — 1 dim (PWM normalizado)
    # reward: alpha_theta_reward (ver sección 4.3)

    def __init__(self, dyn, control_freq=50, reward="cos_alpha",
                 angle_limits=[np.inf, np.inf],
                 speed_limits=[50, 400],
                 encoders_CPRs=None,
                 velocity_filter_order=2):
        ...

    def step(self, action):
        # 1. Integrar dinámica (substeps a 500 Hz internamente)
        # 2. Simular encoder (quantización por CPR)
        # 3. Aplicar filtro de velocidad (como en firmware)
        # 4. Calcular reward
        # 5. Verificar termination (ángulo fuera de límites)
        ...

    def reset(self, seed=None, options=None):
        # 1. Randomizar parámetros físicos
        # 2. Estado inicial cercano a equilibrio inestable (α ≈ π)
        # 3. Reset filtro de velocidad
        ...
```

### 4.3 Función de Recompensa

Copiar de `furuta/rl/envs/furuta_base.py`:

```python
REWARDS = {
    "cos_alpha": alpha_theta_reward,      # Recomendada: (1-cos(α))/2 × θ_reward
    "exp_alpha_2": exp_alpha_2,           # Más agresiva cerca de ±π
    "exp_alpha_4": exp_alpha_4,           # Muy agresiva
}

def alpha_theta_reward(state):
    """Premiza simultaneamente α vertical y θ centrado."""
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_rew = (1 + -np.cos(al)) / 2        # 0 en vertical, 1 en fondo
    th_rew = 1 - ((np.cos(state[THETA] + np.pi) + 1) / 2)**2
    return al_rew * th_rew
```

### 4.4 Observación

```python
def get_obs(self):
    return np.float32([
        np.cos(self._state[THETA]),
        np.sin(self._state[THETA]),
        np.cos(self._state[ALPHA]),
        np.sin(self._state[ALPHA]),
        self._state[THETA_DOT],
        self._state[ALPHA_DOT],
    ])
```

**Por qué cos/sin en vez de ángulos crudos:** Elimina la discontinuidad en ±π.
Una red neuronal ve α=3.14 y α=-3.14 como distantes, pero cos(3.14) ≈ cos(-3.14).

### 4.5 Wrappers

| Wrapper               | Archivo                     | Función                                                                 |
| --------------------- | --------------------------- | ------------------------------------------------------------------------ |
| `ControlFrequency`  | `src/qube_rl/wrappers.py` | Enforce 50 Hz (sleep entre steps)                                        |
| `GentlyTerminating` | `src/qube_rl/wrappers.py` | Envía acción 0 al terminar episodio                                    |
| `DeadZone`          | `src/qube_rl/wrappers.py` | Compensa zona muerta del motor (deadzone=0.2, center=0.01, max_act=0.75) |
| `HistoryWrapper`    | `src/qube_rl/wrappers.py` | Stack N pasos de [obs, acción] + continuity cost                        |

### 4.6 Integración con firmware existente

El firmware ya tiene `QubeDynamics` implícito en las ecuaciones del LQR y swing-up.
La simulación debe replicar exactamente:

- Filtro de velocidad EMA (τ configurable, default 5ms)
- Cuantización encoder (2048 CPR servo, 2048 CPR péndulo)
- Dead-zone del motor (PWM mínimo ~12 para vencer fricción)
- Saturación suave (soft saturation cerca de límites mecánicos)

---

## 5. Fase 2: Modo RL en Firmware ESP32

### 5.1 Cambios en `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino`

#### 5.1.1 Agregar modo 6 (RL)

```cpp
// En el enum de modos existente, agregar:
// Modo 6: RL — recibe acción por HTTP, aplica PWM directo
// Endpoints:
//   GET /rl_cmd?a=0.5   → acción RL [-1.0, 1.0]
//   GET /rl_state       → JSON compacto con θ, α, θ̇, α̇
```

#### 5.1.2 Endpoint `/rl_state` (JSON compacto de baja latencia)

```cpp
void handleRlState(AsyncWebServerRequest *request) {
  // Posiciones (grados → radianes)
  const float theta_rad = getPositionDeg() * DEG_TO_RAD;
  const float alpha_rad = getPendulumPositionDeg() * DEG_TO_RAD;
  // Velocidades (ya calculadas por el filtro EMA del firmware)
  const float theta_dot = lqr_filteredVelTheta;  // rad/s
  const float alpha_dot = lqr_filteredVelAlpha;   // rad/s

  // JSON mínimo para baja latencia (~60 bytes vs ~800 bytes de /state)
  String json = "{";
  json += "\"th\":" + String(theta_rad, 4) + ",";
  json += "\"al\":" + String(alpha_rad, 4) + ",";
  json += "\"thd\":" + String(theta_dot, 4) + ",";
  json += "\"ald\":" + String(alpha_dot, 4);
  json += "}";
  request->send(200, "application/json", json);
}
```

**NOTA CRÍTICA:** El JSON de `/state` actual NO incluye velocidades angulares
(solo posiciones). El endpoint `/rl_state` SÍ las incluye usando los filtros
ya existentes en el firmware (`lqr_filteredVelTheta`, `lqr_filteredVelAlpha`).

#### 5.1.3 Endpoint `/rl_cmd`

```cpp
volatile float rlAction = 0.0f;  // Acción RL [-1.0, 1.0]

void handleRlCmd(AsyncWebServerRequest *request) {
  if (request->hasParam("a")) {
    rlAction = constrain(request->getParam("a")->value().toFloat(), -1.0f, 1.0f);
    lastCommandMs = millis();
  }
  if (request->hasParam("r")) {
    // Reset encoders + estado
    resetPcnt(pcnt_servo_unit);
    resetPcnt(pcnt_pendulum_unit);
    positionOffsetDeg = 0.0f;
    pendulumOffsetDeg = 0.0f;
    lqr_filteredVelTheta = 0.0f;
    lqr_filteredVelAlpha = 0.0f;
    rlAction = 0.0f;
    lastCommandMs = millis();
  }
  request->send(200, "application/json", "{\"ok\":true}");
}
```

#### 5.1.4 Loop de control para modo 6

```cpp
// En el loop principal, case MODE_RL:
case 6:  // RL
{
  // Aplicar acción RL como PWM directo
  int duty = (int)(fabsf(rlAction) * PWM_MAX);
  duty = constrain(duty, 0, PWM_MAX);
  if (rlAction < 0) {
    setMotor(-duty);
  } else {
    setMotor(duty);
  }
  // Actualizar velocidades para /rl_state
  // (ya se actualizan en el loop de LQR, pero necesitamos
  //  calcularlas también en modo 6)
  const float theta = getPositionDeg() * DEG_TO_RAD;
  const float alpha = getPendulumPositionDeg() * DEG_TO_RAD;
  const float dt = (micros() - lastControlUs) / 1e6f;
  if (dt > 0.0f) {
    const float rawVelTheta = (theta - lqr_prevTheta) / dt;
    const float rawVelAlpha = (alpha - lqr_prevAlpha) / dt;
    lqr_filteredVelTheta = velAlpha * rawVelTheta + (1.0f - velAlpha) * lqr_filteredVelTheta;
    lqr_filteredVelAlpha = VEL_ALPHA_PEND * rawVelAlpha + (1.0f - VEL_ALPHA_PEND) * lqr_filteredVelAlpha;
    lqr_prevTheta = theta;
    lqr_prevAlpha = alpha;
  }
  break;
}
```

#### 5.1.5 Registro de endpoints

```cpp
// En setup(), agregar:
server.on("/rl_state", HTTP_GET, handleRlState);
server.on("/rl_cmd", HTTP_GET, handleRlCmd);
```

### 5.2 Latencia esperada

| Componente                     | Tiempo                 |
| ------------------------------ | ---------------------- |
| HTTP GET round-trip (WiFi LAN) | ~2-5 ms                |
| Procesamiento en ESP32         | ~0.5 ms                |
| Python predict() (SAC MLP)     | ~0.1 ms                |
| **Total por step**       | **~3-6 ms**      |
| **Período a 50 Hz**     | **20 ms**        |
| **Margen**               | **~14-17 ms** ✅ |

---

## 6. Fase 3: Entorno Real Gym

### 6.1 Archivo: `src/qube_rl/envs/qube_real.py`

Basado en `furuta/rl/envs/furuta_real.py`:

```python
class QubeRealEnv(gym.Env):
    """Entorno RL que controla el QUBE ESP32 por HTTP."""

    def __init__(self, esp32_ip="192.168.4.1", control_freq=50,
                 reward="cos_alpha", angle_limits=[np.inf, np.inf],
                 speed_limits=[50, 400]):
        # Mismos espacios que QubeSimEnv
        # observation: [cos θ, sin θ, cos α, sin α, θ̇, α̇]
        # action: [-1.0, 1.0]
        ...

    def _update_state(self, action):
        # 1. Enviar acción al ESP32
        resp = self.session.get(f"http://{self.esp32_ip}/rl_cmd?a={action:.4f}")
        # 2. Leer estado
        resp = self.session.get(f"http://{self.esp32_ip}/rl_state")
        data = resp.json()
        # 3. Construir estado interno
        self._state[THETA] = data['th']
        self._state[ALPHA] = data['al']
        self._state[THETA_DOT] = data['thd']
        self._state[ALPHA_DOT] = data['ald']

    def reset(self, seed=None, options=None):
        # 1. Enviar reset al ESP32
        self.session.get(f"http://{self.esp32_ip}/rl_cmd?r=1")
        # 2. Esperar a que el péndulo se estabilice (caiga)
        # 3. Reset filtro de velocidad
        # 4. Leer estado inicial
        ...

    def close(self):
        # Enviar acción 0 al ESP32
        self.session.get(f"http://{self.esp32_ip}/rl_cmd?a=0")
        ...
```

### 6.2 Protocolo de Reset

El reset en hardware real requiere:

1. Enviar acción 0 (kill motor)
2. Esperar a que el péndulo caiga (~2-3 segundos)
3. Resetear encoders (`/rl_cmd?r=1`)
4. Esperar estabilización (~0.5 segundos)
5. Leer estado inicial

**Tiempo total de reset:** ~3-4 segundos (vs instantáneo en simulación)

---

## 7. Fase 4: Entrenamiento Sim

### 7.1 Script: `src/qube_rl/train.py`

```python
"""Entrenamiento SAC para QUBE Servo en simulación."""
import gymnasium as gym
from stable_baselines3 import SAC
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import (ControlFrequency, DeadZone,
                                GentlyTerminating, HistoryWrapper)

def make_env():
    """Crea entorno con wrappers estándar."""
    env = QubeSimEnv(
        control_freq=50,
        reward="cos_alpha",
        angle_limits=[np.inf, np.inf],  # Sin límite en θ
        speed_limits=[50, 400],          # Límites de velocidad
        encoders_CPRs=None,              # Sin cuantización en sim inicial
        velocity_filter_order=2,
    )
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    env = ControlFrequency(env)
    return env

def main():
    env = DummyVecEnv([make_env])
    check_env(env.envs[0].unwrapped)

    model = SAC(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        buffer_size=1_000_000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        use_sde=True,               # State-Dependent Exploration
        use_sde_at_warmup=True,
        sde_sample_freq=64,
        train_freq=(1, "episode"),   # Entrena al final de cada episodio
        gradient_steps=-1,           # Tantos gradient steps como env steps
        learning_starts=1000,
        tensorboard_log="runs/",
        verbose=1,
        policy_kwargs=dict(
            net_arch=dict(pi=[256, 256], qf=[256, 256]),
        ),
    )

    model.learn(
        total_timesteps=200_000,
        progress_bar=True,
    )

    model.save("models/qube_sac_sim")
    print("Modelo guardado en models/qube_sac_sim.zip")

if __name__ == "__main__":
    main()
```

### 7.2 Hiperparámetros

| Parámetro          | Valor          | Justificación                                            |
| ------------------- | -------------- | --------------------------------------------------------- |
| `learning_rate`   | 3e-4           | Default SB3, probado en Furuta                            |
| `buffer_size`     | 1M             | Off-policy, almacena mucha experiencia                    |
| `batch_size`      | 256            | Default SAC                                               |
| `tau`             | 0.005          | Soft update del target network                            |
| `gamma`           | 0.99           | Discount factor (episodios ~5s a 50Hz = 250 steps)        |
| `use_sde`         | True           | gSDE para mejor sim-to-real                               |
| `sde_sample_freq` | 64             | Reset ruido cada 64 steps                                 |
| `train_freq`      | (1, "episode") | Entrena al final de cada episodio                         |
| `net_arch`        | [256, 256]     | Red más grande que default [256, 256] para política y Q |
| `total_timesteps` | 200K           | Suficiente para convergencia en Furuta                    |

### 7.3 Métricas de éxito (simulación)

| Métrica                           | Umbral | Descripción                                             |
| ---------------------------------- | ------ | -------------------------------------------------------- |
| Reward promedio (últimos 100 eps) | > 200  | Indica que el péndulo se mantiene vertical              |
| Tiempo de balance                  | > 30 s | Péndulo invertido sin caer                              |
| Catch rate                         | > 50%  | Episodios donde el péndulo alcanza vertical desde abajo |

### 7.4 Tracking con TensorBoard

```bash
uv run tensorboard --logdir runs/
```

Métricas a monitorear:

- `rollout/ep_rew_mean` — Reward promedio por episodio
- `rollout/ep_len_mean` — Duración promedio del episodio
- `train/ent_coef` — Coeficiente de entropía (debería estabilizarse)
- `train/critic_loss` — Loss del crítico (debería converger)

---

## 8. Fase 5: Inferencia en Hardware Real

### 8.1 Script: `src/qube_rl/inference.py`

```python
"""Inferencia del agente SAC en el QUBE real vía HTTP."""
import numpy as np
from stable_baselines3 import SAC

from qube_rl.envs.qube_real import QubeRealEnv
from qube_rl.wrappers import (ControlFrequency, DeadZone,
                                GentlyTerminating, HistoryWrapper)

def main():
    # Cargar modelo entrenado en simulación
    model = SAC.load("models/qube_sac_sim")

    env = QubeRealEnv(esp32_ip="192.168.4.1", control_freq=50)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=False)
    env = ControlFrequency(env)

    for episode in range(10):
        obs, _ = env.reset()
        total_reward = 0
        steps = 0

        while True:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1

            if terminated or truncated:
                break

        print(f"Ep {episode}: reward={total_reward:.1f}, steps={steps}")

    env.close()

if __name__ == "__main__":
    main()
```

### 8.2 Protocolo de inferencia

1. Conectar PC al WiFi del ESP32 (AP: `QUBE-ESP32`, pass: `qube1234`)
   — O conectar ambos a la misma red LAN
2. Ejecutar `uv run python src/qube_rl/inference.py`
3. El agente predice acción a 50 Hz
4. Acción se envía como `GET /rl_cmd?a=X`
5. Estado se lee como `GET /rl_state`

---

## 9. Fase 6: Fine-Tuning Sim-to-Real

### 9.1 Script: `src/qube_rl/finetune.py`

```python
"""Fine-tuning del modelo simulado en el hardware real."""
from stable_baselines3 import SAC

from qube_rl.envs.qube_real import QubeRealEnv
from qube_rl.wrappers import (ControlFrequency, DeadZone,
                                GentlyTerminating, HistoryWrapper)

def main():
    # Cargar modelo pre-entrenado en simulación
    model = SAC.load("models/qube_sac_sim")

    env = QubeRealEnv(esp32_ip="192.168.4.1", control_freq=50)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    env = ControlFrequency(env)

    # Fine-tuning con learning rate más bajo
    model.set_env(env)
    model.learning_rate = 1e-4  # Más conservador que el entrenamiento sim

    model.learn(
        total_timesteps=100_000,
        progress_bar=True,
        reset_num_timesteps=False,  # Continuar conteo desde sim
    )

    model.save("models/qube_sac_finetuned")
    print("Modelo fine-tuned guardado")

    env.close()

if __name__ == "__main__":
    main()
```

### 9.2 Consideraciones de fine-tuning

| Aspecto              | Detalle                                         |
| -------------------- | ----------------------------------------------- |
| Learning rate        | 1e-4 (3x menor que entrenamiento sim)           |
| Steps                | 100K (suficiente para adaptar, no para olvidar) |
| Tiempo estimado      | ~33 minutos a 50 Hz (100K / 50 / 60)            |
| Replay buffer        | Cargar del modelo sim para warm-start           |
| Domain randomization | NO en fine-tuning (hardware real es fijo)       |
| Reset                | ~3-4 segundos por episodio (péndulo debe caer) |

---

## 10. Fase 7: Exportación a ESP32 (opcional/futura)

### 10.1 Opción A: ONNX → TFLite Micro

```
model.zip → ONNX → TFLite → INT8 → C array → ESP32 flash
```

- Red pequeña `[6] → [64] → [64] → [1]` ≈ 4,609 params ≈ 18 KB (F32) ≈ 5 KB (INT8)
- Inferencia en ESP32: ~0.5 ms (F32) o ~0.2 ms (INT8)
- Sin necesidad de WiFi para inferencia

### 10.2 Opción B: PyTorch JIT → C++

```python
# Exportar con torch.jit.trace
traced = th.jit.trace(model.policy.actor.eval(), dummy_input)
frozen = th.jit.freeze(traced)
frozen = th.jit.optimize_for_inference(frozen)
th.jit.save(frozen, "actor_traced.pt")
```

- Requiere runtime PyTorch en el ESP32 (no práctico)
- ❌ No recomendado para embebido

### 10.3 Opción C: Calcular pesos manualmente

```python
# Extraer pesos de la red entrenada
weights = model.policy.actor.state_dict()
# Convertir a C arrays
# Implementar forward pass en C puro
```

- Más trabajo pero más eficiente
- Sin dependencias externas
- ✅ Recomendado si se necesita offline

### 10.4 Recomendación

**Para la tesis: usar WiFi (Fases 1-6).** La inferencia por HTTP a 50 Hz es
suficiente y simplifica enormemente el desarrollo. La exportación a C (Fase 7)
es un trabajo adicional significativo que puede quedarse como trabajo futuro.

---

## 11. Decisiones de Diseño

### 11.1 Por qué NO reemplazar el LQR

El LQR (modo 4) ya funciona bien para balance una vez que el péndulo está
cerca de la vertical. El RL es mejor para:

- **Swing-up**: El firmware actual usa heurística de energía con ~25-40% catch rate.
  RL puede lograr 70-90%.
- **Transición**: Decidir cuándo cambiar de swing-up a balance.
- **Robustez**: Domain randomization compensa imprecisiones del modelo.

**Estrategia:** RL controla todo (swing-up + balance) como un único agente.
Si no funciona bien, fallback a: RL solo para swing-up, LQR para balance.

### 11.2 Por qué 50 Hz y no 200 Hz o 500 Hz

- El firmware actual opera el LQR a ~500 Hz (CONTROL_PERIOD_US = 2000)
- El Furuta usa 50 Hz exitosamente
- 50 Hz da 20 ms por step, suficiente para HTTP round-trip (~5 ms)
- Más Hz = más datos de entrenamiento = más lento para converger
- 50 Hz es el estándar para RL en péndulos rotatorios

### 11.3 Por qué HTTP en vez de Serial

- El ESP32 ya tiene servidor web implementado
- WiFi permite desarrollo sin cable USB
- HTTP es debuggeable (curl, navegador)
- Serial requiere pyserial y puerto COM (problemas en Windows)
- Latencia HTTP (~5ms) es aceptable a 50 Hz

### 11.4 Por qué HistoryWrapper

El péndulo es un sistema de segundo orden. Con solo la observación actual
[pos, vel], el agente no ve la tendencia (aceleración). Stackear 4 pasos
de [obs, acción] le da contexto temporal:

- Input: 4 × (6 obs + 1 action) = 28 dimensiones
- Permite al agente estimar aceleración y fricción implícitamente

### 11.5 Por qué DeadZone

El motor DC con L298N/BTS7960 tiene una zona muerta: PWM bajo no mueve
el motor por fricción estática. Sin compensación, el agente aprende que
acciones pequeñas no tienen efecto y explora mal. El wrapper mapea:

- `|action| < center` → 0 (no mover)
- `|action| > center` → escala linealmente entre deadzone y max_act

---

## 12. Riesgos y Mitigaciones

| # | Riesgo                           | Probabilidad | Impacto | Mitigación                                                       |
| - | -------------------------------- | ------------ | ------- | ----------------------------------------------------------------- |
| 1 | Modelo de simulación inexacto   | Alta         | Alto    | Domain randomization (parámetros variados ±10-50%)              |
| 2 | Latencia HTTP inestable          | Media        | Medio   | ControlFrequency wrapper enforce 50Hz; timeout en requests        |
| 3 | Péndulo daña hardware al caer  | Baja         | Alto    | GentlyTerminating (kill motor al terminar); límites de velocidad |
| 4 | Overfitting a simulación        | Alta         | Alto    | Fine-tuning obligatorio en hardware real (100K steps)             |
| 5 | Convergencia lenta en sim        | Media        | Bajo    | 200K steps es suficiente según Furuta; aumentar si necesario     |
| 6 | WiFi inestable (modo AP)         | Media        | Medio   | Usar red LAN compartida en vez de AP directo                      |
| 7 | Encoder ruidoso                  | Media        | Medio   | Filtro de velocidad EMA ya implementado en firmware               |
| 8 | Motor se calienta en fine-tuning | Baja         | Medio   | Limitar episodios a 10s; pausa entre episodios                    |

---

## 13. Criterios de Aceptación

### Fase 1 — Simulación

- [ ] `QubeSimEnv` pasa `check_env()` de SB3
- [ ] Péndulo se mantiene invertido >10 segundos en simulación
- [ ] Reward promedio > 200 en últimos 100 episodios

### Fase 2 — Firmware

- [ ] `GET /rl_state` devuelve JSON con `th, al, thd, ald` en radianes
- [ ] `GET /rl_cmd?a=0.5` mueve el motor al 50% PWM
- [ ] Latencia de `/rl_state` < 5 ms (medida con curl)
- [ ] Modos 0-5 existentes NO se ven afectados

### Fase 3 — Entorno Real

- [ ] `QubeRealEnv.reset()` estabiliza el péndulo en <5 segundos
- [ ] `QubeRealEnv.step()` completa un ciclo en <20 ms (50 Hz)
- [ ] Estado leído coincide con posición real del péndulo

### Fase 4 — Entrenamiento

- [ ] SAC converge en 200K steps (reward creciente en TensorBoard)
- [ ] Modelo guardado como `models/qube_sac_sim.zip`

### Fase 5 — Inferencia Real

- [ ] Agente controla el motor por WiFi sin errores de conexión
- [ ] Péndulo oscila (muestra que el agente intenta algo)

### Fase 6 — Fine-Tuning

- [ ] Catch rate > 50% (el péndulo alcanza vertical desde abajo)
- [ ] Tiempo de balance > 10 segundos sostenido
- [ ] Modelo fine-tuned guardado como `models/qube_sac_finetuned.zip`

---

## 14. Dependencias

### Python (agregar a pyproject.toml)

```toml
[project.optional-dependencies]
rl = [
    "stable-baselines3>=2.2.1",
    "gymnasium>=0.29.1",
    "torch>=2.8.0",
    "tensorboard>=2.15.1",
    "requests>=2.31.0",
    "numpy>=1.24.0",
]
```

### Comandos de instalación

```bash
uv add --optional rl stable-baselines3 gymnasium torch tensorboard requests
```

### Hardware

- PC con GPU (para entrenamiento) — puede ser la GTX 1050 del workstation
- ESP32 conectado por WiFi
- QUBE Servo con encoders funcionando

---

## 15. Referencias Bibliográficas

1. **Haarnoja, T. et al.** (2018). "Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor." *ICML*. https://arxiv.org/abs/1801.01290
2. **Raffin, A. et al.** (2021). "Stable Baselines 3: Reliable Reinforcement Learning Implementations." *JMLR*. https://jmlr.org/papers/v22/20-1364.html
3. **Armandpl/furuta** (2024). "Building and Training a Rotary Inverted Pendulum Robot." https://github.com/Armandpl/furuta
4. **gSDE paper** — Raffin, A. et al. (2020). "State-Dependent Exploration for Policy Gradient Methods." https://arxiv.org/abs/2005.05719
5. **Hernandez, R. et al.** (2024). "Modeling, simulation, and control of a rotary inverted pendulum: A reinforcement learning-based control approach." *Modelling*.
6. **RLtools** (2024). "Fast Gradient-Free Reinforcement Learning for Robotics." https://github.com/rl-tools/rl-tools

---

## Estructura de Archivos Propuesta

```
src/qube_rl/
├── __init__.py
├── train.py                    # Entrenamiento SAC en simulación
├── inference.py                # Inferencia en hardware real
├── finetune.py                 # Fine-tuning sim-to-real
├── envs/
│   ├── __init__.py
│   ├── qube_dynamics.py        # Modelo analítico QubeDynamics
│   ├── qube_sim.py             # Entorno Gymnasium simulación
│   └── qube_real.py            # Entorno Gymnasium hardware real
├── wrappers/
│   ├── __init__.py
│   ├── control_frequency.py    # Enforce 50 Hz
│   ├── gently_terminating.py   # Kill motor al terminar
│   ├── deadzone.py             # Compensar zona muerta
│   └── history_wrapper.py      # Stack obs pasadas + continuity cost
├── rewards.py                  # Funciones de recompensa
├── utils.py                    # VelocityFilter, constantes, helpers
└── configs/
    ├── sac_sim.yaml            # Config SAC para simulación
    └── sac_finetune.yaml       # Config SAC para fine-tuning

models/                         # Modelos guardados (gitignored)
runs/                           # Logs TensorBoard (gitignored)
```

---

## Notas para Implementación

### Orden de ejecución

1. **Primero:** `qube_dynamics.py` + `qube_sim.py` (sin firmware)
2. **Segundo:** `train.py` — validar que SAC converge en sim
3. **Tercero:** Modificar firmware (modo 6)
4. **Cuarto:** `qube_real.py` + `inference.py`
5. **Quinto:** `finetune.py` — transferencia a hardware real
6. **Último:** Evaluar resultados y decidir si Fase 7

### Tiempo estimado

| Fase               | Tiempo               | Dependencia   |
| ------------------ | -------------------- | ------------- |
| Fase 1 (sim env)   | 2-3 días            | Ninguna       |
| Fase 2 (firmware)  | 1 día               | Ninguna       |
| Fase 3 (real env)  | 1 día               | Fase 2        |
| Fase 4 (train sim) | 1 día (GPU)         | Fase 1        |
| Fase 5 (inference) | 0.5 días            | Fases 2, 3, 4 |
| Fase 6 (finetune)  | 1-2 días            | Fase 5        |
| **Total**    | **~7-9 días** |               |

### Compatibilidad con Windows

El proyecto corre en Windows 10. Consideraciones:

- `pyserial` funciona en Windows (pero no se usa — se usa HTTP)
- `torch` con CUDA funciona en Windows con GTX 1050
- `tensorboard` funciona en Windows
- `requests` funciona en Windows
- No hay dependencias Unix-only
