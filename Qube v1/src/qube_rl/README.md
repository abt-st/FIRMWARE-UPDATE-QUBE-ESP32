# `qube_rl` — Paquete de Reinforcement Learning del QUBE

Entrenamiento, evaluación y despliegue (sim-to-real) de políticas de **Deep RL** para el
**swing-up y balance** del péndulo rotatorio invertido (Furuta) del proyecto QUBE-ESP32.

El algoritmo es **SAC (Soft Actor-Critic)** de [Stable-Baselines3](https://stable-baselines3.readthedocs.io/),
entrenado en un simulador con *domain randomization* y desplegado en el ESP32 (modo HTTP o
inferencia on-device). La red por defecto es `[64, 64]` para que quepa en la flash del ESP32.

> 📖 **¿Nuevo en ML/RL?** Lee primero [`../../REFERENCE.md`](../../REFERENCE.md): explica de cero
> ML, RL, Deep RL y SAC, además de la formulación del problema, ideas de mejora y una auditoría
> de errores. Este README es la **referencia operativa** del paquete (qué hace cada módulo y cómo
> ejecutarlo).

---

## Tabla de contenidos

- [Instalación](#instalación)
- [Inicio rápido](#inicio-rápido)
- [El problema como MDP](#el-problema-como-mdp)
- [Mapa del paquete](#mapa-del-paquete)
- [Entornos (`envs/`)](#entornos-envs)
- [La env factory](#la-env-factory-fuente-única-de-verdad)
- [Recompensas (`rewards.py`)](#recompensas-rewardspy)
- [Wrappers (`wrappers/`)](#wrappers-wrappers)
- [Scripts / CLI](#scripts--cli)
- [Métricas de evaluación (`metrics.py`)](#métricas-de-evaluación-metricspy)
- [Configuración (`config.py`)](#configuración-configpy)
- [Sim-to-real y despliegue en ESP32](#sim-to-real-y-despliegue-en-esp32)
- [Controladores clásicos (baseline)](#controladores-clásicos-baseline)
- [Tracking de experimentos (MLflow)](#tracking-de-experimentos-mlflow)
- [Tests](#tests)
- [Estado y limitaciones conocidas](#estado-y-limitaciones-conocidas)

---

## Instalación

```bash
uv sync            # instala dependencias (SB3, gymnasium, torch, numpy, scipy, …)
```

Todos los comandos se ejecutan desde la raíz del repo con `uv run python -m qube_rl.<script>`.

---

## Inicio rápido

```bash
# 1) Entrenar SAC en simulación (red [64,64], reward swingup_balance)
uv run python -m qube_rl.train --timesteps 500000 --reward swingup_balance --seed 0

# 2) Evaluar el modelo en el HARDWARE real (ESP32 por WiFi)
uv run python -m qube_rl.inference --model models/qube_sac_64x2.zip --episodes 10 --ip 192.168.4.1

# 3) Exportar la política a un header C++ para inferencia on-device (modo 7)
uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip
```

---

## El problema como MDP

| Elemento | Definición en el código |
|---|---|
| **Observación** (8-D) | `[θ, α, cos θ, sin θ, cos α, sin α, θ̇, α̇]` — `utils.observation_from_state` |
| **Acción** (1-D) | `a ∈ [-1, 1]` → voltaje del motor `[-12, 12] V` |
| **Dinámica** | Ecuaciones de Furuta analíticas (`envs/qube_dynamics.py`), Euler semi-implícito 500 Hz, control 50 Hz |
| **Recompensa** | 9 variantes en `rewards.py` (+ shaping PBRS opcional) |
| **Terminación** | Solo por límite de **brazo** (θ), sobrevelocidad, estado no finito o **TimeLimit**; **no** por `α` (el invertido es la meta) |
| **Convención de ángulo** | `α = 0` colgando (estable), `α = ±π` invertido (meta, inestable) |

`θ` (theta) = ángulo del brazo rotatorio; `α` (alpha) = ángulo del péndulo. El sistema es
**subactuado** (1 motor, 2 GDL): no se puede empujar el péndulo directo, hay que **bombear energía**.

---

## Mapa del paquete

| Archivo | Rol |
|---|---|
| `config.py` | Dataclasses de configuración (`EnvConfig`, `WrapperConfig`, `SACConfig`) y semillas |
| `envs/qube_sim.py` | Entorno Gymnasium de **simulación** (`QubeSimEnv`) |
| `envs/qube_real.py` | Entorno Gymnasium del **hardware real** vía HTTP (`QubeRealEnv`) |
| `envs/qube_dynamics.py` | Dinámica analítica de Furuta + **domain randomization** |
| `envs/factory.py` | **Fuente única** para construir entornos (`make_sim_env` / `make_real_env`) |
| `rewards.py` | 9 funciones de recompensa registradas en `REWARDS` |
| `rewards_simple.py` | Recompensa auxiliar simplificada (`swingup_simple`) para redes pequeñas |
| `wrappers/` | DeadZone, GentlyTerminating, HistoryWrapper, ControlFrequency, **PotentialShaping** |
| `utils.py` | `observation_from_state`, `wrap_angle`, `VelocityFilter`, `Timing`, índices de estado |
| `metrics.py` | `evaluate_balance` — métrica de éxito basada en balance (no en pico de ángulo) |
| `train.py` | Entrenamiento SAC estándar |
| `fast_train.py` | Entrenamiento SAC por *chunks* con checkpoints |
| `auto_train.py` | Bucle autónomo **multi-semilla** (media ± std) con selección por `balance_rate` |
| `distill.py` | Compresión teacher→student (behavioral cloning + RL) y export a C++ |
| `finetune.py` | Fine-tuning de un modelo de sim sobre el hardware real |
| `inference.py` | Ejecuta un modelo entrenado en el hardware real |
| `export_rltools.py` | Exporta los pesos del actor a un header C++ (formato RLtools) |
| `lqr.py` | Controlador **LQR** clásico (linealización + Riccati) para balance |
| `energy_swingup.py` | Swing-up clásico por **energía** + handoff a LQR |
| `mlflow_tracking.py` | Integración opcional con MLflow |

---

## Entornos (`envs/`)

### `QubeSimEnv` (simulación)
Entorno Gymnasium con la dinámica analítica de Furuta. En cada `reset()` aplica
**domain randomization** sobre 8 parámetros físicos (masa, longitud, fricción del brazo y del
péndulo, resistencia y constante del motor) muestreados de una gaussiana alrededor del nominal —
clave para el *sim-to-real*. Simula cuantización de encoder y filtrado de velocidad **igual que el
firmware**. El estado inicia colgando (`α ≈ 0`) con ruido pequeño.

### `QubeRealEnv` (hardware)
Habla con el ESP32 por HTTP (`/rl_state`, `/rl_cmd`) a 50 Hz; misma observación 8-D que la sim
(contrato fijado por tests). Pone el firmware en modo 6 (`/cmd?m=6`) automáticamente.

### `QubeDynamics`
Resuelve `M(q)·q̈ + C(q,q̇) = τ` para el Furuta, con modelo de motor DC. El método `randomize()`
aplica el *domain randomization* (siempre relativo al nominal → sin deriva).

---

## La env factory (fuente única de verdad)

`envs/factory.py` centraliza la construcción de entornos para que sim, real y firmware **nunca
diverjan**. Stack de wrappers (de dentro hacia fuera):

```
QubeSimEnv → TimeLimit → Monitor → GentlyTerminating → DeadZone → HistoryWrapper → [PotentialShaping]
```

`TimeLimit` va **dentro** de `Monitor` para que la truncación se registre; `Monitor` reporta la
recompensa **base** (sin continuity cost ni shaping).

```python
from qube_rl.envs.factory import make_sim_env, make_real_env

env = make_sim_env(reward="swingup_balance")                 # defaults de EnvConfig/WrapperConfig
env = make_sim_env(reward="linear_alpha", potential="upright")  # con shaping PBRS opt-in
env = make_sim_env(max_episode_steps=0, history_steps=0)     # sin TimeLimit ni history (debug)
real = make_real_env(esp32_ip="192.168.4.1")
```

Parámetros útiles: `control_freq`, `reward`, `angle_limits`, `speed_limits`, `max_episode_steps`
(0 = off), `history_steps` (0 = off), `monitor`, `potential` (`"upright"`), `potential_gamma`.

---

## Recompensas (`rewards.py`)

Todas reciben el estado 4-D `[θ, α, θ̇, α̇]` y devuelven un escalar. `α = 0` colgando, `α = ±π`
invertido. Seleccionables por nombre con `--reward`:

| Nombre | Idea |
|---|---|
| `cos_alpha` | Verticalidad `(1−cos α)/2` × centrado del brazo (multiplicativo) |
| `exp_alpha_2/3/4/6` | Gradiente exponencial más agresivo cerca del invertido |
| `cos_alpha_centered` | `(1−cos α)/2` + penalización aditiva fuerte de θ |
| `linear_alpha` | `|α|/π` (gradiente denso, útil para descubrir el bombeo) + penalización ligera de θ |
| `linear_alpha_dense` | `linear_alpha` + *shaping* de velocidad (bombear abajo, frenar arriba) |
| `swingup_balance` | **Por defecto**: adaptativa por fase (penaliza poco en swing-up, mucho en balance) |

> **PBRS (shaping basado en potencial).** Como cambiar de recompensa cambia la política óptima,
> existe la alternativa **policy-invariante** (Ng et al. 1999): el wrapper `PotentialShaping`
> añade `F = γ·Φ(s') − Φ(s)` sin distorsionar el objetivo. Actívalo con `--potential upright`.

---

## Wrappers (`wrappers/`)

| Wrapper | Qué hace |
|---|---|
| `DeadZone` | Compensa la fricción estática del motor (mapea acciones pequeñas a 0, reescala el resto) |
| `GentlyTerminating` | Manda acción 0 al motor al terminar/truncar el episodio (seguridad de hardware) |
| `HistoryWrapper` | Apila los últimos 4 pares `(obs, acción)` → contexto temporal (sistema de 2º orden); *continuity cost* opcional |
| `ControlFrequency` | Respeta el tiempo real del lazo (solo para inferencia, no entrenamiento) |
| `PotentialShaping` | Shaping PBRS policy-invariante (ver arriba) |

---

## Scripts / CLI

### `train.py` — entrenamiento SAC
```bash
uv run python -m qube_rl.train --timesteps 500000 --reward swingup_balance --net-arch 64 --seed 0
# Flags: --lr --batch-size --buffer-size --freq --potential upright --mlflow
# Guarda models/qube_sac_<net>x2.zip
```

### `fast_train.py` — entrenamiento por chunks con checkpoints
```bash
uv run python -m qube_rl.fast_train --steps 100000 --chunk 20000 --reward swingup_balance
```

### `auto_train.py` — bucle autónomo multi-semilla
```bash
uv run python -m qube_rl.auto_train --seeds 0 1 2 3 4     # ≥5 semillas recomendado
# Corre varias configs, evalúa con la métrica de balance y escribe
# experiments/<fecha>_training/training_progress.md con media ± std.
```

### `distill.py` — teacher→student (BC + RL) + export a C++
```bash
uv run python -m qube_rl.distill --teacher models/qube_sac_128x2.zip --student-arch 64 --timesteps 200000
# Behavioral cloning (100k demos) + fine-tuning SAC; verifica con la métrica de balance
# y exporta el header C++ del firmware. (No es KD con soft-targets — eso es trabajo futuro.)
```

### `finetune.py` — fine-tuning en hardware real
```bash
uv run python -m qube_rl.finetune --model models/qube_sac_sim.zip --timesteps 50000 --ip 192.168.4.1
```

### `inference.py` — correr un modelo en el hardware
```bash
uv run python -m qube_rl.inference --model models/qube_sac_64x2.zip --episodes 10 --ip 192.168.4.1
```

### `export_rltools.py` — exportar pesos a header C++
```bash
uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip --output src/firmware/esp32_qube/policy_weights.h
# Avisa si el INPUT_DIM del modelo no coincide con el esperado por el firmware (36 = 4×9).
```

---

## Métricas de evaluación (`metrics.py`)

`evaluate_balance(model, env, n_episodes=...)` es la **fuente única de verdad** para medir éxito.
A diferencia del viejo proxy "pico de `α > 120°`" (que mide *alcanzar*, no *balancear*, y se deja
engañar por el *spinning*), reporta:

- `reach_rate` — fracción de episodios que llegan cerca del invertido.
- `balance_rate` — fracción que **mantiene** el invertido-y-lento (`|α−π|<tol` y `|α̇|` baja)
  durante ≥ 1 s (el verdadero éxito).
- `upright_fraction` — fracción de pasos arriba.
- `max_hold_s` — tiempo continuo máximo arriba.

```python
from qube_rl.metrics import evaluate_balance, format_balance_metrics
m = evaluate_balance(model, make_sim_env(), n_episodes=20)
print(format_balance_metrics(m))
```

---

## Configuración (`config.py`)

Fuente única de hiperparámetros (elimina "números mágicos" duplicados):

| Dataclass | Campos clave (defaults) |
|---|---|
| `EnvConfig` | `control_freq=50`, `reward="swingup_balance"`, `angle_limit_theta=2π/3` (**±120°**), `angle_limit_alpha=π`, `max_episode_steps=500` |
| `WrapperConfig` | `deadzone=0.2`, `deadzone_center=0.01`, `deadzone_max_act=0.75`, `history_steps=4`, `use_continuity_cost=True` |
| `SACConfig` | `learning_rate=3e-4`, `batch_size=256`, `buffer_size=1e6`, `tau=0.005`, `gamma=0.99`, `use_sde=True`, `net_arch=64` |

`set_global_seeds(seed)` siembra Python/NumPy/PyTorch para reproducibilidad (`MAX_VELOCITY=50 rad/s`).

---

## Sim-to-real y despliegue en ESP32

1. **Entrenar en sim** con domain randomization (`train` / `fast_train`).
2. **(Opcional) Fine-tuning** en hardware (`finetune`) o **destilar** a una red pequeña (`distill`).
3. **Desplegar** de dos formas:
   - **Modo 6 (RL por HTTP):** un agente Python externo envía acciones por WiFi (`inference`).
   - **Modo 7 (on-device):** exportar los pesos a C++ (`export_rltools`) y compilarlos en el
     firmware para inferencia en el propio ESP32.

> ⚠️ **Contrato de observación.** La inferencia on-device del firmware espera **36 entradas**
> (history de 4 × 9 features). `export_rltools` avisa si el modelo no coincide. Ver "limitaciones".

---

## Controladores clásicos (baseline)

Sirven de **línea base a superar** y de posible *teacher* para destilación:

- `lqr.py` — linealiza alrededor del invertido (`α=π`) y resuelve la ecuación de Riccati (CARE)
  para la ganancia óptima `u = −Kx`. Estabiliza una vez que ya estás casi arriba.
- `energy_swingup.py` — bombea energía meciendo el brazo y hace *handoff* al LQR cerca del invertido.

---

## Tracking de experimentos (MLflow)

Pasa `--mlflow` a `train`/`fast_train`/`finetune`/`auto_train` para registrar parámetros, métricas
y el artefacto del modelo. Configurable con `--mlflow-uri` y `--mlflow-experiment`
(ver `mlflow_tracking.py`).

---

## Tests

```bash
uv run pytest                          # toda la suite
uv run pytest tests/test_fixes.py -q   # regresiones de los arreglos de RL
```

Tests relevantes: `test_qube_sim.py`, `test_qube_dynamics.py`, `test_rewards.py`,
`test_observation_contract.py` (fija el contrato sim↔real↔firmware), `test_wrappers.py`,
`test_fixes.py` (terminación, TimeLimit, wrap de α, métrica de balance, PBRS).

---

## Estado y limitaciones conocidas

**Funciona:** swing-up parcial en sim (alcanza ~169° con `linear_alpha`); pipeline completo
sim→export→firmware.

**Abierto:** el **balance sostenido** sigue sin resolverse de forma robusta (problema central de la
tesis). Los arreglos de la v1.44.0 (no terminar en la meta, `TimeLimit`, métrica correcta,
multi-semilla, θ±120°, PBRS) **mejoran el planteamiento** pero requieren **reentrenar** para verse
en resultados.

**Issue de despliegue (D3):** el firmware on-device fija 36 entradas (history-4) mientras los
hallazgos sugieren que la mejor config ESP32 es raw-8 `[64,64]`; reconciliar esto requiere tocar el
firmware y probar en hardware.

> Detalle completo de mejoras propuestas y auditoría de errores en
> [`../../REFERENCE.md`](../../REFERENCE.md) (Partes V y VI) y en `CHANGELOG.md` [1.44.0].
